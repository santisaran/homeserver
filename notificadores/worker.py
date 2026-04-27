import paho.mqtt.client as mqtt
import subprocess
import dotenv
import os

print("Iniciando Worker MQTT...")

dotenv.load_dotenv()

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
        print("Conectado al broker MQTT")
        for topico in TOPICOS.keys():
            client.subscribe(topico)
            print(f"Suscripto a {topico}")
    else:
        print(f"Error de conexión, código: {reason_code}")
        client.disconnect()


def on_message(client, userdata, msg):
    print(f"Mensaje recibido en {msg.topic}: {msg.payload.decode()}")
    script = TOPICOS.get(msg.topic)
    if script:
        print(f"Ejecutando {script} por comando MQTT...")
        subprocess.Popen(["python3", script])


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        print("Worker MQTT escuchando...")
        client.loop_forever()
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
