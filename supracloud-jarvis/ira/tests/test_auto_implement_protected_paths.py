"""Phase 2 — auto_implement refuses patches that touch a protected path.

The architect apply pipeline must never git-apply a diff that rewrites IRA's own
security/control surface (auth, approval gate, command/URL safety, biometric gate,
router, config) or its CI workflows. The denylist is checked before any git apply,
so even a dry run cannot probe a protected file.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio

import pytest

from utils.auto_implement import _is_protected_path, apply_implementation


@pytest.mark.parametrize("path", [
    "supracloud-jarvis/ira/api/middleware/auth.py",
    "utils/approval.py",
    "supracloud-jarvis/ira/utils/auto_implement.py",
    "utils/cmd_safety.py",
    "utils/net_safety.py",
    "voice/biometrics.py",
    "voice/gate.py",
    "supracloud-jarvis/ira/router.py",
    "config.py",
    ".github/workflows/test.yml",
    "supracloud-jarvis/.github/workflows/ci.yml",
])
def test_protected_paths_detected(path):
    assert _is_protected_path(path) is True


@pytest.mark.parametrize("path", [
    "supracloud-jarvis/ira/api/routes/chat.py",
    "README.md",
    "utils/search_tools.py",
    "utils/myconfig.py",          # not config.py — component boundary must hold
    "voice/voice_output.py",
])
def test_normal_paths_allowed(path):
    assert _is_protected_path(path) is False


def _impl_text(file_path: str) -> str:
    return (
        "Here is the patch:\n\n"
        "```diff\n"
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
        "```\n"
    )


def test_apply_refuses_patch_touching_auth(monkeypatch):
    monkeypatch.setenv("IRA_GIT_AUTHOR_EMAIL", "test@example.com")
    result = asyncio.run(apply_implementation(
        _impl_text("supracloud-jarvis/ira/api/middleware/auth.py"),
        author_email="test@example.com",
        dry_run=True,
    ))
    assert result.success is False
    assert "protected path" in result.error
    assert "auth.py" in result.error


def test_apply_allows_normal_file_past_denylist(monkeypatch):
    """A normal-file diff is NOT refused by the denylist (it proceeds to git apply).

    The bogus patch won't apply cleanly against the real tree, so success is False —
    but the failure must come from git apply, NOT the protected-path denylist.
    """
    monkeypatch.setenv("IRA_GIT_AUTHOR_EMAIL", "test@example.com")
    result = asyncio.run(apply_implementation(
        _impl_text("supracloud-jarvis/ira/docs/SOME_NEW_NOTE.md"),
        author_email="test@example.com",
        dry_run=True,
    ))
    assert "protected path" not in (result.error or "")


# ── Deletion / rename bypass regression ───────────────────────────────────────
# The denylist screens the file list produced by extract_changed_files(). A
# deletion puts the real path only on the "--- a/..." header (its "+++" is
# /dev/null) and a pure rename carries no "+++ b/" line at all, so a header
# extractor that matches only "+++ b/" would hand the screen an empty list and
# wave the patch through. These prove deletions and renames are caught.


def _deletion_impl(file_path: str) -> str:
    return (
        "```diff\n"
        f"diff --git a/{file_path} b/{file_path}\n"
        "deleted file mode 100644\n"
        f"--- a/{file_path}\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-a\n"
        "-b\n"
        "```\n"
    )


def _rename_impl(old: str, new: str) -> str:
    return (
        "```diff\n"
        f"diff --git a/{old} b/{new}\n"
        "similarity index 100%\n"
        f"rename from {old}\n"
        f"rename to {new}\n"
        "```\n"
    )


def test_extract_changed_files_captures_deletion_and_rename():
    from utils.auto_implement import extract_changed_files

    deleted = extract_changed_files(
        "diff --git a/x.py b/x.py\ndeleted file mode 100644\n"
        "--- a/x.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n"
    )
    assert deleted == ["x.py"]            # captured, and /dev/null dropped

    renamed = extract_changed_files(
        "diff --git a/old.py b/new.py\nsimilarity index 100%\n"
        "rename from old.py\nrename to new.py\n"
    )
    assert "old.py" in renamed and "new.py" in renamed


def test_apply_refuses_deleting_protected(monkeypatch):
    monkeypatch.setenv("IRA_GIT_AUTHOR_EMAIL", "test@example.com")
    result = asyncio.run(apply_implementation(
        _deletion_impl("supracloud-jarvis/ira/utils/approval.py"),
        author_email="test@example.com",
        dry_run=True,
    ))
    assert result.success is False
    assert "protected path" in result.error


def test_apply_refuses_renaming_protected(monkeypatch):
    monkeypatch.setenv("IRA_GIT_AUTHOR_EMAIL", "test@example.com")
    result = asyncio.run(apply_implementation(
        _rename_impl(
            "supracloud-jarvis/ira/utils/cmd_safety.py",
            "supracloud-jarvis/ira/utils/cmd_safety_off.py",
        ),
        author_email="test@example.com",
        dry_run=True,
    ))
    assert result.success is False
    assert "protected path" in result.error
