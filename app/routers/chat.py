"""Chat router — POST /api/chat returns an SSE token stream."""

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.message import ChatRequest
from app.services.llm_client import LLMUnavailableError
from app.services.stream_parser import format_sse

router = APIRouter()

# Number of recent messages to include in the prompt — keep within 2048 token context
_CONTEXT_MESSAGE_LIMIT = 10


@router.post("/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # 1. Verify conversation exists
    conv = await db.get(Conversation, body.conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 2. Load last N messages ordered by creation time
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == body.conversation_id)
        .order_by(Message.created_at.desc())
        .limit(_CONTEXT_MESSAGE_LIMIT)
    )
    recent_messages = list(reversed(result.scalars().all()))

    # 3. Persist the new user message
    user_msg = Message(
        conversation_id=body.conversation_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.commit()

    # 4. Build the messages list for llama.cpp (oldest-first)
    llm_messages: list[dict[str, str]] = [
        {"role": m.role, "content": m.content} for m in recent_messages
    ]
    llm_messages.append({"role": "user", "content": body.content})

    # 5. Get the LLMClient singleton stored on app.state during lifespan
    llm_client = request.app.state.llm_client

    async def token_generator() -> AsyncIterator[str]:
        """Stream tokens and persist the full assistant reply after the stream ends."""
        collected: list[str] = []
        try:
            async for token in llm_client.stream_chat(llm_messages):
                collected.append(token)
                yield token
        except LLMUnavailableError as exc:
            # Yield an error event so the client knows the stream failed
            import json
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return
        finally:
            # 6. Persist assistant reply even if generation was interrupted
            if collected:
                full_content = "".join(collected)
                async with db.__class__(bind=db.get_bind()) as new_session:
                    # TODO: replace with a proper session factory call if db is closed
                    assistant_msg = Message(
                        conversation_id=body.conversation_id,
                        role="assistant",
                        content=full_content,
                        token_count=len(full_content.split()),  # rough estimate
                    )
                    new_session.add(assistant_msg)
                    await new_session.commit()

    # 7. Return streaming response with SSE headers
    sse_stream = format_sse(token_generator())
    return StreamingResponse(
        sse_stream,
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",   # prevents Nginx from buffering the SSE stream
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
