"""FastAPI entry point for the Axari POC agent system."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path (needed when uvicorn reloader spawns child processes)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.router import router
from tools.integrations import register_all_integration_tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Axari POC Agent",
    description="Hybrid orchestrator agent with Claude native tool_use",
    version="0.1.0",
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.on_event("startup")
async def startup():
    """Register all integration tools on startup."""
    count = register_all_integration_tools()
    logger.info(f"Registered {count} integration tools")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8100, reload=True)
