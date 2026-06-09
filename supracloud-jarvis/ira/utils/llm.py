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

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from utils.yaml_config import get_fast_keywords, get_deep_keywords, get_reasoning_keywords

# ── Agents that always use the deep path ────────────────────────────────────
_DEEP_AGENTS = {"security", "creator", "researcher"}


def should_use_deep(query: str, agent: str | None = None) -> bool:
    """Return True if this query should route to the deep (Qwen3-14B) model."""
    if agent in _DEEP_AGENTS:
        return True
    q = query.lower()
    if any(kw in q for kw in get_fast_keywords()):
        return False
    if len(query.split()) > 60:
        return True
    return any(kw in q for kw in get_deep_keywords())


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
    return any(kw in q for kw in get_reasoning_keywords())


# ── Client factories ──────────────────────────────────────────────────────────

_LLM_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)


def _make_vllm_client(base_url: str) -> AsyncOpenAI:
    cfg = get_settings()
    return AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=base_url, timeout=_LLM_TIMEOUT)


def _make_ollama_client() -> AsyncOpenAI:
    """Local Ollama client — points at the OpenAI-compatible API on localhost."""
    cfg = get_settings()
    return AsyncOpenAI(api_key="ollama", base_url=cfg.ollama_base_url, timeout=_LLM_TIMEOUT)


def _use_ollama() -> bool:
    """L2: True when the local Ollama backend is active.

    Driven by the LLM_BACKEND switch (independent of auth/biometrics) OR the
    legacy dev_mode flag. Keeping dev_mode here preserves backwards compatibility
    without relying on it — set llm_backend="ollama" to run locally with auth ON.
    """
    cfg = get_settings()
    return cfg.llm_backend == "ollama" or cfg.dev_mode


def get_fast_client() -> AsyncOpenAI:
    cfg = get_settings()
    return _make_ollama_client() if _use_ollama() else _make_vllm_client(cfg.vllm_fast_url)


def get_deep_client() -> AsyncOpenAI:
    cfg = get_settings()
    return _make_ollama_client() if _use_ollama() else _make_vllm_client(cfg.vllm_deep_url)


def get_reasoning_client() -> AsyncOpenAI:
    """
    Returns the reasoning-tier client.
    Falls back to the deep client if no dedicated reasoning endpoint is configured.
    """
    cfg = get_settings()
    if _use_ollama():  # L2
        return _make_ollama_client()
    if cfg.vllm_reasoning_url:
        return _make_vllm_client(cfg.vllm_reasoning_url)
    # Graceful fallback — use deep path (still much better than fast for reasoning)
    return _make_vllm_client(cfg.vllm_deep_url)


# ── Core completion function ──────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _complete_no_stream(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> str:
    """
    Non-streaming completion with automatic Tenacity retry (up to 3 attempts).

    Kept as a private helper so the retry decorator is NEVER applied to
    streaming requests — retrying a broken stream would restart the generation
    from scratch and send duplicate tokens to the client.
    """
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=False,
    )
    return response.choices[0].message.content or ""


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

    Note: non-streaming calls are retried up to 3× via _complete_no_stream().
    Streaming calls are NOT retried — mid-stream retry would duplicate tokens.
    """
    cfg = get_settings()
    ollama = _use_ollama()  # L2: local Ollama backend active?

    if use_reasoning:
        client = get_reasoning_client()
        # L2: with Ollama every tier maps to the configured 14B; on vLLM use the
        # dedicated reasoning model only when a reasoning endpoint is configured.
        if ollama:
            model = cfg.ollama_model_reasoning
        else:
            model = cfg.vllm_reasoning_model if cfg.vllm_reasoning_url else cfg.vllm_deep_model
        max_tokens = max_tokens or cfg.reasoning_max_tokens
        temperature = temperature if temperature is not None else cfg.reasoning_temperature
    elif use_deep:
        client = get_deep_client()
        model = cfg.ollama_model_deep if ollama else cfg.vllm_deep_model  # L2
        max_tokens = max_tokens or cfg.deep_max_tokens
        temperature = temperature if temperature is not None else cfg.deep_temperature
    else:
        client = get_fast_client()
        model = cfg.ollama_model_fast if ollama else cfg.vllm_fast_model  # L2
        max_tokens = max_tokens or cfg.fast_max_tokens
        temperature = temperature if temperature is not None else cfg.fast_temperature

    if stream:
        # No retry — a mid-stream failure cannot be safely replayed
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        return response

    tier = "reasoning" if use_reasoning else ("deep" if use_deep else "fast")
    from utils.telemetry import trace_span
    with trace_span("llm.complete", {"tier": tier, "model": model, "max_tokens": max_tokens}):
        return await _complete_no_stream(client, model, messages, max_tokens, temperature)


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


# ── Vision (image) path — local Ollama VL model, fail-soft ───────────────────
# Prompt 3.1: a local vision-language model served by Ollama (e.g. qwen2.5-VL /
# llava). Selection mirrors the text tiers (_use_ollama): local Ollama VL when the
# backend is ollama, otherwise the vLLM vision endpoint. Both fail soft.

_VISION_UNAVAILABLE = (
    "Vision is unavailable — no vision-language model is configured. Pull a VL model "
    "on the Shadow box (e.g. `ollama pull qwen2.5vl`) and set OLLAMA_VISION_MODEL."
)


def _vision_client_and_model() -> tuple[AsyncOpenAI | None, str | None]:
    """Return (client, model) for the vision path, or (None, None) if unconfigured."""
    cfg = get_settings()
    if _use_ollama():
        model = getattr(cfg, "ollama_vision_model", "") or ""
        if not model:
            return None, None
        return _make_ollama_client(), model
    if not cfg.vllm_vision_url:
        return None, None
    return _make_vllm_client(cfg.vllm_vision_url), (cfg.vllm_vision_model or "vision")


def vision_available() -> bool:
    """True when a vision-language model is configured for the active backend."""
    client, _model = _vision_client_and_model()
    return client is not None


def _vision_messages(prompt: str, image_b64: str, mime_type: str, system: str | None) -> list[dict]:
    data_url = f"data:{mime_type};base64,{image_b64}"
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]})
    return messages


async def vision_complete(
    *, prompt: str, image_b64: str, mime_type: str = "image/jpeg", system: str | None = None,
) -> str:
    """Call the VL model with an image + prompt and return text. Fail soft (never raises)."""
    client, model = _vision_client_and_model()
    if client is None:
        return _VISION_UNAVAILABLE
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=_vision_messages(prompt, image_b64, mime_type, system),  # type: ignore[arg-type]
            max_tokens=2048,
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — fail soft
        return f"Vision unavailable: {str(exc)[:160]}"


async def stream_vision_tokens(
    *, prompt: str, image_b64: str, mime_type: str = "image/jpeg", system: str | None = None,
) -> AsyncIterator[str]:
    """Stream tokens from the VL model; on unavailable/error yield a clear message (fail soft)."""
    client, model = _vision_client_and_model()
    if client is None:
        yield _VISION_UNAVAILABLE
        return
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=_vision_messages(prompt, image_b64, mime_type, system),  # type: ignore[arg-type]
            max_tokens=2048,
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as exc:  # noqa: BLE001 — fail soft
        yield f"Vision unavailable: {str(exc)[:160]}"
