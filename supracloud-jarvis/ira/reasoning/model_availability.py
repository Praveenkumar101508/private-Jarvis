"""
ira/reasoning/model_availability.py — "is this local model actually installed?"

The model router (``ira/reasoning/model_router.py``) needs to know which Ollama
models are present so it can fall back to a smaller local model when the
preferred one is missing. This module answers that — and ONLY that — by reading
Ollama's native ``/api/tags`` endpoint.

Design rules:
  * **Local-first & fail-soft.** A probe that can't reach Ollama returns
    ``reachable=False`` with an empty model set; it never raises. The router
    treats "can't tell" as "don't override the configured model" so a transient
    probe failure never degrades IRA's answers.
  * **Dependency-light.** Uses only the standard library (``urllib``) so importing
    this module pulls in nothing heavy. The HTTP fetch is injectable so tests
    never touch the network.
  * **No model calls.** This module lists installed models; it never generates.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger("ira.reasoning.model_availability")

#: How long a successful probe is cached, in seconds.
DEFAULT_TTL_SECONDS = 30.0

#: Default native Ollama host (the tags API lives at the root, not under /v1).
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"

#: A function that takes a tags-URL and returns the decoded JSON dict.
Fetcher = Callable[[str], dict]


@dataclass(frozen=True)
class ModelAvailability:
    """Snapshot of which local models Ollama reports as installed.

    ``reachable`` is False when the probe failed (Ollama down / not installed);
    in that case ``models`` is empty and ``error`` explains why.
    """

    reachable: bool
    models: frozenset[str]
    source: str
    error: Optional[str] = None

    def has(self, model: str) -> bool:
        """Strict membership: True iff Ollama reports ``model`` as installed.

        Tag-aware: ``qwen3`` matches an installed ``qwen3:latest`` and vice-versa,
        because Ollama treats a bare name as the ``:latest`` tag.
        """
        if not model:
            return False
        name = model.strip()
        if name in self.models:
            return True
        # Normalise the implicit ":latest" tag in both directions.
        bare = name.split(":", 1)[0]
        if ":" not in name:
            return f"{bare}:latest" in self.models
        if name == f"{bare}:latest":
            return bare in self.models
        return False


def _ollama_host(env: Optional[dict] = None) -> str:
    """Resolve the native Ollama host root from the environment.

    Accepts ``IRA_OLLAMA_BASE_URL`` / ``OLLAMA_BASE_URL`` (which may point at the
    OpenAI-compatible ``/v1`` surface) and strips a trailing ``/v1`` so we hit the
    native ``/api/tags`` endpoint.
    """
    env = os.environ if env is None else env
    raw = (env.get("IRA_OLLAMA_BASE_URL") or env.get("OLLAMA_BASE_URL") or _DEFAULT_OLLAMA_HOST).strip()
    raw = raw.rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw or _DEFAULT_OLLAMA_HOST


def _default_fetch(url: str, timeout: float) -> dict:
    """Fetch + decode JSON from ``url`` using only the stdlib."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - localhost only
        return json.loads(resp.read().decode("utf-8"))


def _parse_models(payload: dict) -> frozenset[str]:
    """Extract installed model names from an Ollama ``/api/tags`` payload."""
    out: set[str] = set()
    for entry in payload.get("models", []) or []:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("model")
            if name:
                out.add(str(name).strip())
    return frozenset(out)


def probe_availability(
    *,
    env: Optional[dict] = None,
    fetch: Optional[Fetcher] = None,
    timeout: float = 2.0,
) -> ModelAvailability:
    """Probe Ollama for installed models. Never raises (fail-soft).

    ``fetch`` is injectable for tests: it receives the full tags URL and returns
    the decoded JSON dict.
    """
    host = _ollama_host(env)
    url = f"{host}/api/tags"
    try:
        payload = fetch(url) if fetch is not None else _default_fetch(url, timeout)
        models = _parse_models(payload if isinstance(payload, dict) else {})
        return ModelAvailability(reachable=True, models=models, source=url)
    except Exception as exc:  # noqa: BLE001 — any failure is "unreachable", not fatal
        logger.warning("Ollama availability probe failed (%s): %s", url, exc)
        return ModelAvailability(
            reachable=False, models=frozenset(), source=url, error=str(exc)[:200]
        )


# ── Cached convenience layer ────────────────────────────────────────────────────
# The router may ask several times per request; cache successful probes briefly so
# we don't hammer Ollama. Failed probes are not cached (so recovery is immediate).

@dataclass
class _Cache:
    value: Optional[ModelAvailability] = None
    expires_at: float = 0.0
    lock_marker: object = field(default_factory=object)


_CACHE = _Cache()


def get_availability(
    *,
    env: Optional[dict] = None,
    fetch: Optional[Fetcher] = None,
    timeout: float = 2.0,
    ttl: float = DEFAULT_TTL_SECONDS,
    force: bool = False,
) -> ModelAvailability:
    """Cached :func:`probe_availability` (successful probes only, ``ttl`` seconds)."""
    now = time.monotonic()
    if not force and _CACHE.value is not None and now < _CACHE.expires_at:
        return _CACHE.value
    result = probe_availability(env=env, fetch=fetch, timeout=timeout)
    if result.reachable:
        _CACHE.value = result
        _CACHE.expires_at = now + max(0.0, ttl)
    return result


def reset_cache() -> None:
    """Clear the availability cache (tests / explicit refresh)."""
    _CACHE.value = None
    _CACHE.expires_at = 0.0


def is_available(
    model: str,
    *,
    env: Optional[dict] = None,
    fetch: Optional[Fetcher] = None,
    availability: Optional[ModelAvailability] = None,
) -> bool:
    """Strict check: True iff Ollama positively reports ``model`` installed.

    When the probe is unreachable this returns False — callers that want the
    local-first "don't override on a probe failure" behaviour should use
    :func:`available_or_unknown` instead.
    """
    snap = availability or get_availability(env=env, fetch=fetch)
    return snap.reachable and snap.has(model)


def available_or_unknown(
    model: str,
    *,
    env: Optional[dict] = None,
    fetch: Optional[Fetcher] = None,
    availability: Optional[ModelAvailability] = None,
) -> bool:
    """Optimistic check used by the router for the *preferred* model.

    Returns True when Ollama positively reports the model **or** when the probe
    is unreachable (we can't tell, so we don't override the user's configured
    model). Only a positive "this model is missing" (reachable + absent) returns
    False, which is what triggers a fallback.
    """
    snap = availability or get_availability(env=env, fetch=fetch)
    if not snap.reachable:
        return True
    return snap.has(model)


__all__ = [
    "ModelAvailability",
    "DEFAULT_TTL_SECONDS",
    "probe_availability",
    "get_availability",
    "reset_cache",
    "is_available",
    "available_or_unknown",
]
