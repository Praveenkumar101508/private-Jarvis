"""
IRA Worker — Background intelligence process entry point.

Initialises DB/Redis connections, starts the APScheduler,
then keeps running until SIGTERM.

Run: python -m worker.main
"""

from __future__ import annotations

import asyncio
import logging
import signal

from config import get_settings
from utils.db import init_pool, close_pool
from utils.redis_client import init_redis, close_redis
from worker.scheduler import start_scheduler, stop_scheduler
from worker.notifier import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("ira.worker")


async def main() -> None:
    logger.info("IRA Worker starting...")

    await init_pool()
    logger.info("Database pool ready")

    await init_redis()
    logger.info("Redis connection ready")

    await start_scheduler()

    # Announce startup
    owner = get_settings().owner_name
    await notify(
        "IRA Worker Online",
        f"{owner}, IRA's proactive intelligence system is now active. "
        "I will monitor your systems, alert you to threats, and send your morning briefing at 08:00 UTC.",
        category="system",
        priority="info",
    )

    logger.info("IRA Worker is running. All monitors active.")

    # Block until SIGTERM / SIGINT
    stop_event = asyncio.Event()

    def _shutdown(sig, frame):
        logger.info(f"Received signal {sig}. Shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    await stop_event.wait()

    await stop_scheduler()
    await close_pool()
    await close_redis()
    logger.info("IRA Worker stopped. Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
