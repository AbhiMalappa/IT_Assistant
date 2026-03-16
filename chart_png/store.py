"""
Chart storage — saves Plotly figures as PNG and HTML to a temp directory.

Files are written to /tmp/charts/ which is ephemeral (wiped on container restart).
That is intentional — charts are single-use per query, not long-lived.
PNG  → uploaded inline to Slack via files_upload_v2
HTML → served via FastAPI GET /charts/{chart_id} for interactive viewing
"""

import uuid
from pathlib import Path
from typing import Tuple

import plotly.graph_objects as go

CHART_DIR = Path("/tmp/charts")


def save(fig: go.Figure, scale: int = 2) -> Tuple[str, str]:
    """
    Save a Plotly figure as both PNG and HTML.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
    scale : int
        Pixel density multiplier for PNG. Default 2 (retina quality).

    Returns
    -------
    (png_path, chart_id)
        png_path  — absolute path to the PNG file
        chart_id  — UUID string; HTML served at /charts/{chart_id}
    """
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    chart_id = str(uuid.uuid4())

    png_path = CHART_DIR / f"{chart_id}.png"
    html_path = CHART_DIR / f"{chart_id}.html"

    fig.write_image(str(png_path), scale=scale)
    html_path.write_text(
        fig.to_html(include_plotlyjs="cdn", full_html=True),
        encoding="utf-8",
    )

    return str(png_path), chart_id
