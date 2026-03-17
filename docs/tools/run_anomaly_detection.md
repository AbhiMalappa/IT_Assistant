# Tool: run_anomaly_detection

## Purpose

Runs anomaly detection on a time series using the method chosen by the user. Returns flagged anomalous periods with Z-scores, direction (spike/drop), expected vs actual values, and data for charting.

Always call `analyse_for_anomalies` first and present method options to the user before calling this tool.

---

## When Claude Picks This Tool

After the user responds to the method options presented by `analyse_for_anomalies`. The user will have replied with a letter (A, B, C), "auto", or "go with recommendation".

---

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `series_data` | array of objects | Yes | Same data passed to `analyse_for_anomalies` |
| `period_column` | string | Yes | Column name for the time period |
| `value_column` | string | Yes | Column name for the numeric value |
| `method` | string (enum) | Yes | `"stl"`, `"mstl"`, `"rolling_zscore"`, or `"auto"` |
| `threshold` | number | No | Z-score threshold. Auto-selected if not provided. |
| `seasonal_periods` | array of integers | No | Override detected seasonal periods |

---

## Methods

### STL + Z-score
Decomposes the series into trend + seasonal + residual using Seasonal-Trend decomposition (Loess). Runs Z-score on residuals. Handles one seasonal period.

**Requires:** At least one detected seasonal period and `n ≥ 2 × period`.

### MSTL + Z-score
Same as STL but handles multiple seasonal periods simultaneously (e.g. daily + weekly for hourly data).

**Requires:** 2+ detected seasonal periods and `n ≥ 2 × max(period)`.

### Rolling Z-score
Computes deviation from a centered rolling mean. No trend or seasonality removal. Simpler but less accurate when trend or seasonality is present.

**Always available** when `n ≥ 8`.

### Auto
Selects the most capable viable method based on detected data characteristics. Falls back gracefully: MSTL → STL → Rolling Z-score.

---

## Pre-processing: IQR Outlier Capping

Before fitting the decomposition model, extreme outliers are capped using IQR fences:

```
upper_fence = Q3 + 3.0 × IQR
lower_fence = Q1 - 3.0 × IQR
Values outside fences → capped to fence value
```

**Important:** Capping applies only to model fitting — original values are used for anomaly scoring. Capped points are reported in the output so the user is aware. This prevents one massive spike from distorting the baseline for all other periods.

---

## Threshold Auto-Selection

If `threshold` is not provided, it is selected based on the Coefficient of Variation (CV) of residuals:

| CV (noise level) | Threshold | Label |
|---|---|---|
| CV ≤ 0.20 | 3.0 | Low noise |
| CV ≤ 0.50 | 4.0 | Moderate noise |
| CV ≤ 1.00 | 6.0 | High noise |
| CV > 1.00 | 9.0 | Very high noise |

A point is flagged as anomalous if `|Z-score| > threshold`.

---

## Output

```json
{
  "method_used": "STL + Z-score (seasonal period=12)",
  "method_reason": "user-selected",
  "threshold_used": 3.0,
  "threshold_reason": "threshold 3.0 selected for low noise (CV of residuals = 0.18)",
  "anomaly_count": 2,
  "total_periods": 24,
  "anomalies": [
    {
      "period": "2025-03",
      "actual": 87,
      "expected": 42,
      "residual": 45,
      "z_score": 3.8,
      "direction": "spike"
    },
    {
      "period": "2024-11",
      "actual": 12,
      "expected": 40,
      "residual": -28,
      "z_score": -3.1,
      "direction": "drop"
    }
  ],
  "capped_outliers": [],
  "warnings": [],
  "series_stats": {
    "mean": 41.5,
    "std": 9.2,
    "min": 12,
    "max": 87
  },
  "all_z_scores": [
    {"period": "2024-01", "z_score": 0.3},
    {"period": "2024-02", "z_score": -0.8}
  ]
}
```

`all_z_scores` contains Z-scores for every period — used to build the chart.

---

## After Running: Chart

After calling `run_anomaly_detection`, Claude calls `plot_chart` with:
```json
{
  "data": <original series_data>,
  "chart_type": "anomaly",
  "x_column": <period_column>,
  "y_column": <value_column>,
  "title": "Anomaly Detection — ...",
  "anomaly_data": <anomalies list with period→x_column, actual→y_column>
}
```

This produces a solid blue line for all actual values with red X markers at anomalous periods.

---

## Module Structure

```
anomaly_detection/               ← standalone internal package, no project knowledge
├── __init__.py
├── analyser.py                  ← pre-flight checks, granularity/trend/seasonality detection
├── threshold.py                 ← auto-suggest Z-score threshold (3–9) based on CV
├── detector.py                  ← IQR capping, STL/MSTL/rolling Z-score, anomaly flagging
└── tool.py                      ← thin wrappers: analyse_for_anomalies + run_anomaly_detection
```

`analyser.py`, `threshold.py`, and `detector.py` have zero knowledge of incidents or Slack. They accept any numeric pandas Series. The module is reusable in other projects.

---

## Known Limitations

- **Structural breaks:** A permanent shift in the mean (e.g. after a system migration) will cause STL to flag the transition periods as anomalies before normalising. Not handled in v1.
- **Very short series:** With fewer than 2 full seasonal cycles, STL/MSTL fall back to rolling Z-score.
- **Sparse data:** High zero-inflation reduces Z-score reliability. A warning is shown but detection still runs.

---

## Related Tools

| Tool | Use when |
|---|---|
| `analyse_for_anomalies` | Always call before this — presents method options to user |
| `plot_chart` | Always call after this — visualises anomalies inline in Slack |
| `sql_query` | Call before `analyse_for_anomalies` to get the time series data |
