"""
Meta Agent Creator — generates complete, deployable LangGraph agents from a description.

Output: full Python source + Dockerfile + docker-compose snippet + test command.
The generated code is persisted to the agents table for later retrieval/deployment.
"""

from __future__ import annotations

import json
import time
import uuid

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete
from utils.db import acquire

_SYSTEM = """\
You are the Meta Agent Creator module of IRA — an expert LangGraph engineer.

When a user describes a new agent, you produce:

1. **agents/<agent_name>.py** — complete, runnable LangGraph agent code with:
   - Typed state (TypedDict)
   - All nodes implemented (no stubs, no TODOs)
   - Proper async/await throughout
   - Error handling in every node
   - OpenAI-compatible vLLM client (base_url from env)
   - Clear docstrings on every function

2. **Dockerfile** — production-grade, non-root user, multi-stage

3. **docker-compose snippet** — ready to paste into docker-compose.yml

4. **Verification** — exact command to test the agent is working

Rules:
- Use LangGraph ≥ 0.2 API (StateGraph, add_messages, etc.)
- Import from langchain_core, not langchain directly
- All secrets via environment variables — never hardcoded
- Every agent must have a /health endpoint if it exposes HTTP
- Generated code must be production-ready, not a demo

Format your response as:
### Agent: <name>
<description>

```python
# agents/<name>.py
<full code>
```

```dockerfile
# Dockerfile
<full code>
```

```yaml
# docker-compose snippet
<snippet>
```

**Test command:**
```bash
<command>
```
\
"""


async def meta_agent_creator(state: IRAState) -> IRAState:
    t0 = time.monotonic()

    messages = [{"role": "system", "content": _SYSTEM}]

    if state.get("memory_context"):
        messages.append({
            "role": "system",
            "content": f"Previously created agents (for reference):\n{state['memory_context']}",
        })

    messages.append({"role": "user", "content": state["user_query"]})

    # Always deep model — code generation requires maximum capability
    response = await chat_complete(messages, use_deep=True, temperature=0.2, max_tokens=8192)

    # Persist the generated agent to the database
    agent_name = _extract_agent_name(state["user_query"])
    await _save_agent(agent_name, state["user_query"], response)

    latency = int((time.monotonic() - t0) * 1000)
    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen3-deep",  # Fix L11: was "qwen-deep" — matches config.vllm_deep_model
    }


def _extract_agent_name(query: str) -> str:
    """Best-effort extraction of agent name from query."""
    import re
    match = re.search(r"(?:agent|called|named)\s+['\"]?(\w+)['\"]?", query, re.I)
    return match.group(1).lower() if match else f"agent_{uuid.uuid4().hex[:6]}"


async def _save_agent(name: str, description: str, code: str) -> None:
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO agents (name, description, code, status)
               VALUES ($1, $2, $3, 'draft')
               ON CONFLICT (name) DO UPDATE
               SET code = EXCLUDED.code, updated_at = NOW()""",
            name, description, code,
        )
