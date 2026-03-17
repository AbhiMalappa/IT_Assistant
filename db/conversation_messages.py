import json
from typing import List, Dict, Any, Optional
from .supabase_client import supabase


def save(row: Dict[str, Any]) -> Dict:
    """Insert a message row into conversation_messages."""
    response = supabase.table("conversation_messages").insert(row).execute()
    return response.data[0]


def delete_thread(thread_id: str) -> None:
    """Delete all messages for a thread — used by /incident reset."""
    supabase.table("conversation_messages").delete().eq("thread_id", thread_id).execute()


def get_recent(thread_id: str, limit: int = 20) -> List[Dict]:
    """
    Fetch the most recent messages for a thread, newest first.
    Caller reverses to get chronological order for Claude.
    """
    response = (
        supabase.table("conversation_messages")
        .select("*")
        .eq("thread_id", thread_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data
