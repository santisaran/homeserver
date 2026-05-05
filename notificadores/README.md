# MQTT messages soportados por el worker

Este proyecto tiene un `worker.py` que escucha dos topics MQTT:

- `home/scripts/etig`
- `home/scripts/acadeu`

## 1) Topic `home/scripts/etig`

Cualquier payload dispara `notificador_etig.py`.
El contenido del mensaje no se usa para filtrar ni parametrizar.

Ejemplos:

```bash
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/etig" -m "start"
```

```bash
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/etig" -m "{}"
```

## 2) Topic `home/scripts/acadeu`

Dispara `acadeu_notificador.py`.
Puede recibir IDs de conversación/mensaje y opciones de Immich.

### 2.1 Formatos de IDs aceptados

Se aceptan estos formatos para indicar qué conversación(es) procesar:

- JSON con `message_id`, `message_ids`, `conversation_id` o `conversation_ids`
- JSON array
- String simple
- String con IDs numéricos separados por coma

Ejemplos válidos:

```bash
# Un ID
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" -m '{"message_id": 19031650}'
```

```bash
# Varios IDs
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" -m '{"message_ids": [19031650, 19031651]}'
```

```bash
# Alias conversation_id
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" -m '{"conversation_id": "19031650"}'
```

```bash
# JSON array
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" -m '[19031650, 19031651]'
```

```bash
# Texto (solo números separados por coma)
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" -m '19031650,19031651'
```

Notas:

- Si no hay IDs, el script cae en modo normal (lee no leídos).
- Si enviás texto no JSON, solo se toman como IDs los segmentos numéricos.

### 2.2 Opciones de Immich

Se leen solo desde JSON objeto:

- `immich`: `true` o `false`
- `album_name`: string (opcional)

Ejemplo:

```bash
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" \
  -m '{"message_id": 19031650, "immich": true, "album_name": ""}'
```

Con álbum:

```bash
mosquitto_pub -h "$MQTT_BROKER" -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "home/scripts/acadeu" \
  -m '{"message_id": 19031650, "immich": true, "album_name": "Colegio"}'
```

## 3) Payloads que no rompen pero no parametrizan

En `home/scripts/acadeu`, estos payloads no generan error, pero no activan parámetros útiles:

- JSON inválido sin números (ej: `start`)
- JSON que no sea objeto/lista (ej: `true`, `123`) sin IDs explícitos

En esos casos, el script suele ejecutar en modo normal (notificaciones sin leer).
