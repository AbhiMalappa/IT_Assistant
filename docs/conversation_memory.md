# Conversation Memory

## Purpose

The conversation memory system gives the bot context awareness across a Slack conversation thread. Without it, every message Claude receives is stateless — it has no knowledge of what was said earlier in the same thread. With memory, the bot can handle follow-up questions, pronoun references, and multi-turn investigations naturally.

**Example of what memory enables:**
```
User:  Top 5 printer issues this year
Bot:   [lists top 5 printer incidents]

User:  Which of those are still open?
Bot:   [correctly filters the previous results — knows "those" refers to printer incidents]

User:  Who is assigned to the first one?
Bot:   [answers correctly without needing the user to repeat the INC number]
```

Without memory, the second and third messages above would confuse the bot entirely.

---

## Architecture

```
Slack message arrives (with thread_id)
      ↓
agent.run(user_message, thread_id)
      ↓
conversation_manager.get_buffer(thread_id)   ← load history from Supabase
      ↓
[history messages] + [new user message] → Claude
      ↓
Claude calls tools, generates response
      ↓
conversation_manager.save_message(...)        ← persist to Supabase
      ↓
Response sent to Slack
```

Memory is injected into Claude's `messages` array on every turn, giving it full conversational context within the configured budget.

---

## Components

| File | Role |
|---|---|
| `bot/conversation_manager.py` | Core logic — buffer retrieval, summarisation, storage interface |
| `db/conversation_messages.py` | Supabase CRUD — save and fetch message rows |
| Supabase `conversation_messages` table | Persistent storage for all message history |

---

## Thread ID Strategy

Every Slack conversation maps to a unique `thread_id` string used as the key for message storage and retrieval.

| Slack context | thread_id format | Example |
|---|---|---|
| DM (direct message) | `channel` ID | `D08ABCDEF` |
| Channel mention (top-level) | `{channel}_{ts}` | `C08ABC_1741234567.123` |
| Channel mention (in a thread) | `{channel}_{thread_ts}` | `C08ABC_1741234500.000` |
| Slash command | `slash_{channel_id}_{user_id}` | `slash_C08ABC_U08XYZ` |

**Why DMs use channel ID only:** In Slack, each DM conversation is already a unique channel per user pair. No timestamp is needed to identify it.

**Why slash commands use channel + user:** Slash commands don't carry thread context, so the thread_id is scoped to that user in that channel.

---

## Buffer Strategy

When loading history for a given thread, the manager applies two limits:

### Turn Window
- Maximum **10 turns** (20 messages: 10 user + 10 assistant)
- Older messages beyond this window are not included, even if they fit in the token budget

### Token Budget
- Maximum **4,000 tokens** of history injected into Claude's context
- Token count is stored per message at write time (no re-counting on retrieval)
- Token approximation: `len(text) // 4` (4 characters ≈ 1 token)

### Retrieval Algorithm

```
1. Fetch last 20 rows from Supabase (newest first)
2. Iterate from most recent to oldest:
   a. Add message token count to running total
   b. If total would exceed 4,000 → stop
   c. Otherwise include the message
3. Reverse the selected messages → chronological order for Claude
```

This ensures the most recent context always fits, and older messages are dropped first when the budget is tight.

---

## Dual Storage: Full Content + Summary

Every message is stored with **two versions** of the content:

| Column | Description |
|---|---|
| `full_content` | The complete, untruncated response — always preserved |
| `summary` | A 2-3 sentence Claude-generated summary — used in buffer when flagged |
| `use_summary` | Boolean — whether to inject `summary` instead of `full_content` into the buffer |

`full_content` is **never discarded**. It is always available in Supabase for audit, debugging, or future re-processing. Only the buffer injection is affected by summarisation.

---

## Summarisation

Long or data-heavy responses are summarised before being injected into Claude's context. This prevents verbose tool results (e.g., 100 incident records) from consuming the entire token budget.

### Trigger Conditions

Summarisation is triggered (`use_summary = TRUE`) when **either** of these is true:

| Condition | Reason |
|---|---|
| `tool_used` is `sql_query` | SQL results can contain many rows and be very verbose |
| `tool_used` is `get_all_by_system` | Returns up to 100 incident records |
| Token count > 300 | Any long response, regardless of tool used |

### Summary Generation

