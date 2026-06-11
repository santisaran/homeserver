import paho.mqtt.client as mqtt
import subprocess
import dotenv
import os
import json
import logging
import sys
import asyncio
import websockets
from pathlib import Path
from datetime import datetime
from aiohttp import web

from telegram_client import TelegramClient

dotenv.load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",

    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

log.info("Iniciando Worker MQTT...")

MQTT_USER = os.getenv("MQTT_USER", "mqtt_user")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mqtt_password")
MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.1.118")
MQTT_PORT = 1883
TOPICOS = {
    "home/scripts/etig": "notificador_etig.py",
    "home/scripts/acadeu": "acadeu_notificador.py"
}

# WebSocket
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", "8765"))
ws_clients = set()

# Webhook
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8766"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # e.g. https://notif.terispi.duckdns.org/webhook
CLIENT_HTML = Path(__file__).with_name("websocket-client.html")


def publish_immich_request(mqtt_client: mqtt.Client, conv_id: str, album_name: str, source: str) -> None:
    payload = json.dumps({
        "message_id": conv_id,
        "immich": True,
        "album_name": album_name,
    })
    mqtt_client.publish("home/scripts/acadeu", payload)
    log.info("%s Immich: conv_id=%s album=%r -> MQTT publicado", source, conv_id, album_name)


def publish_telegram_request(mqtt_client: mqtt.Client, conv_id: str, source: str) -> None:
    payload = json.dumps({
        "message_id": conv_id,
    })
    mqtt_client.publish("home/scripts/acadeu", payload)
    log.info("%s Telegram: conv_id=%s -> MQTT publicado", source, conv_id)


def on_connect(client, userdata, connect_flags, reason_code, properties):
    if reason_code == 0:
        log.info("Conectado al broker MQTT")
        for topico in TOPICOS.keys():
            client.subscribe(topico)
            log.info("Suscripto a %s", topico)
    else:
        log.error("Error de conexión, código: %s", reason_code)
        client.disconnect()


def on_message(client, userdata, msg):
    payload_text = msg.payload.decode(errors="replace")
    log.info("Mensaje recibido en %s: %s", msg.topic, payload_text)
    script = TOPICOS.get(msg.topic)
    if script:
        log.info("Ejecutando %s con payload MQTT reenviado al entorno del proceso.", script)
        env = os.environ.copy()
        env["MQTT_PAYLOAD"] = payload_text
        env["MQTT_TOPIC"] = msg.topic
        subprocess.Popen(["python3", script], env=env)


async def broadcast_ws(event_type: str, data: dict):
    """Envía un evento a todos los clientes WebSocket conectados."""
    if not ws_clients:
        return
    
    message = json.dumps({
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        "data": data
    })
    
    disconnected = set()
    for ws in ws_clients:
        try:
            await ws.send(message)
        except Exception as e:
            log.warning("Error enviando a WebSocket: %s", e)
            disconnected.add(ws)
    
    # Limpiar clientes desconectados
    for ws in disconnected:
        ws_clients.discard(ws)


async def handle_ws_client(websocket, mqtt_client: mqtt.Client):
    """Maneja conexiones de clientes WebSocket."""
    ws_clients.add(websocket)
    log.info("Cliente WebSocket conectado. Total: %d", len(ws_clients))
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                command = data.get("command")
                _payload = data.get("data", {})
                
                if command == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                elif command == "subscribe":
                    # El cliente se suscribe a eventos
                    await websocket.send(json.dumps({
                        "type": "subscribed",
                        "message": "Conectado al worker"
                    }))
                    log.info("Cliente suscripto a eventos")
                elif command == "save_immich":
                    conv_id = str(_payload.get("message_id", "")).strip()
                    album_name = str(_payload.get("album_name", "")).strip()
                    if not conv_id:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Falta message_id",
                        }))
                        continue

                    publish_immich_request(mqtt_client, conv_id, album_name, "WebSocket")
                    await broadcast_ws("immich_requested", {
                        "message_id": conv_id,
                        "immich": True,
                        "album_name": album_name,
                        "source": "websocket",
                    })
                    await websocket.send(json.dumps({
                        "type": "ack",
                        "message": "Solicitud enviada",
                        "data": {
                            "message_id": conv_id,
                            "album_name": album_name,
                        },
                    }))
                elif command == "send_telegram":
                    conv_id = str(_payload.get("message_id", "")).strip()
                    if not conv_id:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Falta message_id",
                        }))
                        continue

                    publish_telegram_request(mqtt_client, conv_id, "WebSocket")
                    await broadcast_ws("telegram_requested", {
                        "message_id": conv_id,
                        "source": "websocket",
                    })
                    await websocket.send(json.dumps({
                        "type": "ack",
                        "message": "Solicitud de envio a Telegram enviada",
                        "data": {
                            "message_id": conv_id,
                        },
                    }))
                else:
                    log.warning("Comando WebSocket desconocido: %s", command)
            except json.JSONDecodeError:
                log.warning("Mensaje WebSocket inválido: %s", message)
    except websockets.exceptions.ConnectionClosed:
        log.info("Cliente WebSocket desconectado")
    finally:
        ws_clients.discard(websocket)
        log.info("Cliente removido. Total: %d", len(ws_clients))


