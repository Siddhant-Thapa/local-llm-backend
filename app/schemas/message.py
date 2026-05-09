"""Pydantic schemas for Message and Chat endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


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
    # alias_generator accepts camelCase from JS clients (conversationId → conversation_id)
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    conversation_id: uuid.UUID
    content: str
