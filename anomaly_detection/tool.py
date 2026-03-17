"""
Anomaly detection tool wrappers — called by Claude via the agentic loop.

Two tools exposed to TOOL_REGISTRY:
    analyse_for_anomalies    — inspect series, return method options
    run_anomaly_detection    — run chosen method, return flagged anomalies

Both accept raw list-of-dicts (from sql_query results) and convert to pd.Series
internally. Zero knowledge of incidents or Slack.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from anomaly_detection.analyser import analyse_series
from anomaly_detection.detector import detect_anomalies


def _to_series(
    series_data: List[Dict[str, Any]],
    period_column: str,
    value_column: str,
) -> pd.Series:
    """Convert a list of row dicts to a pandas Series indexed by period."""
    return pd.Series(
        {row[period_column]: float(row[value_column]) for row in series_data},
        name=value_column,
    )


def analyse_for_anomalies(
    series_data: List[Dict[str, Any]],
    period_column: str,
    value_column: str,
    periods_hint: Optional[List[int]] = None,
) -> Dict:
    """
    Analyse a time series and return data characteristics + method options.
    Call this first before run_anomaly_detection to present options to the user.

    Parameters
    ----------
    series_data : list of dicts
        Row data from a sql_query result. Must contain period_column and value_column.
    period_column : str
        Column name for the time period (x-axis).
    value_column : str
        Column name for the numeric value to analyse (y-axis).
    periods_hint : list of int, optional
        Known seasonal periods to use instead of auto-detection.

    Returns
    -------
    dict — analysis result from analyse_series(), ready to present to user.
    """
    if not series_data:
        return {"error": "No data provided."}

    try:
        series = _to_series(series_data, period_column, value_column)
        return analyse_series(series, periods_hint=periods_hint)
    except KeyError as e:
        return {"error": f"Column not found in data: {e}"}
    except Exception as e:
        return {"error": f"Analysis failed: {e}"}


def run_anomaly_detection(
    series_data: List[Dict[str, Any]],
    period_column: str,
    value_column: str,
    method: str = "auto",
    threshold: Optional[float] = None,
    seasonal_periods: Optional[List[int]] = None,
    rolling_window: int = 12,
) -> Dict:
    """
    Run anomaly detection on a time series using the specified method.

    Parameters
    ----------
    series_data : list of dicts
        Row data from a sql_query result.
    period_column : str
        Column name for the time period.
    value_column : str
        Column name for the numeric value.
    method : str
        "stl", "mstl", "rolling_zscore", or "auto".
    threshold : float, optional
        Z-score threshold. Auto-selected based on noise level if not provided.
    seasonal_periods : list of int, optional
        Override auto-detected seasonal periods.
    rolling_window : int
        Window size for rolling Z-score. Default 12.

    Returns
    -------
    dict — full anomaly detection result including flagged points,
           method used, threshold, warnings, and z_scores for charting.
    """
    if not series_data:
        return {"error": "No data provided."}

    try:
        series = _to_series(series_data, period_column, value_column)
        return detect_anomalies(
            series=series,
            method=method,
            seasonal_periods=seasonal_periods,
            threshold=threshold,
            rolling_window=rolling_window,
        )
    except KeyError as e:
        return {"error": f"Column not found in data: {e}"}
    except Exception as e:
        return {"error": f"Anomaly detection failed: {e}"}
