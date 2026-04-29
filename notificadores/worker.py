import paho.mqtt.client as mqtt
import subprocess
import dotenv
import os
import logging
import sys

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
    "home/scripts/acadeu": "notificador_acadeu_nuestra_tierra.py"
}


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


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        log.info("Worker MQTT escuchando...")
        client.loop_forever()
    except Exception as e:
        log.error("Error en worker MQTT: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
