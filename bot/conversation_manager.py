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

Truncation triggers (use_summary = TRUE, no extra API call):
- tool_used in TRUNCATE_LIMITS (sql_query/get_all_by_system → 300 tokens, forecast/anomaly → 500 tokens)
- token_count > TOKEN_THRESHOLD (500)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from db import conversation_messages as db

# Truncation limits (in chars, ~4 chars per token) applied per tool instead of LLM summarisation.
# Tools not listed here are stored in full (responses are already short).
TRUNCATE_LIMITS = {
    "sql_query":            1200,   # 300 tokens — aggregation lists fit fine
    "get_all_by_system":    1200,   # 300 tokens
    "forecast_incidents":   2000,   # 500 tokens — needs model, values, accuracy
    "run_anomaly_detection": 2000,  # 500 tokens — needs method, threshold, flagged periods
}
TOKEN_THRESHOLD = 500   # fallback: truncate any response exceeding this many tokens
BUFFER_TOKEN_BUDGET = 2000
BUFFER_TURN_LIMIT = 10  # 5 turns = 10 messages


def _count_tokens(text: str) -> int:
    """Approximate token count — 4 chars ≈ 1 token."""
    if not text:
        return 0
    return max(1, len(text) // 4)



def _truncate(content: str, tool_used: Optional[str] = None) -> str:
    """
    Truncate content to the tool-specific char limit.
    No extra API call — just a string cut with an ellipsis marker.
    """
    char_limit = TRUNCATE_LIMITS.get(tool_used, TOKEN_THRESHOLD * 4)
    if len(content) <= char_limit:
        return content
    return content[:char_limit] + "… [truncated]"


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
        return (tool_used in TRUNCATE_LIMITS) or (token_count > TOKEN_THRESHOLD)

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
            summary = _truncate(content, tool_used=tool_used)

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
