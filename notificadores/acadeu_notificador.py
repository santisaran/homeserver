import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import sys

from acadeu_client import AcadeuClient
from acadeu_inputs import get_immich_options_from_payload, get_requested_conversation_ids
from immich_client import ImmichClient
from acadeu_parsing import (
    conversation_key,
    conversation_mode,
    extract_image_urls,
    message_key,
    pick_first_nonempty,
    strip_html,
)
from acadeu_store import AcadeuStore
from telegram_client import TelegramClient

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
    def __init__(self):
        self.username = os.getenv("NT_USERNAME")
        self.password = os.getenv("NT_PASSWORD")
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.db_path = "data/notificaciones.db"
        self.store = AcadeuStore(self.db_path)
        self.acadeu_client = AcadeuClient(self.username, self.password, log)
        self.telegram_client = TelegramClient(self.token, self.chat_id, log)
        immich_url = os.getenv("IMMICH_URL")
        immich_api_key = os.getenv("IMMICH_API_KEY")
        self.immich_client: ImmichClient | None = (
            ImmichClient(immich_url, immich_api_key, log)
            if immich_url and immich_api_key
            else None
        )

    def _already_sent(self, message_key: str) -> bool:
        return self.store.already_sent(message_key)

    def _mark_sent(self, message_key: str):
        self.store.mark_sent(message_key)

    def _get_debate_root_message_id(self, conversation_key: str) -> int | None:
        return self.store.get_debate_root_message_id(conversation_key)

    def _set_debate_root_message_id(self, conversation_key: str, root_message_id: int):
        self.store.set_debate_root_message_id(conversation_key, root_message_id)

    @staticmethod
    def _pick_first_nonempty(data: dict, keys: list[str], default: str = "") -> str:
        return pick_first_nonempty(data, keys, default)

    def _conversation_mode(self, data: dict) -> str:
        return conversation_mode(data)

    def _conversation_key(self, data: dict, asunto: str) -> str:
        return conversation_key(data, asunto)

    @staticmethod
    def _message_key(conversation_key: str, msg: dict) -> str:
        return message_key(conversation_key, msg)

    @staticmethod
    def _strip_html(html_content: str) -> str:
        """Elimina tags HTML y colapsa espacios."""
        return strip_html(html_content)

    @staticmethod
    def _extract_image_urls(html_content: str) -> list[str]:
        """Extrae URLs de imágenes desde etiquetas <img src="...">."""
        return extract_image_urls(html_content)

    # ------------------------------------------------------------------
    # Sesión (crítico: si falla, no tiene sentido continuar)
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Inicia sesión. Devuelve False si falla; el llamador decide si abortar."""
        return self.acadeu_client.login()

    # ------------------------------------------------------------------
    # Obtención de datos (tolerantes a fallos)
    # ------------------------------------------------------------------

    def get_unread(self) -> dict | None:
        """Retorna el JSON de notificaciones sin leer, o None si falla."""
        return self.acadeu_client.get_unread()

    def get_messages(self, notifications: dict) -> list[dict]:
        """
        Itera las conversaciones sin leer y recupera el JSON de cada una.
        Las que fallen se omiten; el resto continúa.
        """
        return self.acadeu_client.get_messages(notifications)

    def get_messages_by_conversation_ids(self, conversation_ids: list[str]) -> list[dict]:
        """
        Recupera conversaciones específicas por ID vía POST /conversaciones/{id}.
        Si alguna falla, continúa con las demás.
        """
        return self.acadeu_client.get_messages_by_conversation_ids(conversation_ids)

    # ------------------------------------------------------------------
    # Telegram (tolerante a fallos)
    # ------------------------------------------------------------------

    HEADER = "NUESTRA TIERRA"

    def send_telegram(
        self,
        notification: dict,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> int | None:
        """Envía una notificación por Telegram. Devuelve message_id si tuvo éxito."""
        return self.telegram_client.send_message(
            notification, self.HEADER, reply_to_message_id, reply_markup=reply_markup
        )

    def send_telegram_photo(
        self,
        notification: dict,
        image_url: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> int | None:
        """Descarga una imagen y la envía a Telegram como foto."""
        downloaded = self.acadeu_client.download_image(image_url)
        if downloaded is None:
            return None

        image_content, content_type = downloaded
        return self.telegram_client.send_photo(
            notification,
            image_content,
            self.HEADER,
            content_type,
            reply_to_message_id,
            reply_markup=reply_markup,
        )

    def _send_image_to_immich(
        self,
        image_url: str,
        album_name: str | None = None,
        filename: str | None = None,
    ) -> str | None:
        """Descarga una imagen y la sube a Immich. Devuelve el asset_id o None."""
        if self.immich_client is None:
            log.warning("Immich: cliente no configurado (faltan IMMICH_URL / IMMICH_API_KEY).")
            return None
        downloaded = self.acadeu_client.download_image(image_url)
        if downloaded is None:
            return None
        image_content, content_type = downloaded
        # Si el servidor no devuelve un content-type de imagen, inferirlo del nombre de archivo
        mime = content_type.split(";")[0].strip().lower() if content_type else ""
        if not mime.startswith("image/") and filename:
            import mimetypes as _mt
            guessed = _mt.guess_type(filename)[0]
            if guessed and guessed.startswith("image/"):
                content_type = guessed
                log.info("Immich: content_type inferido del nombre '%s': %s", filename, content_type)
        return self.immich_client.upload_to_album(
            image_content,
            content_type,
            filename=filename,
            album_name=album_name,
        )

    # ------------------------------------------------------------------
    # Procesamiento y persistencia (tolerante a fallos por mensaje)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_created_datetime(msg: dict) -> tuple[str, datetime | None]:
        creado_str = msg.get("creado", "")
        creado_norm = creado_str.replace("Z", "+00:00") if creado_str else ""
        creado_dt = datetime.fromisoformat(creado_norm) if creado_norm else None
        return creado_str, creado_dt

    def _build_notification(self, msg: dict, asunto: str, creado_str: str) -> tuple[dict, list[str], list[tuple[str, str]], bool, bool]:
        raw_body = msg.get("cuerpo", "")
        contenido = self._strip_html(raw_body)
        image_urls = self._extract_image_urls(raw_body)

        adjuntos_raw = (msg.get("dataAdjuntos") or {}).get("adjuntos") or []
        adjunto_urls: list[tuple[str, str]] = []
        for adj in adjuntos_raw:
            url = adj.get("urlDescarga", "")
            filename = adj.get("originalFilename", "adjunto")
            if url:
                if url.startswith("/"):
                    url = self.acadeu_client.base_url + url
                adjunto_urls.append((url, filename))

        notif = {
            "titulo": asunto,
            "emisor": msg.get("de", {}).get("nombreCompleto", "Desconocido"),
            "fecha": msg.get("creadoFormateado", creado_str),
            "contenido": contenido,
        }

        MAX_ADJUNTOS = 3
        adjuntos_solo_texto = len(adjunto_urls) > MAX_ADJUNTOS
        if adjuntos_solo_texto:
            nombres = ", ".join(fn for _, fn in adjunto_urls)
            aviso = f"📎 {len(adjunto_urls)} archivos adjuntos: {nombres}"
            notif["contenido"] = (notif["contenido"] + "\n" + aviso).strip()

        is_image_only = not contenido and bool(image_urls) and not adjunto_urls
        return notif, image_urls, adjunto_urls, is_image_only, adjuntos_solo_texto

    def _send_adjuntos_to_telegram(
        self,
        adjunto_urls: list[tuple[str, str]],
        reply_to_message_id: int | None = None,
        skip: bool = False,
    ):
        """Descarga y envía cada adjunto a Telegram como foto o documento.
        Si skip=True no hace nada (el resumen ya fue incluido en el texto).
        """
        if skip:
            return
        for url, filename in adjunto_urls:
            downloaded = self.acadeu_client.download_image(url)
            if downloaded is None:
                log.warning("No se pudo descargar adjunto: %s", filename)
                continue
            file_content, content_type = downloaded
            # Inferir content_type desde el nombre si la respuesta no lo indica
            if not content_type:
                import mimetypes as _mt
                content_type = _mt.guess_type(filename)[0] or "application/octet-stream"
            self.telegram_client.send_file(
                file_content,
                filename,
                content_type,
                reply_to_message_id=reply_to_message_id,
            )

    def _send_debate_message(
        self,
        notif: dict,
        is_image_only: bool,
        image_urls: list[str],
        adjunto_urls: list[tuple[str, str]],
        root_message_id: int | None,
        msg_id,
        immich_options: dict | None = None,
        conv_id: str | None = None,
        adjuntos_solo_texto: bool = False,
    ) -> tuple[int | None, int | None]:
        send_to_immich = bool(immich_options and immich_options.get("immich"))

        if send_to_immich:
            sent_id = None
            album_name = immich_options.get("album_name")
            for url in image_urls:
                self._send_image_to_immich(url, album_name)
            for url, filename in adjunto_urls:
                self._send_image_to_immich(url, album_name, filename=filename)
        else:
            # Adjuntar botón solo en el mensaje raíz y cuando hay imágenes
            reply_markup = None
            if conv_id and (image_urls or adjunto_urls) and root_message_id is None:
                reply_markup = self.telegram_client.immich_inline_keyboard(conv_id)

            if is_image_only:
                sent_id = self.send_telegram_photo(
                    notif,
                    image_urls[0],
                    reply_to_message_id=root_message_id,
                    reply_markup=reply_markup,
                )
            else:
                sent_id = self.send_telegram(
                    notif,
                    reply_to_message_id=root_message_id,
                    reply_markup=reply_markup,
                )

            if sent_id is None and image_urls:
                log.info("Mensaje %s: fallback a sendMessage con URL de imagen", msg_id)
                notif["contenido"] = f"Imagen: {image_urls[0]}"
                sent_id = self.send_telegram(
                    notif,
                    reply_to_message_id=root_message_id,
                    reply_markup=reply_markup,
                )

            self._send_adjuntos_to_telegram(
                adjunto_urls,
                reply_to_message_id=root_message_id,
                skip=adjuntos_solo_texto,
            )

        if sent_id and root_message_id is None:
            root_message_id = sent_id
        return sent_id, root_message_id

    def _send_direct_message(
        self,
        notif: dict,
        is_image_only: bool,
        image_urls: list[str],
        adjunto_urls: list[tuple[str, str]],
        msg_id,
        immich_options: dict | None = None,
        conv_id: str | None = None,
        adjuntos_solo_texto: bool = False,
    ) -> int | None:
        send_to_immich = bool(immich_options and immich_options.get("immich"))

        if send_to_immich:
            album_name = immich_options.get("album_name")
            for url in image_urls:
                self._send_image_to_immich(url, album_name)
            for url, filename in adjunto_urls:
                self._send_image_to_immich(url, album_name, filename=filename)
            return None

        reply_markup = None
        if conv_id and (image_urls or adjunto_urls):
            reply_markup = self.telegram_client.immich_inline_keyboard(conv_id)

        if is_image_only:
            sent_id = self.send_telegram_photo(notif, image_urls[0], reply_markup=reply_markup)
        else:
            sent_id = self.send_telegram(notif, reply_markup=reply_markup)

        if sent_id is None and image_urls:
            log.info("Mensaje %s: fallback a sendMessage con URL de imagen", msg_id)
            notif["contenido"] = f"Imagen: {image_urls[0]}"
            sent_id = self.send_telegram(notif, reply_markup=reply_markup)

        self._send_adjuntos_to_telegram(adjunto_urls, skip=adjuntos_solo_texto)

        return sent_id

    def process_and_notify(
        self,
        conversation: dict,
        ignore_date_limit: bool = False,
        ignore_already_sent: bool = False,
        immich_options: dict | None = None,
    ):
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
        conv_id = self._pick_first_nonempty(data, ["id", "idConversacion", "conversacionId", "uuid", "codigo"])
        root_message_id = (
            self._get_debate_root_message_id(conversation_key) if is_debate else None
        )
        mensajes = data.get("mensajes", [])
        hoy = datetime.now()
        limite = hoy - timedelta(days=4)
        log.info(
            "Procesando conversación %s asunto=%r modo=%s mensajes=%s ignore_date_limit=%s",
            conversation_key,
            asunto,
            modo or "(sin modo)",
            len(mensajes),
            ignore_date_limit,
        )

        for msg in mensajes:
            try:
                msg_id = msg.get("id")
                message_key = self._message_key(conversation_key, msg)
                if not ignore_already_sent and self._already_sent(message_key):
                    log.info("Mensaje %s omitido: ya fue enviado antes (%s)", msg_id, message_key)
                    continue

                creado_str, creado_dt = self._parse_created_datetime(msg)

                if not ignore_date_limit and creado_dt and creado_dt < limite:
                    log.info("Mensaje %s omitido por fecha: %s < %s", msg_id, creado_dt, limite)
                    continue

                notif, image_urls, adjunto_urls, is_image_only, adjuntos_solo_texto = self._build_notification(msg, asunto, creado_str)
                log.info(
                    "Mensaje %s listo para enviar: texto=%s imagenes=%s adjuntos=%s image_only=%s",
                    msg_id,
                    bool(notif["contenido"]),
                    len(image_urls),
                    len(adjunto_urls),
                    is_image_only,
                )

                if is_debate:
                    sent_id, new_root_id = self._send_debate_message(
                        notif,
                        is_image_only,
                        image_urls,
                        adjunto_urls,
                        root_message_id,
                        msg_id,
                        immich_options=immich_options,
                        conv_id=conv_id,
                        adjuntos_solo_texto=adjuntos_solo_texto,
                    )
                    if new_root_id is not None and root_message_id is None:
                        root_message_id = new_root_id
                        self._set_debate_root_message_id(conversation_key, root_message_id)
                else:
                    sent_id = self._send_direct_message(
                        notif,
                        is_image_only,
                        image_urls,
                        adjunto_urls,
                        msg_id,
                        immich_options=immich_options,
                        conv_id=conv_id,
                        adjuntos_solo_texto=adjuntos_solo_texto,
                    )

                send_to_immich = bool(immich_options and immich_options.get("immich"))
                if sent_id:
                    self._mark_sent(message_key)
                    log.info("Mensaje %s marcado como enviado (%s)", msg_id, message_key)
                elif send_to_immich:
                    log.info("Mensaje %s procesado en modo Immich (sin envío a Telegram)", msg_id)
                else:
                    log.warning("Mensaje %s no pudo enviarse a Telegram", msg_id)

            except Exception as e:
                log.warning("Error procesando mensaje id=%s, omitido: %s", msg.get("id"), e)

    # ------------------------------------------------------------------
    # Punto de entrada 
    # ------------------------------------------------------------------

    def run(self, conversation_ids: list[str] | None = None, immich_options: dict | None = None):
        if not self.login():
            log.error("Login fallido. Abortando ejecución.")
            return

        if conversation_ids:
            log.info("Modo manual: procesando conversaciones explícitas: %s", ", ".join(conversation_ids))
            messages = self.get_messages_by_conversation_ids(conversation_ids)
            for msg in messages:
                self.process_and_notify(
                    msg,
                    ignore_date_limit=True,
                    ignore_already_sent=True,
                    immich_options=immich_options,
                )
        else:
            notifications = self.get_unread()
            if notifications is None:
                log.warning("No se pudieron obtener notificaciones sin leer.")
                return

            messages = self.get_messages(notifications)
            for msg in messages:
                self.process_and_notify(msg)

        log.info("Check finalizado: %s", datetime.now())


if __name__ == "__main__":
    mqtt_payload = os.getenv("MQTT_PAYLOAD", "")
    ids = get_requested_conversation_ids(sys.argv[1:], mqtt_payload)
    immich_opts = get_immich_options_from_payload(mqtt_payload)
    AcadeuMonitor().run(conversation_ids=ids, immich_options=immich_opts)
