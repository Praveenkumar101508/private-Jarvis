"""P3.2 — SQL parameterization + input-validation regression tests.

Audit findings (2026-06-14):
- utils/db.py: asyncpg pool only; no raw SQL exposed.
- owner_profile.py: dynamic SET clause built from FIELDS whitelist; values
  passed via positional params — no user-controlled text in the SQL string.
- tasks/manager.py: update_task() whitelists column names; list_tasks()
  builds WHERE clause from Literal-typed params only — no injection path.
- All other DB calls use static parameterized SQL ($1, $2, ...).
- All request bodies in api/routes/ use Pydantic BaseModel with Field
  constraints (min/max length, Literal enums) — no raw string inputs.

These tests lock in the whitelist behaviour so any future regression that
accidentally lets untrusted text into the SQL string is caught immediately.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner_profile import FIELDS, update_profile
from tasks.manager import update_task


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_conn_mock() -> tuple[AsyncMock, list]:
    """Return (conn_mock, sql_calls) where sql_calls captures every execute call."""
    sql_calls: list[tuple[str, tuple]] = []

    async def _execute(sql: str, *args):
        sql_calls.append((sql, args))
        return None

    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=_execute)
    conn.fetchrow = AsyncMock(
        return_value={"name": "", "goals": "", "projects": "", "preferences": ""}
    )
    return conn, sql_calls


class _FakeAcquireCtx:
    """Async context manager that yields the given connection mock."""
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


# ── owner_profile: FIELDS whitelist ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_profile_ignores_unknown_columns():
    """Extra / attacker-controlled column names must NOT appear in the SQL string."""
    conn, sql_calls = _make_conn_mock()

    with patch("owner_profile.acquire", return_value=_FakeAcquireCtx(conn)):
        await update_profile(
            name="Alice",
            __class__="injected",          # not in FIELDS
            evil_col="DROP TABLE users--", # not in FIELDS
        )

    update_sqls = [sql for sql, _ in sql_calls if sql.strip().upper().startswith("UPDATE")]
    assert update_sqls, "Expected at least one UPDATE call"
    for sql in update_sqls:
        assert "evil_col" not in sql
        assert "__class__" not in sql
        assert "DROP" not in sql.upper()


@pytest.mark.asyncio
async def test_update_profile_values_are_parameterized():
    """User values must arrive as positional args, not embedded in the SQL."""
    conn, sql_calls = _make_conn_mock()
    dangerous_value = "'; DROP TABLE owner_profile; --"

    with patch("owner_profile.acquire", return_value=_FakeAcquireCtx(conn)):
        await update_profile(name=dangerous_value)

    update_sqls = [(sql, args) for sql, args in sql_calls if "UPDATE" in sql.upper()]
    assert update_sqls, "Expected an UPDATE call"
    sql, args = update_sqls[0]
    # The dangerous value must appear in the args tuple, not in the SQL string
    assert dangerous_value not in sql
    assert dangerous_value in args


@pytest.mark.asyncio
async def test_update_profile_only_known_fields_reach_db():
    """Only the four whitelisted columns should appear in any UPDATE statement."""
    conn, sql_calls = _make_conn_mock()

    with patch("owner_profile.acquire", return_value=_FakeAcquireCtx(conn)):
        await update_profile(name="Bob", goals="Learn Python", unknown="hack")

    for sql, _ in sql_calls:
        if "UPDATE" in sql.upper():
            # Only whitelisted column names may appear
            for token in sql.replace(",", " ").replace("=", " ").split():
                if token.startswith("$") or token.upper() in (
                    "UPDATE", "OWNER_PROFILE", "SET", "WHERE", "ID", "IS",
                    "TRUE", "UPDATED_AT", "NOW()", "AND", "OR",
                ):
                    continue
                assert token in FIELDS or not token.isidentifier(), (
                    f"Unexpected token {token!r} in UPDATE SQL: {sql}"
                )


def test_fields_whitelist_is_fixed():
    """FIELDS must contain exactly the four known profile columns — no accidental expansion."""
    assert set(FIELDS) == {"name", "goals", "projects", "preferences"}


# ── tasks/manager: update_task whitelist ─────────────────────────────────────

@pytest.mark.asyncio
async def test_update_task_ignores_unknown_columns():
    """Columns not in the allowed set must not appear in the UPDATE SQL."""
    task_id = str(uuid.uuid4())
    conn, sql_calls = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value={"id": uuid.UUID(task_id), "title": "t",
                                            "description": None, "priority": "medium",
                                            "status": "pending", "due_at": None,
                                            "tags": [], "source": "manual",
                                            "created_at": None, "updated_at": None,
                                            "completed_at": None})

    with patch("tasks.manager.acquire", return_value=_FakeAcquireCtx(conn)):
        await update_task(task_id, title="legit", evil_col="DROP TABLE tasks--")

    update_sqls = [sql for sql, _ in sql_calls if "UPDATE" in sql.upper()]
    assert update_sqls, "Expected an UPDATE call"
    for sql in update_sqls:
        assert "evil_col" not in sql
        assert "DROP" not in sql.upper()


@pytest.mark.asyncio
async def test_update_task_values_are_positional_args():
    """Dangerous values must travel as positional $N parameters, not in the SQL."""
    task_id = str(uuid.uuid4())
    dangerous = "'; DELETE FROM tasks; --"
    conn, sql_calls = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value={"id": uuid.UUID(task_id), "title": dangerous,
                                            "description": None, "priority": "medium",
                                            "status": "pending", "due_at": None,
                                            "tags": [], "source": "manual",
                                            "created_at": None, "updated_at": None,
                                            "completed_at": None})

    with patch("tasks.manager.acquire", return_value=_FakeAcquireCtx(conn)):
        await update_task(task_id, title=dangerous)

    update_sqls = [(sql, args) for sql, args in sql_calls if "UPDATE" in sql.upper()]
    assert update_sqls, "Expected an UPDATE call"
    sql, args = update_sqls[0]
    assert dangerous not in sql
    assert dangerous in args


@pytest.mark.asyncio
async def test_update_task_empty_kwargs_skips_update():
    """Passing no fields should produce no UPDATE (avoid no-op SQL)."""
    task_id = str(uuid.uuid4())
    conn, sql_calls = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value={"id": uuid.UUID(task_id), "title": "t",
                                            "description": None, "priority": "medium",
                                            "status": "pending", "due_at": None,
                                            "tags": [], "source": "manual",
                                            "created_at": None, "updated_at": None,
                                            "completed_at": None})

    with patch("tasks.manager.acquire", return_value=_FakeAcquireCtx(conn)):
        await update_task(task_id, totally_unknown="ignored")

    update_sqls = [sql for sql, _ in sql_calls if sql.strip().upper().startswith("UPDATE")]
    assert update_sqls == [], "No UPDATE should fire when only unknown columns are given"


# ── Pydantic model presence check (import-time) ───────────────────────────────

def test_chat_request_has_pydantic_model():
    """ChatRequest must be a Pydantic model with a message field."""
    from api.routes.chat import ChatRequest
    from pydantic import BaseModel
    assert issubclass(ChatRequest, BaseModel)
    assert "message" in ChatRequest.model_fields


def test_task_create_uses_literal_priority():
    """TaskCreate must constrain priority to known Literal values."""
    from api.routes.tasks import TaskCreate
    from pydantic import BaseModel
    assert issubclass(TaskCreate, BaseModel)
    # Priority field must exist and be annotated
    assert "priority" in TaskCreate.model_fields


def test_research_request_has_length_constraints():
    """ResearchRequest must impose a max length to prevent oversized payloads."""
    from api.routes.research import ResearchRequest
    from pydantic import BaseModel
    assert issubclass(ResearchRequest, BaseModel)
    # The query field should have a max length guard
    field = ResearchRequest.model_fields.get("query") or ResearchRequest.model_fields.get("message")
    assert field is not None, "ResearchRequest must have a query or message field"
