#!/bin/bash
# =============================================================================
# backup.sh — Backup incremental cifrado a Backblaze B2 con Restic
#
# Qué respalda:
#   - Configs y datos de todos los stacks Docker
#   - Excluye: media (videos/música ya en disco externo), downloads, caché
#
# Dependencias: restic, docker
# Instalar restic: https://restic.readthedocs.io/en/stable/020_installation.html
#   sudo apt install restic   (o descarga el binario)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Cargar variables de entorno ──────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "ERROR: $SCRIPT_DIR/.env no existe. Copiá .env.template y completalo." >&2
    exit 1
fi
# shellcheck source=.env
source "$SCRIPT_DIR/.env"

# ─── Variables de Restic/B2 ───────────────────────────────────────────────────
export RESTIC_REPOSITORY="b2:${B2_BUCKET}:homeserver"
export RESTIC_PASSWORD
export B2_ACCOUNT_ID
export B2_ACCOUNT_KEY

LOG_FILE="$SCRIPT_DIR/backup.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$TIMESTAMP] $*" | tee -a "$LOG_FILE"; }

log "═══════════════════════════════════════"
log "Iniciando backup"

# ─── Inicializar repositorio si no existe ─────────────────────────────────────
if ! restic snapshots &>/dev/null; then
    log "Repositorio no encontrado. Inicializando en B2..."
    restic init
fi

# ─── Detener contenedores con base de datos antes del backup ─────────────────
# Evita backups de DBs en estado inconsistente.
DB_CONTAINERS=(
    "immich_postgres"
    "paperless-ngx-db-1"
)

log "Deteniendo contenedores de base de datos..."
for ct in "${DB_CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${ct}$"; then
        docker stop "$ct" && log "  ✓ Detenido: $ct"
    fi
done

# ─── Backup ───────────────────────────────────────────────────────────────────
log "Ejecutando restic backup..."

restic backup \
    --verbose \
    --tag "homeserver" \
    --tag "$(hostname)" \
    \
    "$DOCKERS_DIR/hass/homeassistant" \
    "$DOCKERS_DIR/hass/zigbee2mqtt" \
    "$DOCKERS_DIR/hass/mosquitto" \
    "$DOCKERS_DIR/hass/nodered" \
    "$DOCKERS_DIR/hass/otbr" \
    \
    "$DOCKERS_DIR/immich/pgdata" \
    "$DOCKERS_DIR/immich/.env" \
    \
    "$DOCKERS_DIR/paperless/data" \
    "$DOCKERS_DIR/paperless/media" \
    "$DOCKERS_DIR/paperless/pgdata" \
    \
    "$DOCKERS_DIR/esphome/config" \
    \
    "$DOCKERS_DIR/jellyfin/config" \
    \
    "$DOCKERS_DIR/wg-easy/data" \
    \
    "$DOCKERS_DIR/flame/data" \
    \
    "$DOCKERS_DIR/nginx/nginx/conf" \
    "$DOCKERS_DIR/nginx/certbot/conf" \
    \
    "$DOCKERS_DIR/transmission/config" \
    \
    --exclude "*.log" \
    --exclude "*.tmp" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    2>&1 | tee -a "$LOG_FILE"

# ─── Reiniciar contenedores detenidos ─────────────────────────────────────────
log "Reiniciando contenedores de base de datos..."
for ct in "${DB_CONTAINERS[@]}"; do
    if docker inspect "$ct" &>/dev/null; then
        docker start "$ct" && log "  ✓ Reiniciado: $ct"
    fi
done

# ─── Política de retención ────────────────────────────────────────────────────
log "Aplicando política de retención..."
restic forget \
    --keep-daily  "${KEEP_DAILY:-7}" \
    --keep-weekly "${KEEP_WEEKLY:-4}" \
    --keep-monthly "${KEEP_MONTHLY:-6}" \
    --prune \
    2>&1 | tee -a "$LOG_FILE"

# ─── Verificación de integridad (una vez por semana, los domingos) ────────────
if [ "$(date +%u)" = "7" ]; then
    log "Domingo: verificando integridad del repositorio..."
    restic check 2>&1 | tee -a "$LOG_FILE"
fi

log "Backup completado."
log "═══════════════════════════════════════"
