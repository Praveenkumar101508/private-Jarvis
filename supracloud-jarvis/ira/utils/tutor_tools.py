"""
IRA Tutor Tools — Phase 5.

evaluate_student_submission(submission_text, topic) → structured Socratic critique.
Returns hints and leading questions — never reveals the answer directly.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("ira.tutor_tools")

_EVAL_SYSTEM = """\
You are an expert code reviewer and technical educator.
Analyse the student's submission for the given topic.
Return a JSON object with EXACTLY these fields:
{
  "correctness": <0-10 integer>,
  "logic_errors": [<string>, ...],
  "syntax_errors": [<string>, ...],
  "security_risks": [<string>, ...],
  "strengths": [<string>, ...],
  "socratic_hints": [<2-3 leading questions that guide toward the answer WITHOUT revealing it>],
  "one_liner": "<max 15 words of encouragement or gentle redirection>"
}
Respond with ONLY the JSON object. No markdown fences, no extra text.
"""


async def evaluate_student_submission(submission_text: str, topic: str) -> dict:
    """
    Deep-analyse a student's code or written answer.
    Returns structured critique with Socratic hints — never reveals the solution.
    """
    from utils.llm import chat_complete

    try:
        raw = await chat_complete(
            [
                {"role": "system", "content": _EVAL_SYSTEM},
                {"role": "user", "content": f"Topic: {topic}\n\nSubmission:\n{submission_text[:3000]}"},
            ],
            use_deep=True,
            temperature=0.2,
            max_tokens=1024,
        )

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)
        logger.info(f"Submission evaluated — correctness: {result.get('correctness')}/10")
        return result

    except json.JSONDecodeError:
        return {
            "correctness": None,
            "logic_errors": [],
            "syntax_errors": [],
            "security_risks": [],
            "strengths": [],
            "socratic_hints": [raw[:200] if raw else "Think about the core concept again."],
            "one_liner": "Let's keep working through this together.",
        }
    except Exception as e:
        logger.error(f"evaluate_student_submission failed: {e}")
        return {"error": str(e)}
