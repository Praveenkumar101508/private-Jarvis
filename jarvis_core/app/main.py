import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import initialize_database_schema
from app.tools.daemons import start_email_daemon, start_lead_generation_daemon

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

@app.get("/telemetry/status")
async def get_system_health():
    return {
        "status": "ONLINE",
        "active_background_daemons": len(active_daemons),
        "hardware_mesh": "SYNCED"
    }
