"""
Chart generator — builds Plotly figures for different chart types.

Zero knowledge of incidents, Slack, or this project.
Accepts generic tabular data (list of dicts) and chart configuration.

Supported chart types:
    bar             — vertical bar chart (categorical x, numeric y)
    horizontal_bar  — horizontal bar chart (good for long category names / rankings)
    line            — line chart with markers (time series)
    forecast        — historical bars + forecast line overlay
"""

from typing import Any, Dict, List, Optional

import plotly.graph_objects as go


# Colour palette
_BLUE = "#4A90D9"
_ORANGE = "#E8813A"
_GRID = "#E5E5E5"


def build_chart(
    data: List[Dict[str, Any]],
    chart_type: str,
    x_column: str,
    y_column: str,
    title: str = "Chart",
    x_label: str = "",
    y_label: str = "",
    forecast_data: Optional[List[Dict[str, Any]]] = None,
    forecast_y_column: str = "forecasted_count",
) -> go.Figure:
    """
    Build a Plotly Figure for the given data and chart type.

    Parameters
    ----------
    data : list of dicts
        Row data. Each dict must contain x_column and y_column keys.
    chart_type : str
        One of: "bar", "line", "horizontal_bar", "forecast"
    x_column : str
        Column name to use for the x-axis (or y-axis for horizontal_bar).
    y_column : str
        Column name to use for the y-axis (numeric).
    title : str
        Chart title displayed at the top.
    x_label : str
        Human-readable x-axis label. Defaults to x_column if empty.
    y_label : str
        Human-readable y-axis label. Defaults to y_column if empty.
    forecast_data : list of dicts, optional
        Forecast rows for the "forecast" chart type.
        Each dict must have "period" and forecast_y_column keys.
    forecast_y_column : str
        Key in forecast_data dicts that holds the forecasted value.
        Default "forecasted_count".

    Returns
    -------
    plotly.graph_objects.Figure
    """
    x_label = x_label or x_column
    y_label = y_label or y_column

    x_vals = [str(row[x_column]) for row in data]
    y_vals = [row[y_column] for row in data]

    fig = go.Figure()

    if chart_type == "bar":
        fig.add_trace(go.Bar(
            x=x_vals,
            y=y_vals,
            name=y_label,
            marker_color=_BLUE,
        ))

    elif chart_type == "horizontal_bar":
        fig.add_trace(go.Bar(
            x=y_vals,
            y=x_vals,
            orientation="h",
            name=y_label,
            marker_color=_BLUE,
        ))
        fig.update_layout(yaxis=dict(autorange="reversed"))

    elif chart_type == "line":
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            name=y_label,
            line=dict(color=_BLUE, width=2),
            marker=dict(size=6),
        ))

    elif chart_type == "forecast":
        # Historical bars
        fig.add_trace(go.Bar(
            x=x_vals,
            y=y_vals,
            name="Historical",
            marker_color=_BLUE,
        ))
        # Forecast line — connect last historical point for visual continuity
        if forecast_data:
            fx_vals = [str(row["period"]) for row in forecast_data]
            fy_vals = [row[forecast_y_column] for row in forecast_data]
            connect_x = [x_vals[-1]] + fx_vals
            connect_y = [y_vals[-1]] + fy_vals
            fig.add_trace(go.Scatter(
                x=connect_x,
                y=connect_y,
                mode="lines+markers",
                name="Forecast",
                line=dict(color=_ORANGE, width=2, dash="dash"),
                marker=dict(size=8, symbol="diamond"),
            ))

    else:
        raise ValueError(
            f"Unknown chart_type: '{chart_type}'. "
            "Use: bar, line, horizontal_bar, forecast"
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title=x_label,
        yaxis_title=y_label,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Arial, sans-serif", size=12),
        margin=dict(l=60, r=30, t=70, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        width=900,
        height=500,
    )
    fig.update_xaxes(showgrid=True, gridcolor=_GRID)
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, rangemode="tozero")

    return fig
