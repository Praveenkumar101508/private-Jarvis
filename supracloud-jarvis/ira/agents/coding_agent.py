"""
ira/agents/coding_agent.py — sovereign coding agent (Aider + local coder model).

Owner-gated, BRANCH-ONLY, local-by-default. Shells out to Aider headlessly:
  CODER_BACKEND=local (default) -> aider --model ollama/<CODER_MODEL>
    (qwen2.5-coder:14b — fits the 20GB A4500) against local Ollama (OLLAMA_API_BASE).
    Nothing leaves the box.
  CODER_BACKEND=claude          -> aider --model <CODER_CLAUDE_MODEL>; logs a cloud
    egress warning ("CLOUD: code sent to the toolmaker").

It NEVER edits main/master and NEVER pushes/deletes/deploys (those return
needs-confirmation, mirroring AGENTS.md's gated self-modification rule). It creates a
fresh branch, runs Aider, runs the repo's test command, and commits on the branch.

Config (env):
  CODER_BACKEND       local | claude            (default local)
  CODER_MODEL         ollama coder tag          (default qwen2.5-coder:14b)
  CODER_CLAUDE_MODEL  aider's the assistant model alias (default "sonnet")
  OLLAMA_API_BASE     http://127.0.0.1:11434
  CODING_REQUIRE_OWNER  true|false              (default true — owner-gate)
  CODER_ALLOWED_REPOS   comma-separated absolute repo paths (empty = any)
  CODER_REPO_PATH       default repo to edit    (default: the IRA package dir)
  CODER_TEST_CMD        test command            (default "pytest -q")
  CODER_TIMEOUT         per-subprocess seconds   (default 1800)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("ira.coding")


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


CODER_BACKEND = _env("CODER_BACKEND", "local").lower()
CODER_MODEL = _env("CODER_MODEL", "qwen2.5-coder:14b")   # 14B fits 20GB; 32B only on 24GB+ — never default
CODER_CLAUDE_MODEL = _env("CODER_CLAUDE_MODEL", "sonnet")
OLLAMA_API_BASE = _env("OLLAMA_API_BASE", "http://127.0.0.1:11434").rstrip("/")
CODER_TEST_CMD = _env("CODER_TEST_CMD", "pytest -q")
CODER_TIMEOUT = float(_env("CODER_TIMEOUT", "1800"))
CODING_REQUIRE_OWNER = _env("CODING_REQUIRE_OWNER", "true").lower() in ("1", "true", "yes", "on")
_ALLOWED_REPOS = [p.strip() for p in (os.getenv("CODER_ALLOWED_REPOS") or "").split(",") if p.strip()]

# ── Intent detection ──────────────────────────────────────────────────────────
# Strong phrases that are unambiguously coding asks.
_STRONG_RE = re.compile(r"\b(find (?:the )?bug|add a test|refactor|debug)\b", re.I)
# A coding verb…
_VERB_RE = re.compile(r"\b(fix|edit|implement|rename|patch|optimi[sz]e|add|write|find|change)\b", re.I)
# …paired with code context (keeps "fix my dinner reservation" out).
_CTX_RE = re.compile(
    r"(\bcode\b|\bbug\b|\btest(s)?\b|\bfunction\b|\bmethod\b|\bendpoint\b|\bmodule\b|"
    r"\bfile\b|\brepo(sitory)?\b|\bbranch\b|\bclass\b|\bimport\b|\btypo\b|\breadme\b|"
    r"\.py\b|\.ts(x)?\b|\.js\b|\.md\b)",
    re.I,
)
# Intents we will NOT auto-act on — return needs-confirmation instead.
_DANGER_RE = re.compile(
    r"\b(delete|remove the (?:repo|project)|rm\s+-rf|force.?push|push\s+--?force|"
    r"deploy|publish|drop (?:table|database)|wipe|destroy|reset --hard)\b",
    re.I,
)


def is_coding_request(query: str) -> bool:
    """True for spoken/typed coding asks (verb + code context, or a strong phrase)."""
    if not query:
        return False
    if _STRONG_RE.search(query):
        return True
    return bool(_VERB_RE.search(query) and _CTX_RE.search(query))


def needs_confirmation(instruction: str) -> str | None:
    """Return the matched dangerous keyword (delete/force-push/deploy/…) or None."""
    m = _DANGER_RE.search(instruction or "")
    return m.group(0).strip() if m else None


def default_repo_path() -> str:
    # The IRA package dir — git resolves the repo root from here; tests run here.
    return os.getenv("CODER_REPO_PATH") or str(Path(__file__).resolve().parent.parent)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:40] or "task").strip("-")


def _aider_bin() -> str:
    return os.getenv("CODER_AIDER_BIN") or shutil.which("aider") or "aider"


def _aider_cmd(instruction: str) -> tuple[list[str], dict, bool]:
    """Build the headless Aider command + env. Returns (cmd, env, is_cloud)."""
    env = dict(os.environ)
    if CODER_BACKEND == "claude":
        model = CODER_CLAUDE_MODEL
        cloud = True
    else:
        model = CODER_MODEL if CODER_MODEL.startswith("ollama/") else f"ollama/{CODER_MODEL}"
        env["OLLAMA_API_BASE"] = OLLAMA_API_BASE
        cloud = False
    cmd = [
        _aider_bin(),
        "--model", model,
        "--yes-always",        # headless — auto-confirm
        "--no-auto-commits",   # we run tests, then commit ourselves
        "--message", instruction,
    ]
    return cmd, env, cloud


def _git(repo: str, *args: str) -> tuple[int, str, str]:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _changed_files(repo: str) -> list[str]:
    _rc, out, _err = _git(repo, "status", "--porcelain")
    files = []
    for line in out.splitlines():
        name = line[3:].strip() if len(line) > 3 else line.strip()
        if name:
            files.append(name)
    return files


def _run_tests(repo: str) -> tuple[bool | None, str]:
    try:
        p = subprocess.run(
            shlex.split(CODER_TEST_CMD), cwd=repo, capture_output=True, text=True, timeout=CODER_TIMEOUT
        )
        return (p.returncode == 0), (p.stdout or p.stderr or "")[-800:].strip()
    except FileNotFoundError:
        return None, f"test command not found: {CODER_TEST_CMD!r}"
    except subprocess.TimeoutExpired:
        return False, "tests timed out"


def _run_sync(instruction: str, repo: str) -> dict:
    branch = f"ira/{_slug(instruction)}-{int(time.time())}"
    rc, _out, err = _git(repo, "checkout", "-b", branch)
    if rc != 0:
        return {"ok": False, "reason": "git-branch-failed", "summary": err.strip()[:400], "branch": branch}
    # Belt-and-braces: never operate on main/master.
    cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    if cur in ("main", "master"):
        return {"ok": False, "reason": "refused-main", "summary": "Refusing to edit main/master."}

    cmd, env, cloud = _aider_cmd(instruction)
    if cloud:
        logger.warning("CLOUD: code sent to the toolmaker")
    try:
        proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=CODER_TIMEOUT)
    except FileNotFoundError:
        return {"ok": False, "reason": "aider-not-found", "branch": branch,
                "summary": "Aider is not installed. Run: pipx install aider-chat"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "aider-timeout", "branch": branch,
                "summary": f"Aider timed out after {CODER_TIMEOUT:.0f}s"}

    files = _changed_files(repo)
    tests_passed, test_out = _run_tests(repo)

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"ira: {instruction[:72]}")
    commit = _git(repo, "rev-parse", "HEAD")[1].strip()[:10]

    return {
        "ok": proc.returncode == 0,
        "summary": (proc.stdout or "").strip()[-600:] or "Edits applied.",
        "files_changed": files,
        "tests_passed": tests_passed,
        "test_output": test_out,
        "branch": branch,
        "commit": commit,
        "backend": "claude" if cloud else "local",
    }


async def run_coding_task(instruction: str, repo_path: str | None = None, *, is_owner: bool) -> dict:
    """Owner-gated, branch-only coding task via Aider. See the module docstring."""
    if CODING_REQUIRE_OWNER and not is_owner:
        return {"ok": False, "reason": "owner-gate",
                "summary": "Coding changes are restricted to the verified owner."}
    action = needs_confirmation(instruction)
    if action:
        return {"ok": False, "reason": "needs-confirmation", "action": action,
                "summary": f"That asks me to {action!r}. I won't do that without explicit confirmation."}

    repo = str(Path(repo_path or default_repo_path()).resolve())
    if _ALLOWED_REPOS:
        allowed = [str(Path(p).resolve()) for p in _ALLOWED_REPOS]
        if not any(repo == a or repo.startswith(a + os.sep) for a in allowed):
            return {"ok": False, "reason": "repo-not-allowed",
                    "summary": f"{repo} is not in CODER_ALLOWED_REPOS."}

    return await asyncio.to_thread(_run_sync, instruction, repo)


def spoken_result(result: dict) -> str:
    """A one/two-sentence spoken summary of a coding result (for the voice path)."""
    if result.get("ok"):
        n = len(result.get("files_changed") or [])
        tp = result.get("tests_passed")
        tests = "tests passed" if tp else ("tests failed" if tp is False else "tests not run")
        return f"Done. I changed {n} file{'' if n == 1 else 's'} on branch {result.get('branch', '')} and {tests}."
    reason = result.get("reason", "error")
    if reason == "owner-gate":
        return "Sorry, I can only make code changes for my owner."
    if reason == "needs-confirmation":
        return f"That looks like a {result.get('action')} action — say 'confirm' and I'll proceed."
    return f"I couldn't complete that: {str(result.get('summary', 'unknown error'))[:160]}"


__all__ = [
    "run_coding_task", "is_coding_request", "needs_confirmation",
    "default_repo_path", "spoken_result",
]