When triggered, Claude itself is called to summarise the response:

```
Prompt: "Summarise this IT assistant response in 2-3 sentences,
         preserving key facts, incident numbers, and conclusions:

         [full response text]"

Model: claude-sonnet-4-20250514
Max tokens: 120
```

If the Claude call fails for any reason, the fallback is a hard truncation to the first 300 characters of the full content — ensuring the pipeline never breaks due to a summarisation error.

---

## Tool Tracking

Every saved message row captures what tool Claude used to generate it. This enables future analytics, debugging, and audit trails.

| Column | Description |
|---|---|
| `tool_used` | Name of the first tool called in that turn (e.g., `sql_query`, `search_incidents`) |
| `tool_input` | Parameters Claude passed to the tool, stored as JSONB |
| `tool_result` | Raw JSON result returned by the tool |
| `sql_query` | The actual SQL string — only populated when `tool_used = 'sql_query'` |

Only the **first tool** called per turn is tracked. If Claude calls multiple tools in a single turn (chaining), only the first is recorded in these fields.

---

## Database Schema

```sql
CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id       TEXT NOT NULL,
    role            VARCHAR(10) NOT NULL,        -- 'user' or 'assistant'
    full_content    TEXT,                        -- complete message text
    summary         TEXT,                        -- condensed version (if summarised)
    use_summary     BOOLEAN DEFAULT FALSE,       -- TRUE = inject summary into buffer
    tool_used       TEXT,                        -- e.g. 'sql_query'
    tool_input      JSONB,                       -- parameters passed to the tool
    tool_result     TEXT,                        -- raw tool output
    sql_query       TEXT,                        -- SQL string if tool_used = 'sql_query'
    token_count     INTEGER,                     -- approximate token count of full_content
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_thread_id_created ON conversation_messages(thread_id, created_at DESC);
```

---

## ConversationManager Class

Defined in `bot/conversation_manager.py`. Follows a storage-agnostic abstract base class pattern, making the storage backend swappable without changing any calling code.

### Interface

```python
class BaseConversationManager(ABC):
    def save_message(self, thread_id, role, content, tool_used, tool_input, tool_result, sql_query) -> None
    def get_buffer(self, thread_id) -> List[Dict]   # returns Claude-ready messages list
    def should_summarise(self, tool_used, token_count) -> bool
```

### Current Implementation

`SupabaseConversationManager` — backs storage in Supabase `conversation_messages` table.

### Swapping Storage Backends

The abstract base class makes it straightforward to swap to Redis, Upstash, or any other store later by implementing the same three methods. No changes needed in `agent.py` or `slack_handler.py`.

---

## Constraints and Limits

| Constraint | Value | Reason |
|---|---|---|
| Turn window | 10 turns (20 messages) | Keeps history focused on the current investigation |
| Token budget | 4,000 tokens | Leaves room for the user's question and Claude's response within the model's context limit |
| Summary max tokens | 120 tokens | Keeps summaries concise; 2-3 sentences is enough to retain key facts |
| Summarisation fallback | First 300 characters | Ensures the pipeline never breaks if Claude summarisation fails |
| Tool tracking | First tool per turn only | Simple and sufficient — chained tools are rare |

---

## What Is and Is Not Remembered

### Remembered (within the turn window + token budget)
- Previous questions and bot responses in the same Slack thread
- INC numbers mentioned earlier in the thread
- Systems or teams discussed earlier
- Analytical results Claude returned (in summary form if long)

### Not Remembered
- Messages from a different Slack thread or DM channel
- Messages older than the 10-turn window
- Messages that would push the token budget over 4,000 tokens (dropped starting from oldest)
- Tool inputs and results are stored in Supabase but **not** re-injected into Claude's context — only the final assistant response text is injected

---

## Future Considerations

- **Redis / Upstash backend:** For lower latency on high-volume deployments. The abstract base class makes this a drop-in replacement.
- **Cross-thread memory:** Currently each thread is fully isolated. A global user-level memory layer could be added without changing the existing thread buffer logic.
- **Summary quality tuning:** The summarisation prompt can be refined as real usage data reveals what context matters most across turns.
- **Token counter upgrade:** The current `len(text) // 4` approximation can be replaced with `tiktoken` for precise counts if budget accuracy becomes important.
