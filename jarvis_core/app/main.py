import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from app.database import initialize_database_schema
from app.tools.daemons import start_email_daemon, start_lead_generation_daemon
from app.agents.swarm import compiled_ira_brain

active_daemons = set()

@asynccontextmanager
async def app_lifespan_handler(app: FastAPI):
    """Initializes local storage schema layouts and ensures background daemons remain unblocked."""
    initialize_database_schema()

    email_loop_task = asyncio.create_task(start_email_daemon())
    leads_loop_task = asyncio.create_task(start_lead_generation_daemon())

    active_daemons.add(email_loop_task)
    active_daemons.add(leads_loop_task)

    email_loop_task.add_done_callback(active_daemons.discard)
    leads_loop_task.add_done_callback(active_daemons.discard)

    yield

    print("Safely winding down autonomous corporate daemons...")
    for task in active_daemons:
        task.cancel()
    await asyncio.gather(*active_daemons, return_exceptions=True)

app = FastAPI(title="IRA_CORE", lifespan=app_lifespan_handler)

class QueryRequest(BaseModel):
    message: str

@app.get("/telemetry/status")
async def get_system_health():
    return {
        "status": "ONLINE",
        "active_background_daemons": len(active_daemons),
        "hardware_mesh": "SYNCED"
    }

@app.post("/ira/query")
async def invoke_ira(request: QueryRequest):
    """Routes a natural-language query through the IRA swarm and returns the response."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "intent_classification": "",
        "target_deliverable_spec": "",
        "execution_errors": [],
    }
    result = await asyncio.get_event_loop().run_in_executor(
        None, compiled_ira_brain.invoke, initial_state
    )
    last_message = result["messages"][-1].content
    return {
        "intent": result.get("intent_classification"),
        "response": last_message,
    }
