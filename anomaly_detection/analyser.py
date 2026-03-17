"""
Series Analyser — inspects a time series and recommends an anomaly detection method.

Zero knowledge of incidents, Slack, or this project.
Accepts any numeric time series as a pandas Series.

Responsibilities:
- Pre-flight validation (hard stops + warnings)
- Granularity inference from index labels
- Trend detection (linear regression slope)
- Seasonality detection (ACF peaks at known candidate lags)
- Method option generation with ranked recommendations
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import acf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_POINTS = 8
SPARSITY_THRESHOLD = 0.40   # 40% zeros triggers a warning

# Candidate seasonal periods per granularity
_GRANULARITY_PERIODS: Dict[str, List[int]] = {
    "monthly": [12],
    "weekly":  [52],
    "daily":   [7],
    "hourly":  [24, 168],
    "unknown": [4, 7, 12, 24, 52],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_granularity(series: pd.Series) -> str:
    """Infer time granularity from the series index labels."""
    if len(series) < 2:
        return "unknown"
    label = str(series.index[0])
    if len(label) == 7 and label[4] == "-":
        return "monthly"           # YYYY-MM
    if "W" in label.upper():
        return "weekly"            # YYYY-WNN
    if len(label) == 10 and label[4] == "-":
        return "daily"             # YYYY-MM-DD
    if len(label) > 10:
        return "hourly"            # YYYY-MM-DD HH:MM or similar
    return "unknown"


def _detect_trend(series: pd.Series) -> Tuple[bool, float]:
    """
    Detect significant trend using linear regression.
    Returns (has_trend, slope_per_period).
    Trend is considered significant if slope > 2% of mean per period.
    """
    x = np.arange(len(series))
    slope = float(np.polyfit(x, series.values.astype(float), 1)[0])
    mean = series.mean()
    relative_slope = abs(slope) / mean if mean != 0 else 0.0
    return relative_slope > 0.02, round(slope, 4)


def _detect_seasonality(series: pd.Series, granularity: str) -> List[int]:
    """
    Detect seasonal periods using ACF peaks at candidate lags.
    Returns list of detected periods sorted ascending.
    """
    n = len(series)
    candidates = _GRANULARITY_PERIODS.get(granularity, _GRANULARITY_PERIODS["unknown"])
    candidates = [p for p in candidates if p < n // 2]
    if not candidates:
        return []

    max_lag = max(candidates)
    try:
        acf_vals = acf(series, nlags=max_lag, fft=True, missing="drop")
    except Exception:
        return []

    conf = 1.96 / np.sqrt(n)   # 95% confidence threshold
    detected = []
    for period in candidates:
        if period < len(acf_vals) and abs(acf_vals[period]) > max(conf, 0.20):
            detected.append(period)

    return sorted(detected)


def _check_sparsity(series: pd.Series) -> float:
    """Return fraction of zero values in the series."""
    return float((series == 0).sum() / len(series))


def _build_method_options(
    n: int,
    detected_periods: List[int],
) -> Tuple[List[Dict], str]:
    """
    Build ordered list of available method options with descriptions.
    Most capable applicable method is listed first and recommended.

    Returns (options_list, recommended_key).
    """
    options = []

    # MSTL — requires 2+ seasonal periods and enough data for largest
    if len(detected_periods) >= 2 and n >= 2 * max(detected_periods):
        options.append({
            "method": "mstl",
            "label": "MSTL + Z-score",
            "description": (
                f"Removes trend and multiple seasonal patterns "
                f"(periods={detected_periods}). Best for complex seasonality."
            ),
        })

    # STL — requires 1+ seasonal period and enough data
    if detected_periods and n >= 2 * detected_periods[0]:
        options.append({
            "method": "stl",
            "label": "STL + Z-score",
            "description": (
                f"Removes trend and one seasonal pattern "
                f"(period={detected_periods[0]}). Good for single seasonality."
            ),
        })

    # Rolling Z-score — always available if n >= MIN_POINTS
    options.append({
        "method": "rolling_zscore",
        "label": "Rolling Z-score",
        "description": (
            "Sliding window baseline. No trend or seasonality removal. "
            "Simple and interpretable."
        ),
    })

    # Auto — always last
    options.append({
        "method": "auto",
        "label": "Auto — let the system decide",
        "description": "Automatically selects the best method based on your data.",
    })

    # Assign letter keys A, B, C...
    for i, opt in enumerate(options):
        opt["key"] = chr(65 + i)

    # Recommended = first option (most capable, excluding auto)
    recommended_key = options[0]["key"]

    return options, recommended_key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_series(
    series: pd.Series,
    periods_hint: Optional[List[int]] = None,
) -> Dict:
    """
    Analyse a time series and return data characteristics,
    available method options, recommended method, and any warnings.

    Parameters
    ----------
    series : pd.Series
        Numeric time series indexed by period labels.
    periods_hint : list of int, optional
        Override automatic seasonality detection with known periods.

    Returns
    -------
    dict with keys:
        can_run       : bool — False means a hard stop was hit
        error         : str  — only present if can_run is False
        characteristics : dict — data shape, trend, seasonality, sparsity
        warnings      : list of str
        method_options : list of dicts — available methods with keys A, B, C...
        recommended_method : str — key of recommended option (e.g. "A")
    """
    warnings_list = []

    # --- Hard stops ---------------------------------------------------------
    n = len(series)

    if n < MIN_POINTS:
        return {
            "can_run": False,
            "error": (
                f"Not enough data — need at least {MIN_POINTS} periods. "
                f"Got {n}."
            ),
        }

    if series.sum() == 0:
        return {
            "can_run": False,
            "error": "All values are zero — nothing to analyse.",
        }

    if series.std() == 0:
        return {
            "can_run": False,
            "error": "All values are identical — no variation to detect anomalies in.",
        }

    # --- Warnings -----------------------------------------------------------
    sparsity = _check_sparsity(series)
    if sparsity > SPARSITY_THRESHOLD:
        warnings_list.append(
            f"Data is sparse ({sparsity:.0%} zeros) — results may be less reliable. "
            "Consider broadening your filters or using a wider time window."
        )

    # --- Characteristics ----------------------------------------------------
    granularity = _detect_granularity(series)
    has_trend, slope = _detect_trend(series)
    detected_periods = periods_hint or _detect_seasonality(series, granularity)

    # --- Method options -----------------------------------------------------
    options, recommended_key = _build_method_options(n, detected_periods)

    return {
        "can_run": True,
        "characteristics": {
            "n_periods": n,
            "granularity": granularity,
            "has_trend": has_trend,
            "trend_slope_per_period": slope,
            "detected_seasonal_periods": detected_periods,
            "sparsity": round(sparsity, 3),
        },
        "warnings": warnings_list,
        "method_options": options,
        "recommended_method": recommended_key,
    }
