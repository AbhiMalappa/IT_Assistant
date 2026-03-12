import os
import json
from typing import Optional
from anthropic import Anthropic
from bot.tools import TOOL_REGISTRY
from bot.conversation_manager import conversation_manager

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """
You are the IT Assistant bot, built for IT incident managers to quickly find information, diagnose issues, and understand incident trends.

You were built by Abhiraj Malappa. For support, feedback, bugs, or questions about the bot, contact: abhiraj7m@gmail.com

---

WHAT YOU CAN DO:
- Search past incidents semantically ("why does SAP fail?", "how are printer issues resolved?")
- Look up a specific incident by number ("what state is INC17089320 in?", "summarize INC17089043")
- Aggregate and rank incidents ("top 5 printer issues", "how many open incidents?", "which team has the most critical incidents?")
- Fetch all incidents for a system ("all SAP incidents", "every network issue")
- Forecast future incident volume ("how many incidents next month?", "predict SAP incidents for next quarter")
- Answer general IT troubleshooting questions using past incident knowledge

---

TOOLS — choose based on the question:
- search_incidents: semantic similarity search. Use for open-ended questions about past incidents, root causes, resolutions.
- get_incident_by_number: exact lookup. Use whenever the user mentions a specific INC number.
- get_all_by_system: full dataset for a system. Use when the user wants ALL incidents for a system, not just the top few.
- sql_query: aggregation and ranking. Use for counts, rankings, trends, averages. Write safe SELECT queries against the incidents table.
- forecast_incidents: predict future incident volume using exponential smoothing. Use for any forward-looking volume question ("next month", "next quarter", "predict", "forecast", "expected volume"). Supports optional filters by priority, state, assignment_group, configuration_item, or label.

incidents table columns:
  id, number, opened_at, opened_by, state, contact_type, assignment_group,
  assigned_to, priority, configuration_item, resolution_tier, short_description,
  caller, label, resolution_notes, created_at, updated_at

state values: Open, Closed, In Progress, Cancelled, On hold
priority values: Low, Medium, High, Critical

---

RESPONSE RULES:
1. Be concise and actionable. Incident managers are under pressure.
2. Use bullet points for lists. No markdown headers.
3. When referencing specific incidents, always include the INC number.
4. After answering with incident data, add "References: INC..., INC..." listing incidents used.
5. For aggregation results, present as a clean ranked list or summary.
6. If you cannot find relevant information, say so clearly. Never fabricate incident details.
7. For greetings or general questions, respond conversationally and guide the user toward asking about incidents.
8. If a user reports a bug or wants to give feedback, provide the support contact: abhiraj7m@gmail.com
9. For forecast results: state the model used, show the forecasted values per period, and include the MSE so the user knows the accuracy. If R² is negative, briefly note that it reflects limited historical data, not a broken model.
""".strip()

