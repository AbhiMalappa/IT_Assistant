import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from bot.slack_handler import start_socket_mode
import threading

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/charts/{chart_id}", response_class=HTMLResponse)
def serve_chart(chart_id: str):
    """Serve an interactive Plotly HTML chart by ID."""
    # Sanitise — only allow UUID-like filenames, no path traversal
    if not chart_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chart ID")
    path = Path(f"/tmp/charts/{chart_id}.html")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chart not found or expired")
    return path.read_text()


@app.on_event("startup")
def startup():
    # Run Slack socket mode in a background thread
    thread = threading.Thread(target=start_socket_mode, daemon=True)
    thread.start()
