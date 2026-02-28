#!/bin/bash
# =============================================================================
# restore.sh — Restaurar backup desde Backblaze B2 con Restic
#
# Uso:
#   bash restore.sh                     # restaura el último snapshot
#   bash restore.sh <snapshot-id>       # restaura un snapshot específico
#   bash restore.sh --list              # lista snapshots disponibles
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "ERROR: $SCRIPT_DIR/.env no existe." >&2
    exit 1
fi
source "$SCRIPT_DIR/.env"

export RESTIC_REPOSITORY="b2:${B2_BUCKET}:homeserver"
export RESTIC_PASSWORD
export B2_ACCOUNT_ID
export B2_ACCOUNT_KEY

# ─── Modo lista ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "--list" ]; then
    echo "Snapshots disponibles:"
    restic snapshots --compact
    exit 0
fi

SNAPSHOT="${1:-latest}"

echo "════════════════════════════════════════"
echo "  Restaurando snapshot: $SNAPSHOT"
echo "  Destino: $DOCKERS_DIR"
echo "════════════════════════════════════════"
echo ""
echo "⚠  ATENCIÓN: Esto sobreescribirá los datos actuales en $DOCKERS_DIR"
read -rp "   ¿Confirmar? (s/N): " confirm
[[ "$confirm" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }

# ─── Detener todos los contenedores antes de restaurar ────────────────────────
echo ""
echo "[1/3] Deteniendo contenedores..."
docker ps -q | xargs -r docker stop && echo "  ✓ Contenedores detenidos"

# ─── Restaurar ────────────────────────────────────────────────────────────────
echo ""
echo "[2/3] Restaurando desde B2..."
restic restore "$SNAPSHOT" \
    --target / \
    --verbose

echo ""
echo "[3/3] Reiniciando stacks..."
# Levanta en orden correcto
STACKS=(nginx dockge hass jellyfin musicassistant syncthing immich paperless wg-easy flame transmission)
for stack in "${STACKS[@]}"; do
    STACK_DIR="$DOCKERS_DIR/$stack"
    if [ -f "$STACK_DIR/docker-compose.yaml" ] || [ -f "$STACK_DIR/docker-compose.yml" ]; then
        echo "  → Levantando $stack..."
        (cd "$STACK_DIR" && docker compose up -d) && echo "    ✓ $stack"
    fi
done

echo ""
echo "════════════════════════════════════════"
echo "  Restauración completada."
echo "  Revisá los logs con: docker compose logs -f"
echo "════════════════════════════════════════"
