import os
import re
import psycopg2
import psycopg2.extras
import pandas as pd
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Optional


def _get_db_connection():
    """Build a psycopg2 connection using individual parameters to avoid URL encoding issues."""
    raw_url = os.environ["DATABASE_URL"]
    parsed = urlparse(raw_url)
    # Strip path to get dbname and clean any invisible characters from copy-paste
    dbname = parsed.path.lstrip("/").strip().replace(" ", "")
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        dbname=dbname,
        user=parsed.username,
        password=parsed.password,
        sslmode="require",
    )

from db import incidents as db
from db.supabase_client import supabase

# Initialise embedding provider
_provider = os.getenv("EMBEDDING_PROVIDER", "openai")
if _provider == "openai":
    from embeddings.openai_embedder import OpenAIEmbedder
    _embedder = OpenAIEmbedder()
else:
    from embeddings.voyage_embedder import VoyageEmbedder
    _embedder = VoyageEmbedder()

from vectorstore.pinecone_store import PineconeStore
_vector_store = PineconeStore(
    api_key=os.environ["PINECONE_API_KEY"],
    index_name=os.environ["PINECONE_INDEX_NAME"],
)


def search_incidents(query: str, top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
    """Semantic search — embeds query, searches Pinecone, fetches full records from Supabase."""
    query_vector = _embedder.embed(query)
    matches = _vector_store.search(query_vector, top_k=top_k, filters=filters, namespace="incidents")
    incident_ids = [m.metadata["source_id"] for m in matches]
    return db.get_by_ids(incident_ids)


def get_incident_by_number(number: str) -> Optional[Dict]:
    """Exact lookup by INC number."""
    return db.get_by_number(number.upper())


def get_all_by_system(system: str, limit: int = 100) -> List[Dict]:
    """Fetch all incidents for a specific configuration item / system."""
    response = (
        supabase.table("incidents")
        .select("*")
        .ilike("configuration_item", f"%{system}%")
        .limit(limit)
        .execute()
    )
    return response.data


ALLOWED_TABLES = {"incidents"}  # extend to {"incidents", "changes"} when changes table is added
DATE_FILTER = "opened_at >= NOW() - INTERVAL '2 years'"
MAX_ROW_ESTIMATE = 10_000


def _validate_tables(query: str) -> None:
    """Block queries that reference tables outside the whitelist."""
    referenced = set(re.findall(r'\b(?:FROM|JOIN)\s+(\w+)', query, re.IGNORECASE))
    disallowed = referenced - ALLOWED_TABLES
    if disallowed:
        raise ValueError(
            f"Query references disallowed table(s): {disallowed}. "
            f"Allowed: {ALLOWED_TABLES}"
        )


def _inject_date_filter(query: str) -> str:
    """
    Ensure every query is scoped to the past 1 year.
    If the query already references opened_at, leave it alone.
    Otherwise inject the filter before GROUP BY / ORDER BY / LIMIT / end of query.
    """
    if "opened_at" in query.lower():
        return query  # already has a date filter

    where_match = re.search(r'\bWHERE\b', query, re.IGNORECASE)
    if where_match:
        pos = where_match.end()
        return query[:pos] + f" {DATE_FILTER} AND " + query[pos:]

    # No WHERE clause — insert before first clause keyword or at end
    for keyword in ['GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT']:
        kw_match = re.search(rf'\b{keyword}\b', query, re.IGNORECASE)
        if kw_match:
            pos = kw_match.start()
            return query[:pos].rstrip() + f" WHERE {DATE_FILTER} " + query[pos:]

    return query.rstrip(';') + f" WHERE {DATE_FILTER}"


def _check_row_estimate(cur, query: str) -> None:
    """
    Run EXPLAIN and reject queries that Postgres estimates will scan
    more than MAX_ROW_ESTIMATE rows.
    """
    cur.execute(f"EXPLAIN {query}")
    for (line,) in cur.fetchall():
        match = re.search(r'rows=(\d+)', line)
        if match:
            estimate = int(match.group(1))
            if estimate > MAX_ROW_ESTIMATE:
                raise ValueError(
                    f"Query would scan ~{estimate:,} estimated rows "
                    f"(limit: {MAX_ROW_ESTIMATE:,}). Add more specific filters."
                )
            break


def sql_query(query: str) -> List[Dict]:
    """Execute a safe SELECT SQL query on the incidents database for aggregation and ranking."""
    clean = query.strip()

    # 1. Only SELECT allowed
    if not clean.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted.")

    # 2. Table whitelist
    _validate_tables(clean)

    # 3. Inject 1-year date filter if not already present
    clean = _inject_date_filter(clean)

    # 4. Auto-add LIMIT if missing
    if "LIMIT" not in clean.upper():
        clean = clean.rstrip(";") + " LIMIT 200"

    conn = _get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 5. Statement timeout — kill query after 30 seconds
            cur.execute("SET statement_timeout = '30s'")

            # 6. Row estimate guard — reject before running if too wide
            _check_row_estimate(cur, clean)

            # 7. Execute
            cur.execute(clean)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


from forecasting.forecaster import ExponentialSmoothingForecaster
from chart_png.tool import plot_chart

SUPPORTED_FILTERS = {"priority", "state", "assignment_group", "configuration_item", "label"}
SUPPORTED_INTERVALS = {"month", "week"}


def forecast_incidents(
    periods: int = 3,
    group_by: str = "month",
    filters: Optional[Dict] = None,
) -> Dict:
    """
    Forecast future incident volume using Exponential Smoothing.

    Fetches historical incident counts aggregated by the requested time interval,
    fits multiple ES models, selects the best by MSE, and returns a forecast.

    Parameters
    ----------
    periods : int
        Number of future periods to forecast. Default 3.
    group_by : str
        Time interval to aggregate on — 'month' or 'week'. Default 'month'.
    filters : dict, optional
        Column-value pairs to narrow the dataset before forecasting.
        Supported keys: priority, state, assignment_group, configuration_item, label.
        Example: {"priority": "Critical"} or {"configuration_item": "SAP"}
    """
    if group_by not in SUPPORTED_INTERVALS:
        raise ValueError(f"group_by must be one of {SUPPORTED_INTERVALS}. Got: '{group_by}'")

    if periods < 1 or periods > 24:
        raise ValueError(f"periods must be between 1 and 24. Got: {periods}")

    # --- Build parameterized SQL -----------------------------------------
    if group_by == "month":
        trunc_expr = "DATE_TRUNC('month', opened_at)"
        # Exclude the current partial month
        cutoff_expr = "DATE_TRUNC('month', NOW())"
    else:  # week
        trunc_expr = "DATE_TRUNC('week', opened_at)"
        cutoff_expr = "DATE_TRUNC('week', NOW())"

    where_clauses = [f"opened_at < {cutoff_expr}", "opened_at IS NOT NULL"]
    params = []

    if filters:
        for col, val in filters.items():
            if col not in SUPPORTED_FILTERS:
                raise ValueError(
                    f"Unsupported filter key: '{col}'. Allowed: {SUPPORTED_FILTERS}"
                )
            where_clauses.append(f"{col} = %s")
            params.append(val)

    where_sql = " AND ".join(where_clauses)
    query = f"""
        SELECT {trunc_expr} AS period, COUNT(*) AS count
        FROM incidents
        WHERE {where_sql}
        GROUP BY period
        ORDER BY period ASC
    """

    # --- Execute query ---------------------------------------------------
    conn = _get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            cur.execute(query, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {"error": "No historical data found for the given filters. Cannot forecast."}

    if len(rows) < 5:
        return {
            "error": (
                f"Only {len(rows)} complete {group_by}(s) of data available. "
                f"Need at least 5 to produce a reliable forecast."
            )
        }

    # --- Build time series -----------------------------------------------
    series = pd.Series(
        {str(row["period"])[:7 if group_by == "month" else 10]: float(row["count"])
         for row in rows},
        name="incident_count",
    )
    series.index.name = group_by

    # --- Fit and forecast -------------------------------------------------
    n_test = min(3, len(series) - 2)   # hold out up to 3 periods, keep >= 2 for training
    forecaster = ExponentialSmoothingForecaster(
        seasonal_periods=12 if group_by == "month" else 52,
        n_test=n_test,
    )
    forecaster.fit(series)
    result = forecaster.forecast(periods=periods)

    # --- Format output for Claude ----------------------------------------
    # all_predictions: fitted values for all historical periods + future forecast
    # Used by plot_chart as forecast_data to draw the full model prediction line
    all_predictions = (
        [{"period": p, "forecasted_count": v} for p, v in result.fitted_values]
        + [{"period": p, "forecasted_count": v} for p, v in result.forecast]
    )

    return {
        "group_by": group_by,
        "filters_applied": filters or {},
        "historical_periods": len(series),
        "historical_data": [
            {"period": p, "count": int(v)} for p, v in series.items()
        ],
        "best_model": result.best_model_label,
        "best_model_params": result.best_model_params,
        "accuracy": {
            "mse": result.mse,
            "r2": result.r2,
            "test_periods_used": n_test,
        },
        "forecast": [
            {"period": period, "forecasted_count": value}
            for period, value in result.forecast
        ],
        "all_predictions": all_predictions,
        "all_models_ranked": result.all_models_ranked,
    }


# Registry used by agent.py to dispatch tool calls
TOOL_REGISTRY = {
    "search_incidents": search_incidents,
    "get_incident_by_number": get_incident_by_number,
    "get_all_by_system": get_all_by_system,
    "sql_query": sql_query,
    "forecast_incidents": forecast_incidents,
    "plot_chart": plot_chart,
}
