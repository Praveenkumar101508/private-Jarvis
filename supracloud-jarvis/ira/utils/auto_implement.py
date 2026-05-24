"""
IRA Auto-Implementation Utility — safe code application pipeline.

Pipeline:
  1. Extract unified diffs from LLM output
  2. git apply --check   (dry-run — fail loudly if patch won't apply)
  3. git apply            (apply the patch)
  4. git commit -m "..."  (commit with Praveenkumar as author)
  5. docker compose restart <services>  (only restart affected services)
  6. Return structured result dict

All git operations run in the repo root so they work whether IRA
is running inside Docker or outside.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger("ira.auto_implement")

# The repo root is assumed to be 3 levels up from this file:
# ira/utils/auto_implement.py → ira/ → supracloud-jarvis/ → private-Jarvis-main/
# We find it at runtime so it works in both Docker (mounted) and local dev.
_REPO_ROOT: Path | None = None


def _find_repo_root() -> Path:
    """Walk up from this file until we find the git root."""
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    candidate = Path(__file__).resolve().parent
    for _ in range(6):
        if (candidate / ".git").is_dir():
            _REPO_ROOT = candidate
            return _REPO_ROOT
        candidate = candidate.parent
    # Fallback — use the env var set by docker-compose
    fallback = os.getenv("IRA_REPO_ROOT", "/app")
    _REPO_ROOT = Path(fallback)
    logger.warning(f"Could not find .git dir — using fallback repo root: {_REPO_ROOT}")
    return _REPO_ROOT


def _run(cmd: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


class ApplyResult(NamedTuple):
    success: bool
    message: str
    files_changed: list[str]
    commit_hash: str
    services_restarted: list[str]
    error: str


# ── Diff extraction ───────────────────────────────────────────────────────────

_DIFF_BLOCK_RE = re.compile(
    r"```diff\s*\n(.*?)```",
    re.DOTALL,
)

_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)

_COMMIT_MSG_RE = re.compile(
    r"```\s*(?:bash|text|commit)?\s*\n(feat|fix|chore|docs|refactor|style|test|perf).+?```",
    re.DOTALL | re.IGNORECASE,
)

_RESTART_CMD_RE = re.compile(
    r"docker compose restart\s+(.+?)(?:\n|$)",
    re.IGNORECASE,
)


def extract_diffs(implementation_text: str) -> list[str]:
    """Extract raw unified diff blocks from LLM output."""
    return [m.group(1).strip() for m in _DIFF_BLOCK_RE.finditer(implementation_text)]


def extract_commit_message(implementation_text: str) -> str:
    """Extract the git commit message from LLM output."""
    m = _COMMIT_MSG_RE.search(implementation_text)
    if m:
        return m.group(0).strip().strip("`").strip()
    # Fallback: extract first feat/fix line
    for line in implementation_text.splitlines():
        line = line.strip()
        if line.startswith(("feat:", "fix:", "chore:", "refactor:")):
            return line
    return "feat: auto-implement architect feature"


def extract_services(implementation_text: str) -> list[str]:
    """Extract docker compose service names to restart from LLM output."""
    m = _RESTART_CMD_RE.search(implementation_text)
    if m:
        raw = m.group(1).strip()
        return [s.strip() for s in raw.split() if s.strip()]
    # Default: restart the API (safe default)
    return ["ira-api"]


def extract_changed_files(diff_text: str) -> list[str]:
    """Extract file paths from a unified diff."""
    return _FILE_HEADER_RE.findall(diff_text)


# ── Core apply pipeline ───────────────────────────────────────────────────────

async def apply_implementation(
    implementation_text: str,
    author_name: str = "Praveenkumar",
    author_email: str = "praveenkumar101508@gmail.com",
    dry_run: bool = False,
    push: bool = False,
) -> ApplyResult:
    """
    Extract diffs from LLM output, apply them safely, commit, restart services.

    dry_run=True: only validates the patch without applying (use for preview).
    """
    repo = _find_repo_root()
    diffs = extract_diffs(implementation_text)

    if not diffs:
        return ApplyResult(
            success=False,
            message="No unified diffs found in the implementation output.",
            files_changed=[],
            commit_hash="",
            services_restarted=[],
            error="No diff blocks detected — ensure the LLM output contains ```diff blocks.",
        )

    # Combine all diffs into a single patch file
    combined_patch = "\n".join(diffs)
    files_changed: list[str] = []
    for diff in diffs:
        files_changed.extend(extract_changed_files(diff))
    files_changed = list(dict.fromkeys(files_changed))  # deduplicate, preserve order

    commit_msg = extract_commit_message(implementation_text)
    services = extract_services(implementation_text)

    # ── Step 1: Write patch to temp file ─────────────────────────────────────
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as f:
        f.write(combined_patch + "\n")
        patch_path = f.name

    try:
        # ── Step 2: Dry-run validation ────────────────────────────────────────
        code, out, err = _run(
            ["git", "apply", "--check", "--whitespace=fix", patch_path],
            cwd=repo,
        )
        if code != 0:
            return ApplyResult(
                success=False,
                message="Patch validation failed — no changes were made.",
                files_changed=files_changed,
                commit_hash="",
                services_restarted=[],
                error=f"git apply --check:\n{err}",
            )

        if dry_run:
            return ApplyResult(
                success=True,
                message="Dry-run validation passed — patch is safe to apply.",
                files_changed=files_changed,
                commit_hash="",
                services_restarted=[],
                error="",
            )

        # ── Step 3: Apply patch ───────────────────────────────────────────────
        code, out, err = _run(
            ["git", "apply", "--whitespace=fix", patch_path],
            cwd=repo,
        )
        if code != 0:
            return ApplyResult(
                success=False,
                message="Patch application failed.",
                files_changed=files_changed,
                commit_hash="",
                services_restarted=[],
                error=f"git apply:\n{err}",
            )

        # ── Step 4: Stage changed files ───────────────────────────────────────
        _run(["git", "add"] + files_changed, cwd=repo)

        # ── Step 5: Commit ────────────────────────────────────────────────────
        full_commit_msg = (
            f"{commit_msg}\n\n"
            f"Auto-implemented by IRA Architect Agent.\n"
            f"Files: {', '.join(files_changed)}\n\n"
            f"Co-Authored-By: {author_name} <{author_email}>"
        )
        code, out, err = _run(
            [
                "git",
                "-c", f"user.name={author_name}",
                "-c", f"user.email={author_email}",
                "commit", "-m", full_commit_msg,
            ],
            cwd=repo,
        )
        if code != 0:
            return ApplyResult(
                success=False,
                message="Commit failed (patch was applied but not committed).",
                files_changed=files_changed,
                commit_hash="",
                services_restarted=[],
                error=f"git commit:\n{err}",
            )

        # Extract commit hash
        _, hash_out, _ = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo)
        commit_hash = hash_out.strip()

        # ── Step 6: Push to remote ────────────────────────────────────────────
        if push:
            _run(["git", "push", "origin", "HEAD"], cwd=repo, timeout=60)

        # ── Step 7: Restart affected services ─────────────────────────────────
        restarted: list[str] = []
        for svc in services:
            rc, _, _ = _run(
                ["docker", "compose", "restart", svc],
                cwd=repo / "supracloud-jarvis",
                timeout=120,
            )
            if rc == 0:
                restarted.append(svc)

        return ApplyResult(
            success=True,
            message=(
                f"✅ Feature implemented successfully!\n"
                f"- {len(files_changed)} file(s) changed: {', '.join(files_changed)}\n"
                f"- Committed as `{commit_hash}`\n"
                f"- Services restarted: {', '.join(restarted) if restarted else 'none (manual restart may be needed)'}"
            ),
            files_changed=files_changed,
            commit_hash=commit_hash,
            services_restarted=restarted,
            error="",
        )

    except subprocess.TimeoutExpired as e:
        return ApplyResult(
            success=False,
            message="Operation timed out.",
            files_changed=files_changed,
            commit_hash="",
            services_restarted=[],
            error=str(e),
        )
    except Exception as e:
        logger.exception("Auto-implement pipeline failed")
        return ApplyResult(
            success=False,
            message="Unexpected error during implementation.",
            files_changed=files_changed,
            commit_hash="",
            services_restarted=[],
            error=str(e),
        )
    finally:
        # Clean up temp file
        try:
            os.unlink(patch_path)
        except OSError:
            pass


async def apply_implementation_async(
    implementation_text: str,
    author_name: str = "Praveenkumar",
    author_email: str = "praveenkumar101508@gmail.com",
    dry_run: bool = False,
) -> ApplyResult:
    """Async wrapper — runs the blocking apply pipeline in an executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: asyncio.run(apply_implementation(
            implementation_text, author_name, author_email, dry_run
        )),
    )
