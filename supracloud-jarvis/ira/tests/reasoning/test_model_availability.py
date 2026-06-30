"""Phase 2 — local model availability detection.

Proves the probe that the router uses to decide whether to fall back:
  * a fake Ollama ``/api/tags`` payload is parsed into a model set;
  * tag-aware membership (``qwen3`` <-> ``qwen3:latest``);
  * an unreachable probe is fail-soft (no raise) and reports ``reachable=False``;
  * the optimistic ``available_or_unknown`` does NOT override on a probe failure;
  * the strict ``is_available`` DOES report missing models as missing;
  * successful probes are cached, failures are not.
"""
import pytest

from reasoning import model_availability as ma


@pytest.fixture(autouse=True)
def _fresh_cache():
    ma.reset_cache()
    yield
    ma.reset_cache()


def _fake_tags(*names):
    payload = {"models": [{"name": n} for n in names]}
    return lambda url: payload


def _boom(url):
    raise OSError("connection refused")


def test_probe_parses_installed_models():
    snap = ma.probe_availability(fetch=_fake_tags("qwen3:8b", "gemma3:12b"), env={})
    assert snap.reachable is True
    assert snap.models == frozenset({"qwen3:8b", "gemma3:12b"})
    assert snap.has("qwen3:8b")
    assert not snap.has("deepseek-r1:14b")


def test_membership_is_tag_aware():
    snap = ma.probe_availability(fetch=_fake_tags("qwen3:latest"), env={})
    assert snap.has("qwen3")          # bare name matches :latest
    snap2 = ma.probe_availability(fetch=_fake_tags("qwen3"), env={})
    assert snap2.has("qwen3:latest")  # and vice-versa


def test_unreachable_probe_is_failsoft():
    snap = ma.probe_availability(fetch=_boom, env={})
    assert snap.reachable is False
    assert snap.models == frozenset()
    assert snap.error
    assert not snap.has("qwen3:8b")


def test_is_available_strict_reports_missing():
    snap = ma.probe_availability(fetch=_fake_tags("qwen3:8b"), env={})
    assert ma.is_available("qwen3:8b", availability=snap) is True
    assert ma.is_available("deepseek-r1:32b", availability=snap) is False


def test_is_available_false_when_unreachable():
    snap = ma.probe_availability(fetch=_boom, env={})
    assert ma.is_available("qwen3:8b", availability=snap) is False


def test_available_or_unknown_is_optimistic_when_unreachable():
    snap = ma.probe_availability(fetch=_boom, env={})
    # Can't tell -> don't override the configured model.
    assert ma.available_or_unknown("qwen3:8b", availability=snap) is True


def test_available_or_unknown_reports_missing_when_reachable():
    snap = ma.probe_availability(fetch=_fake_tags("qwen3:8b"), env={})
    assert ma.available_or_unknown("qwen3:8b", availability=snap) is True
    assert ma.available_or_unknown("deepseek-r1:32b", availability=snap) is False


def test_host_strips_v1_suffix():
    captured = {}

    def fetch(url):
        captured["url"] = url
        return {"models": []}

    ma.probe_availability(fetch=fetch, env={"OLLAMA_BASE_URL": "http://box:11434/v1"})
    assert captured["url"] == "http://box:11434/api/tags"


def test_successful_probe_is_cached_failures_are_not():
    calls = {"n": 0}

    def counting(url):
        calls["n"] += 1
        return {"models": [{"name": "qwen3:8b"}]}

    a = ma.get_availability(fetch=counting, env={})
    b = ma.get_availability(fetch=counting, env={})
    assert a is b           # second read served from cache
    assert calls["n"] == 1

    ma.reset_cache()

    fail_calls = {"n": 0}

    def failing(url):
        fail_calls["n"] += 1
        raise OSError("down")

    ma.get_availability(fetch=failing, env={})
    ma.get_availability(fetch=failing, env={})
    assert fail_calls["n"] == 2  # failures re-probe every time (fast recovery)
