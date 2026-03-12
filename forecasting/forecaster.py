"""
Exponential Smoothing Forecaster

Uses statsmodels ExponentialSmoothing to fit multiple model configurations,
select the best by MSE on a held-out test set, and forecast forward.

Supported configurations (auto-selected based on available data):
  - Simple Exponential Smoothing (SES): no trend, no seasonality
  - Holt Linear Trend: additive or multiplicative trend, no seasonality
  - Holt-Winters: trend + seasonality (requires >= 2 full seasonal cycles)

Accuracy metrics:
  - MSE  (Mean Squared Error) — primary selection criterion
  - R²   (Coefficient of Determination) — goodness of fit
"""

import warnings
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")  # suppress statsmodels convergence warnings


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModelResult:
    """Holds fit results for a single model configuration."""
    label: str
    trend: Optional[str]
    damped_trend: bool
    seasonal: Optional[str]
    seasonal_periods: Optional[int]
    mse: float
    r2: float
    fitted_model: object = field(repr=False)


@dataclass
class ForecastResult:
    """Final output returned to the caller."""
    best_model_label: str
    best_model_params: dict
    mse: float
    r2: float
    forecast_periods: int
    forecast: List[Tuple[str, float]]       # (period_label, value)
    all_models_ranked: List[dict]           # every config tried, ranked by MSE


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _mse(actual: List[float], predicted: List[float]) -> float:
    n = len(actual)
    return sum((a - p) ** 2 for a, p in zip(actual, predicted)) / n


def _r2(actual: List[float], predicted: List[float]) -> float:
    mean_actual = sum(actual) / len(actual)
    ss_tot = sum((a - mean_actual) ** 2 for a in actual)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1 - (ss_res / ss_tot)


# ---------------------------------------------------------------------------
# Model configuration grid
# ---------------------------------------------------------------------------

def _build_configs(n_obs: int, seasonal_periods: int) -> List[dict]:
    """
    Return the list of ES configurations to try, based on available data.

    Holt-Winters (seasonal) requires at least 2 full seasonal cycles.
    Multiplicative trend/seasonal requires all-positive values (checked later).
    """
    has_seasonality = n_obs >= 2 * seasonal_periods

    configs = [
        # Simple Exponential Smoothing
        {"trend": None, "damped_trend": False, "seasonal": None,
         "seasonal_periods": None, "label": "SES (no trend, no seasonal)"},

        # Holt — additive trend
        {"trend": "add", "damped_trend": False, "seasonal": None,
         "seasonal_periods": None, "label": "Holt (additive trend)"},

        # Holt — additive trend, damped
        {"trend": "add", "damped_trend": True, "seasonal": None,
         "seasonal_periods": None, "label": "Holt (additive trend, damped)"},

        # Holt — multiplicative trend
        {"trend": "mul", "damped_trend": False, "seasonal": None,
         "seasonal_periods": None, "label": "Holt (multiplicative trend)"},

        # Holt — multiplicative trend, damped
        {"trend": "mul", "damped_trend": True, "seasonal": None,
         "seasonal_periods": None, "label": "Holt (multiplicative trend, damped)"},
    ]

    if has_seasonality:
        configs += [
            # Holt-Winters — additive trend + additive seasonal
            {"trend": "add", "damped_trend": False, "seasonal": "add",
             "seasonal_periods": seasonal_periods,
             "label": "Holt-Winters (add trend, add seasonal)"},

            # Holt-Winters — additive trend, damped + additive seasonal
            {"trend": "add", "damped_trend": True, "seasonal": "add",
             "seasonal_periods": seasonal_periods,
             "label": "Holt-Winters (add trend damped, add seasonal)"},

            # Holt-Winters — additive trend + multiplicative seasonal
            {"trend": "add", "damped_trend": False, "seasonal": "mul",
             "seasonal_periods": seasonal_periods,
             "label": "Holt-Winters (add trend, mul seasonal)"},

            # Holt-Winters — multiplicative trend + multiplicative seasonal
            {"trend": "mul", "damped_trend": False, "seasonal": "mul",
             "seasonal_periods": seasonal_periods,
             "label": "Holt-Winters (mul trend, mul seasonal)"},
        ]

    return configs


# ---------------------------------------------------------------------------
# Core forecaster
# ---------------------------------------------------------------------------

