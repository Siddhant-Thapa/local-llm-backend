"""Conversations router — CRUD for chat sessions and their messages."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.conversation import ConversationCreate, ConversationList, ConversationRead
from app.schemas.message import MessageRead

router = APIRouter()


@router.get("/conversations", response_model=ConversationList)
async def list_conversations(db: AsyncSession = Depends(get_db)) -> ConversationList:
    result = await db.execute(select(Conversation).order_by(Conversation.updated_at.desc()))
    conversations = result.scalars().all()
    return ConversationList(
        items=[ConversationRead.model_validate(c) for c in conversations],
        total=len(conversations),
    )


@router.post("/conversations", response_model=ConversationRead, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    conv = Conversation(title=body.title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationRead.model_validate(conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
async def list_messages(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[MessageRead]:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    return [MessageRead.model_validate(m) for m in messages]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(conv)
    await db.commit()
