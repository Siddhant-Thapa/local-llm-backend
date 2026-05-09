"""Async HTTP client for the llama.cpp OpenAI-compatible inference server."""

from collections.abc import AsyncIterator

import httpx


class LLMUnavailableError(Exception):
    """Raised when llama.cpp server is unreachable or returns a non-200 response."""


class LLMClient:
    """Wraps llama.cpp's /v1/chat/completions SSE endpoint."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        # 120 s read timeout — long enough for a full generation on t2.micro
        self._timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
    ) -> AsyncIterator[str]:
        """
        POST to llama.cpp /v1/chat/completions with stream=True.
        Yields each text delta as a plain string.
        Raises LLMUnavailableError if the server is unreachable.
        """
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/v1/chat/completions",
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise LLMUnavailableError(
                            f"llama.cpp returned {response.status_code}: {body.decode()}"
                        )

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload_str = line[len("data: "):]
                        if payload_str.strip() == "[DONE]":
                            return
                        try:
                            import json
                            chunk = json.loads(payload_str)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except (KeyError, IndexError, json.JSONDecodeError):
                            # Malformed chunk — skip silently
                            continue

        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"Cannot reach llama.cpp at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(f"llama.cpp request timed out: {exc}") from exc
