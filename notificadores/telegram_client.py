import logging
import mimetypes

import requests


class TelegramClient:
    def __init__(self, token: str | None, chat_id: str | None, logger: logging.Logger):
        self.token = token
        self.chat_id = chat_id
        self.log = logger

    def _message_id_from_response(self, resp: requests.Response, action: str) -> int | None:
        try:
            data = resp.json()
        except ValueError:
            self.log.warning(
                "Telegram devolvió una respuesta no JSON para %s: %s",
                action,
                resp.text[:500],
            )
            return None

        if not isinstance(data, dict):
            self.log.warning("Telegram devolvió una respuesta inesperada para %s: %s", action, data)
            return None

        if not data.get("ok", False):
            self.log.warning(
                "Telegram rechazó %s: error_code=%s description=%s",
                action,
                data.get("error_code"),
                data.get("description"),
            )
            return None

        message_id = data.get("result", {}).get("message_id")
        if message_id is None:
            self.log.warning("Telegram respondió ok para %s pero sin message_id: %s", action, data)
            return None

        self.log.info("Telegram %s enviado correctamente: message_id=%s", action, message_id)
        return message_id

    @staticmethod
    def immich_inline_keyboard(conv_id: str) -> dict:
        """Construye un inline keyboard con el botón 'Guardar en Immich'."""
        return {
            "inline_keyboard": [[
                {"text": "📷 Guardar en Immich", "callback_data": f"immich:{conv_id}"}
            ]]
        }

    def send_message(
        self,
        notification: dict,
        header: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> int | None:
        texto = (
            f"*{header}* \n\n"
            f"*Título:* {notification['titulo']}\n"
            f"*De:* {notification['emisor']}\n"
            f"*Fecha:* {notification['fecha']}\n\n"
            f"{notification['contenido']}"
        )
        return self.send_text(
            texto,
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )

    def send_text(
        self,
        text: str,
        parse_mode: str = "Markdown",
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> int | None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
            payload["allow_sending_without_reply"] = True
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return self._message_id_from_response(resp, "sendMessage")
        except Exception as e:
            self.log.warning("Error enviando a Telegram: %s", e)
            return None

    def send_photo(
        self,
        notification: dict,
        image_content: bytes,
        header: str,
        content_type: str = "",
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> int | None:
        caption = (
            f"{header}\n\n"
            f"Título: {notification['titulo']}\n"
            f"De: {notification['emisor']}\n"
            f"Fecha: {notification['fecha']}"
        )
        caption = caption[:1024]

        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".jpg"
        filename = f"nuestra_tierra{ext}"

        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        data = {
            "chat_id": self.chat_id,
            "caption": caption,
        }
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id
            data["allow_sending_without_reply"] = True
        if reply_markup is not None:
            import json as _json
            data["reply_markup"] = _json.dumps(reply_markup)

        files = {
            "photo": (
                filename,
                image_content,
                content_type or "application/octet-stream",
            )
        }

        try:
            resp = requests.post(url, data=data, files=files, timeout=20)
            resp.raise_for_status()
            return self._message_id_from_response(resp, "sendPhoto")
        except Exception as e:
            self.log.warning("Error enviando imagen a Telegram: %s", e)
            return None

    def send_document(
        self,
        file_content: bytes,
        filename: str,
        content_type: str = "",
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> int | None:
        url = f"https://api.telegram.org/bot{self.token}/sendDocument"
        data: dict = {"chat_id": self.chat_id}
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id
            data["allow_sending_without_reply"] = True

        files = {
            "document": (
                filename,
                file_content,
                content_type or "application/octet-stream",
            )
        }

        try:
            resp = requests.post(url, data=data, files=files, timeout=20)
            resp.raise_for_status()
            return self._message_id_from_response(resp, "sendDocument")
        except Exception as e:
            self.log.warning("Error enviando documento a Telegram: %s", e)
            return None

    def send_file(
        self,
        file_content: bytes,
        filename: str,
        content_type: str = "",
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> int | None:
        """Sends a photo if content_type is image/*, otherwise sends a document."""
        mime = content_type.split(";")[0].strip().lower()
        if mime.startswith("image/"):
            ext = mimetypes.guess_extension(mime) or ".jpg"
            safe_filename = filename or f"adjunto{ext}"
            url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            data: dict = {"chat_id": self.chat_id}
            if caption:
                data["caption"] = caption[:1024]
            if reply_to_message_id is not None:
                data["reply_to_message_id"] = reply_to_message_id
                data["allow_sending_without_reply"] = True
            files = {"photo": (safe_filename, file_content, content_type or "application/octet-stream")}
            try:
                resp = requests.post(url, data=data, files=files, timeout=20)
                resp.raise_for_status()
                return self._message_id_from_response(resp, "sendPhoto(adjunto)")
            except Exception as e:
                self.log.warning("Error enviando adjunto imagen a Telegram: %s", e)
                return None
        else:
            return self.send_document(
                file_content,
                filename,
                content_type,
                caption,
                reply_to_message_id,
            )

    # ------------------------------------------------------------------
    # Polling de callbacks de Telegram
    # ------------------------------------------------------------------

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        """Long-polling de getUpdates. Devuelve lista de updates (puede ser vacía)."""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params: dict = {"timeout": timeout, "allowed_updates": ["callback_query"]}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(url, params=params, timeout=timeout + 5)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        except Exception as e:
            self.log.warning("Error en getUpdates: %s", e)
        return []

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        """Responde a un callback_query para quitar el spinner del botón."""
        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            self.log.warning("Error en answerCallbackQuery: %s", e)

    def set_webhook(self, webhook_url: str, secret: str = "") -> bool:
        """Registra el webhook en la API de Telegram."""
        url = f"https://api.telegram.org/bot{self.token}/setWebhook"
        payload: dict = {
            "url": webhook_url,
            "allowed_updates": ["callback_query"],
        }
        if secret:
            payload["secret_token"] = secret
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                self.log.info("Webhook registrado en: %s", webhook_url)
                return True
            self.log.warning("Telegram rechazó setWebhook: %s", data)
            return False
        except Exception as e:
            self.log.warning("Error en setWebhook: %s", e)
            return False

    def delete_webhook(self) -> bool:
        """Elimina el webhook activo (vuelve al modo polling)."""
        url = f"https://api.telegram.org/bot{self.token}/deleteWebhook"
        try:
            resp = requests.post(url, json={"drop_pending_updates": False}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                self.log.info("Webhook eliminado correctamente")
                return True
            self.log.warning("Error eliminando webhook: %s", data)
            return False
        except Exception as e:
            self.log.warning("Error en deleteWebhook: %s", e)
            return False
