import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from bot.slack_handler import start_socket_mode
import threading

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup():
    # Run Slack socket mode in a background thread
    thread = threading.Thread(target=start_socket_mode, daemon=True)
    thread.start()
