"""Prompt 2.1 — the reusable approval guardrail (draft -> confirm -> execute).

Covers the required cases: a draft is returned without executing, execution happens
ONLY after confirm, and an expired token is rejected. Plus owner-scoping and async
execute callables.
"""
import asyncio

from utils.approval import ApprovalGuardrail


def test_draft_returns_token_and_preview_without_executing():
    g = ApprovalGuardrail()
    fired = []
    d = g.draft(owner="owner", action="send_email", preview="To: x@y\nHi there",
                execute=lambda: fired.append(1))
    assert d.token
    assert d.action == "send_email"
    assert "To: x@y" in d.preview
    assert fired == []                      # nothing runs at draft time
    assert g.pending_count("owner") == 1


def test_execute_only_after_confirm():
    g = ApprovalGuardrail()
    fired = []
    d = g.draft(owner="owner", action="send_email", preview="p",
                execute=lambda: (fired.append("sent"), "ok")[1])
    assert fired == []                      # still nothing before confirm

    res = asyncio.run(g.confirm(owner="owner", token=d.token))
    assert res.executed and res.result == "ok"
    assert fired == ["sent"]

    # One-shot: confirming the same token again does nothing.
    res2 = asyncio.run(g.confirm(owner="owner", token=d.token))
    assert res2.status == "not_found"
    assert fired == ["sent"]


def test_expired_token_is_rejected():
    clock = [1000.0]
    g = ApprovalGuardrail(ttl_seconds=60, now=lambda: clock[0])
    fired = []
    d = g.draft(owner="owner", action="send_email", preview="p",
                execute=lambda: fired.append(1))

    clock[0] += 61                          # advance past the TTL
    res = asyncio.run(g.confirm(owner="owner", token=d.token))
    assert res.status == "expired"
    assert fired == []                      # an expired draft never executes


def test_other_owner_cannot_confirm():
    g = ApprovalGuardrail()
    fired = []
    d = g.draft(owner="alice", action="send_email", preview="p",
                execute=lambda: fired.append(1))

    res = asyncio.run(g.confirm(owner="bob", token=d.token))
    assert res.status == "not_found"
    assert fired == []                      # a different user can't confirm it

    res2 = asyncio.run(g.confirm(owner="alice", token=d.token))
    assert res2.executed
    assert fired == [1]


def test_confirm_awaits_async_execute():
    g = ApprovalGuardrail()

    async def _send():
        return "async-ok"

    d = g.draft(owner="owner", action="send_email", preview="p", execute=_send)
    res = asyncio.run(g.confirm(owner="owner", token=d.token))
    assert res.executed and res.result == "async-ok"
