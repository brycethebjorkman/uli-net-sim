"""
3D trajectory and spoofed-beacon visualizations.

Provides an animated 3D replay and a static overview plot.
Both auto-adapt to whatever score column is available.
"""

import numpy as np
import plotly.graph_objects as go

from .scenario_data import ScenarioData, interp_pos


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

BENIGN_COLORS = [
    '#1f77b4', '#2ca02c', '#9467bd', '#8c564b',
    '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]
SPOOFER_ACTUAL_COLOR = '#ff7f0e'


def _host_color(hid: int, sd: ScenarioData) -> str:
    if hid in sd.spoofer_ids:
        return SPOOFER_ACTUAL_COLOR
    idx = sd.benign_ids.index(hid) if hid in sd.benign_ids else 0
    return BENIGN_COLORS[idx % len(BENIGN_COLORS)]


# ---------------------------------------------------------------------------
# Hover text
# ---------------------------------------------------------------------------

def _score_hover(row, sd: ScenarioData) -> str:
    """Build hover text for a spoofed beacon, listing all available scores."""
    parts = [f"t={row['time']:.2f}s, SN={int(row['serial_number'])}"]
    parts.append(f"actual=({row['pos_x']:.0f}, {row['pos_y']:.0f}, {row['pos_z']:.0f})")
    parts.append(f"claimed=({row['rid_pos_x']:.0f}, {row['rid_pos_y']:.0f}, {row['rid_pos_z']:.0f})")
    dist = np.sqrt((row['pos_x'] - row['rid_pos_x'])**2 +
                   (row['pos_y'] - row['rid_pos_y'])**2 +
                   (row['pos_z'] - row['rid_pos_z'])**2)
    parts.append(f"offset={dist:.1f}m")
    for sc in sd.scores:
        val = row.get(sc.column, np.nan)
        if not np.isnan(val):
            parts.append(f"{sc.label}={val:.3f}")
    return '<br>'.join(parts)


# ---------------------------------------------------------------------------
# Score values for colorscale
# ---------------------------------------------------------------------------

def _get_score_vals(spoof_tx, sd: ScenarioData):
    """Return (values_array, colorbar_title, cmax) for the primary score."""
    if sd.primary_score is None or sd.primary_score.column not in spoof_tx.columns:
        return np.zeros(len(spoof_tx)), 'Score', 1.0
    vals = spoof_tx[sd.primary_score.column].fillna(0).values
    cmax = max(vals.max(), 1.0) if len(vals) > 0 else 1.0
    return vals, sd.primary_score.label, cmax


# ---------------------------------------------------------------------------
# Animated 3D replay
# ---------------------------------------------------------------------------

def build_animation(sd: ScenarioData, frame_dt: float = 0.5) -> go.Figure:
    """Build animated 3D replay of trajectories and spoofed beacons.

    Args:
        sd: Loaded scenario data.
        frame_dt: Time step between animation frames (seconds).

    Returns:
        Plotly Figure with animation frames and play/pause controls.
    """
    frame_times = np.arange(sd.t_min, sd.t_max + frame_dt, frame_dt)
    N = len(sd.host_ids)

    all_score_vals, score_label, color_max = _get_score_vals(sd.spoof_tx, sd)

    def empty(**kwargs):
        return go.Scatter3d(x=[], y=[], z=[], **kwargs)

    # -- initial traces (fixed count per frame) --
    traces = []
    # 0..N-1: trail lines
    for hid in sd.host_ids:
        c = _host_color(hid, sd)
        label = f'Host {hid}' + (' (spoofer)' if hid in sd.spoofer_ids else '')
        traces.append(empty(mode='lines', line=dict(color=c, width=3),
                            name=label, showlegend=True, hoverinfo='skip'))
    # N..2N-1: current-position markers
    for hid in sd.host_ids:
        c = _host_color(hid, sd)
        traces.append(empty(mode='markers+text',
                            marker=dict(size=6, color=c, symbol='circle'),
                            textposition='top center',
                            textfont=dict(size=9, color=c),
                            showlegend=False, hoverinfo='text'))
    # 2N: spoofed claimed markers
    traces.append(go.Scatter3d(
        x=[], y=[], z=[], mode='markers',
        marker=dict(size=4, color=[], colorscale='RdYlGn_r',
                    cmin=0, cmax=color_max,
                    colorbar=dict(title=score_label, x=1.0),
                    symbol='diamond', opacity=0.8),
        name='Spoofed RID', showlegend=True, hoverinfo='text',
    ))
    # 2N+1: actual-to-claimed lines
    traces.append(empty(mode='lines',
                        line=dict(color='rgba(214,39,40,0.3)', width=1, dash='dot'),
                        name='Actual-to-claimed', showlegend=True, hoverinfo='skip'))

    # -- frame builder --
    spoof_tx = sd.spoof_tx
    score_col = sd.primary_score.column if sd.primary_score and sd.primary_score.column in spoof_tx.columns else None

    def frame_data(t):
        data = []
        # trails
        for hid in sd.host_ids:
            ht = sd.host_tx[hid]
            trail = ht[ht['time'] <= t]
            if len(trail) > 1:
                data.append(dict(x=trail['pos_x'].tolist(), y=trail['pos_y'].tolist(),
                                 z=trail['pos_z'].tolist()))
            else:
                data.append(dict(x=[], y=[], z=[]))
        # markers
        for hid in sd.host_ids:
            pos = interp_pos(sd.host_tx[hid], t)
            if pos:
                data.append(dict(x=[pos[0]], y=[pos[1]], z=[pos[2]],
                                 text=[f'{hid}'],
                                 hovertext=[f'Host {hid}<br>({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})']))
            else:
                data.append(dict(x=[], y=[], z=[], text=[], hovertext=[]))
        # spoofed
        vis = spoof_tx[spoof_tx['time'] <= t]
        if len(vis) > 0:
            sv = vis[score_col].fillna(0).tolist() if score_col else [0] * len(vis)
            data.append(dict(
                x=vis['rid_pos_x'].tolist(), y=vis['rid_pos_y'].tolist(),
                z=vis['rid_pos_z'].tolist(),
                marker=dict(size=4, color=sv, colorscale='RdYlGn_r',
                            cmin=0, cmax=color_max, symbol='diamond', opacity=0.8),
                hovertext=[_score_hover(row, sd) for _, row in vis.iterrows()],
            ))
        else:
            data.append(dict(x=[], y=[], z=[], hovertext=[]))
        # lines
        if len(vis) > 0:
            lx, ly, lz = [], [], []
            for _, row in vis.iterrows():
                lx.extend([row['pos_x'], row['rid_pos_x'], None])
                ly.extend([row['pos_y'], row['rid_pos_y'], None])
                lz.extend([row['pos_z'], row['rid_pos_z'], None])
            data.append(dict(x=lx, y=ly, z=lz))
        else:
            data.append(dict(x=[], y=[], z=[]))
        return data

    # populate first frame
    first = frame_data(frame_times[0])
    for trace, d in zip(traces, first):
        trace.update(d)

    # build all frames
    frames = []
    for ft in frame_times:
        fd = frame_data(ft)
        frames.append(go.Frame(
            data=[go.Scatter3d(**d) for d in fd],
            name=f'{ft:.1f}',
        ))

    # assemble figure
    fig = go.Figure(data=traces, frames=frames)

    slider_steps = [
        dict(args=[[f'{ft:.1f}'], dict(frame=dict(duration=0, redraw=True), mode='immediate')],
             label=f'{ft:.0f}s', method='animate')
        for ft in frame_times[::max(1, len(frame_times) // 50)]
    ]

    fig.update_layout(
        title=dict(text=f'Scenario: {sd.scenario_id}', font=dict(size=14)),
        scene=dict(xaxis_title='X (m)', yaxis_title='Y (m)', zaxis_title='Z (m)',
                   aspectmode='data'),
        width=900, height=700,
        updatemenus=[dict(
            type='buttons', showactive=False, x=0.05, y=0.02,
            buttons=[
                dict(label='Play', method='animate',
                     args=[None, dict(frame=dict(duration=100, redraw=True),
                                      fromcurrent=True, mode='immediate')]),
                dict(label='Pause', method='animate',
                     args=[[None], dict(frame=dict(duration=0, redraw=False),
                                        mode='immediate')]),
            ],
        )],
        sliders=[dict(active=0, steps=slider_steps, x=0.05, len=0.9,
                      currentvalue=dict(prefix='Time: ', suffix='s'))],
    )
    return fig


# ---------------------------------------------------------------------------
# Static 3D overview
# ---------------------------------------------------------------------------

def build_static_overview(sd: ScenarioData) -> go.Figure:
    """Build static 3D plot of full trajectories with spoofed beacons colored by score."""
    fig = go.Figure()

    # Trajectory lines
    for hid in sd.host_ids:
        ht = sd.host_tx[hid]
        c = _host_color(hid, sd)
        label = f'Host {hid}' + (' (spoofer)' if hid in sd.spoofer_ids else '')
        fig.add_trace(go.Scatter3d(
            x=ht['pos_x'], y=ht['pos_y'], z=ht['pos_z'],
            mode='lines', line=dict(color=c, width=3), name=label,
        ))

    # Spoofed beacons
    spoof_tx = sd.spoof_tx
    if len(spoof_tx) > 0:
        score_vals, score_label, color_max = _get_score_vals(spoof_tx, sd)

        fig.add_trace(go.Scatter3d(
            x=spoof_tx['rid_pos_x'], y=spoof_tx['rid_pos_y'], z=spoof_tx['rid_pos_z'],
            mode='markers',
            marker=dict(size=3, color=score_vals, colorscale='RdYlGn_r',
                        cmin=0, cmax=color_max,
                        colorbar=dict(title=score_label, x=1.0),
                        symbol='diamond', opacity=0.7),
            name='Spoofed RID (claimed)',
            hovertext=[_score_hover(row, sd) for _, row in spoof_tx.iterrows()],
            hoverinfo='text',
        ))

        # Connecting lines
        lx, ly, lz = [], [], []
        for _, row in spoof_tx.iterrows():
            lx.extend([row['pos_x'], row['rid_pos_x'], None])
            ly.extend([row['pos_y'], row['rid_pos_y'], None])
            lz.extend([row['pos_z'], row['rid_pos_z'], None])
        fig.add_trace(go.Scatter3d(
            x=lx, y=ly, z=lz,
            mode='lines', line=dict(color='rgba(214,39,40,0.2)', width=1),
            name='Actual-to-claimed', showlegend=True, hoverinfo='skip',
        ))

    fig.update_layout(
        title=f'Full Trajectories: {sd.scenario_id}',
        scene=dict(xaxis_title='X (m)', yaxis_title='Y (m)', zaxis_title='Z (m)',
                   aspectmode='data'),
        width=900, height=700,
        legend=dict(x=0.01, y=0.99),
    )
    return fig
