import logging
import mimetypes
import uuid
from datetime import datetime, timezone

import requests


class ImmichClient:
    def __init__(self, base_url: str, api_key: str, logger: logging.Logger):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.log = logger

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key}

    def upload_asset(
        self,
        image_content: bytes,
        content_type: str = "image/jpeg",
        filename: str | None = None,
        created_at: datetime | None = None,
    ) -> str | None:
        """Sube un asset a Immich. Devuelve el asset_id o None si falla."""
        if filename is None:
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".jpg"
            filename = f"upload{ext}"

        now = (created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        device_asset_id = str(uuid.uuid4())

        url = f"{self.base_url}/api/assets"
        files = {"assetData": (filename, image_content, content_type)}
        data = {
            "deviceAssetId": device_asset_id,
            "deviceId": "acadeu-notificador",
            "fileCreatedAt": now,
            "fileModifiedAt": now,
            "isFavorite": "false",
        }

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                data=data,
                files=files,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            asset_id = result.get("id")
            if asset_id:
                self.log.info("Immich: asset subido correctamente: %s", asset_id)
            else:
                self.log.warning("Immich: respuesta sin id: %s", result)
            return asset_id
        except requests.HTTPError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            self.log.warning("Immich: error subiendo asset: %s | respuesta: %s", e, body)
            return None
        except Exception as e:
            self.log.warning("Immich: error subiendo asset: %s", e)
            return None

    def get_or_create_album(self, album_name: str) -> str | None:
        """Busca un álbum por nombre o lo crea. Devuelve el album_id o None si falla."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/albums",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            for album in resp.json():
                if album.get("albumName") == album_name:
                    album_id = album.get("id")
                    self.log.info(
                        "Immich: álbum existente encontrado: %s (%s)", album_name, album_id
                    )
                    return album_id
        except Exception as e:
            self.log.warning("Immich: error buscando álbumes: %s", e)
            return None

        try:
            resp = requests.post(
                f"{self.base_url}/api/albums",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"albumName": album_name},
                timeout=10,
            )
            resp.raise_for_status()
            album_id = resp.json().get("id")
            self.log.info("Immich: álbum creado: %s (%s)", album_name, album_id)
            return album_id
        except Exception as e:
            self.log.warning("Immich: error creando álbum: %s", e)
            return None

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> bool:
        """Agrega assets a un álbum. Devuelve True si tuvo éxito."""
        try:
            resp = requests.put(
                f"{self.base_url}/api/albums/{album_id}/assets",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"ids": asset_ids},
                timeout=10,
            )
            resp.raise_for_status()
            self.log.info(
                "Immich: %s asset(s) agregado(s) al álbum %s", len(asset_ids), album_id
            )
            return True
        except Exception as e:
            self.log.warning("Immich: error agregando assets al álbum: %s", e)
            return False

    def upload_to_album(
        self,
        image_content: bytes,
        content_type: str = "image/jpeg",
        filename: str | None = None,
        album_name: str | None = None,
        created_at: datetime | None = None,
    ) -> str | None:
        """
        Sube una imagen a Immich y, si se indica album_name, la agrega al álbum
        (creándolo si no existe). Devuelve el asset_id o None si falla.
        """
        asset_id = self.upload_asset(image_content, content_type, filename, created_at)
        if asset_id is None:
            return None

        if album_name:
            album_id = self.get_or_create_album(album_name)
            if album_id:
                self.add_assets_to_album(album_id, [asset_id])

        return asset_id
