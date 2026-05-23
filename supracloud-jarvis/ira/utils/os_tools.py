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
    "netstat", "curl ", "wget ",
    "df ", "free ", "top -b",
)


async def open_application(app_name: str) -> dict:
    """Launch a desktop application by friendly name."""
    key = app_name.lower().strip()
    cmd = _APP_MAP.get(key, [app_name])

    try:
        if _WIN:
            # shell=True on Windows requires a string, not a list
            cmd_str = " ".join(cmd)
            subprocess.Popen(cmd_str, shell=True, creationflags=subprocess.DETACHED_PROCESS)
        else:
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

    if not any(cmd_lower.startswith(p.lower()) for p in _ALLOWED_PREFIXES):
        return {
            "error": "Command not in allowlist. Only read-only commands are permitted.",
            "allowed_examples": ["git status", "docker ps", "ls", "ping 8.8.8.8"],
            "blocked": command,
        }

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
