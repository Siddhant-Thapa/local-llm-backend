#!/usr/bin/env bash
# Full EC2 setup script — run once on a fresh Ubuntu 22.04 t2.micro instance.
# Prerequisite: .env must already exist in $REPO_DIR with the RDS DATABASE_URL set.
# Usage: bash infra/scripts/setup_ec2.sh
set -euo pipefail

REPO_DIR="/home/ubuntu/llm-chat/backend"
LLAMA_DIR="/home/ubuntu/llama.cpp"
MODEL_DIR="/home/ubuntu/models"
FRONTEND_DIST="/var/www/llm-chat"

# Abort early if .env is missing — Alembic needs the RDS DATABASE_URL
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "ERROR: $REPO_DIR/.env not found."
    echo "Create it from .env.example and set DATABASE_URL to your RDS endpoint before running setup."
    exit 1
fi

echo "==> [1/8] Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    curl \
    wget \
    nginx \
    python3.11 \
    python3.11-venv \
    nodejs \
    npm
# postgresql-15 is NOT installed — database is provided by AWS RDS

echo "==> [2/8] Setting up 2 GB swap"
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    # Make swap permanent across reboots
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
echo "Swap status:"; free -h

echo "==> [3/8] Building llama.cpp"
if [ ! -d "$LLAMA_DIR" ]; then
    git clone https://github.com/ggerganov/llama.cpp "$LLAMA_DIR"
fi
cd "$LLAMA_DIR"
git pull --ff-only
cmake -B build -DLLAMA_NATIVE=OFF   # -DLLAMA_NATIVE=OFF required: t2.micro lacks AVX2
cmake --build build --config Release -j2
cd -

echo "==> [4/8] Downloading model"
bash "$REPO_DIR/infra/scripts/download_model.sh"

echo "==> [5/8] Setting up Python virtual environment"
cd "$REPO_DIR"
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

echo "==> [6/8] Running Alembic migrations against RDS"
cd "$REPO_DIR"
.venv/bin/alembic upgrade head

echo "==> [7/8] Building and deploying frontend"
cd /home/ubuntu/llm-chat/frontend
npm ci
npm run build
sudo mkdir -p "$FRONTEND_DIST"
sudo cp -r dist/. "$FRONTEND_DIST/"

echo "==> [8/8] Configuring Nginx and enabling systemd services"
sudo cp "$REPO_DIR/infra/nginx/llm-chat.conf" /etc/nginx/sites-available/llm-chat
sudo ln -sf /etc/nginx/sites-available/llm-chat /etc/nginx/sites-enabled/llm-chat
sudo rm -f /etc/nginx/sites-enabled/default  # remove default placeholder
sudo nginx -t
sudo systemctl reload nginx

sudo cp "$REPO_DIR/infra/systemd/llama-server.service" /etc/systemd/system/
sudo cp "$REPO_DIR/infra/systemd/llm-api.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now llama-server
sudo systemctl enable --now llm-api

echo ""
echo "Setup complete. Check service status:"
echo "  systemctl status llama-server llm-api nginx"
echo "  journalctl -u llm-api -f"
