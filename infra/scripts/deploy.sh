#!/usr/bin/env bash
# Deploy latest changes to a running EC2 instance.
# Does NOT restart llama-server — model reload takes ~30 s and is unnecessary for code changes.
set -euo pipefail

REPO_DIR="/home/ubuntu/llm-chat/backend"
FRONTEND_DIST="/var/www/llm-chat"

echo "==> Pulling latest changes"
cd "$REPO_DIR"
git pull --ff-only

echo "==> Running database migrations"
.venv/bin/alembic upgrade head

echo "==> Rebuilding frontend"
cd /home/ubuntu/llm-chat/frontend
npm ci
npm run build
sudo cp -r dist/. "$FRONTEND_DIST/"

echo "==> Restarting FastAPI service"
sudo systemctl restart llm-api
sudo systemctl status llm-api --no-pager

echo "Deploy complete."
