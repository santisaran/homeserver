import re
import html
import requests
import logging
import sqlite3
import hashlib
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import sys

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)


class AcadeuMonitor:
    NT_BASE_URL = "https://plataforma.acadeu.com"
    NT_INIT_URL = f"{NT_BASE_URL}/i/nuestra-tierra"
    NT_LOGIN_URL = f"{NT_BASE_URL}/j_spring_security_check"
    NT_UNREAD_URL = f"{NT_BASE_URL}/conversaciones/sin-leer"

    def __init__(self):
        self.username = os.getenv("NT_USERNAME")
        self.password = os.getenv("NT_PASSWORD")
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.db_path = "data/notificaciones.db"
        self.session: requests.Session | None = None
        self._init_db()

    def _db_connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Inicializa tablas para deduplicación y hilos DEBATE."""
        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nt_sent_messages (
                    message_key TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nt_debate_threads (
                    conversation_key TEXT PRIMARY KEY,
                    root_message_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _already_sent(self, message_key: str) -> bool:
        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM nt_sent_messages WHERE message_key = ?",
                (message_key,),
            )
            return cur.fetchone() is not None

    def _mark_sent(self, message_key: str):
        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO nt_sent_messages(message_key, sent_at) VALUES (?, ?)",
                (message_key, datetime.now().isoformat()),
            )
            conn.commit()

    def _get_debate_root_message_id(self, conversation_key: str) -> int | None:
        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT root_message_id FROM nt_debate_threads WHERE conversation_key = ?",
                (conversation_key,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def _set_debate_root_message_id(self, conversation_key: str, root_message_id: int):
        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO nt_debate_threads(conversation_key, root_message_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(conversation_key)
                DO UPDATE SET root_message_id = excluded.root_message_id,
                              updated_at = excluded.updated_at
                """,
                (conversation_key, root_message_id, datetime.now().isoformat()),
            )
            conn.commit()

    @staticmethod
    def _pick_first_nonempty(data: dict, keys: list[str], default: str = "") -> str:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return str(value)
        return default

    def _conversation_mode(self, data: dict) -> str:
        mode = self._pick_first_nonempty(
            data,
            ["modo", "tipo", "tipoConversacion", "modoConversacion"],
            default="",
        )
        return mode.upper()

    def _conversation_key(self, data: dict, asunto: str) -> str:
        raw_key = self._pick_first_nonempty(
            data,
            ["id", "idConversacion", "conversacionId", "uuid", "codigo"],
            default="",
        )
        if raw_key:
            return f"conv:{raw_key}"
        fallback = hashlib.sha256(asunto.strip().lower().encode("utf-8")).hexdigest()[:16]
        return f"conv:asunto:{fallback}"

    @staticmethod
    def _message_key(conversation_key: str, msg: dict) -> str:
        msg_id = msg.get("id")
        if msg_id not in (None, ""):
            return f"{conversation_key}:msg:{msg_id}"

        seed = "|".join(
            [
                str(msg.get("creado", "")),
                str(msg.get("creadoFormateado", "")),
                str(msg.get("de", {}).get("nombreCompleto", "")),
                str(msg.get("cuerpo", ""))[:120],
            ]
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return f"{conversation_key}:msg:hash:{digest}"

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _safe_request(self, method: str, url: str, **kwargs):
        """Wrapper para requests que nunca lanza excepción; devuelve Response o None."""
        if self.session is None:
            log.error("No hay sesión activa para hacer la request.")
            return None
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            log.warning("Request fallido [%s %s]: %s", method.upper(), url, e)
            return None


    @staticmethod
    def _strip_html(html_content: str) -> str:
        """Elimina tags HTML y colapsa espacios."""
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = html.unescape(text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text

    # ------------------------------------------------------------------
    # Sesión (crítico: si falla, no tiene sentido continuar)
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Inicia sesión. Devuelve False si falla; el llamador decide si abortar."""
        try:
            self.session = requests.Session()
            self.session.get(self.NT_INIT_URL, timeout=15)
            self.session.post(
                self.NT_LOGIN_URL,
                data={
                    "institucion": "nuestra-tierra",
                    "j_username": self.username,
                    "j_password": self.password,
                },
                timeout=15,
            )
            log.info("Sesión iniciada correctamente.")
            return True
        except Exception as e:
            log.error("No se pudo iniciar sesión: %s", e)
            self.session = None
            return False

    # ------------------------------------------------------------------
    # Obtención de datos (tolerantes a fallos)
    # ------------------------------------------------------------------

    def get_unread(self) -> dict | None:
        """Retorna el JSON de notificaciones sin leer, o None si falla."""
        resp = self._safe_request("POST", self.NT_UNREAD_URL)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError as e:
            log.warning("Respuesta de 'sin-leer' no es JSON válido: %s", e)
            return None

    def get_messages(self, notifications: dict) -> list[dict]:
        """
        Itera las conversaciones sin leer y recupera el JSON de cada una.
        Las que fallen se omiten; el resto continúa.
        """
        messages = []
        conversations = (
            notifications.get("conversaciones", {}).get("sinLeer", [])
            if notifications
            else []
        )

        for conv in conversations:
            ver = conv.get("verConversacion")
            if not ver:
                log.warning("Conversación sin 'verConversacion', omitida: %s", conv)
                continue

            resp = self._safe_request(
                "POST",
                f"{self.NT_BASE_URL}{ver}",
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            )
            if resp is None:
                continue

            try:
                messages.append(resp.json())
            except ValueError as e:
                log.warning("Respuesta de conversación no es JSON válido: %s", e)

        return messages

    # ------------------------------------------------------------------
    # Telegram (tolerante a fallos)
    # ------------------------------------------------------------------

    def send_telegram(self, notification: dict, reply_to_message_id: int | None = None) -> int | None:
        """Envía una notificación por Telegram. Devuelve message_id si tuvo éxito."""
        texto = (
            f"*NUESTRA TIERRA* \n\n"
            f"*Título:* {notification['titulo']}\n"
            f"*De:* {notification['emisor']}\n"
            f"*Fecha:* {notification['fecha']}\n\n"
            f"{notification['contenido']}"
        )
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": texto,
            "parse_mode": "Markdown",
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
            payload["allow_sending_without_reply"] = True

        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("message_id")
        except Exception as e:
            log.warning("Error enviando a Telegram: %s", e)
            return None

    # ------------------------------------------------------------------
    # Procesamiento y persistencia (tolerante a fallos por mensaje)
    # ------------------------------------------------------------------

    def process_and_notify(self, conversation: dict):
        """
        Recibe el JSON de una conversación, extrae cada mensaje nuevo
        y lo envía por Telegram. Errores individuales no interrumpen el resto.
        """
        if not conversation or conversation.get("estado") != "ok":
            log.warning("Conversación con estado inesperado, omitida.")
            return

        data = conversation.get("viewModel", {}).get("data", {})
        asunto = data.get("asunto", "(sin asunto)")
        modo = self._conversation_mode(data)
        is_debate = modo == "DEBATE"
        conversation_key = self._conversation_key(data, asunto)
        root_message_id = (
            self._get_debate_root_message_id(conversation_key) if is_debate else None
        )
        mensajes = data.get("mensajes", [])
        hoy = datetime.now()
        limite = hoy - timedelta(days=4)

        for msg in mensajes:
            try:
                message_key = self._message_key(conversation_key, msg)
                if self._already_sent(message_key):
                    continue

                creado_str = msg.get("creado", "")
                creado_norm = creado_str.replace("Z", "+00:00") if creado_str else ""
                creado_dt = datetime.fromisoformat(creado_norm) if creado_norm else None

                if creado_dt and creado_dt < limite:
                    continue

                notif = {
                    "titulo": asunto,
                    "emisor": msg.get("de", {}).get("nombreCompleto", "Desconocido"),
                    "fecha": msg.get("creadoFormateado", creado_str),
                    "contenido": self._strip_html(msg.get("cuerpo", "")),
                }

                if is_debate:
                    sent_id = self.send_telegram(notif, reply_to_message_id=root_message_id)
                    if sent_id and root_message_id is None:
                        root_message_id = sent_id
                        self._set_debate_root_message_id(conversation_key, root_message_id)
                else:
                    sent_id = self.send_telegram(notif)

                if sent_id:
                    self._mark_sent(message_key)

            except Exception as e:
                log.warning("Error procesando mensaje id=%s, omitido: %s", msg.get("id"), e)

    # ------------------------------------------------------------------
    # Punto de entrada
    # ------------------------------------------------------------------

    def run(self):
        if not self.login():
            log.error("Login fallido. Abortando ejecución.")
            return

        notifications = self.get_unread()
        if notifications is None:
            log.warning("No se pudieron obtener notificaciones sin leer.")
            return

        messages = self.get_messages(notifications)
        for msg in messages:
            self.process_and_notify(msg)

        log.info("Check finalizado: %s", datetime.now())


if __name__ == "__main__":
    AcadeuMonitor().run()
