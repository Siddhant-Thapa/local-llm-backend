"""FastAPI application entrypoint — configures middleware, lifespan, and routes."""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import chat, conversations
from app.services.llm_client import LLMClient

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting LLM Chat API — model: %s", settings.llama_model_name)
    app.state.llm_client = LLMClient(
        base_url=settings.llama_server_url,
        model=settings.llama_model_name,
    )
    yield
    logger.info("Shutting down LLM Chat API")


app = FastAPI(
    title="LLM Chat API",
    version="0.1.0",
    description="Self-hosted LLM chat backend powered by llama.cpp",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.llama_model_name}
