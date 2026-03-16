import os
import re
import threading
from pathlib import Path
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from bot.agent import run as agent_run
from db import incidents as db

app = App(token=os.environ["SLACK_BOT_TOKEN"])


def _clean_mention(text: str) -> str:
    """Strip the @bot mention from the message text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _post_response(say, text: str):
    """Send response back to Slack. Splits long messages if needed."""
    MAX_LEN = 3000
    if len(text) <= MAX_LEN:
        say(text)
    else:
        chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for chunk in chunks:
            say(chunk)


def _upload_chart(channel: str, chart_path: str, chart_title: str, chart_id: str = None, thread_ts: str = None):
    """Upload a PNG chart to Slack, then delete local files to free /tmp space."""
    try:
        kwargs = {
            "channel": channel,
            "file": chart_path,
            "title": chart_title,
            "filename": "chart.png",
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        app.client.files_upload_v2(**kwargs)
    except Exception as e:
        print(f"[chart_upload] Failed to upload chart PNG: {e}")
    finally:
        # Delete PNG immediately — once uploaded to Slack it's no longer needed
        try:
            os.remove(chart_path)
        except Exception:
            pass

    # Post interactive URL if APP_URL is configured
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    if app_url and chart_id:
        interactive_url = f"{app_url}/charts/{chart_id}"
        try:
            msg_kwargs = {
                "channel": channel,
                "text": f"<{interactive_url}|Open interactive chart>",
            }
            if thread_ts:
                msg_kwargs["thread_ts"] = thread_ts
            app.client.chat_postMessage(**msg_kwargs)
        except Exception as e:
            print(f"[chart_upload] Failed to post interactive URL: {e}")

        # Delete HTML after 10 minutes — long enough to view, frees /tmp space
        html_path = Path(f"/tmp/charts/{chart_id}.html")
        def _cleanup(p=html_path):
            import time
            time.sleep(600)
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        threading.Thread(target=_cleanup, daemon=True).start()
    elif chart_id:
        # No APP_URL — HTML won't be served, delete immediately
        try:
            Path(f"/tmp/charts/{chart_id}.html").unlink(missing_ok=True)
        except Exception:
            pass


def _get_thread_id(event: dict) -> str:
    """
    Extract a stable thread_id from a Slack event.
    - DMs: use channel ID (each DM is a unique channel per user)
    - Channel threads: use thread_ts if available, else channel + ts
    """
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts")
    ts = event.get("ts", "")
    if thread_ts:
        return f"{channel}_{thread_ts}"
    return channel if channel.startswith("D") else f"{channel}_{ts}"


# --- App mention: @IT Assistant <question> ---
@app.event("app_mention")
def handle_mention(event, say):
    user_message = _clean_mention(event.get("text", ""))
    if not user_message:
        say("Hi! Ask me anything about past IT incidents.")
        return

    thread_id = _get_thread_id(event)
    say("Looking into that...")
    response, chart_path, chart_id = agent_run(user_message, thread_id=thread_id)
    _post_response(say, response)
    if chart_path:
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts")  # only thread if already in a thread
        _upload_chart(channel, chart_path, "Chart", chart_id=chart_id, thread_ts=thread_ts)


# --- Direct messages ---
@app.event("message")
def handle_dm(event, say):
    # Ignore bot messages and message edits
    if event.get("bot_id") or event.get("subtype"):
        return

    user_message = event.get("text", "").strip()
    if not user_message:
        return

    thread_id = _get_thread_id(event)
    say("Looking into that...")
    response, chart_path, chart_id = agent_run(user_message, thread_id=thread_id)
    _post_response(say, response)
    if chart_path:
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts")  # only thread if already in a thread
        _upload_chart(channel, chart_path, "Chart", chart_id=chart_id, thread_ts=thread_ts)


# --- Slash command: /incident ---
@app.command("/incident")
def handle_incident_command(ack, say, command):
    ack()
    text = command.get("text", "").strip()

    if not text or text.startswith("help"):
        say(
            "*IT Assistant commands:*\n"
            "• `/incident search <query>` — search past incidents\n"
            "• `/incident status <INC number>` — get status of a specific incident\n"
            "• `/incident summary <INC number>` — plain English summary of an incident"
        )
        return

    parts = text.split(" ", 1)
    subcommand = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    # Slash commands share a thread_id per channel — no thread_ts available
    thread_id = f"slash_{command.get('channel_id', 'unknown')}_{command.get('user_id', '')}"

    if subcommand == "search":
        if not arg:
            say("Usage: `/incident search <your question>`")
            return
        say("Searching...")
        response, chart_path, chart_id = agent_run(arg, thread_id=thread_id)
        _post_response(say, response)
        if chart_path:
            _upload_chart(command.get("channel_id", ""), chart_path, "Chart", chart_id=chart_id)

    elif subcommand == "status":
        if not arg:
            say("Usage: `/incident status <INC number>`")
            return
        incident = db.get_by_number(arg.upper())
        if not incident:
            say(f"No incident found with number `{arg.upper()}`.")
            return
        say(
            f"*{incident['number']}* — {incident['short_description']}\n"
            f"• State: {incident['state']}\n"
            f"• Priority: {incident['priority']}\n"
            f"• Assigned to: {incident['assigned_to']} ({incident['assignment_group']})\n"
            f"• Opened: {incident['opened_at']}"
        )

    elif subcommand == "summary":
        if not arg:
            say("Usage: `/incident summary <INC number>`")
            return
        incident = db.get_by_number(arg.upper())
        if not incident:
            say(f"No incident found with number `{arg.upper()}`.")
            return
        summary_prompt = (
            f"Give a concise plain English summary of this incident:\n"
            f"Number: {incident['number']}\n"
            f"Description: {incident['short_description']}\n"
            f"Label: {incident['label']}\n"
            f"Priority: {incident['priority']}\n"
            f"State: {incident['state']}\n"
            f"Resolution: {incident['resolution_notes']}"
        )
        response, _ = agent_run(summary_prompt, thread_id=thread_id)
        _post_response(say, response)

    else:
        say(f"Unknown subcommand `{subcommand}`. Try `/incident help`.")


def start_socket_mode():
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
