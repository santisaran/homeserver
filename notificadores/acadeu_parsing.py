import hashlib
import html
import re


def pick_first_nonempty(data: dict, keys: list[str], default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def conversation_mode(data: dict) -> str:
    mode = pick_first_nonempty(
        data,
        ["modo", "tipo", "tipoConversacion", "modoConversacion"],
        default="",
    )
    return mode.upper()


def conversation_key(data: dict, asunto: str) -> str:
    raw_key = pick_first_nonempty(
        data,
        ["id", "idConversacion", "conversacionId", "uuid", "codigo"],
        default="",
    )
    if raw_key:
        return f"conv:{raw_key}"

    fallback = hashlib.sha256(asunto.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"conv:asunto:{fallback}"


def message_key(conversation_key_value: str, msg: dict) -> str:
    msg_id = msg.get("id")
    if msg_id not in (None, ""):
        return f"{conversation_key_value}:msg:{msg_id}"

    seed = "|".join(
        [
            str(msg.get("creado", "")),
            str(msg.get("creadoFormateado", "")),
            str(msg.get("de", {}).get("nombreCompleto", "")),
            str(msg.get("cuerpo", ""))[:120],
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{conversation_key_value}:msg:hash:{digest}"


def strip_html(html_content: str) -> str:
    # Basic conversion of some tags to Telegram HTML supported tags
    text = html_content
    # Replace common block elements with newlines first
    text = re.sub(r"<(p|div|br\s*/?|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove all other tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Handle non-breaking spaces
    text = text.replace("\xa0", " ")
    # Normalize whitespaces but keep some newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    # Escape for Telegram HTML
    text = html.escape(text)
    return text


def extract_image_urls(html_content: str) -> list[str]:
    if not html_content:
        return []

    matches = re.findall(
        r'<img[^>]+src=["\']([^"\']+)["\']',
        html_content,
        flags=re.IGNORECASE,
    )
    return [html.unescape(url) for url in matches if url]
