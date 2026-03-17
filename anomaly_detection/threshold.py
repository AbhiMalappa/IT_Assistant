"""
Threshold suggester — auto-selects Z-score threshold based on residual noise level.

Range: 3.0 (low noise, tight) to 9.0 (very noisy, loose).
Uses Coefficient of Variation (CV) of residuals as the noise measure.
"""

from typing import Tuple

import pandas as pd

# CV bands → threshold
_BANDS = [
    (0.20, 3.0, "low noise"),
    (0.50, 4.0, "moderate noise"),
    (1.00, 6.0, "high noise"),
    (float("inf"), 9.0, "very high noise"),
]


def suggest_threshold(residuals: pd.Series, series: pd.Series) -> Tuple[float, str]:
    """
    Suggest a Z-score threshold based on the noise level of the residuals.

    Parameters
    ----------
    residuals : pd.Series
        Residuals from decomposition (or rolling deviation for rolling Z-score).
    series : pd.Series
        Original series — used to compute the mean for CV.

    Returns
    -------
    (threshold, explanation)
        threshold   : float in range [3.0, 9.0]
        explanation : human-readable reason for the chosen threshold
    """
    mean = series.mean()
    cv = residuals.std() / mean if mean != 0 else 1.0

    for cv_limit, threshold, label in _BANDS:
        if cv <= cv_limit:
            explanation = (
                f"threshold {threshold} selected for {label} "
                f"(CV of residuals = {cv:.2f})"
            )
            return threshold, explanation

    # Fallback — should never reach here
    return 9.0, f"maximum threshold applied (CV = {cv:.2f})"