class ExponentialSmoothingForecaster:
    """
    Fits multiple Exponential Smoothing configurations, selects the best by MSE
    on a held-out test set, re-fits on the full series, and forecasts forward.

    Parameters
    ----------
    seasonal_periods : int
        Number of periods per seasonal cycle.
        12 = monthly data with yearly seasonality (default).

    n_test : int
        Number of periods held out for evaluation.
        Default 3 — matches the default forecast horizon.
    """

    def __init__(self, seasonal_periods: int = 12, n_test: int = 3):
        self.seasonal_periods = seasonal_periods
        self.n_test = n_test
        self._best_config: Optional[dict] = None
        self._full_series: Optional[pd.Series] = None
        self._all_results: List[ModelResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, series: pd.Series) -> "ExponentialSmoothingForecaster":
        """
        Fit all applicable ES configurations on a train split.
        Select the best model by lowest MSE on the test split.

        Parameters
        ----------
        series : pd.Series
            Time series indexed by period labels (e.g., '2025-09').
            Values must be numeric (e.g., incident counts).
        """
        if len(series) < self.n_test + 2:
            raise ValueError(
                f"Series has {len(series)} observations — need at least "
                f"{self.n_test + 2} (n_test={self.n_test} + 2 training points)."
            )

        self._full_series = series.copy()
        train = series.iloc[:-self.n_test]
        test = series.iloc[-self.n_test:]
        actual = list(test.values)

        all_positive = all(v > 0 for v in series.values)
        configs = _build_configs(len(series), self.seasonal_periods)
        self._all_results = []

        for cfg in configs:
            # Multiplicative components require all-positive values
            if (cfg["trend"] == "mul" or cfg["seasonal"] == "mul") and not all_positive:
                continue

            try:
                model = ExponentialSmoothing(
                    train,
                    trend=cfg["trend"],
                    damped_trend=cfg["damped_trend"] if cfg["trend"] else False,
                    seasonal=cfg["seasonal"],
                    seasonal_periods=cfg["seasonal_periods"],
                    initialization_method="estimated",
                )
                fitted = model.fit(optimized=True, remove_bias=False)
                predicted = list(fitted.forecast(self.n_test))

                mse = _mse(actual, predicted)
                r2 = _r2(actual, predicted)

                self._all_results.append(ModelResult(
                    label=cfg["label"],
                    trend=cfg["trend"],
                    damped_trend=cfg["damped_trend"],
                    seasonal=cfg["seasonal"],
                    seasonal_periods=cfg["seasonal_periods"],
                    mse=mse,
                    r2=r2,
                    fitted_model=fitted,
                ))
            except Exception:
                # Skip configs that fail to converge or have numeric issues
                continue

        if not self._all_results:
            raise RuntimeError("All model configurations failed. Check your input data.")

        # Sort by MSE ascending — lowest MSE is best
        self._all_results.sort(key=lambda r: r.mse)
        best = self._all_results[0]

        # Store best config for re-fitting on full series
        self._best_config = {k: v for k, v in {
            "trend": best.trend,
            "damped_trend": best.damped_trend,
            "seasonal": best.seasonal,
            "seasonal_periods": best.seasonal_periods,
        }.items()}

        return self

    def forecast(self, periods: int = 3) -> ForecastResult:
        """
        Re-fit the best model on the full series, then forecast forward.

        Parameters
        ----------
        periods : int
            Number of periods to forecast. Default 3.

        Returns
        -------
        ForecastResult
            Contains best model params, accuracy metrics, forecast values,
            and a ranked comparison of all models tried.
        """
        if self._best_config is None or self._full_series is None:
            raise RuntimeError("Call fit() before forecast().")

        best_label = self._all_results[0].label

        # Re-fit best config on full series
        full_model = ExponentialSmoothing(
            self._full_series,
            trend=self._best_config["trend"],
            damped_trend=self._best_config["damped_trend"] if self._best_config["trend"] else False,
            seasonal=self._best_config["seasonal"],
            seasonal_periods=self._best_config["seasonal_periods"],
            initialization_method="estimated",
        )
        full_fitted = full_model.fit(optimized=True, remove_bias=False)
        raw_forecast = list(full_fitted.forecast(periods))

        # Generate period labels from the series index
        forecast_labels = self._next_period_labels(periods)
        forecast_pairs = [
            (label, round(max(0.0, val), 2))   # clip negative forecasts to 0
            for label, val in zip(forecast_labels, raw_forecast)
        ]

        best_result = self._all_results[0]
        all_models_ranked = [
            {
                "rank": i + 1,
                "label": r.label,
                "mse": round(r.mse, 4),
                "r2": round(r.r2, 4),
            }
            for i, r in enumerate(self._all_results)
        ]

        return ForecastResult(
            best_model_label=best_label,
            best_model_params={
                "trend": self._best_config["trend"],
                "damped_trend": self._best_config["damped_trend"],
                "seasonal": self._best_config["seasonal"],
                "seasonal_periods": self._best_config["seasonal_periods"],
            },
            mse=round(best_result.mse, 4),
            r2=round(best_result.r2, 4),
            forecast_periods=periods,
            forecast=forecast_pairs,
            all_models_ranked=all_models_ranked,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_period_labels(self, periods: int) -> List[str]:
        """
        Infer the next period labels from the series index.
        Supports monthly ('YYYY-MM') and weekly ('YYYY-WNN') index formats.
        Falls back to generic 'Period+N' labels.
        """
        last_label = str(self._full_series.index[-1])

        try:
            # Monthly: YYYY-MM
            last_dt = pd.Period(last_label, freq="M")
            return [str(last_dt + i) for i in range(1, periods + 1)]
        except Exception:
            pass

        try:
            # Weekly: YYYY-WNN
            last_dt = pd.Period(last_label, freq="W")
            return [str(last_dt + i) for i in range(1, periods + 1)]
        except Exception:
            pass

        # Fallback
        return [f"Period+{i}" for i in range(1, periods + 1)]
