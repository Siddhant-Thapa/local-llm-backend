#!/usr/bin/env bash
# Deploy backend, frontend, and systemd services on the existing EC2 instance.
# Assumes Phase 1 & 2 are complete: build-essential, cmake, git, curl, wget, nginx,
# postgresql-client, python3 (3.12+), python3-venv, python3-dev, swap, and
# llama.cpp + model are already in place.
#
# Prerequisite: .env must already exist in $REPO_DIR with the RDS DATABASE_URL set.
# Usage: bash infra/scripts/setup_ec2.sh
set -euo pipefail

REPO_DIR="/home/ubuntu/llm-chat/backend"
FRONTEND_DIST="/var/www/llm-chat"

# Abort early if .env is missing — Alembic needs the RDS DATABASE_URL
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "ERROR: $REPO_DIR/.env not found."
    echo "Create it from .env.example and set DATABASE_URL to your RDS endpoint before running setup."
    exit 1
fi

echo "==> [1/6] Installing remaining packages (Node.js for frontend build)"
sudo apt-get update -qq
# Only nodejs/npm are missing from Phase 1 — all other packages already installed
sudo apt-get install -y --no-install-recommends nodejs npm

echo "==> [2/6] Setting up Python virtual environment"
cd "$REPO_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e . --quiet

echo "==> [3/6] Running Alembic migrations against RDS"
.venv/bin/alembic upgrade head

echo "==> [4/6] Building and deploying frontend"
cd /home/ubuntu/llm-chat/frontend
npm ci --silent
npm run build
sudo mkdir -p "$FRONTEND_DIST"
sudo cp -r dist/. "$FRONTEND_DIST/"

echo "==> [5/6] Configuring Nginx"
sudo cp "$REPO_DIR/infra/nginx/llm-chat.conf" /etc/nginx/sites-available/llm-chat
sudo ln -sf /etc/nginx/sites-available/llm-chat /etc/nginx/sites-enabled/llm-chat
sudo rm -f /etc/nginx/sites-enabled/default  # remove default placeholder site
sudo nginx -t
sudo systemctl reload nginx

echo "==> [6/6] Installing and enabling systemd services"
sudo cp "$REPO_DIR/infra/systemd/llama-server.service" /etc/systemd/system/
sudo cp "$REPO_DIR/infra/systemd/llm-api.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now llama-server
sudo systemctl enable --now llm-api

echo ""
echo "Setup complete. Check service status:"
echo "  systemctl status llama-server llm-api nginx"
echo "  journalctl -u llm-api -f"
