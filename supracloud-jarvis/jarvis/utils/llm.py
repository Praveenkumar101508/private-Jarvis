"""
vLLM client with intelligent fast/deep routing.

Routing logic (no LLM call needed — pure heuristics for speed):
  Fast path  → Llama 3.1 8B AWQ  — simple chat, quick lookups, light reasoning
  Deep path  → Qwen 2.5 14B AWQ  — code gen, security analysis, agent creation,
                                    long documents, complex multi-step reasoning
"""

from __future__ import annotations

import re
from typing import AsyncIterator

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings

# ── Keyword sets for rule-based routing ───────────────────────────────────────
_DEEP_AGENTS = {"security", "creator", "researcher"}

_DEEP_KEYWORDS = frozenset({
    "code", "implement", "generate code", "write a", "write the", "build",
    "architecture", "design", "refactor", "debug", "analyse", "analyze",
    "vulnerability", "exploit", "patch", "security", "audit",
    "langgraph", "agent", "docker", "deployment", "kubernetes",
    "comprehensive", "detailed", "thorough", "step by step",
})

_FAST_KEYWORDS = frozenset({
    "hi", "hello", "hey", "thanks", "thank you", "what time", "status",
    "ping", "are you", "how are", "good morning", "good night",
})


def should_use_deep(query: str, agent: str | None = None) -> bool:
    """Return True if this query should route to the deep (14B) model."""
    if agent in _DEEP_AGENTS:
        return True
    q = query.lower()
    if any(kw in q for kw in _FAST_KEYWORDS):
        return False
    # Long queries almost always need more reasoning capacity
    if len(query.split()) > 60:
        return True
    return any(kw in q for kw in _DEEP_KEYWORDS)


def _make_client(base_url: str) -> AsyncOpenAI:
    cfg = get_settings()
    return AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=base_url)


def get_fast_client() -> AsyncOpenAI:
    return _make_client(get_settings().vllm_fast_url)


def get_deep_client() -> AsyncOpenAI:
    return _make_client(get_settings().vllm_deep_url)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def chat_complete(
    messages: list[dict],
    *,
    use_deep: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> str | AsyncIterator:
    """
    Send messages to the appropriate vLLM endpoint.
    Returns the full response string (stream=False) or an async iterator (stream=True).
    """
    cfg = get_settings()

    if use_deep:
        client = get_deep_client()
        model = cfg.vllm_deep_model
        max_tokens = max_tokens or cfg.deep_max_tokens
        temperature = temperature if temperature is not None else cfg.deep_temperature
    else:
        client = get_fast_client()
        model = cfg.vllm_fast_model
        max_tokens = max_tokens or cfg.fast_max_tokens
        temperature = temperature if temperature is not None else cfg.fast_temperature

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=stream,
    )

    if stream:
        return response   # caller iterates over chunks

    return response.choices[0].message.content or ""


async def stream_tokens(
    messages: list[dict],
    *,
    use_deep: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """Yield raw token strings from the streaming response."""
    response = await chat_complete(
        messages,
        use_deep=use_deep,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
