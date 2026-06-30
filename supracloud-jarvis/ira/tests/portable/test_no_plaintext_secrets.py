"""V2·Phase 6 — the example env files must ship no real secrets.

Token/key fields must be blank, and infra secrets must be obvious placeholders, so
copying demo.env.example never leaks a credential into a committed bundle.
"""
from pathlib import Path

import pytest

_SJ = Path(__file__).resolve().parents[3]
_DEMO = _SJ / "portable" / "demo.env.example"
_MAIN = _SJ / ".env.example"

# Keys whose value must be EMPTY in an example file.
_MUST_BE_BLANK = {
    "REPLICATE_API_TOKEN", "APIFY_API_TOKEN", "TAVILY_API_KEY",
    "SERPER_API_KEY", "VLLM_API_KEY", "X_FALLBACK_API_KEY",
}
# Keys that may carry a value but only an obvious placeholder.
_PLACEHOLDER_OK = {"IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD"}
_PLACEHOLDER_MARKERS = ("change", "your", "example", "placeholder", "xxx", "<", "ci-")


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        # strip an inline comment (only when '#' follows whitespace, so '#' inside a
        # value is preserved)
        hashpos = v.find(" #")
        if hashpos != -1:
            v = v[:hashpos].strip()
        out[k.strip()] = v
    return out


@pytest.mark.parametrize("path", [_DEMO, _MAIN])
def test_token_fields_are_blank(path):
    env = _parse(path)
    for key in _MUST_BE_BLANK:
        if key in env:
            assert env[key] == "", f"{path.name}: {key} must ship blank, got {env[key]!r}"


def test_demo_infra_secrets_are_placeholders():
    env = _parse(_DEMO)
    for key in _PLACEHOLDER_OK:
        if key in env and env[key]:
            val = env[key].lower()
            assert any(m in val for m in _PLACEHOLDER_MARKERS), (
                f"demo.env.example: {key}={env[key]!r} looks like a real secret"
            )


def test_demo_env_is_hardened():
    env = _parse(_DEMO)
    assert env.get("IRA_MODE") == "portable_demo"
    assert env.get("WEB_SEARCH_ENABLED") == "false"
    assert env.get("IRA_USE_CORTEX") == "false"
    assert env.get("ANDROID_ACTUATOR_ENABLED") == "false"
    assert env.get("IRA_PORTABLE_VOICE_2FA") == "false"
