# Tool: analyse_for_anomalies

## Purpose

Inspects a time series and returns data characteristics, available detection method options, and a recommended method. Always call this **first** before `run_anomaly_detection` — it presents the user with choices so they can confirm or override the method.

---

## When Claude Picks This Tool

Claude calls `analyse_for_anomalies` when the user asks about:
- Anomalies, spikes, or unusual patterns in incident volume
- "Was last month abnormally high?"
- "Are there any outliers in SAP incident counts?"
- "Detect anomalies in network incidents by month"

Claude does **not** call this for:
- Individual incident lookups — use `get_incident_by_number`
- Counts or rankings — use `sql_query`
- Forecasting future values — use `forecast_incidents`

---

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `series_data` | array of objects | Yes | Row dicts from a `sql_query` result |
| `period_column` | string | Yes | Column name for the time period |
| `value_column` | string | Yes | Column name for the numeric value |
| `periods_hint` | array of integers | No | Override auto-detected seasonal periods (e.g. `[12]`) |

---

## Pre-flight Checks

### Hard stops — returns error, detection cannot run

| Condition | Error message |
|---|---|
| Fewer than 8 data points | "Not enough data — need at least 8 periods. Got {n}." |
| All values are zero | "All values are zero — nothing to analyse." |
| All values identical (stddev = 0) | "All values are identical — no variation to detect anomalies in." |

### Warnings — runs but flags to user

| Condition | Warning |
|---|---|
| More than 40% zeros (sparse data) | "Data is sparse ({x}% zeros) — results may be less reliable." |

---

## Method Options

The tool evaluates which methods are viable for the data and returns them in order from most to least capable:

| Method key | Method | When available |
|---|---|---|
| A (or first) | MSTL + Z-score | 2+ seasonal periods detected AND enough data for largest period |
| B (or first if no MSTL) | STL + Z-score | 1 seasonal period detected AND n ≥ 2 × period |
| Always | Rolling Z-score | Always available if n ≥ 8 |
| Always last | Auto | Selects best method automatically |

The recommended method is always the first listed (most capable viable option). "Auto" and "go with recommendation" both resolve to the same choice.

---

## How Seasonality Is Detected

Uses autocorrelation (ACF) at known candidate lags per granularity:

| Granularity | Candidate periods checked |
|---|---|
| Monthly (YYYY-MM) | 12 |
| Weekly (YYYY-WNN) | 52 |
| Daily (YYYY-MM-DD) | 7 |
| Hourly | 24, 168 |
| Unknown | 4, 7, 12, 24, 52 |

A period is detected if ACF at that lag exceeds `max(1.96/√n, 0.20)`.

---

## Output

```json
{
  "can_run": true,
  "characteristics": {
    "n_periods": 24,
    "granularity": "monthly",
    "has_trend": true,
    "trend_slope_per_period": 1.2,
    "detected_seasonal_periods": [12],
    "sparsity": 0.04
  },
  "warnings": [],
  "method_options": [
    {
      "key": "A",
      "method": "stl",
      "label": "STL + Z-score",
      "description": "Removes trend and one seasonal pattern (period=12). Good for single seasonality."
    },
    {
      "key": "B",
      "method": "rolling_zscore",
      "label": "Rolling Z-score",
      "description": "Sliding window baseline. No trend or seasonality removal. Simple and interpretable."
    },
    {
      "key": "C",
      "method": "auto",
      "label": "Auto — let the system decide",
      "description": "Automatically selects the best method based on your data."
    }
  ],
  "recommended_method": "A"
}
```

If `can_run` is `false`:
```json
{
  "can_run": false,
  "error": "Not enough data — need at least 8 periods. Got 5."
}
```

---

## Two-Step Flow

```
User: "detect anomalies in monthly incident volume"
        ↓
Claude calls sql_query to get time series data
        ↓
Claude calls analyse_for_anomalies
        ↓
Claude presents options to user:
  "Here's what I found in your data:
    • 24 monthly data points
    • Seasonal pattern detected: yearly (12 months)
    • Mild upward trend

  Which method would you like?
    A. STL + Z-score ← recommended
    B. Rolling Z-score
    C. Auto — I'll decide

  Reply with A, B, C, 'auto', or 'go with recommendation'."
        ↓
User replies
        ↓
Claude calls run_anomaly_detection with chosen method
```

---

## Related Tools

| Tool | Use when |
|---|---|
| `run_anomaly_detection` | Always call after this — runs the chosen method |
| `sql_query` | Call before this to get the time series data |
| `forecast_incidents` | Forward-looking volume questions (not anomaly detection) |
