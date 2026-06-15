"""
Digital Robot Brain Agent — OS control and browser automation (Phase 6).

IRA's "digital hands and eyes":
  open_application()            → launch desktop apps by name
  run_terminal_command()        → safe read-only shell commands
  browse_and_summarize_website() → headless browser + LLM page summary
"""
from __future__ import annotations

import json
import re
import time

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete

_SYSTEM = """\
You are IRA, the central digital intelligence for Supracloud — a fully autonomous digital brain.
You have just executed digital tools (results provided in context below). Present the outcomes clearly.

Capabilities:
- Open any desktop application on command
- Run safe read-only terminal commands and report the output
- Browse any URL, extract content, and answer specific questions about it

When tools ran: summarise what happened, quote key outputs, and suggest any follow-up actions.
When no tools ran: explain what you can do and ask the user for specifics.
"""

_OPEN_RE = re.compile(
    r"\b(open|launch|start)\b.{0,25}\b(vs\s*code|vscode|terminal|browser|chrome|firefox|powershell|notepad|explorer|calculator)\b",
    re.I,
)
_CMD_RE = re.compile(
    r"\b(run|execute|check|show me)\b.{0,25}\b(command|terminal|shell|git|docker|directory|files|ping|version)\b",
    re.I,
)
_URL_RE = re.compile(r"https?://\S+", re.I)


async def digital_agent(state: IRAState) -> IRAState:
    t0 = time.monotonic()
    query = state["user_query"]
    tool_results: list[dict] = []

    try:
        from utils.os_tools import open_application, run_terminal_command
        from utils.browser_tools import browse_and_summarize_website

        # Open an application
        if _OPEN_RE.search(query):
            app_match = re.search(
                r"\b(vs\s*code|vscode|visual studio code|terminal|browser|chrome|firefox|"
                r"powershell|notepad|file explorer|calculator)\b",
                query, re.I,
            )
            app = app_match.group(0).strip() if app_match else "terminal"
            result = await open_application(app)
            tool_results.append({"tool": "open_application", "app": app, "result": result})

        # Run a terminal command
        if _CMD_RE.search(query) and not _OPEN_RE.search(query):
            cmd_match = re.search(
                r"(?:run|execute|check|show me)[:\s]+[\"']?(.+?)[\"']?(?:\.|$)",
                query, re.I,
            )
            cmd = cmd_match.group(1).strip() if cmd_match else "git status"
            result = await run_terminal_command(cmd)
            tool_results.append({"tool": "run_terminal_command", "command": cmd, "result": result})

        # Browse URLs
        for url in _URL_RE.findall(query)[:2]:
            user_query_clean = _URL_RE.sub("", query).strip() or "summarize this page"
            result = await browse_and_summarize_website(url, user_query_clean)
            tool_results.append({"tool": "browse_and_summarize", "url": url, "result": result})

    except Exception as e:
        tool_results.append({"tool": "error", "message": str(e)})

    messages = [{"role": "system", "content": _SYSTEM}]

    if tool_results:
        messages.append({
            "role": "system",
            "content": f"Tool execution results:\n{json.dumps(tool_results, indent=2)[:4000]}",
        })

    if state.get("memory_context"):
        messages.append({"role": "system", "content": f"Memory:\n{state['memory_context']}"})

    messages.append({"role": "user", "content": query})

    response = await chat_complete(messages, use_deep=False, temperature=0.3)
    latency = int((time.monotonic() - t0) * 1000)

    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen3-fast",  # Fix L12: was "llama-fast" — matches config.vllm_fast_model
    }
