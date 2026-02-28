#!/bin/bash
# =============================================================================
# setup.sh — Script de arranque inicial del servidor doméstico
#
# Ejecutar UNA VEZ después de una instalación limpia.
# Requiere Docker instalado.
# =============================================================================

set -e

DOCKERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_DISK="/mnt/externo"

echo "=== [1/6] Creando red Docker compartida para nginx (proxy_net) ==="
docker network create proxy_net 2>/dev/null && echo "  ✓ proxy_net creada" \
  || echo "  ⚠ proxy_net ya existe, continuando..."

echo ""
echo "=== [2/6] Verificando disco externo ==="
if mountpoint -q "$MEDIA_DISK"; then
    echo "  ✓ $MEDIA_DISK está montado"
else
    echo "  ✗ ATENCIÓN: $MEDIA_DISK no está montado."
    echo "    Jellyfin, Music Assistant, Syncthing, Paperless y Nextcloud lo necesitan."
    echo "    Agrega la entrada en /etc/fstab antes de continuar."
fi

echo ""
echo "=== [3/6] Verificando grupos de renderizado (necesario para Immich/Jellyfin) ==="
RENDER_GID=$(getent group render | cut -d: -f3)
VIDEO_GID=$(getent group video | cut -d: -f3)
echo "  Grupo 'render': ${RENDER_GID:-NO EXISTE}"
echo "  Grupo 'video':  ${VIDEO_GID:-NO EXISTE}"
echo "  → Actualiza estos valores en immich/docker-compose.yaml si difieren."

echo ""
echo "=== [4/6] Preparando archivos de entorno (.env) ==="

for template_file in $(find "$DOCKERS_DIR" -name "*.env.template"); do
    target="${template_file%.template}"
    if [ ! -f "$target" ]; then
        cp "$template_file" "$target"
        echo "  ✓ Creado: $target — EDITAR con tus datos antes de levantar el stack"
    else
        echo "  - $(basename $target) ya existe, no sobreescribiendo"
    fi
done

# Certbot duckdns.ini
DUCKDNS_TEMPLATE="$DOCKERS_DIR/nginx/certbot/duckdns.ini.template"
DUCKDNS_TARGET="$DOCKERS_DIR/nginx/certbot/duckdns.ini"
if [ ! -f "$DUCKDNS_TARGET" ]; then
    cp "$DUCKDNS_TEMPLATE" "$DUCKDNS_TARGET"
    chmod 600 "$DUCKDNS_TARGET"
    echo "  ✓ Creado: $DUCKDNS_TARGET — AGREGAR tu token DuckDNS"
fi

echo ""
echo "=== [5/6] Orden recomendada para levantar los stacks ==="
cat << 'EOF'

  1. nginx          → primero, establece el proxy reverso + certbot
  2. dockge         → gestor de stacks (UI en http://localhost:5001)
  ─── HomeAuto ───
  3. hass           → Home Assistant + Z2M + MQTT + Node-RED + OTBR
  ─── Media ──────
  4. jellyfin       → servidor de medios
  5. musicassistant → música
  ─── Fotos ──────
  6. syncthing      → sincronización de fotos desde celulares
  7. immich         → galería de fotos (levantar DESPUÉS de syncthing)
  ─── Documentos ─
  8. paperless      → gestión de documentos
  ─── Red ────────
  9. wg-easy        → VPN WireGuard
  ─── Extras ─────
  10. flame         → dashboard de inicio
  11. transmission  → cliente torrent
  12. minecraft     → servidor Minecraft

  Levanta cada stack con: cd <nombre> && docker compose up -d

EOF

echo "  Cuando todos estén arriba, obtener el certificado SSL con:"
echo ""
echo "    cd nginx"
echo "    docker compose run --rm certbot certonly \\"
echo "      --authenticator dns-duckdns \\"
echo "      --dns-duckdns-credentials /etc/letsencrypt/duckdns.ini \\"
echo "      --dns-duckdns-propagation-seconds 60 \\"
echo "      -d terispi.duckdns.org \\"
echo "      -d '*.terispi.duckdns.org'"
echo ""

echo "=== [6/6] Configurando backups automáticos con Restic + Backblaze B2 ==="

# Instalar restic si no está
if ! command -v restic &>/dev/null; then
    echo "  Instalando restic..."
    sudo apt-get install -y restic 2>/dev/null || {
        echo "  apt no disponible, descargando binario..."
        RESTIC_VERSION=$(curl -s https://api.github.com/repos/restic/restic/releases/latest | grep '"tag_name"' | cut -d'"' -f4 | tr -d v)
        curl -fsSL "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2" | bunzip2 > /tmp/restic
        sudo install -m 755 /tmp/restic /usr/local/bin/restic
    }
    echo "  ✓ restic instalado: $(restic version)"
else
    echo "  ✓ restic ya instalado: $(restic version)"
fi

# Instalar units de systemd
BACKUP_DIR="$DOCKERS_DIR/backup"
if [ -f "$BACKUP_DIR/restic-backup.service" ]; then
    chmod +x "$BACKUP_DIR/backup.sh"
    sudo cp "$BACKUP_DIR/restic-backup.service" /etc/systemd/system/
    sudo cp "$BACKUP_DIR/restic-backup.timer"   /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now restic-backup.timer
    echo "  ✓ Timer de backup habilitado (diario a las 3:00 AM)"
    echo "  → Ver estado:    systemctl status restic-backup.timer"
    echo "  → Backup manual: sudo systemctl start restic-backup.service"
    echo "  → Ver logs:      journalctl -u restic-backup -f"
else
    echo "  ✗ No se encontraron las units. Copiá los archivos del repo primero."
fi

echo ""
echo "  IMPORTANTE: Editar $BACKUP_DIR/.env con tu Key ID y Application Key de B2"
echo "  antes de ejecutar el primer backup."
echo ""
echo "=== Setup completo. Revisa los .env antes de levantar los stacks. ==="
