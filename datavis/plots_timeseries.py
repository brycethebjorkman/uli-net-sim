"""
Score timeseries plots.

Auto-detects available score columns and builds a stacked subplot
for each one.  Works with KF NIS, MLAT, CUSUM, or any future detector.
"""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .scenario_data import ScenarioData


# Colors cycled per subplot
_COLORS = ['steelblue', 'green', 'crimson', 'purple', 'darkorange', 'teal']


def build_score_timeseries(sd: ScenarioData) -> go.Figure | None:
    """Build stacked timeseries of all available detection scores.

    One subplot per detected score column, plotted over spoofed TX events
    (or GCS events if the score lives there).

    Returns None if no scores are available.
    """
    if not sd.scores:
        return None

    n_rows = len(sd.scores)
    subtitles = [sc.label for sc in sd.scores]

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        subplot_titles=subtitles,
        vertical_spacing=0.08 if n_rows > 1 else 0.0,
    )

    for i, sc in enumerate(sd.scores, start=1):
        color = _COLORS[(i - 1) % len(_COLORS)]

        # Pick the source dataframe for this score
        if sc.event_type == 'GCS' and not sd.gcs.empty:
            source = sd.gcs
        else:
            source = sd.spoof_tx

        if sc.column not in source.columns:
            continue

        valid = source.dropna(subset=[sc.column])
        if valid.empty:
            continue

        fig.add_trace(go.Scatter(
            x=valid['time'], y=valid[sc.column],
            mode='markers+lines',
            marker=dict(size=4, color=color),
            line=dict(width=1, color=color),
            name=sc.label,
            hovertext=[
                f"t={r['time']:.2f}s, {sc.label}={r[sc.column]:.3f}"
                for _, r in valid.iterrows()
            ],
            hoverinfo='text+x',
        ), row=i, col=1)

    fig.update_layout(
        title=f'Detector Scores Over Time: {sd.scenario_id}',
        height=250 * n_rows + 100,
        width=900,
        showlegend=True,
    )
    fig.update_xaxes(title_text='Time (s)', row=n_rows, col=1)
    return fig
