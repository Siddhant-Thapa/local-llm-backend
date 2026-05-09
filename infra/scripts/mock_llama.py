#!/usr/bin/env python3
"""
Local mock for the llama.cpp HTTP server.

Mimics the OpenAI-compatible /v1/chat/completions SSE endpoint so the
FastAPI backend can be tested end-to-end without a real model.

Usage (from repo root, with venv active):
    uvicorn infra.scripts.mock_llama:app --port 8080 --log-level warning

Listens on http://127.0.0.1:8080 — same address FastAPI expects.
"""

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

REPLIES: dict[str, str] = {
    "hello": "Hello! How can I help you today?",
    "hi": "Hi there! What can I do for you?",
    "who are you": "I am TinyLlama, a small but mighty language model.",
    "how are you": "I am just a mock server, but I am doing great!",
    "what can you do": "I can answer questions, help with writing, and have a conversation.",
    "bye": "Goodbye! Have a great day.",
}
DEFAULT_REPLY = (
    "This is a mock llama.cpp response. "
    "The real model runs on EC2. "
    "Use the SSH tunnel option to get real TinyLlama responses."
)


def pick_reply(messages: list[dict]) -> str:
    last = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    lower = last.lower()
    for key, reply in REPLIES.items():
        if key in lower:
            return reply
    return DEFAULT_REPLY


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages: list[dict] = body.get("messages", [])
    reply = pick_reply(messages)
    words = reply.split(" ")

    async def token_stream():
        for i, word in enumerate(words):
            token = word if i == 0 else f" {word}"
            chunk = {
                "choices": [
                    {"delta": {"content": token}, "index": 0, "finish_reason": None}
                ]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.05)  # ~20 tokens/sec
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
