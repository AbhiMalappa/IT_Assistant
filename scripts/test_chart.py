"""
Quick test for chart_png module — runs without Slack or Railway.
Tests both PNG generation (kaleido) and HTML generation (no kaleido needed).

Run with:
    python scripts/test_chart.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from chart_png.tool import plot_chart

# --- Test 1: Bar chart ---
print("Test 1: Bar chart...")
result = plot_chart(
    data=[
        {"state": "Closed", "count": 210},
        {"state": "Open", "count": 45},
        {"state": "In Progress", "count": 30},
        {"state": "On hold", "count": 15},
        {"state": "Cancelled", "count": 10},
    ],
    chart_type="bar",
    x_column="state",
    y_column="count",
    title="Incidents by State",
    y_label="Incident Count",
)
print(f"  Result: {result}")

# --- Test 2: Forecast chart ---
print("\nTest 2: Forecast chart...")
result2 = plot_chart(
    data=[
        {"period": "2025-08", "count": 38},
        {"period": "2025-09", "count": 42},
        {"period": "2025-10", "count": 35},
        {"period": "2025-11", "count": 50},
        {"period": "2025-12", "count": 44},
    ],
    chart_type="forecast",
    x_column="period",
    y_column="count",
    title="Monthly Incident Forecast",
    forecast_data=[
        {"period": "2026-01", "forecasted_count": 46},
        {"period": "2026-02", "forecasted_count": 43},
        {"period": "2026-03", "forecasted_count": 45},
    ],
)
print(f"  Result: {result2}")

# --- Summary ---
print("\n--- Summary ---")
for i, r in enumerate([result, result2], 1):
    if "error" in r:
        print(f"Test {i}: FAILED — {r['error']}")
    else:
        print(f"Test {i}: OK")
        print(f"  PNG:  {r['chart_path']}")
        print(f"  HTML: /tmp/charts/{r['chart_id']}.html")
        # Check files exist
        import os
        png_ok = os.path.exists(r["chart_path"])
        html_ok = os.path.exists(f"/tmp/charts/{r['chart_id']}.html")
        print(f"  PNG exists:  {png_ok}")
        print(f"  HTML exists: {html_ok}")
