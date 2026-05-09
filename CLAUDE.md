# CLAUDE.md — LLM Chat Backend

Re-read this file at the start of every session before touching any code.

## Project Overview

This is the FastAPI backend for a self-hosted LLM chat application running on a single
EC2 t2.micro instance (1 vCPU, 1 GB RAM + 2 GB swap). The tight memory budget shapes
every architectural decision: one llama.cpp worker, async-only DB access, SSE instead
of WebSockets, and a strictly capped context window. The backend proxies chat requests
to a local llama.cpp HTTP server, streams tokens back to the browser via SSE, and
persists conversations and messages in PostgreSQL 15.

---

## Architecture Decisions

| Decision | Choice | Reason |
|---|---|---|
| LLM runtime | llama.cpp HTTP server | Runs without Python ML deps; minimal RAM overhead vs torch/transformers |
| Model file | TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf | ~638 MB on disk, ~700 MB loaded — fits within 1 GB + swap |
| Quantisation | Q4_K_M | Best quality/size tradeoff for 4-bit; K-quant gives better perplexity |
| Context window | 2048 tokens | Hard ceiling for t2.micro; larger contexts expand KV-cache and OOM the instance |
| Streaming approach | SSE (Server-Sent Events) | One-directional server push; no auth header upgrade needed; works through Nginx with `proxy_buffering off` |
| ORM | SQLAlchemy 2.0 async | Native async support with asyncpg; type-safe mapped columns |
| Migration tool | Alembic | Standard companion to SQLAlchemy; supports async engines via `run_sync` |
| Python runtime | 3.11 | Required for `tomllib`, better async perf, type annotation improvements |

---

## Memory Budget

| Component | Approx RAM |
|---|---|
| Ubuntu OS + swap daemon | ~250 MB |
| llama.cpp server + model | ~700 MB |
| PostgreSQL 15 | ~50 MB |
| FastAPI (uvicorn, 1 worker) | ~40 MB |
| Nginx | ~10 MB |
| **Headroom** | **~18 MB** (of 1024 MB physical + 2048 MB swap) |

> Swap absorbs llama.cpp startup spikes. Keep it enabled; never disable.

---

## Critical Constraints

- **Never** increase `--ctx-size` above `2048` when launching llama.cpp on t2.micro
- **Never** run more than 1 llama.cpp worker thread (`--threads 1`)
- **Never** import `torch`, `transformers`, or any CUDA library in this codebase
- **Always** use `stream=True` when calling llama.cpp — blocking calls will hold the
  connection open and eventually timeout Nginx (default 60 s)
- **All** database access must use async SQLAlchemy with the `asyncpg` driver
- **Always** set `X-Accel-Buffering: no` on SSE responses or Nginx will buffer the
  entire stream and deliver it in one batch at the end
- **Never** run more than 1 uvicorn worker — concurrent LLM requests will OOM the instance
- **Never** put the RDS endpoint in `.env.example` or commit it to git — it goes only in `.env` on the EC2 instance

---

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | asyncpg connection string | Yes |
| `LLAMA_SERVER_URL` | Base URL of local llama.cpp HTTP server | Yes |
| `LLAMA_MODEL_NAME` | Model name passed in OpenAI-compat API body | Yes |
| `API_SECRET_KEY` | Secret for future auth middleware | Yes |
| `CORS_ORIGINS` | Comma-separated allowed origins | No (default: localhost:5173) |
| `LOG_LEVEL` | Python logging level | No (default: INFO) |

---

## Local Dev Workflow

**Database environments:**
- Local dev → PostgreSQL on `localhost:5432` (local install or one-off container)
- Production → AWS RDS. The RDS endpoint lives **only** in `.env` on the EC2 instance. Never commit it or put it in `.env.example`.

1. Start a local Postgres instance (skip if already running natively):
   ```
   docker run -d --name llmchat-pg \
     -e POSTGRES_USER=llmchat \
     -e POSTGRES_PASSWORD=llmchat \
     -e POSTGRES_DB=llmchat \
     -p 5432:5432 \
     postgres:15-alpine
   ```
2. Copy environment file (already points at localhost:5432):
   ```
   cp .env.example .env
   ```
3. Create a Python virtual environment and install deps:
   ```
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
4. Run Alembic migrations:
   ```
   alembic upgrade head
   ```
5. Start FastAPI dev server:
   ```
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
6. (Optional) Start llama.cpp natively or point `LLAMA_SERVER_URL` at a mock.

---

## EC2 Deployment Checklist

1. SSH into the Ubuntu 22.04 instance
2. Clone this repo: `git clone <url> /home/ubuntu/llm-chat/backend`
3. **Create `.env` with the RDS endpoint before running anything:**
   ```
   cp .env.example .env
   # Edit .env: set DATABASE_URL to your RDS endpoint, API_SECRET_KEY, etc.
   ```
   PostgreSQL is **not** installed on the instance — RDS provides it.
   The RDS URL must never be committed to git or appear in `.env.example`.
4. Run setup script: `bash infra/scripts/setup_ec2.sh`
   - Installs system packages, swap, llama.cpp, Python venv
   - Runs Alembic migrations against RDS
   - Enables and starts systemd services
5. Verify services: `systemctl status llama-server llm-api nginx`
6. Check logs: `journalctl -u llm-api -f`

---

## Database Schema

```sql
CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL DEFAULT 'New conversation',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content          TEXT NOT NULL,
    token_count      INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX idx_messages_created_at ON messages(created_at);
```

---

## API Contract

### `POST /api/chat`
**Request body:**
```json
{ "conversation_id": "uuid", "content": "Hello!" }
```
**Response:** `text/event-stream`
```
data: {"token": "Hello"}\n\n
data: {"token": " world"}\n\n
data: [DONE]\n\n
```
**Error codes:** 404 (conversation not found), 503 (llama.cpp unreachable)

### `GET /api/conversations`
**Response:**
```json
{ "items": [{ "id": "uuid", "title": "...", "createdAt": "...", "updatedAt": "..." }], "total": 1 }
```

### `POST /api/conversations`
**Request:** `{ "title": "My chat" }` (title optional)
**Response:** 201 + `ConversationRead`

### `GET /api/conversations/{id}/messages`
**Response:** `[{ "id": "uuid", "conversationId": "uuid", "role": "user", "content": "...", "tokenCount": null, "createdAt": "..." }]`

### `DELETE /api/conversations/{id}`
**Response:** 204 No Content

### `GET /api/health`
**Response:** `{ "status": "ok", "model": "tinyllama" }`

---

## Known Limitations & Future Work

- No authentication — single-user deployment; protect via SSH tunnel or HTTP basic auth in Nginx
- No request queue — concurrent chat requests will OOM the instance; add a queue (e.g. asyncio.Semaphore) before multi-user use
- TinyLlama quality is limited — upgrade path is swapping the `.gguf` file and adjusting `--ctx-size` if RAM allows
- No message editing or regeneration yet
- `updated_at` on conversations is not auto-updated on message insert — needs a trigger or explicit ORM event
