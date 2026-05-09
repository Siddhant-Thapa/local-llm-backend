#!/usr/bin/env bash
# Download TinyLlama Q4_K_M GGUF from Hugging Face into ~/models/.
# Uses --continue so the download resumes if interrupted.
set -euo pipefail

MODEL_DIR="/home/ubuntu/models"
MODEL_FILE="tinyllama.gguf"
HF_URL="https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

mkdir -p "$MODEL_DIR"

echo "Downloading TinyLlama Q4_K_M (~638 MB) ..."
wget --continue --show-progress -O "$MODEL_DIR/$MODEL_FILE" "$HF_URL"

echo ""
echo "Download complete. SHA256 (verify against Hugging Face model card):"
sha256sum "$MODEL_DIR/$MODEL_FILE"
