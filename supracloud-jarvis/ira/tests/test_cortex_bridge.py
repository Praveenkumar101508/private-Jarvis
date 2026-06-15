"""Unit tests for the Cortex bridge — subprocess `cortex -z` against local Ollama.

Cortex 0.15.2 ships no HTTP gateway, so the bridge shells out to the `cortex` CLI.
subprocess.run is mocked, so no cortex/Ollama is needed. Covers: the one-shot command
shape, system prepended to the prompt, stdout returned, a non-zero exit raising, and
that session_id/user_key are accepted but NOT used (thread memory is IRA-owned now).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import cortex_bridge
from cortex_bridge import CortexBridge, CortexConfig


def _bridge_with_proc(monkeypatch, *, stdout="ok", returncode=0, stderr=""):
    """Patch subprocess.run on the bridge module; return (bridge, run mock)."""
    run = MagicMock(return_value=SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode))
    monkeypatch.setattr(cortex_bridge.subprocess, "run", run)
    return CortexBridge(CortexConfig()), run


def test_ask_builds_oneshot_command(monkeypatch):
    bridge, run = _bridge_with_proc(monkeypatch, stdout="BRIDGE_OK")
    out = bridge.ask("hello")
    assert out == "BRIDGE_OK"
    cmd = run.call_args.args[0]
    assert cmd[0] == bridge.cfg.cortex_bin
    assert "-z" in cmd and cmd[-1] == "hello"
    assert "--continue" not in cmd                 # one-shot is stateless


def test_ask_prepends_system_to_prompt(monkeypatch):
    bridge, run = _bridge_with_proc(monkeypatch)
    bridge.ask("question?", system="You are terse.")
    sent = run.call_args.args[0][-1]               # the -z prompt
    assert sent.startswith("You are terse.")
    assert "question?" in sent


def test_ask_accepts_but_ignores_session_ids(monkeypatch):
    bridge, run = _bridge_with_proc(monkeypatch)
    bridge.ask("hi", session_id="conv-1", user_key="owner", session_key="legacy")
    cmd = run.call_args.args[0]
    # No --continue, and none of the ids leak into the command (memory is IRA-owned).
    assert "--continue" not in cmd
    assert "conv-1" not in cmd and "owner" not in cmd and "legacy" not in cmd


def test_ask_nonzero_exit_raises(monkeypatch):
    bridge, _ = _bridge_with_proc(monkeypatch, stdout="", returncode=2, stderr="boom")
    with pytest.raises(RuntimeError) as ei:
        bridge.ask("hi")
    assert "exited 2" in str(ei.value) and "boom" in str(ei.value)


def test_ask_returns_stripped_stdout(monkeypatch):
    bridge, _ = _bridge_with_proc(monkeypatch, stdout="  answer \n")
    assert bridge.ask("hi") == "answer"


def test_config_keeps_back_compat_fields():
    # The HTTP-era fields stay (some callers/tests import them) but are unused now.
    cfg = CortexConfig()
    assert hasattr(cfg, "base_url") and hasattr(cfg, "api_key") and hasattr(cfg, "model")
    assert cfg.cortex_bin  # resolved (env -> PATH -> native install -> "cortex")
