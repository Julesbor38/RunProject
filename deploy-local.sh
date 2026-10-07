#!/usr/bin/env bash
# Updates the self-hosted app: pull, dependencies, front build, tests, service restart.
# Stops at the first error: the running service is only restarted when everything passed.
# Usage: ./deploy-local.sh [--no-pull]
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"
# Node >= 20 for Vite 8: prefer the one in ~/.local/node when the system one is too old.
[ -d "$HOME/.local/node/bin" ] && export PATH="$HOME/.local/node/bin:$PATH"

step() { printf '\n==> %s\n' "$*"; }

if [ "${1:-}" != "--no-pull" ]; then
  step "git pull"
  git pull --ff-only
fi

step "Dépendances Python"
if [ ! -x backend/.venv/bin/python ]; then
  python3 -m venv backend/.venv 2>/dev/null || "$HOME/.local/bin/uv" venv backend/.venv
fi
if [ -x backend/.venv/bin/pip ]; then
  backend/.venv/bin/pip install -q -e "backend[dev]"
else
  "$HOME/.local/bin/uv" pip install -q --python backend/.venv/bin/python -e "backend[dev]"
fi

step "Dépendances et build du front"
(cd frontend && npm ci --no-audit --no-fund && npm run build)

step "Tests"
(cd backend && .venv/bin/pytest -q)

step "Redémarrage du service"
if ! systemctl cat trailmap >/dev/null 2>&1; then
  deploy/install-service.sh
else
  sudo systemctl restart trailmap
fi

step "Vérification (/api/health)"
for _ in $(seq 1 120); do
  if health="$(curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null)"; then
    echo "$health"
    echo "OK : http://localhost:8000 (et via Tailscale)"
    exit 0
  fi
  sleep 1
done
echo "Le service ne répond pas après 2 min : journalctl -u trailmap -n 50" >&2
exit 1
