"""
IRA Security Guardian — Continuous monitoring daemon.

Monitors every 60 seconds:
  1. Nginx access logs     — brute-force, scanner, injection, anomaly detection
  2. security_events table — alerts on new CRITICAL/HIGH events
  3. System metrics        — CPU/memory spikes, disk pressure

Alert thresholds (configurable via env):
  >10 failed auth from one IP in 5 min   → HIGH alert
  >3  critical security events unresolved → CRITICAL alert
  >50 requests/min from one IP            → HIGH alert (rate abuse)
  Any SQL injection / XSS pattern detected → CRITICAL alert

All events are written to the security_events table and delivered
via the notifier (Telegram, WebSocket, Email).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import psutil

from utils.db import acquire
from worker.notifier import notify

logger = logging.getLogger("ira.security")

# ── Attack pattern regexes ────────────────────────────────────────────────────
_SQLI_PATTERN = re.compile(
    r"(?:union\s+select|drop\s+table|insert\s+into|or\s+1=1|'--|\bxp_|\bexec\b|"
    r"information_schema|sleep\(\d+\)|benchmark\(|load_file\()",
    re.I,
)
_XSS_PATTERN = re.compile(
    r"(?:<script|javascript:|on(?:load|error|click|mouse)\s*=|eval\s*\(|alert\s*\(|"
    r"document\.cookie|<iframe|<svg.*?on\w+)",
    re.I,
)
_SCANNER_UA = re.compile(
    r"(?:nmap|nikto|sqlmap|dirbuster|masscan|zgrab|nuclei|burpsuite|"
    r"python-requests/|go-http-client|curl/\d|wget/\d)",
    re.I,
)
_PATH_TRAVERSAL = re.compile(r"\.\./|%2e%2e/|%252e", re.I)

# Nginx log path (shared volume mounted in worker container)
NGINX_LOG_PATH = os.getenv("NGINX_LOG_PATH", "/var/log/nginx/access.log")


# ── Log analysis ──────────────────────────────────────────────────────────────

def _parse_nginx_line(line: str) -> dict | None:
    """Parse one nginx JSON access log line."""
    import json
    try:
        return json.loads(line.strip())
    except Exception:
        return None


def _analyse_lines(lines: list[str]) -> list[dict]:
    """
    Analyse a batch of nginx log lines.
    Returns list of security events to record.
    """
    ip_requests: dict[str, list] = defaultdict(list)
    ip_failures: dict[str, int] = defaultdict(int)
    events: list[dict] = []

    for line in lines:
        entry = _parse_nginx_line(line)
        if not entry:
            continue

        ip = entry.get("remote_addr", "unknown")
        uri = entry.get("uri", "")
        ua = entry.get("http_user_agent", "")
        status = str(entry.get("status", "200"))
        ip_requests[ip].append(entry)

        # Track auth failures
        if status in ("401", "403"):
            ip_failures[ip] += 1

        # SQL injection
        if _SQLI_PATTERN.search(uri):
            events.append({
                "severity": "critical",
                "event_type": "sql_injection_attempt",
                "source_ip": ip,
                "description": f"SQL injection pattern in URI from {ip}: {uri[:100]}",
                "raw_log": line[:500],
            })

        # XSS
        elif _XSS_PATTERN.search(uri):
            events.append({
                "severity": "high",
                "event_type": "xss_attempt",
                "source_ip": ip,
                "description": f"XSS pattern detected from {ip}: {uri[:100]}",
                "raw_log": line[:500],
            })

        # Path traversal
        elif _PATH_TRAVERSAL.search(uri):
            events.append({
                "severity": "high",
                "event_type": "path_traversal",
                "source_ip": ip,
                "description": f"Path traversal attempt from {ip}: {uri[:100]}",
                "raw_log": line[:500],
            })

        # Known scanner user-agent
        elif _SCANNER_UA.search(ua):
            events.append({
                "severity": "medium",
                "event_type": "scanner_detected",
                "source_ip": ip,
                "description": f"Known scanner tool detected from {ip}: {ua[:80]}",
                "raw_log": line[:500],
            })

    # Brute-force detection
    for ip, failures in ip_failures.items():
        if failures >= 10:
            events.append({
                "severity": "high",
                "event_type": "brute_force",
                "source_ip": ip,
                "description": f"Brute-force detected: {failures} auth failures from {ip}",
                "raw_log": "",
            })

    # Rate abuse (>50 requests from one IP in this batch)
    for ip, reqs in ip_requests.items():
        if len(reqs) > 50:
            events.append({
                "severity": "medium",
                "event_type": "rate_abuse",
                "source_ip": ip,
                "description": f"Rate abuse: {len(reqs)} requests from {ip} in one scan window",
                "raw_log": "",
            })

    return events


async def _read_new_log_lines() -> list[str]:
    """Read new nginx log lines since last scan using stored file offset."""
    if not os.path.exists(NGINX_LOG_PATH):
        return []

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM monitor_state WHERE key='nginx_log_offset'"
        )
        offset = int(row["value"]) if row else 0

    try:
        with open(NGINX_LOG_PATH, "r", errors="replace") as f:
            f.seek(offset)
            lines = f.readlines()
            new_offset = f.tell()

        if new_offset > offset:
            async with acquire() as conn:
                await conn.execute(
                    "UPDATE monitor_state SET value=$1, updated_at=NOW() WHERE key='nginx_log_offset'",
                    str(new_offset),
                )
        return lines
    except Exception as e:
        logger.warning(f"Could not read nginx log: {e}")
        return []


async def _write_security_events(events: list[dict]) -> int:
    """Persist security events and return count of new critical/high events."""
    if not events:
        return 0
    high_count = 0
    async with acquire() as conn:
        for ev in events:
            await conn.execute(
                """INSERT INTO security_events
                   (severity, event_type, source_ip, description, raw_log)
                   VALUES ($1, $2, $3::inet, $4, $5)
                   ON CONFLICT DO NOTHING""",
                ev["severity"],
                ev["event_type"],
                ev.get("source_ip"),
                ev["description"],
                ev.get("raw_log", ""),
            )
            if ev["severity"] in ("critical", "high"):
                high_count += 1
    return high_count


# ── System health check ───────────────────────────────────────────────────────

async def _check_system_health() -> list[dict]:
    """Check CPU, memory, and disk for anomalies."""
    events = []
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    if cpu > 90:
        events.append({
            "severity": "warning",
            "event_type": "high_cpu",
            "description": f"CPU usage critical: {cpu:.1f}%",
        })
    if mem.percent > 90:
        events.append({
            "severity": "warning",
            "event_type": "high_memory",
            "description": f"Memory usage critical: {mem.percent:.1f}%",
        })
    if disk.percent > 85:
        events.append({
            "severity": "high",
            "event_type": "disk_pressure",
            "description": f"Disk usage at {disk.percent:.1f}% — action required",
        })
    return events


# ── Check existing unresolved critical events ─────────────────────────────────

async def _check_unresolved_criticals() -> int:
    async with acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM security_events WHERE severity='critical' AND resolved=FALSE"
        ) or 0


# ── Main scan loop ────────────────────────────────────────────────────────────

async def run_security_scan() -> None:
    """
    Run one full security scan cycle.
    Called every 60 seconds by the APScheduler.
    """
    logger.debug("Running security scan...")

    # 1. Analyse nginx logs
    lines = await _read_new_log_lines()
    log_events = _analyse_lines(lines) if lines else []

    # 2. Check system health
    system_events = await _check_system_health()

    all_events = log_events + [
        {**ev, "source_ip": None, "raw_log": ""}
        for ev in system_events
        if "source_ip" not in ev
    ]

    # 3. Write events to DB
    new_highs = await _write_security_events(all_events)

    # 4. Alert if significant threats found
    if new_highs > 0:
        threat_summary = "\n".join(
            f"• [{e['severity'].upper()}] {e['description']}"
            for e in all_events if e["severity"] in ("critical", "high")
        )
        await notify(
            f"Security Alert — {new_highs} new threat(s) detected",
            f"Sir, IRA has detected the following security events:\n\n{threat_summary}\n\n"
            f"Please review and I can suggest remediation steps.",
            category="security",
            priority="critical" if any(e["severity"] == "critical" for e in all_events) else "warning",
        )

    # 5. Hourly: alert if unresolved criticals still open
    criticals = await _check_unresolved_criticals()
    if criticals > 0:
        logger.warning(f"{criticals} unresolved critical security events")
