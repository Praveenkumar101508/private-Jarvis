"""Protected-path enforcement for the architect auto-apply pipeline.

The architect agent emits unified diffs that ``apply_implementation`` applies to
the working tree. It must never be able to modify, delete, or rename IRA's
security-critical modules via a crafted diff.

Deletion and rename diffs put the real path on the ``--- a/...`` / ``rename``
header lines (deletions carry ``+++ /dev/null``), so the file-header extraction
must capture those too — otherwise the protected-path screen sees an empty file
list and waves the patch through.
"""
import os
import sys

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auto_implement import (  # noqa: E402
    apply_implementation,
    extract_changed_files,
    _is_protected_path,
)


def _deletion_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"deleted file mode 100644\n"
        f"--- a/{path}\n"
        f"+++ /dev/null\n"
        f"@@ -1,2 +0,0 @@\n"
        f"-a\n"
        f"-b\n"
    )


def _rename_diff(old: str, new: str) -> str:
    return (
        f"diff --git a/{old} b/{new}\n"
        f"similarity index 100%\n"
        f"rename from {old}\n"
        f"rename to {new}\n"
    )


def test_extract_changed_files_catches_deletion():
    diff = _deletion_diff("ira/utils/approval.py")
    assert extract_changed_files(diff) == ["ira/utils/approval.py"]


def test_extract_changed_files_drops_dev_null():
    paths = extract_changed_files(_deletion_diff("ira/utils/approval.py"))
    assert "/dev/null" not in paths


def test_extract_changed_files_catches_rename():
    diff = _rename_diff("ira/utils/approval.py", "ira/utils/approval_old.py")
    paths = extract_changed_files(diff)
    assert "ira/utils/approval.py" in paths
    assert "ira/utils/approval_old.py" in paths


def test_is_protected_path_normalizes_prefixes():
    assert _is_protected_path("ira/utils/approval.py")
    assert _is_protected_path("supracloud-jarvis/ira/utils/approval.py")
    assert _is_protected_path("./ira/utils/approval.py")
    assert not _is_protected_path("ira/agents/note.py")


async def test_apply_refuses_patch_deleting_protected():
    impl = "```diff\n" + _deletion_diff("ira/utils/approval.py") + "```\n"
    result = await apply_implementation(impl, dry_run=True)
    assert result.success is False
    assert "protected path" in result.error.lower()


async def test_apply_refuses_patch_renaming_protected():
    impl = "```diff\n" + _rename_diff(
        "ira/utils/cmd_safety.py", "ira/utils/cmd_safety_disabled.py"
    ) + "```\n"
    result = await apply_implementation(impl, dry_run=True)
    assert result.success is False
    assert "protected path" in result.error.lower()