TOOL_DEFINITIONS = [
    {
        "name": "search_incidents",
        "description": (
            "Semantic search over past IT incidents. Use for open-ended questions like "
            "'why does SAP fail?', 'how are printer issues resolved?', 'find incidents about network outages'. "
            "Returns the most semantically similar incidents. NOT suitable for counting or ranking all incidents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing the incident or issue."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return. Default 5, max 20.",
                    "default": 5
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Optional Pinecone metadata filters. Supported keys: priority, state, "
                        "assignment_group, configuration_item, label. "
                        "Example: {\"priority\": {\"$eq\": \"Critical\"}}"
                    )
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_incident_by_number",
        "description": (
            "Exact lookup of a single incident by its INC number. "
            "Use whenever the user references a specific incident number like INC17089320."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "The incident number, e.g. INC17089320."
                }
            },
            "required": ["number"]
        }
    },
    {
        "name": "get_all_by_system",
        "description": (
            "Fetch all incidents for a specific system or configuration item. "
            "Use when the user wants the complete picture for a system (e.g., 'all SAP incidents', 'every printer issue'). "
            "Better than search_incidents for full coverage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "system": {
                    "type": "string",
                    "description": "The system or configuration item name, e.g. SAP, Printer, Server, Workstation."
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return. Default 100.",
                    "default": 100
                }
            },
            "required": ["system"]
        }
    },
    {
        "name": "sql_query",
        "description": (
            "Execute a SELECT SQL query on the incidents database. "
            "Use for aggregation, counting, ranking, and trend questions like "
            "'how many open incidents?', 'top 5 printer issues by count', 'which assignment group has the most critical incidents?'. "
            "Rules: SELECT only. Query the 'incidents' table only. "
            "Always scope to the past 2 years: include 'opened_at >= NOW() - INTERVAL ''2 years''' in your WHERE clause. "
            "Always include a LIMIT clause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A safe SELECT SQL query against the incidents table. "
                        "Columns: id, number, opened_at, opened_by, state, contact_type, assignment_group, "
                        "assigned_to, priority, configuration_item, resolution_tier, short_description, "
                        "caller, label, resolution_notes, created_at, updated_at."
                    )
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "forecast_incidents",
        "description": (
            "Forecast future IT incident volume using Exponential Smoothing (statsmodels). "
            "Use for any forward-looking volume question: 'how many incidents next month?', "
            "'predict SAP incidents for next quarter', 'what is the expected volume?', 'forecast'. "
            "Tries multiple ES model configurations (SES, Holt, Holt-Winters where data allows), "
            "selects the best by MSE on a held-out test set, and returns a forecast with accuracy metrics. "
            "Do NOT use this for historical counts or rankings — use sql_query for those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periods": {
                    "type": "integer",
                    "description": "Number of future periods to forecast. Default 3. Max 24.",
                    "default": 3
                },
                "group_by": {
                    "type": "string",
                    "enum": ["month", "week"],
                    "description": "Time interval to aggregate on. Default 'month'.",
                    "default": "month"
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Optional column-value filters to narrow the dataset before forecasting. "
                        "Supported keys: priority, state, assignment_group, configuration_item, label. "
                        "Example: {\"configuration_item\": \"SAP\"} or {\"priority\": \"Critical\"}"
                    )
                }
            },
            "required": []
        }
    }
]


def _execute_tool(name: str, inputs: dict) -> str:
    """Dispatch a tool call and return result as a JSON string."""
    fn = TOOL_REGISTRY.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**inputs)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def run(user_message: str, thread_id: Optional[str] = None) -> str:
    """
    Agentic loop — Claude decides which tools to call, we execute them, loop until done.
    If thread_id is provided, conversation history is loaded and saved to Supabase.
    """
    # Load conversation buffer for this thread
    messages = []
    if thread_id:
        messages = conversation_manager.get_buffer(thread_id)

    # Append current user message
    messages.append({"role": "user", "content": user_message})

    # Save user message to memory
    if thread_id:
        conversation_manager.save_message(thread_id, "user", user_message)

    # Track the primary tool used in this turn (first tool called)
    primary_tool: Optional[str] = None
    primary_tool_input: Optional[dict] = None
    primary_tool_result: Optional[str] = None
    primary_sql: Optional[str] = None

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Claude is done — save assistant message and return
        if response.stop_reason == "end_turn":
            final_text = None
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break
            final_text = final_text or "I couldn't generate a response. Please try again."

            if thread_id:
                conversation_manager.save_message(
                    thread_id=thread_id,
                    role="assistant",
                    content=final_text,
                    tool_used=primary_tool,
                    tool_input=primary_tool_input,
                    tool_result=primary_tool_result,
                    sql_query=primary_sql,
                )

            return final_text

        # Claude wants to use tools
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(block.name, block.input)

                    # Track the first tool called in this turn
                    if primary_tool is None:
                        primary_tool = block.name
                        primary_tool_input = block.input
                        primary_tool_result = result
                        if block.name == "sql_query":
                            primary_sql = block.input.get("query")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            return "Unexpected response from AI. Please try again."
