# Infrastructure Setup Log — Phase 1 & 2

This document records what was done **manually** on the AWS infrastructure before any
code was deployed. It is a permanent reference — do not delete it. If you make further
manual changes to the instance or AWS resources, append them here.

---

## Phase 1 — AWS Infrastructure

### EC2 Instance

| Property | Value |
|---|---|
| Instance type | t3.micro (2 vCPU, 1 GB RAM, burstable) |
| OS | Ubuntu 25.04 |
| Region | ap-south-1 (Mumbai) |
| Private IP | 172.31.41.176 |
| Storage | 20 GB gp3 (extended from default 8 GB; filesystem grown with `growpart`) |

### Swap

- 2 GB swapfile created at `/swapfile`
- Activated and persisted in `/etc/fstab`
- `vm.swappiness` set to `10` in `/etc/sysctl.conf`

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Security Groups

**EC2 security group (`llm-chat-ec2-sg`)**

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | 0.0.0.0/0 | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP (Nginx) |
| 443 | TCP | 0.0.0.0/0 | HTTPS (Nginx) |

Ports 8000 (FastAPI) and 8080 (llama.cpp) are **not** open to the public — internal only.

**RDS security group (`llm-chat-rds-sg`)**

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 5432 | TCP | llm-chat-ec2-sg | PostgreSQL from EC2 only |

Public access on RDS is disabled.

### Packages Installed on EC2

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential cmake git curl wget htop \
    nginx \
    postgresql-client \
    python3 python3-venv python3-dev \
    ufw
```

**UFW rules applied:**

```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

Nginx was enabled and confirmed listening on port 80.

### RDS Instance

| Property | Value |
|---|---|
| Engine | PostgreSQL 15 |
| Instance type | db.t3.micro |
| Database name | llmchat |
| Master username | llmchat |
| VPC | Same VPC as EC2 |
| Public access | No |
| Status | Available, reachable from EC2 only |

---

## Phase 2 — llama.cpp Build & Model

### llama.cpp Build

Cloned and built at `/home/ubuntu/llama.cpp/`:

```bash
git clone https://github.com/ggerganov/llama.cpp /home/ubuntu/llama.cpp
cd /home/ubuntu/llama.cpp
cmake -B build
cmake --build build --config Release -j2
```

Binary location: `/home/ubuntu/llama.cpp/build/bin/llama-server`

OpenSSL was not included (not needed — Nginx handles TLS termination).

### Model Download

```bash
mkdir -p /home/ubuntu/models
wget --continue -O /home/ubuntu/models/tinyllama.gguf \
  "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
```

| Property | Value |
|---|---|
| File | `/home/ubuntu/models/tinyllama.gguf` |
| Size | 638 MB |
| Model | TinyLlama-1.1B-Chat-v1.0 |
| Quantisation | Q4_K_M |
| Source | TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF on Hugging Face |

### Confirmed Working Server Flags

These flags were tested and confirmed stable on this hardware. **Do not change them.**

```bash
/home/ubuntu/llama.cpp/build/bin/llama-server \
  --model /home/ubuntu/models/tinyllama.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size 2048 \
  --threads 1 \
  --parallel 1 \
  --no-mmap
```

| Flag | Value | Why |
|---|---|---|
| `--threads` | 1 | Single inference thread — leaves headroom for FastAPI and OS on the 2-vCPU instance |
| `--parallel` | 1 | Prevents llama.cpp spawning 4 parallel KV-cache slots; saves ~200 MB RAM |
| `--no-mmap` | — | Avoids CPU_REPACK buffer overhead (~455 MB) observed without this flag |
| `--ctx-size` | 2048 | Matches model training context; keeps KV cache at ~44 MB |

### Smoke Test Result

A direct HTTP test returned HTTP 200 with a valid token stream at **~5.4 tokens/second**:

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"tinyllama","messages":[{"role":"user","content":"Say hello in one word."}],"max_tokens":10}'
```

Response:
```json
{
  "choices": [{
    "finish_reason": "length",
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Say hello in one word.\n\nExample"
    }
  }],
  "model": "tinyllama.gguf",
  "usage": {
    "completion_tokens": 10,
    "prompt_tokens": 24,
    "total_tokens": 34
  },
  "timings": {
    "predicted_per_second": 5.35
  }
}
```

> Note: the response echoed the prompt because no system prompt was set during the raw
> test. The FastAPI layer injects a proper system prompt in the `messages` array.

---

## Memory Budget (confirmed post-Phase 2)

| Component | Approx RAM |
|---|---|
| Ubuntu OS (25.04) | ~250 MB |
| llama.cpp + model (with `--no-mmap`, `--parallel 1`) | ~700 MB |
| FastAPI (uvicorn, 1 worker) | ~40 MB |
| Nginx | ~10 MB |
| **Total** | **~1000 MB** |
| **Overflow to swap** | **~0–100 MB** |

PostgreSQL is on RDS — no local Postgres process on the instance.

---

## What Comes Next

- **Phase 3** — FastAPI backend (Python, SSE streaming, PostgreSQL via asyncpg)
- **Phase 4** — Systemd services (`llama-server.service`, `llm-api.service`)
- **Phase 5** — Nginx reverse proxy config (with `proxy_buffering off` for SSE)
- **Phase 6** — React + TypeScript frontend with SSE chat UI
- **Phase 7** — CLAUDE.md and README.md finalisation