async def start_websocket_server(mqtt_client: mqtt.Client):
    """Inicia el servidor WebSocket."""
    log.info("Iniciando servidor WebSocket en ws://%s:%d", WS_HOST, WS_PORT)
    # Silenciar los errores de handshake de clientes HTTP que no son WebSocket
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    async with websockets.serve(lambda ws: handle_ws_client(ws, mqtt_client), WS_HOST, WS_PORT):
        await asyncio.Future()  # run forever


async def handle_telegram_webhook(request: web.Request, mqtt_client: mqtt.Client) -> web.Response:
    """Recibe actualizaciones de Telegram via webhook POST."""
    if WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != WEBHOOK_SECRET:
            log.warning("Webhook: token secreto inválido desde %s", request.remote)
            return web.Response(status=403)

    try:
        update = await request.json()
    except Exception as e:
        log.warning("Webhook: payload inválido: %s", e)
        return web.Response(status=400)

    cb = update.get("callback_query")
    if cb:
        data_str = cb.get("data", "")
        if data_str.startswith("immich:"):
            parts = data_str.split(":", 2)  # ["immich", "<conv_id>"] o ["immich", "<conv_id>", "<album>"]
            conv_id = parts[1] if len(parts) > 1 else ""
            album_name = parts[2] if len(parts) > 2 else ""

            publish_immich_request(mqtt_client, conv_id, album_name, "Webhook")

            await broadcast_ws("telegram_callback", {
                "message_id": conv_id,
                "immich": True,
                "album_name": album_name,
                "source": "telegram",
            })

            token = os.getenv("TELEGRAM_BOT_TOKEN")
            TelegramClient(token, None, log).answer_callback_query(cb["id"], text="✅ Guardando en Immich…")

    return web.Response(status=200)


async def start_webhook_server(mqtt_client: mqtt.Client):
    """Inicia el servidor HTTP para recibir webhooks de Telegram."""
    app = web.Application()
    app.router.add_post("/webhook", lambda r: handle_telegram_webhook(r, mqtt_client))

    async def handle_webhook_get(_request: web.Request) -> web.Response:
        return web.Response(
            content_type="application/json",
            text='{"ok":true,"status":"webhook activo"}',
        )

    app.router.add_get("/webhook", handle_webhook_get)

    async def handle_client_page(_request: web.Request) -> web.Response:
        if not CLIENT_HTML.exists():
            return web.Response(status=404, text="websocket-client.html no encontrado")
        return web.FileResponse(CLIENT_HTML)

    app.router.add_get("/client", handle_client_page)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    log.info("Servidor webhook escuchando en http://%s:%d/webhook", WEBHOOK_HOST, WEBHOOK_PORT)

    # Registrar el webhook con Telegram al arrancar
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token and WEBHOOK_URL:
        tg = TelegramClient(token, None, log)
        tg.set_webhook(WEBHOOK_URL, secret=WEBHOOK_SECRET)
    elif not WEBHOOK_URL:
        log.warning("WEBHOOK_URL no configurada; el webhook de Telegram no se registrará automáticamente.")

    await asyncio.Future()  # run forever


async def async_main(mqtt_client: mqtt.Client):
    await asyncio.gather(
        start_websocket_server(mqtt_client),
        start_webhook_server(mqtt_client),
    )


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        log.info("Worker MQTT conectado. Iniciando servidores async...")
        client.loop_start()  # MQTT en su propio hilo, no bloqueante
        asyncio.run(async_main(client))
    except KeyboardInterrupt:
        log.info("Deteniendo worker...")
    except Exception as e:
        log.error("Error en worker: %s", e, exc_info=True)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
