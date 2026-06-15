"""ira/skills/executor/ — Executor, ported as a Cortex skill (Option A).

SECURITY-CRITICAL: the allowlist, shell-metachar rejection, blocked-command list,
sandboxed subprocess, path checks, and security_events logging ALL stay in IRA
(agents/executor.py + utils.cmd_safety). This skill only does the explain/summarise
reasoning over the command + execution result that IRA passes in. It executes nothing.
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def executor_report(
    query: str,
    *,
    exec_context: Optional[str] = None,
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    """Reason over IRA's command-execution result. `exec_context` is built by IRA
    (extracted command + allowlist verdict + sandboxed output). This skill never runs
    anything itself."""
    blocks = [exec_context] if exec_context else None
    return run_skill("executor", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["executor_report"]
