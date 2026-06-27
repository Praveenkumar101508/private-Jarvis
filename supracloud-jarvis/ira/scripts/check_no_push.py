#!/usr/bin/env python3
"""AST guard: fail if any git helper can run `git push`.

IRA never pushes to a remote automatically (the architect apply pipeline is
git apply -> commit -> restart, no push). The old CI check grepped the literal
string "git push", which cannot see the arg-vector form ``["git", "push"]`` the
codebase actually uses — so it could not catch a real regression. This parses the
target files and flags:

  * a list/tuple command vector that contains BOTH "git" and "push" as string
    literals (e.g. ``["git", "push"]`` or ``["git", "-c", "x", "push"]``);
  * positional subprocess args containing both "git" and "push"
    (e.g. ``create_subprocess_exec("git", "push", ...)``);
  * any string literal containing the substring "git push" (shell form).

It deliberately does NOT flag a dynamic runner like ``["git", *args]`` (no literal
"push"); that generic helper is fine — only a literal push is a regression.

Usage:
  python scripts/check_no_push.py [FILE ...]
Exit 0 = clean, 1 = a literal git push was found.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Scanned by default (relative to the ira/ package root = this file's parent.parent).
DEFAULT_TARGETS = [
    "utils/auto_implement.py",
    "agents/coding_agent.py",
    "agents/executor.py",
]


def _string_consts(nodes) -> list[str]:
    """Return the string-literal values among a sequence of AST nodes."""
    out = []
    for n in nodes:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def _vector_is_git_push(strings: list[str]) -> bool:
    """True if a command vector's string literals include both 'git' and 'push'."""
    lowered = [s.lower() for s in strings]
    return "git" in lowered and "push" in lowered


def find_git_push_violations(source: str, filename: str = "<src>") -> list[str]:
    """Return a list of human-readable violation descriptions (empty = clean)."""
    violations: list[str] = []
    tree = ast.parse(source, filename=filename)

    for node in ast.walk(tree):
        # (1) substring "git push" in any string literal (shell form).
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "git push" in node.value.lower():
                violations.append(f"{filename}:{node.lineno}: string literal contains 'git push'")

        # (2) list/tuple command vectors: ["git", ..., "push"].
        if isinstance(node, (ast.List, ast.Tuple)):
            if _vector_is_git_push(_string_consts(node.elts)):
                violations.append(f"{filename}:{node.lineno}: command vector contains 'git' + 'push'")

        # (3) positional subprocess args: create_subprocess_exec("git", "push", ...).
        if isinstance(node, ast.Call):
            if _vector_is_git_push(_string_consts(node.args)):
                violations.append(f"{filename}:{node.lineno}: call args contain 'git' + 'push'")

    return violations


def scan_files(paths: list[Path]) -> list[str]:
    all_violations: list[str] = []
    for p in paths:
        if not p.exists():
            continue
        all_violations.extend(find_git_push_violations(p.read_text(encoding="utf-8"), str(p)))
    return all_violations


def main(argv: list[str]) -> int:
    if argv:
        targets = [Path(a) for a in argv]
    else:
        root = Path(__file__).resolve().parent.parent  # ira/
        targets = [root / t for t in DEFAULT_TARGETS]

    violations = scan_files(targets)
    if violations:
        print("❌ CRITICAL: literal `git push` found in a git helper:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("✅ No literal `git push` found in scanned git helpers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
