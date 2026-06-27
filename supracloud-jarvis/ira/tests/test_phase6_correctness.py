"""Phase 6 — correctness nits.

(a) coding_agent._run_sync: the never-operate-on-main guard must run BEFORE creating
    the work branch (it used to run after `checkout -b`, so it always saw the new
    branch and never fired), and the commit must stage ONLY the files Aider changed
    (not `git add -A`, which sweeps a pre-existing dirty tree into the commit).
(b) cmd_safety allow-roots must be evaluated at CALL time so a later os.chdir is
    respected (they used to be frozen at import).
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
from types import SimpleNamespace

import agents.coding_agent as ca
from utils import cmd_safety


def _ns(rc=0, out="", err=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


# ── (a) coding agent ──────────────────────────────────────────────────────────

def test_refuses_when_starting_on_main_before_any_branch(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if cmd[0] == "git" and cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
            return _ns(0, "main\n")
        return _ns(0)

    monkeypatch.setattr(ca, "CODER_BACKEND", "local")
    monkeypatch.setattr(ca.subprocess, "run", fake_run)

    res = asyncio.run(ca.run_coding_task("fix the bug in voice/x.py", "/tmp/repo", is_owner=True))
    assert res["ok"] is False and res["reason"] == "refused-main"
    # The guard must fire BEFORE any branch is created and before Aider runs.
    assert not any(c[:2] == ["git", "checkout"] for c in calls), "no branch should be created on main"
    assert not any("aider" in c[0] for c in calls if c), "Aider must not run when refused on main"


def test_commit_stages_only_changed_files(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if cmd[0] == "git":
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return _ns(0, "feature-x\n")          # not main → proceed
            if cmd[1] == "rev-parse":
                return _ns(0, "deadbeef1234567\n")
            if cmd[1] == "status":
                return _ns(0, " M voice/x.py\n?? new_test.py\n")
            return _ns(0)
        if "aider" in cmd[0]:
            return _ns(0, "Applied edits")
        if "pytest" in " ".join(cmd):
            return _ns(0, "1 passed")
        return _ns(0)

    monkeypatch.setattr(ca, "CODER_BACKEND", "local")
    monkeypatch.setattr(ca.subprocess, "run", fake_run)

    res = asyncio.run(ca.run_coding_task("fix the bug in voice/x.py", "/tmp/repo", is_owner=True))
    assert res["ok"] is True

    add_calls = [c for c in calls if c[:2] == ["git", "add"]]
    assert add_calls, "expected a git add"
    assert all("-A" not in c for c in add_calls), "must not use `git add -A`"
    assert any(c[:3] == ["git", "add", "--"] and "voice/x.py" in c and "new_test.py" in c
               for c in add_calls), "must stage exactly the changed files"


# ── (b) cmd_safety allow-roots at call time ───────────────────────────────────

def test_allow_roots_track_chdir(tmp_path, monkeypatch):
    (tmp_path / "data.txt").write_text("x")
    monkeypatch.chdir(tmp_path)

    # Evaluated at call time → the new cwd is now an allow-root.
    assert tmp_path.resolve() in cmd_safety._allow_roots()

    ok, _reason = cmd_safety.check_command_args(["cat", "data.txt"])
    assert ok, "a path under the (new) cwd must be allowed"


def test_path_outside_allow_roots_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ok, reason = cmd_safety.check_command_args(["cat", "/etc/passwd"])
    assert ok is False and reason
