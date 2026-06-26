"""Phase 5(b) — self-test for the AST-based no-push CI guard.

Proves the checker catches the arg-vector form (which the old literal grep missed)
as well as the shell-string form, and does NOT false-positive on the dynamic git
runner or on the real (push-free) auto_implement.py.
"""
from pathlib import Path

from scripts.check_no_push import find_git_push_violations, scan_files

_IRA_ROOT = Path(__file__).resolve().parent.parent


def test_catches_arg_vector_push():
    src = 'def f():\n    return subprocess.run(["git", "push", "origin", "main"])\n'
    assert find_git_push_violations(src)


def test_catches_arg_vector_with_config_flags():
    src = 'x = ["git", "-c", "user.name=x", "push"]\n'
    assert find_git_push_violations(src)


def test_catches_positional_call_args():
    src = 'await create_subprocess_exec("git", "push")\n'
    assert find_git_push_violations(src)


def test_catches_shell_string_form():
    src = 'cmd = "git push origin main"\n'
    assert find_git_push_violations(src)


def test_clean_when_no_push():
    src = (
        'a = ["git", "apply", "--check", patch]\n'
        'b = ["git", "add"] + files\n'
        'c = subprocess.run(["git", *args])\n'   # dynamic runner — not a literal push
        'd = ["git", "rev-parse", "HEAD"]\n'
    )
    assert find_git_push_violations(src) == []


def test_real_auto_implement_is_clean():
    """The shipped auto_implement.py must contain no literal git push."""
    assert scan_files([_IRA_ROOT / "utils" / "auto_implement.py"]) == []
