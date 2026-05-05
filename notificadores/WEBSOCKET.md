# Worker de Notificadores con WebSocket

Este worker maneja notificaciones de Telegram y las distribuye por MQTT y WebSocket.

## Características

- 📡 **MQTT**: Recibe mensajes y los distribuye a scripts locales
- 🔔 **Telegram**: Webhook de callbacks (sin polling)
- 🌐 **WebSocket**: Servidor de WebSocket para clientes en tiempo real
- 🔌 **Bidireccional**: Los clientes WebSocket pueden enviar comandos

## Configuración

### Variables de entorno (`.env`)

```env
# MQTT
MQTT_USER=mqtt_user
MQTT_PASSWORD=mqtt_password
MQTT_BROKER=192.168.1.118

# Telegram
TELEGRAM_BOT_TOKEN=tu_token_aqui
WEBHOOK_URL=https://notif.terispi.duckdns.org/webhook
WEBHOOK_SECRET=tu_token_secreto_largo

# Webhook server (interno)
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8766

# WebSocket (opcional)
WS_HOST=0.0.0.0
WS_PORT=8765
```

## Uso

### Docker Compose

```bash
# Construir y ejecutar
docker-compose up -d

# Ver logs
docker-compose logs -f notificadores-mqtt

# Parar
docker-compose down
```

### Acceso a WebSocket

**Localmente (sin HTTPS):**
```javascript
const ws = new WebSocket('ws://localhost:8765');
```

**Remotamente (con HTTPS via nginx):**
```javascript
const ws = new WebSocket('wss://notif.terispi.duckdns.org');
```

### Protocolo WebSocket

#### Cliente → Servidor

**Suscribirse a eventos:**
```json
{
  "command": "subscribe",
  "data": {}
}
```

**Ping (para mantener viva la conexión):**
```json
{
  "command": "ping",
  "data": {}
}
```

#### Servidor → Cliente

**Callback de Telegram:**
```json
{
  "type": "telegram_callback",
  "timestamp": "2026-04-29T10:30:45.123456",
  "data": {
    "message_id": "conv_123",
    "immich": true,
    "album_name": "Vacation",
    "source": "telegram"
  }
}
```

**Respuesta a suscripción:**
```json
{
  "type": "subscribed",
  "timestamp": "2026-04-29T10:30:45.123456",
  "message": "Conectado al worker"
}
```

**Pong:**
```json
{
  "type": "pong",
  "timestamp": "2026-04-29T10:30:45.123456"
}
```

## Cliente Web

Hay un cliente HTML de ejemplo en `websocket-client.html`. Puedes:

1. Abrirlo localmente en `file:///` para probar contra `localhost:8765`
2. Servirlo con nginx para acceso remoto

Para servir el cliente HTML con nginx:

```nginx
location /ws-client {
    alias /path/to/notificadores;
    try_files $uri $uri/ /websocket-client.html;
}
```

## Flujo de datos

```
Telegram Callback Button
  -> POST https://notif.terispi.duckdns.org/webhook
    -> nginx /webhook -> worker:8766
      -> MQTT publish (home/scripts/acadeu)
      -> WebSocket broadcast (clientes conectados)
      -> answerCallbackQuery (quita el spinner en Telegram)
```

## Seguridad en Nginx

La configuración en `nginx/nginx/conf/notificadores.conf` incluye:

- ✅ SSL/TLS (HTTPS/WSS)
- ✅ Ruta `/` para WebSocket
- ✅ Ruta `/webhook` para Telegram
- ✅ Reenvío de `X-Telegram-Bot-Api-Secret-Token`

Para mayor seguridad, puedes agregar restricción por IP:

```nginx
location / {
    allow 192.168.1.0/24;
    allow 10.0.0.0/8;
    deny all;
    
    proxy_pass http://host.docker.internal:8765;
    # ... resto de config
}
```

## Troubleshooting

### "Connection refused"
- Verifica que el container está corriendo: `docker-compose ps`
- Comprueba los logs: `docker-compose logs notificadores-mqtt`

### "WebSocket upgrade failed"
- Asegúrate de que nginx tiene los headers correctos
- Verifica que `Upgrade: websocket` y `Connection: upgrade` están presentes

### Telegram no entrega eventos
- Verifica que `WEBHOOK_URL` sea pública y use HTTPS
- Revisa que `WEBHOOK_SECRET` coincida en Telegram y en el worker
- Confirma que la ruta `/webhook` esté publicada en nginx

### Clientes se desconectan frecuentemente
- Ajusta `proxy_read_timeout` en el snippet de nginx si necesitas más tiempo
- Implementa reconexión automática en el cliente
