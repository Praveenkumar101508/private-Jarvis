"""Phase 3 — reasoning-only Cortex calls are an ENFORCED constraint, not a soft prompt.

hermes-agent 0.15.2 has no per-invocation no-tools flag (tools are disabled at the
config level — see CORTEX_OPS.md), so the per-call enforcement is: omit --accept-hooks
(Cortex can't auto-accept a tool/hook call in a non-interactive subprocess) and prepend
a hardened no-tools directive. skills/_common.run_skill must use this mode for every
Option-A skill call. subprocess.run is mocked, so no cortex/Ollama is needed.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import cortex_bridge
from cortex_bridge import CortexBridge, CortexConfig, _REASONING_ONLY_DIRECTIVE


def _bridge_with_proc(monkeypatch, *, stdout="ok", returncode=0, stderr=""):
    run = MagicMock(return_value=SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode))
    monkeypatch.setattr(cortex_bridge.subprocess, "run", run)
    return CortexBridge(CortexConfig()), run


def test_reasoning_only_omits_accept_hooks_and_wraps_prompt(monkeypatch):
    bridge, run = _bridge_with_proc(monkeypatch)
    bridge.ask("analyze these events", reasoning_only=True)
    cmd = run.call_args.args[0]
    assert "--accept-hooks" not in cmd, "reasoning-only must NOT auto-accept tool/hook execution"
    assert "-z" in cmd
    sent = cmd[-1]                                   # the -z prompt
    assert sent.startswith(_REASONING_ONLY_DIRECTIVE)  # no-tools directive enforced up front
    assert "analyze these events" in sent


def test_default_mode_still_accepts_hooks(monkeypatch):
    """Regression guard: the normal (agentic) path keeps --accept-hooks."""
    bridge, run = _bridge_with_proc(monkeypatch)
    bridge.ask("do the thing")
    cmd = run.call_args.args[0]
    assert "--accept-hooks" in cmd
    assert cmd[-1] == "do the thing"                 # no directive injected in default mode


def test_run_skill_calls_bridge_in_reasoning_only_mode():
    """skills/_common.run_skill must invoke the bridge with reasoning_only=True."""
    from skills._common import run_skill

    captured = {}

    class _FakeBridge:
        def ask(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "FAKE-REPLY"

    out = run_skill("conversational", "hello there", bridge=_FakeBridge(), owner_name="Praveen")
    assert out == "FAKE-REPLY"
    assert captured["kwargs"].get("reasoning_only") is True
