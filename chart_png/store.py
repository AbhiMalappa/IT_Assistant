"""
Chart storage — saves Plotly figures as PNG files to a temp directory.

Files are written to /tmp/charts/ which is ephemeral (wiped on container restart).
That is intentional — charts are single-use per query, not long-lived.
"""

import uuid
from pathlib import Path

import plotly.graph_objects as go

CHART_DIR = Path("/tmp/charts")


def save_png(fig: go.Figure, scale: int = 2) -> str:
    """
    Save a Plotly figure as a PNG file.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
    scale : int
        Pixel density multiplier. Default 2 (retina quality).

    Returns
    -------
    str — absolute path to the saved PNG file.
    """
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / f"{uuid.uuid4()}.png"
    fig.write_image(str(path), scale=scale)
    return str(path)
