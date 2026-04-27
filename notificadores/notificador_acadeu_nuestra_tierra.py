import re
import html
import requests
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("nuestra_tierra.log", encoding="utf-8")
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

    def send_telegram(self, notification: dict) -> bool:
        """Envía una notificación por Telegram. Devuelve True si tuvo éxito."""
        texto = (
            f"*NUESTRA TIERRA* \n\n"
            f"*Título:* {notification['titulo']}\n"
            f"*De:* {notification['emisor']}\n"
            f"*Fecha:* {notification['fecha']}\n\n"
            f"{notification['contenido']}"
        )
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": texto, "parse_mode": "Markdown"},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            log.warning("Error enviando a Telegram: %s", e)
            return False

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
        mensajes = data.get("mensajes", [])
        hoy = datetime.now()
        limite = hoy - timedelta(days=4)

        for msg in mensajes:
            try:
                creado_str = msg.get("creado", "") 
                creado_dt = datetime.fromisoformat(creado_str) if creado_str else None

                if creado_dt and creado_dt < limite:
                    continue

                notif = {
                    "titulo": asunto,
                    "emisor": msg.get("de", {}).get("nombreCompleto", "Desconocido"),
                    "fecha": msg.get("creadoFormateado", creado_str),
                    "contenido": self._strip_html(msg.get("cuerpo", "")),
                }

                self.send_telegram(notif)

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
