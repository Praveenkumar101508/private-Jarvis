"""
vLLM / Ollama client with 3-tier intelligent routing (2026 model stack).

Production model tiers:
  Fast      — Qwen3-8B           (<2s TTFT, conversational/quick lookups)
  Deep      — Qwen3-14B          (code gen, security, complex reasoning)
  Reasoning — Qwen3-32B / R1-32B (Think Mode, DeepSearch, long chains)

Dev mode: all tiers → local Ollama (qwen3:8b recommended)

Cloud upgrade path (8×H100):
  Fast      → Qwen3-30B-A3B (MoE — set VLLM_FAST_URL + FAST_MODEL)
  Deep      → Qwen3-72B     (set VLLM_DEEP_URL + DEEP_MODEL)
  Reasoning → DeepSeek-R1 671B or Qwen3-235B-A22B (VLLM_REASONING_URL)
"""

from __future__ import annotations

from typing import AsyncIterator

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings

# ── Agents that always use the deep path ────────────────────────────────────
_DEEP_AGENTS = {"security", "creator", "researcher"}

# ── Keywords that force deep path ────────────────────────────────────────────
_DEEP_KEYWORDS = frozenset({
    "code", "implement", "generate code", "write a", "write the", "build",
    "architecture", "design", "refactor", "debug", "analyse", "analyze",
    "vulnerability", "exploit", "patch", "security", "audit",
    "langgraph", "agent", "docker", "deployment", "kubernetes",
    "comprehensive", "detailed", "thorough", "step by step",
    "compare", "contrast", "explain in depth", "full implementation",
    "unit test", "integration test", "review this", "fix this bug",
    "optimize", "performance", "algorithm", "data structure",
    "proof", "derive", "mathematical", "theorem",
})

# ── Keywords that force fast path regardless of length ───────────────────────
_FAST_KEYWORDS = frozenset({
    "hi", "hello", "hey", "thanks", "thank you", "what time", "status",
    "ping", "are you", "how are", "good morning", "good night", "bye",
    "who are you", "what's your name",
})

# ── Keywords that hint at needing the reasoning path ─────────────────────────
_REASONING_KEYWORDS = frozenset({
    "reason step by step", "think through", "chain of thought", "solve this",
    "prove", "disprove", "philosophical", "ethical dilemma", "game theory",
    "multi-step", "plan a strategy", "research paper", "scientific analysis",
    "what are the implications", "write a dissertation", "deep analysis",
})


def should_use_deep(query: str, agent: str | None = None) -> bool:
    """Return True if this query should route to the deep (Qwen3-14B) model."""
    if agent in _DEEP_AGENTS:
        return True
    q = query.lower()
    if any(kw in q for kw in _FAST_KEYWORDS):
        return False
    if len(query.split()) > 60:
        return True
    return any(kw in q for kw in _DEEP_KEYWORDS)


def should_use_reasoning(
    query: str,
    *,
    think_mode: bool = False,
    deep_search: bool = False,
) -> bool:
    """
    Return True if this query should route to the reasoning path (Qwen3-32B / R1).
    Triggered by: Think Mode toggle, DeepSearch, or explicit reasoning keywords.
    """
    if think_mode or deep_search:
        return True
    q = query.lower()
    return any(kw in q for kw in _REASONING_KEYWORDS)


# ── Client factories ──────────────────────────────────────────────────────────

def _make_vllm_client(base_url: str) -> AsyncOpenAI:
    cfg = get_settings()
    return AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=base_url)


def _make_ollama_client() -> AsyncOpenAI:
    """Dev-mode client — points at local Ollama (OpenAI-compatible API)."""
    cfg = get_settings()
    return AsyncOpenAI(api_key="ollama", base_url=cfg.ollama_base_url)


def get_fast_client() -> AsyncOpenAI:
    cfg = get_settings()
    return _make_ollama_client() if cfg.dev_mode else _make_vllm_client(cfg.vllm_fast_url)


def get_deep_client() -> AsyncOpenAI:
    cfg = get_settings()
    return _make_ollama_client() if cfg.dev_mode else _make_vllm_client(cfg.vllm_deep_url)


def get_reasoning_client() -> AsyncOpenAI:
    """
    Returns the reasoning-tier client.
    Falls back to the deep client if no dedicated reasoning endpoint is configured.
    """
    cfg = get_settings()
    if cfg.dev_mode:
        return _make_ollama_client()
    if cfg.vllm_reasoning_url:
        return _make_vllm_client(cfg.vllm_reasoning_url)
    # Graceful fallback — use deep path (still much better than fast for reasoning)
    return _make_vllm_client(cfg.vllm_deep_url)


# ── Core completion function ──────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def chat_complete(
    messages: list[dict],
    *,
    use_deep: bool = False,
    use_reasoning: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> str | AsyncIterator:
    """
    Send messages to the appropriate LLM endpoint (fast / deep / reasoning).
    Returns the full response string (stream=False) or an async iterator (stream=True).

    Tier selection (first match wins):
      use_reasoning=True → reasoning tier (Qwen3-32B or DeepSeek-R1)
      use_deep=True      → deep tier      (Qwen3-14B)
      default            → fast tier      (Qwen3-8B)
    """
    cfg = get_settings()

    if cfg.dev_mode:
        client = _make_ollama_client()
        model = cfg.dev_model
        max_tokens = max_tokens or cfg.deep_max_tokens
        temperature = temperature if temperature is not None else 0.6
    elif use_reasoning:
        client = get_reasoning_client()
        # Use reasoning model name only if we have a dedicated endpoint
        model = cfg.vllm_reasoning_model if cfg.vllm_reasoning_url else cfg.vllm_deep_model
        max_tokens = max_tokens or cfg.reasoning_max_tokens
        temperature = temperature if temperature is not None else cfg.reasoning_temperature
    elif use_deep:
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
        return response

    return response.choices[0].message.content or ""


async def stream_tokens(
    messages: list[dict],
    *,
    use_deep: bool = False,
    use_reasoning: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """Yield raw token strings from the streaming response."""
    response = await chat_complete(
        messages,
        use_deep=use_deep,
        use_reasoning=use_reasoning,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
