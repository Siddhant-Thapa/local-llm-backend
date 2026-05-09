"""Pydantic schemas for Message and Chat endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MessageCreate(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    token_count: int | None
    created_at: datetime


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID
    content: str
