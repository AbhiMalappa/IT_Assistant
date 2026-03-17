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
    anomaly_data: Optional[List[Dict[str, Any]]] = None,
) -> go.Figure:
    """
    Build a Plotly Figure for the given data and chart type.

    Parameters
    ----------
    data : list of dicts
        Row data. Each dict must contain x_column and y_column keys.
    chart_type : str
        One of: "bar", "line", "horizontal_bar", "forecast", "anomaly"
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
    anomaly_data : list of dicts, optional
        Anomalous points for the "anomaly" chart type.
        Same column structure as data — anomalies are highlighted as red markers.
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
    y_vals = [float(row[y_column]) if row[y_column] is not None else 0.0 for row in data]

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
        # Actual historical data — solid blue line
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            name="Actual",
            line=dict(color=_BLUE, width=2),
            marker=dict(size=6),
        ))
        # Model predictions (in-sample fit + future forecast) — orange dashed line
        if forecast_data:
            fx_vals = [str(row["period"]) for row in forecast_data]
            fy_vals = [float(row[forecast_y_column]) if row[forecast_y_column] is not None else 0.0 for row in forecast_data]
            fig.add_trace(go.Scatter(
                x=fx_vals,
                y=fy_vals,
                mode="lines+markers",
                name="Model / Forecast",
                line=dict(color=_ORANGE, width=2, dash="dash"),
                marker=dict(size=5),
            ))

    elif chart_type == "anomaly":
        # Full actual series — solid blue line
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            name="Actual",
            line=dict(color=_BLUE, width=2),
            marker=dict(size=5),
        ))
        # Anomalous points — red X markers overlaid on the line
        if anomaly_data:
            ax_vals = [str(row[x_column]) for row in anomaly_data]
            ay_vals = [float(row[y_column]) if row[y_column] is not None else 0.0 for row in anomaly_data]
            fig.add_trace(go.Scatter(
                x=ax_vals,
                y=ay_vals,
                mode="markers",
                name="Anomaly",
                marker=dict(color="red", size=12, symbol="x", line=dict(width=2)),
            ))

    else:
        raise ValueError(
            f"Unknown chart_type: '{chart_type}'. "
            "Use: bar, line, horizontal_bar, forecast, anomaly"
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
