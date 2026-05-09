# LLM Chat — Backend

FastAPI backend for a self-hosted LLM chat application. Streams tokens from a local
llama.cpp server to the browser via Server-Sent Events and persists conversations in
PostgreSQL.

---

## Architecture

```
Browser
  │  SSE stream (tokens)
  ▼
Nginx :80/:443
  ├── /api/chat  ──────────────────────────► FastAPI :8000
  │                                              │
  ├── /api/*  ──────────────────────────────────┤
  │                                              │ httpx streaming
  └── /*  → React static build                  ▼
                                          llama.cpp :8080
                                          (TinyLlama Q4_K_M)
                                                 │
                                          PostgreSQL :5432
```

---

## Prerequisites (local dev)

- Python 3.12+ (matches Ubuntu 25.04 system Python on EC2)
- PostgreSQL 15 running locally on port 5432
- (Optional) llama.cpp built natively if you want real LLM responses

> **Database environments**
> - **Local dev** — PostgreSQL on `localhost:5432` (installed natively or via a one-off container, see below)
> - **Production (EC2)** — AWS RDS. The RDS endpoint lives only in `.env` on the EC2 instance and must **never** be committed to git or added to `.env.example`.

---

## Quick Start (local)

```bash
# 1. Clone and enter repo
git clone <url> && cd local-llm-backend

# 2. Start a local Postgres instance (one-liner — skip if already running natively)
docker run -d --name llmchat-pg \
  -e POSTGRES_USER=llmchat \
  -e POSTGRES_PASSWORD=llmchat \
  -e POSTGRES_DB=llmchat \
  -p 5432:5432 \
  postgres:15-alpine

# 3. Set up Python env (Python 3.12+ required)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 4. Configure environment
cp .env.example .env   # DATABASE_URL already points at localhost:5432

# 5. Run migrations
alembic upgrade head

# 6. Start dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at `http://localhost:8000`. Health check: `GET /api/health`.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values.

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | Local: `postgresql+asyncpg://llmchat:llmchat@localhost:5432/llmchat`. Prod: RDS endpoint (set only in `.env` on EC2, never committed). | Yes |
| `LLAMA_SERVER_URL` | URL of llama.cpp HTTP server | Yes |
| `LLAMA_MODEL_NAME` | Model name for API requests | Yes |
| `API_SECRET_KEY` | Secret key for future auth | Yes |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) | No |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` | No |

---

## Backend

### Running

```bash
uvicorn app.main:app --reload          # dev
uvicorn app.main:app --workers 1       # prod (NEVER more than 1 worker)
```

### Testing

```bash
pytest                                 # run all tests
pytest -x -v tests/test_chat.py       # single file
```

### Linting

```bash
ruff check app/                        # lint
ruff format app/                       # format
mypy app/                              # type-check
```

### SSE Streaming Endpoint

`POST /api/chat` accepts a JSON body and returns `text/event-stream`. Each event is:
```
data: {"token": "Hello"}\n\n
```
The stream ends with:
```
data: [DONE]\n\n
```

The endpoint sets `X-Accel-Buffering: no` so Nginx forwards each chunk immediately
instead of accumulating them in its buffer.

### LLM Client Service (`app/services/llm_client.py`)

Uses `httpx.AsyncClient` with `stream=True` to open a persistent connection to
llama.cpp's `/v1/chat/completions` endpoint. The response body is an SSE stream itself
(from llama.cpp). The client reads it line by line, parses `data: {...}` JSON, and
yields the `choices[0].delta.content` string. This nested-streaming approach keeps
memory constant regardless of response length.

---

## Database

### Schema overview

Two tables: `conversations` (UUID PK, title, timestamps) and `messages` (UUID PK,
FK to conversations, role, content, optional token_count, timestamp). See `CLAUDE.md`
for the full SQL.

### Run migrations

```bash
alembic upgrade head
```

### Create a new migration

```bash
alembic revision --autogenerate -m "describe_change"
# Review the generated file in alembic/versions/ before applying
alembic upgrade head
```

---

## Deployment to EC2

```bash
# From a fresh Ubuntu 22.04 t2.micro:
git clone <url> /home/ubuntu/llm-chat/backend

# Create .env with your RDS endpoint BEFORE running setup — never commit this file
cp /home/ubuntu/llm-chat/backend/.env.example /home/ubuntu/llm-chat/backend/.env
# Edit .env: set DATABASE_URL to your RDS endpoint, API_SECRET_KEY, etc.

bash /home/ubuntu/llm-chat/backend/infra/scripts/setup_ec2.sh
```

The script installs system dependencies, builds llama.cpp, downloads the model,
runs Alembic migrations against RDS, builds the frontend, and enables systemd services.
PostgreSQL is **not** installed on the instance — RDS provides it.

---

## llama.cpp Server

### Build

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DLLAMA_NATIVE=OFF   # OFF for EC2 — no AVX2 on t2.micro
cmake --build build --config Release -j2
```

### Key flags used in production

```
--ctx-size 2048    # Hard limit — larger values expand KV-cache and OOM the instance
--threads 1        # t2.micro has 1 vCPU; more threads cause context switching overhead
--batch-size 512   # Prompt processing batch; lower = less peak RAM during prefill
--n-predict -1     # Unlimited generation length (controlled by FastAPI max_tokens)
```

### Swapping models

Replace `/home/ubuntu/models/tinyllama.gguf` with any GGUF file and update the
`--model` path in `infra/systemd/llama-server.service`. Larger models require reducing
`--ctx-size` or upgrading the instance.

---

## Nginx

Key SSE configuration in `infra/nginx/llm-chat.conf`:

```nginx
proxy_buffering    off;   # Nginx stops accumulating the response body
proxy_cache        off;   # Disable caching for SSE
add_header         X-Accel-Buffering no;   # Tells Nginx upstream to not buffer
chunked_transfer_encoding on;
proxy_read_timeout 120s;  # Allow long-running generations
```

Without `proxy_buffering off`, Nginx buffers the entire SSE response and sends it
to the browser in one batch when the connection closes — effectively breaking streaming.

---

## Systemd Services

```bash
# Status
systemctl status llama-server llm-api nginx

# Restart (after code deploy)
systemctl restart llm-api   # NOT llama-server — model reload takes ~30s

# Logs
journalctl -u llama-server -f
journalctl -u llm-api -f
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `llama-server` OOM-killed | Model too large / ctx-size too high | Verify `--ctx-size 2048`, `--threads 1`; check `dmesg | grep -i kill` |
| SSE tokens appear in one batch | Nginx buffering enabled | Confirm `proxy_buffering off` and `X-Accel-Buffering: no` header in Nginx config |
| `alembic upgrade head` fails: "target database is not up to date" | Unapplied migration exists | Run `alembic history` to see gap; apply missing revisions |
| llama.cpp cmake build fails on EC2 | AVX2 not supported on t2.micro | Use `-DLLAMA_NATIVE=OFF` flag in cmake |
| `503 Service Unavailable` from `/api/chat` | llama.cpp not running | `systemctl start llama-server`; check `journalctl -u llama-server` |
| `asyncpg` connection refused | Wrong `DATABASE_URL` or RDS security group blocking port 5432 | Verify `.env` on EC2; check RDS SG allows inbound 5432 from the EC2 instance's private IP |

---

## Contributing

- Branch strategy: `main` (stable) → feature branches `feat/<name>` → PR
- Commit style: `type: short description` where type is `feat`, `fix`, `refactor`, `docs`, `chore`
- Run `ruff check` and `mypy` before opening a PR
