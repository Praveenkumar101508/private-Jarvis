"""
Shared command-argument safety validator.  # Fix P6

Two-gate model
--------------
Gate 1 (caller): prefix allowlist — only commands on the allowlist reach gate 2.
Gate 2 (this module): argument path check — reject any path argument that
  resolves outside the allow-roots, contains traversal, glob chars, or shell
  metacharacters.

Usage::

    from utils.cmd_safety import check_command_args
    ok, reason = check_command_args(["cat", "./README.md"])
    if not ok:
        return {"error": reason}
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

# ── Allow-roots: arguments resolved outside these directories are rejected ────
def _allow_roots() -> tuple[Path, ...]:
    """Allow-roots resolved at CALL time so a later os.chdir is respected.

    (Previously these were computed once at import; if the process changed working
    directory afterwards, the allow-root pointed at the stale original cwd.)
    """
    return (Path.cwd().resolve(), Path("/tmp").resolve())

# Commands whose arguments should be path-checked (everything else is free-form)
_PATH_ARG_COMMANDS: frozenset[str] = frozenset({
    "cat", "type", "grep", "find", "ls", "dir",
    "docker logs", "head", "tail", "less", "more",
    "wc", "diff", "stat",
})

# Characters that should never appear in any argument
_GLOB_CHARS_RE = re.compile(r"[*?\[\]]")
_SHELL_META_RE = re.compile(r"[;&|`$\\><]")


def _is_under_allow_root(path_str: str) -> bool:
    """Return True if path_str resolves to a location under one of _ALLOW_ROOTS."""
    try:
        resolved = Path(path_str).resolve()
    except (ValueError, OSError):
        return False
    return any(
        resolved == root or root in resolved.parents
        for root in _allow_roots()
    )


def check_command_args(parts: list[str]) -> tuple[bool, str]:
    """
    Validate command arguments.

    Args:
        parts: shlex-split command tokens (parts[0] is the command name).

    Returns:
        (True, "") if safe; (False, rejection_reason) otherwise.
    """
    if not parts:
        return True, ""

    cmd_name = parts[0].lower()
    args = parts[1:]

    for arg in args:
        # Reject shell metacharacters in any argument
        if _SHELL_META_RE.search(arg):
            return False, f"Shell metacharacter in argument: {arg!r}"

        # Reject glob characters in any argument
        if _GLOB_CHARS_RE.search(arg):
            return False, f"Glob character in argument: {arg!r}"

        # Path check only for path-taking commands
        if cmd_name not in _PATH_ARG_COMMANDS:
            continue

        # Skip flags (e.g. -n, --name)
        if arg.startswith("-"):
            continue

        # Skip non-path-like args (no / or . prefix → treat as a pattern/name literal)
        looks_like_path = arg.startswith(("/", "./", "../", "~")) or Path(arg).suffix != ""
        if not looks_like_path:
            continue

        if not _is_under_allow_root(arg):
            return False, f"Path outside allowed roots: {arg!r}"

    return True, ""


def safe_check(command_str: str) -> tuple[bool, str]:
    """Convenience wrapper: parse command_str with shlex then call check_command_args."""
    try:
        parts = shlex.split(command_str)
    except ValueError as exc:
        return False, f"Invalid command syntax: {exc}"
    return check_command_args(parts)
