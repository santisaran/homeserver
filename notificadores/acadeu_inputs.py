import argparse
import json


def parse_conversation_ids(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(
        description="Notificador de mensajes de Nuestra Tierra",
    )
    parser.add_argument(
        "conversation_ids",
        nargs="*",
        help="Uno o mas IDs de conversacion. Tambien admite valores separados por coma.",
    )
    args = parser.parse_args(argv)

    normalized: list[str] = []
    for value in args.conversation_ids:
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        normalized.extend(parts)

    return normalized


def extract_conversation_ids_from_payload(payload_text: str) -> list[str]:
    if not payload_text or not payload_text.strip():
        return []

    raw = payload_text.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Solo aceptar como IDs las partes que sean numéricas.
        # Payloads de trigger como "start" se ignoran.
        parts = [p.strip() for p in raw.split(",") if p.strip().isdigit()]
        return parts

    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]

    if not isinstance(payload, dict):
        value = str(payload).strip()
        return [value] if value else []

    raw_ids = payload.get("message_ids")
    if raw_ids is None:
        raw_ids = payload.get("message_id")
    if raw_ids is None:
        raw_ids = payload.get("conversation_ids")
    if raw_ids is None:
        raw_ids = payload.get("conversation_id")

    if isinstance(raw_ids, list):
        return [str(item).strip() for item in raw_ids if str(item).strip()]
    if raw_ids not in (None, ""):
        value = str(raw_ids).strip()
        return [value] if value else []

    return []


def get_requested_conversation_ids(argv: list[str], mqtt_payload: str = "") -> list[str]:
    cli_ids = parse_conversation_ids(argv)
    if cli_ids:
        return cli_ids

    return extract_conversation_ids_from_payload(mqtt_payload)


def get_immich_options_from_payload(mqtt_payload: str) -> dict:
    """
    Extrae opciones de Immich del payload MQTT.
    Retorna {'immich': bool, 'album_name': str | None}.
    """
    if not mqtt_payload or not mqtt_payload.strip():
        return {"immich": False, "album_name": None}

    try:
        payload = json.loads(mqtt_payload.strip())
    except json.JSONDecodeError:
        return {"immich": False, "album_name": None}

    if not isinstance(payload, dict):
        return {"immich": False, "album_name": None}

    immich = bool(payload.get("immich", False))
    album_name = payload.get("album_name") or None
    return {"immich": immich, "album_name": album_name}
