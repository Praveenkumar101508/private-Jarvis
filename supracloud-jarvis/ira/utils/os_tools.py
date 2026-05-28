"""
IRA Digital Hands — OS control tools (Phase 6).

open_application(app_name) → launch a desktop application by name
run_terminal_command(cmd)  → execute safe, read-only shell commands
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

logger = logging.getLogger("ira.os_tools")

_WIN = sys.platform == "win32"

_APP_MAP: dict[str, list[str]] = {
    "vscode":               ["code", "."],
    "vs code":              ["code", "."],
    "visual studio code":   ["code", "."],
    "terminal":             ["cmd.exe"] if _WIN else ["bash"],
    "powershell":           ["powershell.exe"] if _WIN else ["pwsh"],
    "chrome":               ["start", "chrome"] if _WIN else ["google-chrome"],
    "firefox":              ["start", "firefox"] if _WIN else ["firefox"],
    "browser":              ["start", "https://google.com"] if _WIN else ["xdg-open", "https://google.com"],
    "notepad":              ["notepad.exe"] if _WIN else ["gedit"],
    "file explorer":        ["explorer.exe"] if _WIN else ["nautilus"],
    "calculator":           ["calc.exe"] if _WIN else ["gnome-calculator"],
}

# Allowlist: only these prefixes are permitted for run_terminal_command
_ALLOWED_PREFIXES = (
    "ls", "dir", "pwd", "echo", "cat ", "type ",
    "ping ", "tracert ", "traceroute ",
    "git status", "git log", "git diff", "git branch",
    "docker ps", "docker stats", "docker logs",
    "python --version", "python3 --version",
    "node --version", "npm --version", "pip list", "pip show",
    "whoami", "hostname", "ipconfig", "ifconfig",
    "netstat",
    "df ", "free ", "top -b",
)


_ALLOWED_APPS: dict[str, str] = {
    "browser":   "chrome.exe" if _WIN else "google-chrome",
    "chrome":    "chrome.exe" if _WIN else "google-chrome",
    "terminal":  "cmd.exe"    if _WIN else "bash",
    "notepad":   "notepad.exe" if _WIN else "gedit",
    "explorer":  "explorer.exe" if _WIN else "nautilus",
    "calculator": "calc.exe"  if _WIN else "gnome-calculator",
    "vscode":    "code",
}


async def open_application(app_name: str) -> dict:
    """Launch a desktop application by friendly name (allowlist only)."""
    key = app_name.lower().strip()

    if key not in _APP_MAP and key not in _ALLOWED_APPS:
        raise ValueError(f"App '{app_name}' is not in the permitted application list.")

    cmd = _APP_MAP.get(key) or [_ALLOWED_APPS[key]]

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Launched: {app_name}")
        return {"status": "launched", "application": app_name, "command": " ".join(cmd)}
    except FileNotFoundError:
        return {"error": f"'{app_name}' not found on this system."}
    except Exception as e:
        logger.error(f"open_application('{app_name}') failed: {e}")
        return {"error": str(e)}


async def run_terminal_command(command: str) -> dict:
    """Execute a safe read-only terminal command and return its stdout."""
    cmd_stripped = command.strip()
    cmd_lower = cmd_stripped.lower()

    # Gate 1: prefix allowlist
    if not any(cmd_lower.startswith(p.lower()) for p in _ALLOWED_PREFIXES):
        return {
            "error": "Command not in allowlist. Only read-only commands are permitted.",
            "allowed_examples": ["git status", "docker ps", "ls", "ping 8.8.8.8"],
            "blocked": command,
        }

    # Gate 2 (Fix P6): reject path traversal, glob chars, and paths outside allow-roots
    try:
        import shlex as _shlex
        from utils.cmd_safety import check_command_args as _check
        _ok, _reason = _check(_shlex.split(cmd_stripped))
        if not _ok:
            logger.warning(f"run_terminal_command blocked by path check: {_reason!r} for cmd={cmd_stripped!r}")
            return {"error": f"Command rejected: {_reason}", "blocked": command}
    except Exception as _ce:
        logger.error(f"cmd_safety check error: {_ce}")
        return {"error": "Command safety check failed.", "blocked": command}

    try:
        import shlex
        args = shlex.split(cmd_stripped)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        result: dict = {
            "command": cmd_stripped,
            "exit_code": proc.returncode,
            "output": stdout.decode("utf-8", errors="replace").strip()[:3000],
        }
        err_text = stderr.decode("utf-8", errors="replace").strip()
        if err_text:
            result["stderr"] = err_text[:500]

        logger.info(f"Command: {cmd_stripped[:60]} → exit {proc.returncode}")
        return result

    except asyncio.TimeoutError:
        return {"error": "Command timed out (15 s)", "command": cmd_stripped}
    except Exception as e:
        logger.error(f"run_terminal_command failed: {e}")
        return {"error": str(e)}
