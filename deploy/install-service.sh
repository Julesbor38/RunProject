#!/usr/bin/env bash
# Installs (or updates) the trailmap systemd service for the current user and repository.
# Usage: deploy/install-service.sh [data_dir]   (default: <repo>/data)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$(realpath -m "${1:-$REPO/data}")"
USER_NAME="$(id -un)"
UNIT=/etc/systemd/system/trailmap.service

if [ ! -x "$REPO/backend/.venv/bin/uvicorn" ]; then
  echo "backend/.venv manquant : lancer d'abord ./deploy-local.sh (ou créer le venv, voir CLAUDE.md)" >&2
  exit 1
fi

sed -e "s|@USER@|$USER_NAME|g" -e "s|@REPO@|$REPO|g" -e "s|@DATA@|$DATA|g" \
  "$REPO/deploy/trailmap.service.in" | sudo tee "$UNIT" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now trailmap
echo "Service installé : $UNIT"
echo "  état : systemctl status trailmap    logs : journalctl -u trailmap -f"
