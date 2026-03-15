"""
plot_chart tool — generates a PNG chart from tabular data and saves it to /tmp.

Called by Claude inside the agentic loop when a visual would add value.
The agent loop detects the returned chart_path and the Slack handler uploads it.

This module has zero knowledge of incidents, Slack, or this project.
"""

from typing import Any, Dict, List, Optional

from chart_png.generator import build_chart
from chart_png.store import save_png


def plot_chart(
    data: List[Dict[str, Any]],
    chart_type: str,
    x_column: str,
    y_column: str,
    title: str = "Chart",
    x_label: str = "",
    y_label: str = "",
    forecast_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generate a PNG chart from tabular data.

    Parameters
    ----------
    data : list of dicts
        Row data to chart. Must contain x_column and y_column keys.
    chart_type : str
        "bar", "line", "horizontal_bar", or "forecast"
    x_column : str
        Column name for the x-axis.
    y_column : str
        Column name for the y-axis (must be numeric).
    title : str
        Chart title shown at the top of the image.
    x_label : str
        Human-readable x-axis label. Defaults to x_column.
    y_label : str
        Human-readable y-axis label. Defaults to y_column.
    forecast_data : list of dicts, optional
        For "forecast" chart_type only.
        List of dicts with "period" and "forecasted_count" keys.

    Returns
    -------
    dict
        {"chart_path": str, "chart_title": str}
        chart_path is the absolute path to the saved PNG — the Slack handler
        reads this and uploads the file.
    """
    if not data:
        return {"error": "No data provided — cannot generate chart."}

    try:
        fig = build_chart(
            data=data,
            chart_type=chart_type,
            x_column=x_column,
            y_column=y_column,
            title=title,
            x_label=x_label,
            y_label=y_label,
            forecast_data=forecast_data,
        )
        path = save_png(fig)
        return {"chart_path": path, "chart_title": title}
    except Exception as e:
        return {"error": f"Chart generation failed: {e}"}
