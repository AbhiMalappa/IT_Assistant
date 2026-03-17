import os
import json
from typing import Optional, Tuple
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
- analyse_for_anomalies: inspect a time series and return data characteristics + method options. Call this FIRST when the user asks about anomalies, spikes, unusual patterns, or outliers in incident volume. Present the method options to the user and wait for their choice before running detection.
- run_anomaly_detection: run anomaly detection on a time series using the chosen method. Call this AFTER the user selects a method from analyse_for_anomalies results. Then call plot_chart with chart_type="anomaly".
- plot_chart: generate a PNG chart from tabular data and post it in Slack. Call this after sql_query or forecast_incidents when a visual would genuinely help the user understand the data. Do NOT call it for single-row results, text lookups, or search results.

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
10. Anomaly detection — two-step flow:
    Step 1: call analyse_for_anomalies with the series data. Present method options to user exactly as returned (key, label, description). Mark the recommended option. Ask user to pick a letter, "auto", or "go with recommendation".
    Step 2: once user replies, call run_anomaly_detection with method=chosen. Then call plot_chart with chart_type="anomaly", passing the original series as data and anomalies list as anomaly_data (map period→x_column, actual→y_column).
    Report: method used, threshold, anomaly count, each flagged period with actual value and z_score. Include any warnings (sparsity, capped outliers).
11. Charting — call plot_chart when the data is clearly visual:
    - After sql_query: call plot_chart if result has multiple rows with a categorical or date/period column + a numeric column. Use "bar" for categorical breakdowns (state, priority, assignment_group), "horizontal_bar" for ranked lists, "line" for time series by month/week.
    - After forecast_incidents: always call plot_chart with chart_type="forecast", passing historical_data as data, all_predictions as forecast_data, x_column="period", y_column="count". This produces a solid blue actual line and an orange dashed model/forecast line covering all periods.
    - Do NOT call plot_chart for: single-row results, search_incidents results, get_incident_by_number results, or get_all_by_system results.
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
    },
    {
        "name": "analyse_for_anomalies",
        "description": (
            "Analyse a time series and return data characteristics plus method options for anomaly detection. "
            "Call this FIRST when the user asks about anomalies, spikes, or unusual patterns. "
            "Present the returned method options to the user and wait for their choice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series_data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of row dicts with period and value columns. Typically from a sql_query result."
                },
                "period_column": {
                    "type": "string",
                    "description": "Column name for the time period (e.g. 'period', 'month', 'opened_at')."
                },
                "value_column": {
                    "type": "string",
                    "description": "Column name for the numeric value to analyse (e.g. 'count', 'total')."
                },
                "periods_hint": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional known seasonal periods to override auto-detection (e.g. [12] for monthly yearly seasonality)."
                }
            },
            "required": ["series_data", "period_column", "value_column"]
        }
    },
    {
        "name": "run_anomaly_detection",
        "description": (
            "Run anomaly detection on a time series using the method chosen by the user. "
            "Call this AFTER the user selects a method from analyse_for_anomalies. "
            "Then call plot_chart with chart_type='anomaly' to visualise results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series_data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Same series data passed to analyse_for_anomalies."
                },
                "period_column": {
                    "type": "string",
                    "description": "Column name for the time period."
                },
                "value_column": {
                    "type": "string",
                    "description": "Column name for the numeric value."
                },
                "method": {
                    "type": "string",
                    "enum": ["stl", "mstl", "rolling_zscore", "auto"],
                    "description": "Method chosen by user. 'auto' selects the best method automatically."
                },
                "threshold": {
                    "type": "number",
                    "description": "Z-score threshold for flagging anomalies. Auto-selected based on noise level if not provided."
                },
                "seasonal_periods": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Override detected seasonal periods if needed."
                }
            },
            "required": ["series_data", "period_column", "value_column", "method"]
        }
    },
    {
        "name": "plot_chart",
        "description": (
            "Generate a PNG chart from tabular data and post it in Slack. "
            "Call after sql_query when the result has multiple rows with a categorical or time column + a numeric column. "
            "Always call after forecast_incidents using chart_type='forecast'. "
            "Do NOT call for single-row results, search results, or individual incident lookups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "List of row dicts from the previous tool result. "
                        "For forecast charts, pass the historical_data list from forecast_incidents."
                    )
                },
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "horizontal_bar", "forecast", "anomaly"],
                    "description": (
                        "bar: vertical bars for categorical breakdowns (state, priority, assignment_group). "
                        "horizontal_bar: horizontal bars for ranked lists (top N). "
                        "line: time series by month or week. "
                        "forecast: solid actual line + dashed model/forecast line. "
                        "anomaly: actual line with red X markers at anomalous points."
                    )
                },
                "x_column": {
                    "type": "string",
                    "description": "Column name from data to use for the x-axis (or categories for horizontal_bar)."
                },
                "y_column": {
                    "type": "string",
                    "description": "Column name from data to use for the y-axis. Must be numeric."
                },
                "title": {
                    "type": "string",
                    "description": "Chart title shown at the top. Be descriptive, e.g. 'Incidents by Priority' or 'Monthly Incident Volume — SAP'."
                },
                "x_label": {
                    "type": "string",
                    "description": "Human-readable x-axis label. Optional — defaults to x_column."
                },
                "y_label": {
                    "type": "string",
                    "description": "Human-readable y-axis label. Optional — defaults to y_column."
                },
                "forecast_data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "For chart_type='forecast' only. "
                        "Pass all_predictions from forecast_incidents result — this contains "
                        "in-sample fitted values for all historical periods plus the future forecast. "
                        "Each dict has 'period' and 'forecasted_count' keys."
                    )
                },
                "anomaly_data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "For chart_type='anomaly' only. "
                        "Pass the anomalies list from run_anomaly_detection. "
                        "Each dict must have 'period' and 'actual' keys — these map to x_column and y_column."
                    )
                }
            },
            "required": ["data", "chart_type", "x_column", "y_column", "title"]
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


def run(user_message: str, thread_id: Optional[str] = None) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Agentic loop — Claude decides which tools to call, we execute them, loop until done.
    If thread_id is provided, conversation history is loaded and saved to Supabase.

    Returns
    -------
    (text_response, chart_path, chart_id)
        chart_path — absolute path to PNG for Slack inline upload (None if no chart)
        chart_id   — UUID for interactive HTML URL at /charts/{chart_id} (None if no chart)
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

    # Chart generated by plot_chart (if called)
    chart_path: Optional[str] = None
    chart_id: Optional[str] = None
    chart_title: Optional[str] = None

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

            return final_text, chart_path, chart_id

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

                    # Capture chart path if plot_chart was called
                    if block.name == "plot_chart":
                        try:
                            result_dict = json.loads(result)
                            if "chart_path" in result_dict:
                                chart_path = result_dict["chart_path"]
                                chart_id = result_dict.get("chart_id")
                                chart_title = result_dict.get("chart_title", "Chart")
                        except Exception:
                            pass

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            return "Unexpected response from AI. Please try again.", None, None
