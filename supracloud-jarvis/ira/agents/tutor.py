"""
Supracloud Tutor Agent — Socratic interactive teaching engine (Phase 5).

Core rules (never negotiable):
1. Never give final code or the exact answer upfront.
2. Socratic method: ask leading questions, guide the student to the answer.
3. Break concepts into metaphors.
4. Keep voice replies under 3 sentences.
5. If code is submitted, evaluate it privately and give hints — not solutions.
"""
from __future__ import annotations

import json
import re
import time

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete

_SYSTEM = """\
You are IRA, an elite technical trainer for Supracloud. Your goal is to teach the student a specific IT or coding concept.

STRICT RULES:
1. NEVER give the student the final code or exact answer immediately.
2. Use the Socratic method: ask 1-2 leading questions that guide them toward the answer themselves.
3. Break complex concepts into tiny, digestible metaphors (max 1 per response).
4. Keep replies under 3 sentences for voice delivery. Expand only when the student asks for more.
5. If a student says "just tell me the answer" → respond: "That would rob you of the learning. Let's take one more step: [leading question]"
6. Always end your response with exactly one question that propels the student forward.
7. Be warm, encouraging, and firm. Celebrate small wins.
"""

_SUBMIT_RE = re.compile(
    r"\b(here is my|here's my|check my|evaluate|review my|is this right|is this correct|my answer|my solution|my code)\b",
    re.I,
)
_TOPIC_RE = re.compile(r"\b(?:about|explain|understand|learn|teach me|how (?:does|do)|what is)\s+(.{3,50})", re.I)


async def tutor_agent(state: IRAState) -> IRAState:
    t0 = time.monotonic()
    query = state["user_query"]
    eval_context = ""

    # If the student is submitting work for review, evaluate it privately first
    if _SUBMIT_RE.search(query) or "```" in query:
        topic_match = _TOPIC_RE.search(query)
        topic = topic_match.group(1).strip() if topic_match else "programming concept"

        try:
            from utils.tutor_tools import evaluate_student_submission
            evaluation = await evaluate_student_submission(query, topic)

            if "error" not in evaluation:
                eval_context = (
                    "[PRIVATE EVALUATION — DO NOT REVEAL TO STUDENT]\n"
                    f"Correctness: {evaluation.get('correctness')}/10\n"
                    f"Logic errors: {json.dumps(evaluation.get('logic_errors', []))}\n"
                    f"Syntax errors: {json.dumps(evaluation.get('syntax_errors', []))}\n"
                    f"Strengths: {json.dumps(evaluation.get('strengths', []))}\n"
                    f"Socratic hints to use: {json.dumps(evaluation.get('socratic_hints', []))}\n"
                    "\nUse ONLY the Socratic hints above. "
                    "Do not reveal scores, errors, or corrections directly to the student."
                )
        except Exception as e:
            eval_context = f"[Evaluation unavailable: {e}]"

    messages = [{"role": "system", "content": _SYSTEM}]

    if eval_context:
        messages.append({"role": "system", "content": eval_context})

    if state.get("memory_context"):
        messages.append({"role": "system", "content": f"Session history:\n{state['memory_context']}"})

    messages.append({"role": "user", "content": query})

    response = await chat_complete(messages, use_deep=False, temperature=0.5)
    latency = int((time.monotonic() - t0) * 1000)

    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen3-fast",  # Fix L12: was "llama-fast" — matches config.vllm_fast_model
    }
