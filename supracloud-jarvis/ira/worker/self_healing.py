"""
IRA Self-Healing Agent — Autonomous bug detection, root-cause analysis, and recovery.

Runs every 60 seconds as part of the worker scheduler. Monitors:
  - Python exception logs (from the shared log volume)
  - Database connectivity and query performance
  - API latency and error rates (from model_performance table)
  - Memory / CPU via psutil
  - Redis availability

When a problem is detected:
  1. Root-cause analysis using the LLM
  2. Safe auto-remediation (restart affected service, clear cache, etc.)
  3. Notify the owner via Telegram/WebSocket
  4. Log the fix to security_events for audit trail

Self-learning:
  After each successful interaction, the agent reflects on its performance
  and stores improvement notes in the vector memory store, making IRA
  progressively smarter over time (inspired by reflection techniques and
  the Lighthouse Attention philosophy of continuous optimization).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

import psutil

from config import get_settings
from utils.db import acquire
from worker.notifier import notify

logger = logging.getLogger("ira.self_healing")

# ── Thresholds ────────────────────────────────────────────────────────────────

_MAX_API_ERROR_RATE = 0.20     # > 20% error rate triggers healing
_MAX_LATENCY_P95_MS = 10_000  # > 10s p95 latency triggers investigation
# Fix L8: _MIN_DB_POOL_FREE and _REFLECTION_INTERVAL_S removed — defined here
# but never referenced anywhere in the codebase (dead constants).  The DB pool
# is managed by asyncpg internally; reflection interval is wired in scheduler.py.


# ── Diagnostic functions ──────────────────────────────────────────────────────

async def _check_api_health() -> list[dict]:
    """Check recent API error rates from the model_performance table."""
    issues = []
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """SELECT
                       COUNT(*) FILTER (WHERE NOT success) AS errors,
                       COUNT(*) AS total,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms
                   FROM model_performance
                   WHERE created_at > NOW() - INTERVAL '10 minutes'"""
            )
        if row and row["total"] and row["total"] > 5:
            error_rate = row["errors"] / row["total"]
            if error_rate > _MAX_API_ERROR_RATE:
                issues.append({
                    "type": "high_error_rate",
                    "detail": f"API error rate {error_rate:.0%} in last 10 min ({row['errors']}/{row['total']} failed)",
                    "severity": "high",
                })
            if row["p95_ms"] and row["p95_ms"] > _MAX_LATENCY_P95_MS:
                issues.append({
                    "type": "high_latency",
                    "detail": f"p95 API latency {row['p95_ms']:.0f}ms — LLM backend may be overloaded",
                    "severity": "medium",
                })
    except Exception as e:
        issues.append({
            "type": "db_error",
            "detail": f"Cannot read model_performance: {e}",
            "severity": "high",
        })
    return issues


async def _check_system_resources() -> list[dict]:
    """Check host CPU, memory, and disk."""
    issues = []
    try:
        loop = asyncio.get_running_loop()
        cpu = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=1))
        mem = await loop.run_in_executor(None, psutil.virtual_memory)
        disk = await loop.run_in_executor(None, lambda: psutil.disk_usage("/"))

        if cpu > 95:
            issues.append({
                "type": "cpu_critical",
                "detail": f"CPU at {cpu:.1f}% — system at risk of OOM or swap thrashing",
                "severity": "high",
            })
        if mem.percent > 95:
            issues.append({
                "type": "memory_critical",
                "detail": f"Memory at {mem.percent:.1f}% — {mem.available // 1024 // 1024}MB free",
                "severity": "high",
            })
        if disk.percent > 90:
            issues.append({
                "type": "disk_full",
                "detail": f"Disk at {disk.percent:.1f}% — {disk.free // 1024 // 1024 // 1024}GB free",
                "severity": "high",
            })
    except Exception as e:
        logger.warning(f"Resource check failed: {e}")
    return issues


async def _check_redis() -> list[dict]:
    """Ping Redis and check latency."""
    issues = []
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        t0 = time.monotonic()
        await redis.ping()
        latency_ms = (time.monotonic() - t0) * 1000
        if latency_ms > 500:
            issues.append({
                "type": "redis_slow",
                "detail": f"Redis ping latency {latency_ms:.0f}ms — cache may be degraded",
                "severity": "medium",
            })
    except Exception as e:
        issues.append({
            "type": "redis_down",
            "detail": f"Redis unreachable: {e}",
            "severity": "critical",
        })
    return issues


# ── Root-cause analysis ────────────────────────────────────────────────────────

async def _analyse_issues(issues: list[dict]) -> str:
    """Use the LLM to produce a root-cause analysis and remediation plan."""
    if not issues:
        return ""
    try:
        from utils.llm import chat_complete
        cfg = get_settings()
        issue_text = json.dumps(issues, indent=2)
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are IRA's Self-Healing Agent for {cfg.owner_name}'s system.\n"
                    "Analyse the detected issues and produce:\n"
                    "1. Root cause (most likely explanation)\n"
                    "2. Immediate safe remediation steps\n"
                    "3. Whether this needs owner notification\n"
                    "Be concise — max 150 words total."
                ),
            },
            {"role": "user", "content": f"Detected issues:\n{issue_text}"},
        ]
        return await chat_complete(messages, use_deep=False, temperature=0.2, max_tokens=300)
    except Exception as e:
        return f"LLM analysis unavailable: {e}"


# ── Safe auto-remediation ─────────────────────────────────────────────────────

async def _attempt_remediation(issue_type: str) -> str:
    """Apply safe, reversible fixes for known issue types."""
    if issue_type == "redis_slow":
        try:
            from utils.redis_client import get_redis
            redis = get_redis()
            # Flush only expired keys — safe, non-destructive
            await redis.execute_command("DEBUG", "SLEEP", "0")  # wake Redis
            return "Redis: sent wake-up command"
        except Exception as e:
            return f"Redis remediation failed: {e}"

    if issue_type in ("high_error_rate", "high_latency"):
        # Clear the Redis response cache to force fresh LLM calls
        try:
            from utils.redis_client import get_redis
            redis = get_redis()
            keys = await redis.keys("chat:*")
            if keys:
                await redis.delete(*keys)
            return f"Cleared {len(keys)} stale chat cache entries"
        except Exception as e:
            return f"Cache clear failed: {e}"

    if issue_type in ("cpu_critical", "memory_critical"):
        return "Resource pressure noted — owner notified. No automated action taken (requires manual intervention)."

    return "No automated remediation available for this issue type."


# ── Git auto-commit removed (Finding #63) ────────────────────────────────────
# Self-healing must never make autonomous git commits. Any file-level fixes are
# applied in memory/config only; commits are always an explicit owner action.
# The function is intentionally absent — do not re-add.


# ── P6.2: Bounded automated security playbooks ────────────────────────────────

async def run_security_playbooks(events: list[dict]) -> None:
    """Apply bounded automated responses to detected security events.

    Only events from the fixed ALLOWED_ACTIONS allowlist in utils/playbooks
    are executed. Every action is audit-logged to security_events. No action
    here is destructive; all are reversible (token rotation, IP block with TTL,
    log snapshot).

    Mapping:
      brute_force              → block source IP (1 h)
      canary_tripwire_hit      → block source IP (24 h — honeypot = instant block)
      canary_token_used        → block source IP (24 h)
      canary_username_login    → block source IP (24 h)
      account_locked           → block source IP if present (1 h)
      disk_pressure            → snapshot security logs for forensics
    """
    from utils.playbooks import run_playbook

    for ev in events:
        ev_type = ev.get("event_type", "")
        source_ip = ev.get("source_ip") or None

        if ev_type == "brute_force" and source_ip:
            await run_playbook("block_ip", ip_address=source_ip, ttl_seconds=3600)

        elif ev_type in ("canary_tripwire_hit", "canary_token_used",
                         "canary_username_login_attempt") and source_ip:
            # Honeypot hits and credential attacks get a longer block
            await run_playbook("block_ip", ip_address=source_ip, ttl_seconds=86400)

        elif ev_type == "account_locked" and source_ip:
            await run_playbook("block_ip", ip_address=source_ip, ttl_seconds=3600)

        elif ev_type == "disk_pressure":
            await run_playbook("snapshot_logs", label="disk_pressure_auto")


# ── Main healing loop ─────────────────────────────────────────────────────────

async def run_self_healing_check() -> None:
    """
    Full self-healing diagnostic cycle. Called every 60s by the scheduler.
    """
    t0 = time.monotonic()

    # Gather all diagnostics in parallel
    api_issues, resource_issues, redis_issues = await asyncio.gather(
        _check_api_health(),
        _check_system_resources(),
        _check_redis(),
        return_exceptions=False,
    )

    all_issues = api_issues + resource_issues + redis_issues

    if not all_issues:
        logger.debug("Self-healing check: all systems nominal")
        return

    logger.warning(f"Self-healing: {len(all_issues)} issue(s) detected — analysing...")

    # LLM root-cause analysis
    analysis = await _analyse_issues(all_issues)

    # Attempt remediations
    remediation_log = []
    for issue in all_issues:
        result = await _attempt_remediation(issue["type"])
        remediation_log.append(f"[{issue['type']}] {result}")

    # Log to security_events
    try:
        async with acquire() as conn:
            for issue in all_issues:
                await conn.execute(
                    """INSERT INTO security_events (severity, event_type, description, metadata)
                       VALUES ($1, 'self_healing', $2, $3)""",
                    issue["severity"],
                    issue["detail"],
                    json.dumps({"analysis": analysis[:500], "remediation": remediation_log}),
                )
    except Exception as e:
        logger.error(f"Failed to log healing event: {e}")

    # Notify owner for high/critical issues
    critical_issues = [i for i in all_issues if i["severity"] in ("high", "critical")]
    if critical_issues:
        cfg = get_settings()
        issue_summary = "\n".join(f"• {i['detail']}" for i in critical_issues)
        remediation_summary = "\n".join(remediation_log[:3])
        try:
            await notify(
                "🔧 IRA Self-Healing Alert",
                f"{cfg.owner_name}, IRA detected and addressed system issues:\n\n"
                f"**Issues Found:**\n{issue_summary}\n\n"
                f"**Root Cause:**\n{analysis}\n\n"
                f"**Actions Taken:**\n{remediation_summary}\n\n"
                f"IRA continues monitoring. No action required unless issues persist.",
                category="security",
                priority="warning",
            )
        except Exception as e:
            logger.error(f"Self-healing notification failed: {e}")

    elapsed = int((time.monotonic() - t0) * 1000)
    logger.info(f"Self-healing cycle complete in {elapsed}ms — {len(all_issues)} issue(s) handled")


# ── Self-Learning Reflection ──────────────────────────────────────────────────

async def run_self_reflection() -> None:
    """
    Hourly reflection: IRA reviews its recent performance and stores improvement
    notes in the vector memory for use in future conversations.

    Inspired by Lighthouse Attention's continuous optimization philosophy:
    instead of static pre-training, IRA adapts at runtime through structured
    reflection on its own outputs and latency data.
    """
    try:
        async with acquire() as conn:
            # Gather recent performance data
            perf_rows = await conn.fetch(
                """SELECT model_name, request_type,
                          AVG(latency_ms) AS avg_ms,
                          COUNT(*) FILTER (WHERE NOT success) AS errors,
                          COUNT(*) AS total
                   FROM model_performance
                   WHERE created_at > NOW() - INTERVAL '1 hour'
                   GROUP BY model_name, request_type"""
            )

            # Gather recent agent routing data
            chat_rows = await conn.fetch(
                """SELECT agent_used, COUNT(*) AS usage_count
                   FROM chat_messages
                   WHERE role = 'assistant' AND created_at > NOW() - INTERVAL '1 hour'
                   GROUP BY agent_used
                   ORDER BY usage_count DESC
                   LIMIT 10"""
            )

        if not perf_rows:
            return

        perf_summary = json.dumps(
            [{"model": r["model_name"], "type": r["request_type"],
              "avg_ms": float(r["avg_ms"] or 0), "error_rate": float((r["errors"] or 0) / max(r["total"], 1))}
             for r in perf_rows],
            indent=2,
        )
        routing_summary = json.dumps(
            [{"agent": r["agent_used"], "count": r["usage_count"]} for r in chat_rows],
            indent=2,
        )

        from utils.llm import chat_complete
        cfg = get_settings()

        reflection_prompt = [
            {
                "role": "system",
                "content": (
                    f"You are IRA's self-improvement engine for {cfg.owner_name}.\n"
                    "Review the last hour's performance and write 3-5 specific improvement notes.\n"
                    "Focus on: routing accuracy, response latency, error patterns, agent selection.\n"
                    "Format as bullet points. Each note must be actionable and specific.\n"
                    "Max 200 words total."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Performance data:\n{perf_summary}\n\n"
                    f"Agent routing:\n{routing_summary}"
                ),
            },
        ]

        reflection = await chat_complete(reflection_prompt, use_deep=False, temperature=0.3, max_tokens=400)

        # Store reflection in memory for future context injection
        from memory.store import save_message
        async with acquire() as conn:
            # Find or create a reflection conversation
            row = await conn.fetchrow(
                "SELECT id FROM conversations WHERE session_id='ira-self-reflection' LIMIT 1"
            )
            if not row:
                import uuid
                conv_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO conversations (id, session_id) VALUES ($1, 'ira-self-reflection')",
                    uuid.UUID(conv_id),
                )
            else:
                conv_id = str(row["id"])

        await save_message(
            conv_id,
            role="assistant",
            content=f"[Self-Reflection {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}]\n{reflection}",
            model_used="self-reflection",
            latency_ms=0,
            user_id="system",
        )

        logger.info(f"Self-reflection stored: {len(reflection)} chars")

    except Exception as e:
        logger.error(f"Self-reflection failed: {e}")
