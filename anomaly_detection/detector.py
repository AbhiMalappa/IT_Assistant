"""
Anomaly Detector — runs anomaly detection on a time series.

Supported methods:
    stl           — STL decomposition + Z-score on residuals (single seasonality)
    mstl          — MSTL decomposition + Z-score on residuals (multiple seasonalities)
    rolling_zscore — Rolling window Z-score (no decomposition)
    auto          — Auto-selects best method based on data characteristics

Pre-flight checks:
    - Minimum data points
    - All-zero / zero-variance series
    - Sparsity warning
    - IQR outlier capping before model fitting (originals used for scoring)

Zero knowledge of incidents, Slack, or this project.
"""

import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL, MSTL

from anomaly_detection.analyser import analyse_series
from anomaly_detection.threshold import suggest_threshold

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# IQR outlier capping
# ---------------------------------------------------------------------------

_IQR_MULTIPLIER = 3.0   # conservative — only caps extreme outliers


def _iqr_cap(series: pd.Series) -> pd.Series:
    """
    Cap extreme outliers using IQR fences before model fitting.
    Original values are preserved — capping applies only to the returned copy.
    """
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - _IQR_MULTIPLIER * iqr
    upper = q3 + _IQR_MULTIPLIER * iqr
    capped = series.clip(lower=lower, upper=upper)

    # Record which points were capped
    capped_points = []
    mask = (series < lower) | (series > upper)
    for idx in series[mask].index:
        capped_points.append({
            "period": str(idx),
            "original_value": round(float(series[idx]), 2),
            "capped_to": round(float(capped[idx]), 2),
        })

    return capped, capped_points


# ---------------------------------------------------------------------------
# Decomposition helpers
# ---------------------------------------------------------------------------

def _residuals_stl(series_capped: pd.Series, period: int) -> pd.Series:
    result = STL(series_capped, period=period, robust=True).fit()
    return result.resid


def _residuals_mstl(series_capped: pd.Series, periods: List[int]) -> pd.Series:
    result = MSTL(series_capped, periods=periods).fit()
    return result.resid


def _residuals_rolling(series: pd.Series, window: int) -> pd.Series:
    """
    For rolling Z-score, residuals = deviation from rolling mean.
    Uses centered window for historical analysis.
    """
    rolling_mean = series.rolling(window=window, center=True, min_periods=3).mean()
    return series - rolling_mean


# ---------------------------------------------------------------------------
# Z-score anomaly flagging
# ---------------------------------------------------------------------------

def _flag_anomalies(
    series: pd.Series,
    residuals: pd.Series,
    threshold: float,
) -> List[Dict]:
    """
    Compute Z-scores on residuals, flag points where |Z| > threshold.
    Uses original series values for output (not capped values).
    """
    mean_r = residuals.mean()
    std_r = residuals.std()

    if std_r == 0:
        return []

    z_scores = (residuals - mean_r) / std_r
    anomalies = []

    for idx in series.index:
        if idx not in z_scores.index:
            continue
        z = float(z_scores[idx])
        if abs(z) > threshold:
            anomalies.append({
                "period": str(idx),
                "actual": round(float(series[idx]), 2),
                "expected": round(float(mean_r + series[idx] - residuals[idx]), 2),
                "residual": round(float(residuals[idx]), 2),
                "z_score": round(z, 2),
                "direction": "spike" if z > 0 else "drop",
            })

    return sorted(anomalies, key=lambda x: abs(x["z_score"]), reverse=True)


# ---------------------------------------------------------------------------
# Method auto-selection
# ---------------------------------------------------------------------------

