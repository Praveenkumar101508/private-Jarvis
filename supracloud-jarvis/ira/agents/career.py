"""
Career Agent — resume tailoring, GitHub portfolio analysis, job scraping (Phase 4).

Handles: job applications, resume generation, GitHub analysis, career strategy.
Calls career_tools before the LLM so results are injected as rich context.
"""
from __future__ import annotations

import json
import re
import time

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete
from config import get_settings


def _build_system(owner_name: str) -> str:
    return (
        f"You are IRA's Career Automation module — an elite career strategist for {owner_name}/Supracloud.\n\n"
        "Capabilities you just executed (results in context):\n"
        "- GitHub codebase analysis: tech stack, recent projects, commit history\n"
        "- Job posting scraper: extracted title, company, requirements, description\n"
        "- Resume tailoring engine: rewrote bullet points to match the job\n\n"
        "Present the tool results clearly and actionably:\n"
        "- Quote actual languages/projects from the GitHub analysis\n"
        "- Mirror keywords directly from the job description\n"
        "- Highlight the strongest skill matches\n"
        "- If a tailored resume was saved, confirm the file path and preview the first section\n"
        "- Give 3 specific interview talking points based on the match\n\n"
        f"Be precise and encouraging. This is {owner_name}'s career pipeline."
    )

# Fix P15: module-level constant is the single source of truth; chat.py imports it
# as CAREER_SYSTEM. The in-function rebuild below was removed — it was identical.
_SYSTEM = _build_system(get_settings().owner_name)

_GITHUB_RE = re.compile(
    r"\b(github|codebase|repositories|repos|portfolio|my code|my projects|my skills|tech stack)\b",
    re.I,
)
_RESUME_RE = re.compile(
    r"\b(resume|cv|tailor|customize|rewrite|cover letter|bullet point|apply)\b",
    re.I,
)
_URL_RE = re.compile(r"https?://\S+", re.I)


async def career_agent(state: IRAState) -> IRAState:
    t0 = time.monotonic()
    query = state["user_query"]
    tool_results: list[dict] = []

    try:
        from utils.career_tools import analyze_my_codebase, scrape_job_posting, generate_tailored_resume

        # 1. GitHub analysis if requested
        if _GITHUB_RE.search(query):
            result = await analyze_my_codebase()
            tool_results.append({"tool": "analyze_my_codebase", "result": result})

        # 2. Scrape any URLs in the message
        urls = _URL_RE.findall(query)
        for url in urls[:2]:
            result = await scrape_job_posting(url)
            tool_results.append({"tool": "scrape_job_posting", "url": url, "result": result})

        # 3. Tailor resume if requested and we have a job description
        if _RESUME_RE.search(query):
            jd_text = ""
            for tr in tool_results:
                if tr.get("tool") == "scrape_job_posting":
                    jd_text = tr["result"].get("description", "")
                    break
            if not jd_text:
                # No URL scraped — use inline text from the query
                jd_text = query
            result = await generate_tailored_resume(jd_text)
            tool_results.append({"tool": "generate_tailored_resume", "result": result})

    except Exception as e:
        tool_results.append({"tool": "error", "message": str(e)})

    messages = [{"role": "system", "content": _SYSTEM}]  # Fix P15: use module constant, not redundant rebuild

    if tool_results:
        messages.append({
            "role": "system",
            "content": f"Tool execution results:\n{json.dumps(tool_results, indent=2)[:4000]}",
        })

    if state.get("memory_context"):
        messages.append({"role": "system", "content": f"Relevant memory:\n{state['memory_context']}"})

    messages.append({"role": "user", "content": query})

    response = await chat_complete(messages, use_deep=True, temperature=0.3)
    latency = int((time.monotonic() - t0) * 1000)

    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen3-deep",  # Fix L11: was "qwen-deep" — matches config.vllm_deep_model
    }
