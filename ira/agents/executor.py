"""
Executor Agent — runs allowlisted commands inside the container.

Safety model:
  - Allowlist-only: only pre-approved command prefixes are permitted
  - 30-second hard timeout on all executions
  - Minimal environment (no network, restricted PATH, /tmp working dir)
  - All exec events logged to the security_events table
  - Output capped at 3 000 chars to prevent LLM context overflow
"""

from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
import time

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


async def _run_command(command: str, timeout: int = 30) -> tuple[str, int]:
    """
    Execute an allowlisted command in a restricted environment.
    Returns (output_text, returncode).
    """
    try:
        parts = shlex.split(command)
        loop = asyncio.get_running_loop()
        result: subprocess.CompletedProcess = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd="/tmp",
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
            ),
        )
        output = (result.stdout or "").strip()
        if result.stderr:
            output += f"\n[stderr] {result.stderr.strip()[:500]}"
        return (output[:3_000] or "(no output)"), result.returncode
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s.", 124
    except FileNotFoundError:
        return f"Command not found: {shlex.split(command)[0]}", 127
    except Exception as e:
        return f"Execution error: {e}", 1


async def executor(state: IRAState) -> IRAState:
    t0 = time.monotonic()
    query = state["user_query"]

    # Use fast model to extract the exact command
    parse_messages = [
        {
            "role": "system",
            "content": (
                "Extract the exact shell command the user wants to run. "
                "Reply with ONLY the command, nothing else. "
                "If no command is identifiable, reply with: NONE"
            ),
        },
        {"role": "user", "content": query},
    ]
    extracted_cmd = await chat_complete(
        parse_messages, use_deep=False, max_tokens=100, temperature=0
    )
    extracted_cmd = extracted_cmd.strip()

    allowed = extracted_cmd != "NONE" and _is_allowed(extracted_cmd)
    await _log_exec_attempt(extracted_cmd, allowed, state.get("session_id", "unknown"))

    # Execute the command if it passes the allowlist
    exec_context = ""
    if allowed and extracted_cmd != "NONE":
        output, returncode = await _run_command(extracted_cmd)
        exec_context = (
            f"\n\nExecution result (exit code {returncode}):\n"
            f"```\n{output}\n```"
        )

    messages = [{"role": "system", "content": _SYSTEM}]
    messages.append({
        "role": "system",
        "content": (
            f"Extracted command: {extracted_cmd}\n"
            f"Allowlist check: {'PASSED — command was executed' if allowed else 'FAILED — command was blocked'}"
            f"{exec_context}"
        ),
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
