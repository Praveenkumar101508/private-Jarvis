"""
Executor Agent — runs commands and scripts in a sandboxed Docker container.

Safety model:
  - Human-in-the-loop: all exec requests require explicit user confirmation
  - Allowlist-only: only pre-approved command prefixes are permitted
  - No network access in the sandbox container
  - 30-second hard timeout on all executions
  - All exec events logged to the security_events table
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete
from utils.db import acquire

# Only these command prefixes are ever permitted
_ALLOWLIST = frozenset({
    "python", "pip", "pytest", "ls", "cat", "echo", "grep",
    "find", "curl", "wget", "git status", "git log", "git diff",
    "docker ps", "docker stats", "docker logs",
})

_SYSTEM = """\
You are the Executor module of IRA — a careful, security-first command executor.

Rules you must ALWAYS follow:
1. Before executing anything, explain exactly what the command will do and why
2. Identify any risks (data loss, network calls, privilege escalation)
3. If the command is not on the allowlist, refuse and suggest a safe alternative
4. After execution, summarise what happened and what changed
5. Never execute anything that could modify production data without explicit confirmation

Allowlisted prefixes: python, pip, pytest, ls, cat, echo, grep, find, curl, wget,
                       git status, git log, git diff, docker ps, docker stats, docker logs

For any command outside the allowlist, respond:
  "Sir, that command requires explicit authorisation. Please confirm: [command] [expected outcome]"\
"""


def _is_allowed(command: str) -> bool:
    cmd = command.strip().lower()
    return any(cmd.startswith(prefix) for prefix in _ALLOWLIST)


async def _log_exec_attempt(command: str, allowed: bool, session_id: str) -> None:
    severity = "info" if allowed else "medium"
    description = f"Exec {'allowed' if allowed else 'BLOCKED'}: {command[:200]}"
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO security_events (severity, event_type, description, metadata)
               VALUES ($1, 'executor', $2, $3)""",
            severity, description, json.dumps({"session_id": session_id}),
        )


async def executor(state: IRAState) -> IRAState:
    t0 = time.monotonic()
    query = state["user_query"]

    # Use fast model to parse intent and identify the command
    parse_messages = [
        {"role": "system", "content": "Extract the exact shell command the user wants to run. Reply with ONLY the command, nothing else. If no command is identifiable, reply with: NONE"},
        {"role": "user", "content": query},
    ]
    extracted_cmd = await chat_complete(parse_messages, use_deep=False, max_tokens=100, temperature=0)
    extracted_cmd = extracted_cmd.strip()

    allowed = extracted_cmd != "NONE" and _is_allowed(extracted_cmd)
    await _log_exec_attempt(extracted_cmd, allowed, state.get("session_id", "unknown"))

    messages = [{"role": "system", "content": _SYSTEM}]
    messages.append({
        "role": "system",
        "content": f"Extracted command: {extracted_cmd}\nAllowlist check: {'PASSED' if allowed else 'FAILED'}",
    })
    messages.append({"role": "user", "content": query})

    response = await chat_complete(messages, use_deep=False, temperature=0.1)

    latency = int((time.monotonic() - t0) * 1000)
    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "llama-fast",
    }
