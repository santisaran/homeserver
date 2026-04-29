import logging
from collections.abc import Sequence

import requests


class AcadeuClient:
    def __init__(
        self,
        username: str | None,
        password: str | None,
        logger: logging.Logger,
        base_url: str = "https://plataforma.acadeu.com",
    ):
        self.username = username
        self.password = password
        self.base_url = base_url
        self.init_url = f"{base_url}/i/nuestra-tierra"
        self.login_url = f"{base_url}/j_spring_security_check"
        self.unread_url = f"{base_url}/conversaciones/sin-leer"
        self.log = logger
        self.session: requests.Session | None = None

    def login(self) -> bool:
        try:
            self.session = requests.Session()
            self.session.get(self.init_url, timeout=15)
            self.session.post(
                self.login_url,
                data={
                    "institucion": "nuestra-tierra",
                    "j_username": self.username,
                    "j_password": self.password,
                },
                timeout=15,
            )
            self.log.info("Sesión iniciada correctamente.")
            return True
        except Exception as e:
            self.log.error("No se pudo iniciar sesión: %s", e)
            self.session = None
            return False

    def _safe_request(self, method: str, url: str, **kwargs) -> requests.Response | None:
        if self.session is None:
            self.log.error("No hay sesión activa para hacer la request.")
            return None
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            self.log.warning("Request fallido [%s %s]: %s", method.upper(), url, e)
            return None

    def get_unread(self) -> dict | None:
        resp = self._safe_request("POST", self.unread_url)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError as e:
            self.log.warning("Respuesta de 'sin-leer' no es JSON válido: %s", e)
            return None

    def get_messages(self, notifications: dict) -> list[dict]:
        messages = []
        conversations = (
            notifications.get("conversaciones", {}).get("sinLeer", [])
            if notifications
            else []
        )

        for conv in conversations:
            ver = conv.get("verConversacion")
            if not ver:
                self.log.warning("Conversación sin 'verConversacion', omitida: %s", conv)
                continue

            resp = self._safe_request(
                "POST",
                f"{self.base_url}{ver}",
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
                self.log.warning("Respuesta de conversación no es JSON válido: %s", e)

        return messages

    def get_messages_by_conversation_ids(self, conversation_ids: Sequence[str]) -> list[dict]:
        messages = []
        for conv_id in conversation_ids:
            clean_id = str(conv_id).strip()
            if not clean_id:
                continue

            resp = self._safe_request(
                "POST",
                f"{self.base_url}/conversaciones/{clean_id}",
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            )
            if resp is None:
                continue

            try:
                conversation = resp.json()
                message_count = len(
                    conversation.get("viewModel", {}).get("data", {}).get("mensajes", [])
                )
                self.log.info(
                    "Conversación %s obtenida: estado=%s mensajes=%s",
                    clean_id,
                    conversation.get("estado"),
                    message_count,
                )
                messages.append(conversation)
            except ValueError as e:
                self.log.warning(
                    "Respuesta de conversación %s no es JSON válido: %s",
                    clean_id,
                    e,
                )

        return messages

    def download_image(self, image_url: str) -> tuple[bytes, str] | None:
        if self.session is None:
            self.log.warning("No hay sesión activa para descargar imágenes.")
            return None

        try:
            self.log.info("Descargando imagen de Acadeu: %s", image_url)
            img_resp = self.session.get(image_url, timeout=20)
            img_resp.raise_for_status()
            return img_resp.content, img_resp.headers.get("Content-Type", "")
        except Exception as e:
            self.log.warning("Error descargando imagen de Acadeu (%s): %s", image_url, e)
            return None
