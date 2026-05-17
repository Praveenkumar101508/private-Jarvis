"""
Phase 1 + 2: Chat router — text conversations with LangGraph agent
"""
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.graph import IRAGraph
from memory.store import MemoryStore
from persona.ira import LANGUAGE_GREETINGS, get_system_prompt

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    language: str = "en"
    stream: bool = True


class ChatResponse(BaseModel):
    response: str
    session_id: str
    detected_language: str


@router.post("/")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    graph = IRAGraph()

    if req.stream:
        async def stream_response() -> AsyncGenerator[str, None]:
            async for chunk in graph.stream(
                message=req.message,
                session_id=session_id,
                language=req.language,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    response = await graph.invoke(
        message=req.message,
        session_id=session_id,
        language=req.language,
    )
    return ChatResponse(
        response=response["output"],
        session_id=session_id,
        detected_language=response.get("detected_language", req.language),
    )


@router.get("/greet")
async def greet(language: str = "en"):
    greeting = LANGUAGE_GREETINGS.get(language, LANGUAGE_GREETINGS["en"])
    return {"greeting": greeting, "language": language}


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    store = MemoryStore()
    await store.clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}
