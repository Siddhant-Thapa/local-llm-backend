"""Chat router — POST /api/chat returns an SSE token stream."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
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

    # 3. Persist the new user message and auto-title on first message
    user_msg = Message(
        conversation_id=body.conversation_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)

    if not recent_messages:
        # First message in this conversation — derive title from it
        raw = body.content.strip().replace("\n", " ")
        conv.title = raw[:60] + ("…" if len(raw) > 60 else "")

    await db.commit()

    # 4. Build the messages list for llama.cpp — system prompt first, then history
    system_prompt = (
        "You are a helpful, concise assistant. "
        "Answer the user's questions directly and clearly. "
        "If you don't know something, say so."
    )
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    llm_messages += [{"role": m.role, "content": m.content} for m in recent_messages]
    llm_messages.append({"role": "user", "content": body.content})

    # 5. Get the LLMClient singleton stored on app.state during lifespan
    llm_client = request.app.state.llm_client

    # Capture for use inside the generator closure
    conversation_id = body.conversation_id

    async def token_generator() -> AsyncIterator[str]:
        """Stream tokens and persist the full assistant reply after the stream ends."""
        collected: list[str] = []
        try:
            async for token in llm_client.stream_chat(llm_messages):
                collected.append(token)
                yield token
        except LLMUnavailableError as exc:
            import json
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return
        finally:
            # 6. Persist the complete assistant reply using a fresh session.
            # The request-scoped `db` session may already be closed by the time
            # the stream finishes, so we open a new one from the factory directly.
            if collected:
                full_content = "".join(collected)
                async with AsyncSessionLocal() as session:
                    assistant_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_content,
                        token_count=len(full_content.split()),
                    )
                    session.add(assistant_msg)
                    await session.commit()

    # 7. Return streaming response with SSE headers
    return StreamingResponse(
        format_sse(token_generator()),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
