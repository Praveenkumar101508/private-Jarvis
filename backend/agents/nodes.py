"""
LangGraph node functions for IRA's reasoning pipeline.

LLM routing strategy (sovereign mode):
  Fast model  (llama3.1:8b  on thin client)  — classify, chat, calendar
  Heavy model (qwen2.5-coder:32b on Shadow PC via Tailscale) — TASK, code, analysis
"""
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langdetect import detect, LangDetectException

from config import settings
from persona.ira import get_system_prompt
from memory.store import MemoryStore
from agents.state import IRAState
from agents.tools.web_search import web_search
from agents.tools.calendar import get_calendar_events
from agents.tools.reminders import set_reminder, list_reminders

log = structlog.get_logger()

# Intents that warrant the heavy Shadow PC model
_HEAVY_INTENTS = {"TASK", "QUESTION_ANSWER"}


def _make_ollama_llm(model: str, base_url: str):
    from langchain_ollama import ChatOllama
    return ChatOllama(model=model, base_url=base_url)


def _get_fast_llm():
    """Low-latency model on the thin client (MacBook Air M1)."""
    if settings.llm_provider == "ollama":
        return _make_ollama_llm(settings.ollama_fast_model, settings.ollama_base_url)
    return _get_cloud_llm()


def _get_heavy_llm():
    """Heavy reasoning model on Shadow PC, reached via Tailscale mesh."""
    if settings.llm_provider == "ollama":
        return _make_ollama_llm(settings.ollama_heavy_model, settings.ollama_heavy_url)
    return _get_cloud_llm()


def _get_cloud_llm():
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=settings.anthropic_model, api_key=settings.anthropic_api_key)
    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key)


def _get_llm_for_intent(intent: str):
    """Route to the appropriate model based on intent complexity."""
    if intent in _HEAVY_INTENTS:
        log.debug("llm_routing", model="heavy", intent=intent)
        return _get_heavy_llm()
    log.debug("llm_routing", model="fast", intent=intent)
    return _get_fast_llm()


async def detect_language_node(state: IRAState) -> IRAState:
    last_message = state["messages"][-1].content if state["messages"] else ""
    try:
        detected = detect(last_message)
        lang_map = {"zh-cn": "zh", "zh-tw": "zh"}
        detected = lang_map.get(detected, detected)
    except LangDetectException:
        detected = state.get("language", "en")
    return {**state, "detected_language": detected}


async def load_memory_node(state: IRAState) -> IRAState:
    store = MemoryStore()
    query = state["messages"][-1].content if state["messages"] else ""

    # Short-term: recent conversation turns from Redis
    short_term = await store.get_context(state["session_id"])

    # Long-term: semantically relevant past exchanges from ChromaDB
    semantic = await store.semantic_recall(query)

    parts = [p for p in [semantic, short_term] if p]
    memory_context = "\n\n".join(parts) if parts else ""

    return {**state, "memory_context": memory_context}


async def classify_intent_node(state: IRAState) -> IRAState:
    llm = _get_fast_llm()  # classification always uses fast model
    last_msg = state["messages"][-1].content if state["messages"] else ""

    classification_prompt = f"""Classify the user's intent into ONE of these categories:
- GENERAL_CHAT: casual conversation, greetings, small talk
- QUESTION_ANSWER: factual questions that need web search
- CALENDAR: scheduling, reminders, events, meetings
- TASK: writing, coding, analysis, summarization
- MEMORY: asking about past conversations

User message: {last_msg}

Respond with ONLY the category name."""

    result = await llm.ainvoke([HumanMessage(content=classification_prompt)])
    intent = result.content.strip().upper()

    valid_intents = {"GENERAL_CHAT", "QUESTION_ANSWER", "CALENDAR", "TASK", "MEMORY"}
    if intent not in valid_intents:
        intent = "GENERAL_CHAT"

    return {
        **state,
        "user_intent": intent,
        "should_search": intent == "QUESTION_ANSWER",
        "should_use_calendar": intent == "CALENDAR",
    }


async def web_search_node(state: IRAState) -> IRAState:
    if not state.get("should_search"):
        return state
    query = state["messages"][-1].content if state["messages"] else ""
    results = await web_search(query)
    return {**state, "tool_results": results}


async def calendar_node(state: IRAState) -> IRAState:
    if not state.get("should_use_calendar"):
        return state
    events = await get_calendar_events()
    return {**state, "tool_results": events}


async def generate_response_node(state: IRAState) -> IRAState:
    intent = state.get("user_intent", "GENERAL_CHAT")
    llm = _get_llm_for_intent(intent)

    system = get_system_prompt("chat")
    messages = [SystemMessage(content=system)]

    if state.get("memory_context"):
        messages.append(SystemMessage(content=f"Memory context:\n{state['memory_context']}"))

    if state.get("tool_results"):
        tool_context = "\n".join(str(r) for r in state["tool_results"])
        messages.append(SystemMessage(content=f"Relevant information:\n{tool_context}"))

    messages.extend(state["messages"])

    detected = state.get("detected_language", "en")
    if detected != "en":
        messages.append(SystemMessage(
            content=f"The user is writing in language code '{detected}'. Respond in the same language."
        ))

    response = await llm.ainvoke(messages)

    store = MemoryStore()
    await store.save_turn(
        session_id=state["session_id"],
        user_msg=state["messages"][-1].content if state["messages"] else "",
        assistant_msg=response.content,
    )

    return {**state, "output": response.content}


def route_after_classify(state: IRAState) -> str:
    intent = state.get("user_intent", "GENERAL_CHAT")
    if intent == "QUESTION_ANSWER":
        return "web_search"
    if intent == "CALENDAR":
        return "calendar"
    return "generate_response"
