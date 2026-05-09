"""Wraps a raw token stream into the SSE wire format consumed by the browser."""

import json
from collections.abc import AsyncIterator


async def format_sse(token_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """
    Converts a stream of token strings into SSE-formatted lines.

    Each token yields:   data: {"token": "hello"}\\n\\n
    Final sentinel:      data: [DONE]\\n\\n

    The double newline is the SSE event delimiter required by the spec.
    """
    async for token in token_stream:
        yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"
