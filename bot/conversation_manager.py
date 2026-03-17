"""
Conversation memory for the IT Assistant bot.

Architecture:
- BaseConversationManager: storage-agnostic interface (swappable to Redis/Upstash later)
- SupabaseConversationManager: Supabase implementation

Buffer strategy:
- Window: last 5 turns (10 messages)
- Token budget: 2000 tokens max for injected history
- Order: most recent first, work backwards until budget exceeded
- Token count stored at write time — no re-counting on retrieval

Summarisation triggers (use_summary = TRUE):
- tool_used in {sql_query, get_all_by_system, forecast_incidents}
- token_count > 300

Summarisation prompt includes tool context (tool name, filters, grouping, SQL query)
so follow-up questions can reference scope details (e.g. "forecast that for SAP")
without the summary stripping them out.
"""

import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from db import conversation_messages as db
from bot.claude_client import client, MODEL

SUMMARISE_TOOLS = {"sql_query", "get_all_by_system", "forecast_incidents"}
TOKEN_THRESHOLD = 300
BUFFER_TOKEN_BUDGET = 2000
BUFFER_TURN_LIMIT = 10  # 5 turns = 10 messages


def _count_tokens(text: str) -> int:
    """Approximate token count — 4 chars ≈ 1 token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _build_context_hint(tool_used: Optional[str], tool_input: Optional[Dict]) -> str:
    """
    Build a one-line hint for the summarisation prompt that captures the
    scope of the tool call — so the summary never drops filters, grouping
    dimensions, or system names that a follow-up question might rely on.
    """
    if not tool_used or not tool_input:
        return ""

    parts = [f"Tool used: {tool_used}."]

    if tool_used == "sql_query":
        query = tool_input.get("query", "")
        if query:
            parts.append(f"SQL query: {query[:300]}")

    elif tool_used == "forecast_incidents":
        group_by = tool_input.get("group_by", "month")
        periods = tool_input.get("periods", 3)
        filters = tool_input.get("filters") or {}
        parts.append(f"Forecast: next {periods} {group_by}(s).")
        if filters:
            parts.append(f"Filters applied: {json.dumps(filters)}.")

    elif tool_used == "get_all_by_system":
        system = tool_input.get("system", "")
        if system:
            parts.append(f"System queried: {system}.")

    elif tool_used == "search_incidents":
        query = tool_input.get("query", "")
        filters = tool_input.get("filters") or {}
        if query:
            parts.append(f"Search query: '{query}'.")
        if filters:
            parts.append(f"Filters: {json.dumps(filters)}.")

    return " ".join(parts)


def _summarise(content: str, tool_used: Optional[str] = None, tool_input: Optional[Dict] = None) -> str:
    """
    Call Claude to produce a short summary of a response.
    Injects a context hint so the summary always preserves scope details
    (system name, filters, grouping) needed for follow-up questions.
    """
    context_hint = _build_context_hint(tool_used, tool_input)

    prompt = (
        f"Summarise this IT assistant response in 2-3 sentences. "
        f"You MUST preserve: any system or configuration item names, filter values "
        f"(priority, state, assignment group), grouping dimensions (e.g. by month, by week), "
        f"key numeric findings, and incident numbers.\n"
    )
    if context_hint:
        prompt += f"\nContext: {context_hint}\n"
    prompt += f"\nResponse to summarise:\n{content}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


class BaseConversationManager(ABC):
    @abstractmethod
    def save_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        tool_used: Optional[str] = None,
        tool_input: Optional[Dict] = None,
        tool_result: Optional[str] = None,
        sql_query: Optional[str] = None,
    ) -> None:
        """Persist a message with optional tool tracking fields."""
        pass

    @abstractmethod
    def get_buffer(self, thread_id: str) -> List[Dict]:
        """
        Return token-aware message history formatted for Claude's messages API.
        Chronological order: oldest → newest.
        """
        pass

    @abstractmethod
    def should_summarise(self, tool_used: Optional[str], token_count: int) -> bool:
        """Return True if this message's content should be summarised."""
        pass

    @abstractmethod
    def reset(self, thread_id: str) -> None:
        """Delete all conversation history for a thread."""
        pass


class SupabaseConversationManager(BaseConversationManager):

    def should_summarise(self, tool_used: Optional[str], token_count: int) -> bool:
        return (tool_used in SUMMARISE_TOOLS) or (token_count > TOKEN_THRESHOLD)

    def reset(self, thread_id: str) -> None:
        db.delete_thread(thread_id)

    def save_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        tool_used: Optional[str] = None,
        tool_input: Optional[Dict] = None,
        tool_result: Optional[str] = None,
        sql_query: Optional[str] = None,
    ) -> None:
        token_count = _count_tokens(content)
        needs_summary = self.should_summarise(tool_used, token_count)

        summary = None
        if needs_summary:
            try:
                summary = _summarise(content, tool_used=tool_used, tool_input=tool_input)
            except Exception:
                summary = content[:300]  # fallback: truncate

        row = {
            "thread_id": thread_id,
            "role": role,
            "full_content": content,
            "summary": summary,
            "use_summary": needs_summary,
            "tool_used": tool_used,
            "tool_input": tool_input,
            "tool_result": tool_result,
            "sql_query": sql_query,
            "token_count": token_count,
        }

        db.save(row)

    def get_buffer(self, thread_id: str) -> List[Dict]:
        """
        Fetch last 20 messages, work backwards from most recent,
        stop when 4000 token budget exceeded. Return in chronological order.
        """
        rows = db.get_recent(thread_id, limit=BUFFER_TURN_LIMIT)
        # rows are newest-first — accumulate within budget
        selected = []
        token_total = 0

        for row in rows:
            token_count = row.get("token_count") or _count_tokens(
                row.get("full_content") or ""
            )
            if token_total + token_count > BUFFER_TOKEN_BUDGET:
                break
            token_total += token_count
            # Use summary if flagged, otherwise full content
            content = (
                row["summary"]
                if row.get("use_summary") and row.get("summary")
                else row.get("full_content") or ""
            )
            selected.append({"role": row["role"], "content": content})

        # Reverse to chronological order for Claude
        selected.reverse()
        return selected


# Singleton — imported by agent.py
conversation_manager = SupabaseConversationManager()
