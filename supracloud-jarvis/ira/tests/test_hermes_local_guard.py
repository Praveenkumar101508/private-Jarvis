"""Prompt 1.3 — Hermes local-only sovereignty guard.

`hermes_local_only_warning` returns a warning string when IRA_USE_HERMES is true
but IRA_HERMES_URL is not local; None otherwise. It must NEVER block startup, so
it only returns a message (main.py logs it loudly).
"""
from config import hermes_local_only_warning


def test_local_urls_produce_no_warning():
    assert hermes_local_only_warning(True, "http://127.0.0.1:8642/v1") is None
    assert hermes_local_only_warning(True, "http://localhost:8642/v1") is None
    assert hermes_local_only_warning(True, "http://[::1]:8642/v1") is None


def test_nonlocal_url_warns_when_hermes_enabled():
    msg = hermes_local_only_warning(True, "https://portal.nousresearch.com/v1")
    assert msg is not None
    assert "NOT local" in msg
    assert "portal.nousresearch.com" in msg


def test_disabled_hermes_never_warns_even_with_remote_url():
    assert hermes_local_only_warning(False, "https://portal.nousresearch.com/v1") is None


def test_reads_environment_when_args_omitted(monkeypatch):
    monkeypatch.setenv("IRA_USE_HERMES", "true")
    monkeypatch.setenv("IRA_HERMES_URL", "https://example.com/v1")
    assert hermes_local_only_warning() is not None

    monkeypatch.setenv("IRA_HERMES_URL", "http://127.0.0.1:8642/v1")
    assert hermes_local_only_warning() is None

    monkeypatch.setenv("IRA_USE_HERMES", "false")
    monkeypatch.setenv("IRA_HERMES_URL", "https://example.com/v1")
    assert hermes_local_only_warning() is None
