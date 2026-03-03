"""FastAPI entry point for the Slack-like messaging app."""
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from messaging.router import router

app = FastAPI(title="Axari Messaging", version="1.0.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8200, reload=True)
