"""Phase 6 security invariants — static regression guards (run anywhere, no infra/gateway).

Guardrail 5: the self-modification path has NO remote push, and the local apply pipeline
is gated behind the explicit `architect apply` trigger. The architect SKILL is
reasoning-only (it produces diffs; it never applies or pushes).
"""
import re
from pathlib import Path

IRA = Path(__file__).resolve().parents[1]  # .../supracloud-jarvis/ira


def _read(rel: str) -> str:
    return (IRA / rel).read_text(encoding="utf-8", errors="ignore")


def test_auto_implement_has_no_remote_push():
    src = _read("utils/auto_implement.py")
    assert "remote sync intentionally absent" in src, "missing the no-remote-push invariant marker"
    assert not re.search(r"git\s+push|['\"]push['\"]", src), "auto_implement.py must never invoke git push"


def test_local_apply_is_gated_by_explicit_trigger():
    chat = _read("api/routes/chat.py")
    assert "is_apply_trigger" in chat and "apply_implementation" in chat
    # the gate (is_apply_trigger) must precede the apply call in the source
    assert chat.index("is_apply_trigger") < chat.index("apply_implementation")


def test_architect_skill_is_reasoning_only():
    src = _read("skills/architect/__init__.py")
    assert "apply_implementation" not in src, "the architect skill must not apply diffs"
    # reasoning-only: it calls the bridge, never shells out (docstrings may *describe* git)
    assert "subprocess" not in src and "os.system" not in src, "the architect skill must not execute commands"
