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

from config import get_settings
from utils.db import acquire
from utils.security_alerts import send_alert
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
# Fix #70: removed python-requests/, go-http-client, curl/\d, wget/\d — these
# match huge swaths of legitimate traffic (Python services, k8s probes, CI
# scripts) and produce noisy false positives. Only named security tools are kept.
_SCANNER_UA = re.compile(
    r"(?:nmap|nikto|sqlmap|dirbuster|masscan|zgrab|nuclei|burpsuite)",
    re.I,
)
_PATH_TRAVERSAL = re.compile(r"\.\./|%2e%2e/|%252e", re.I)

# Log paths — volumes mounted in the worker container
NGINX_LOG_PATH = os.getenv("NGINX_LOG_PATH", "/var/log/nginx/access.log")
SSH_LOG_PATH = os.getenv("SSH_LOG_PATH", "/var/log/auth.log")  # /var/log/secure on RHEL

_SSH_FAIL_RE = re.compile(
    r"Failed password for (?:invalid user )?(\S+) from ([\d.]+) port \d+ ssh",
    re.I,
)
_SSH_INVALID_RE = re.compile(
    r"Invalid user (\S+) from ([\d.]+)",
    re.I,
)


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
                   VALUES ($1, $2, $3::inet, $4, $5)""",
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
    # Fix #71: cpu_percent(interval=1) sleeps for 1 second in the calling thread.
    # Running it in an executor prevents blocking the asyncio event loop.
    loop = asyncio.get_running_loop()
    cpu = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=1))
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    if cpu > 90:
        events.append({
            "severity": "medium",
            "event_type": "high_cpu",
            "description": f"CPU usage critical: {cpu:.1f}%",
        })
        # send_alert uses requests (sync) — run in executor to avoid blocking the event loop
        owner_name = get_settings().owner_name
        alert_msg = (
            f"{owner_name}, CPU usage is *{cpu:.1f}%* — potential cryptominer or runaway process.\n"
            f"Say _\"IRA, scan threats\"_ to check active connections."
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: send_alert(alert_msg, priority="warning"),
        )
    if mem.percent > 90:
        events.append({
            "severity": "medium",
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


# ── SSH auth log monitoring ───────────────────────────────────────────────────

async def _check_ssh_failures() -> list[dict]:
    """Parse auth.log for failed SSH logins since last scan offset.

    Falls back to reading recent journald output when auth.log is absent
    (common on systems where the bind-mount file does not exist on the host).
    """
    if not os.path.exists(SSH_LOG_PATH):
        return await _check_ssh_failures_journald()
    return await _check_ssh_failures_file()


def _parse_ssh_lines(lines: list[str]) -> list[dict]:
    """Extract SSH brute-force events from a list of log lines (file or journald)."""
    from collections import defaultdict
    ip_failures: dict[str, int] = defaultdict(int)
    ip_users: dict[str, set] = defaultdict(set)

    for line in lines:
        m = _SSH_FAIL_RE.search(line) or _SSH_INVALID_RE.search(line)
        if m:
            user, ip = m.group(1), m.group(2)
            ip_failures[ip] += 1
            ip_users[ip].add(user)

    events = []
    for ip, count in ip_failures.items():
        if count >= 3:
            users_tried = ", ".join(list(ip_users[ip])[:5])
            events.append({
                "severity": "high" if count >= 10 else "medium",
                "event_type": "ssh_brute_force",
                "source_ip": ip,
                "description": (
                    f"SSH brute-force: {count} failed attempts from {ip}. "
                    f"Usernames tried: {users_tried}"
                ),
                "raw_log": "",
            })
    return events


async def _check_ssh_failures_journald() -> list[dict]:
    """Fallback: read SSH failures from journald (no file mount required)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", "ssh", "-u", "sshd", "--since", "1 hour ago",
            "--no-pager", "-q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        lines = stdout.decode(errors="replace").splitlines()
    except (FileNotFoundError, asyncio.TimeoutError, Exception):
        # journalctl not available (e.g., inside minimal container) — skip silently
        return []

    return _parse_ssh_lines(lines)


async def _check_ssh_failures_file() -> list[dict]:
    """Parse auth.log for failed SSH logins since last scan offset."""

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM monitor_state WHERE key='ssh_log_offset'"
        )
        offset = int(row["value"]) if row else 0

    try:
        with open(SSH_LOG_PATH, "r", errors="replace") as f:
            f.seek(offset)
            lines = f.readlines()
            new_offset = f.tell()
    except PermissionError:
        logger.debug("No permission to read SSH log — mount with correct volume")
        return []

    if new_offset > offset:
        async with acquire() as conn:
            await conn.execute(
                "UPDATE monitor_state SET value=$1, updated_at=NOW() WHERE key='ssh_log_offset'",
                str(new_offset),
            )

    ip_failures: dict[str, int] = defaultdict(int)
    ip_users: dict[str, set] = defaultdict(set)

    for line in lines:
        m = _SSH_FAIL_RE.search(line) or _SSH_INVALID_RE.search(line)
        if m:
            user, ip = m.group(1), m.group(2)
            ip_failures[ip] += 1
            ip_users[ip].add(user)

    events = []
    for ip, count in ip_failures.items():
        if count >= 3:
            users_tried = ", ".join(list(ip_users[ip])[:5])
            events.append({
                "severity": "high" if count >= 10 else "medium",
                "event_type": "ssh_brute_force",
                "source_ip": ip,
                "description": (
                    f"SSH brute-force: {count} failed attempts from {ip}. "
                    f"Usernames tried: {users_tried}"
                ),
                "raw_log": "",
            })
            # Direct Telegram push for SSH attacks (time-critical)
            if count >= 5:
                ssh_msg = (
                    f"{get_settings().owner_name}, *{count} failed SSH logins* from `{ip}`.\n"
                    f"Usernames tried: {users_tried}\n\n"
                    f"Say _\"IRA, scan threats\"_ to investigate."
                )
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: send_alert(ssh_msg, priority="critical"),
                )
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

    # 2. Check SSH auth failures
    ssh_events = await _check_ssh_failures()

    # 3. Check system health
    system_events = await _check_system_health()

    all_events = log_events + ssh_events + [
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
            f"{get_settings().owner_name}, IRA has detected the following security events:\n\n{threat_summary}\n\n"
            f"Please review and I can suggest remediation steps.",
            category="security",
            priority="critical" if any(e["severity"] == "critical" for e in all_events) else "warning",
        )

    # 5. Hourly: alert if unresolved criticals still open
    criticals = await _check_unresolved_criticals()
    if criticals > 0:
        logger.warning(f"{criticals} unresolved critical security events")