def _auto_select_method(analysis: Dict) -> str:
    """Pick the best method from analysis results (excludes the 'auto' option)."""
    for opt in analysis["method_options"]:
        if opt["method"] != "auto":
            return opt["method"]
    return "rolling_zscore"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_anomalies(
    series: pd.Series,
    method: str = "auto",
    seasonal_periods: Optional[List[int]] = None,
    threshold: Optional[float] = None,
    rolling_window: int = 12,
) -> Dict:
    """
    Run anomaly detection on a time series.

    Parameters
    ----------
    series : pd.Series
        Numeric time series indexed by period labels.
    method : str
        "stl", "mstl", "rolling_zscore", or "auto".
    seasonal_periods : list of int, optional
        Override detected seasonal periods. Required for STL/MSTL if
        auto-detection is unreliable.
    threshold : float, optional
        Z-score threshold for flagging anomalies. Auto-selected if None.
    rolling_window : int
        Window size for rolling Z-score. Default 12.

    Returns
    -------
    dict with keys:
        method_used         : str
        method_reason       : str
        threshold_used      : float
        threshold_reason    : str
        anomalies           : list of dicts (sorted by |z_score| desc)
        anomaly_count       : int
        total_periods       : int
        capped_outliers     : list of dicts (points capped before model fitting)
        warnings            : list of str
        series_stats        : dict (mean, std, min, max)
        all_z_scores        : list of dicts (period, z_score for every point — for charting)
    """
    # --- Pre-flight via analyser --------------------------------------------
    analysis = analyse_series(series, periods_hint=seasonal_periods)
    if not analysis["can_run"]:
        return {"error": analysis["error"]}

    run_warnings = analysis["warnings"][:]
    detected_periods = analysis["characteristics"]["detected_seasonal_periods"]

    # --- Resolve method -----------------------------------------------------
    if method == "auto":
        method = _auto_select_method(analysis)
        method_reason = f"auto-selected based on data characteristics"
    else:
        method_reason = "user-selected"

    # Validate selected method is actually viable
    if method == "mstl" and len(detected_periods) < 2:
        run_warnings.append(
            "MSTL requested but fewer than 2 seasonal periods detected. "
            "Falling back to STL."
        )
        method = "stl" if detected_periods else "rolling_zscore"

    if method == "stl" and not detected_periods:
        run_warnings.append(
            "STL requested but no seasonal period detected. "
            "Falling back to rolling Z-score."
        )
        method = "rolling_zscore"

    # --- IQR cap for model fitting ------------------------------------------
    series_capped, capped_points = _iqr_cap(series)
    if capped_points:
        run_warnings.append(
            f"{len(capped_points)} extreme value(s) were capped before model fitting "
            f"to prevent distortion. Original values used for anomaly scoring."
        )

    # --- Compute residuals --------------------------------------------------
    try:
        if method == "stl":
            period = detected_periods[0]
            residuals = _residuals_stl(series_capped, period)
            method_label = f"STL + Z-score (seasonal period={period})"

        elif method == "mstl":
            residuals = _residuals_mstl(series_capped, detected_periods)
            method_label = f"MSTL + Z-score (periods={detected_periods})"

        else:  # rolling_zscore
            window = min(rolling_window, len(series) // 3)
            residuals = _residuals_rolling(series, window)
            method_label = f"Rolling Z-score (window={window})"

    except Exception as e:
        return {"error": f"Decomposition failed: {e}. Try a different method."}

    # --- Threshold ----------------------------------------------------------
    if threshold is None:
        threshold, threshold_reason = suggest_threshold(residuals, series)
    else:
        threshold_reason = "user-specified"

    # --- Flag anomalies -----------------------------------------------------
    anomalies = _flag_anomalies(series, residuals, threshold)

    # --- All Z-scores (for charting) ----------------------------------------
    mean_r = residuals.mean()
    std_r = residuals.std()
    all_z = []
    if std_r > 0:
        for idx in series.index:
            if idx in residuals.index:
                z = (float(residuals[idx]) - mean_r) / std_r
                all_z.append({"period": str(idx), "z_score": round(z, 2)})

    return {
        "method_used": method_label,
        "method_reason": method_reason,
        "threshold_used": threshold,
        "threshold_reason": threshold_reason,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "total_periods": len(series),
        "capped_outliers": capped_points,
        "warnings": run_warnings,
        "series_stats": {
            "mean": round(float(series.mean()), 2),
            "std": round(float(series.std()), 2),
            "min": round(float(series.min()), 2),
            "max": round(float(series.max()), 2),
        },
        "all_z_scores": all_z,
    }
