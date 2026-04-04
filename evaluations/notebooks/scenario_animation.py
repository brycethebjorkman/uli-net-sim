# %% [markdown]
'''
# Scenario Animation

Interactive 3D replay of a single simulation scenario showing:
- Each drone's trajectory (actual position over time)
- Spoofed RID claimed positions (connected to actual by red lines)
- Per-transmission KF NIS and MLAT detector scores on spoofed beacons

**Usage:** Set `SCENARIO_PATH` and optionally `SCORES_DIR` in the configuration cell below, then Run All.
'''

# %%
import os

# Configuration — override via environment variables for automated testing
SCENARIO_PATH = os.environ.get('NOTEBOOK_SCENARIO', '../../datasets/snowplow/test/e9897d1b-o.parquet')

# Optional: directory containing kf_scores.parquet / mlat_scores.parquet from unified_eval score
# Set to None to use only the raw kf_nis column from the scenario data
SCORES_DIR = os.environ.get('NOTEBOOK_SCORES_DIR', '../../evaluations/results/snowplow')

# Animation time step (seconds) — controls frame spacing
FRAME_DT = 0.5

# %%
import sys
sys.path.insert(0, '../..')

import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path

df = pd.read_parquet(SCENARIO_PATH)
scenario_id = Path(SCENARIO_PATH).stem

# Separate TX and RX events
tx = df[df['event_type'] == 'TX'].copy()
rx = df[df['event_type'] == 'RX'].copy()

# Identify hosts
host_ids = sorted(df['host_id'].unique())
spoofer_ids = set(df[df['host_type'] == 'spoofer']['host_id'].unique())
benign_ids = [h for h in host_ids if h not in spoofer_ids]

print(f'Scenario: {scenario_id}')
print(f'Hosts: {len(host_ids)} ({len(benign_ids)} benign, {len(spoofer_ids)} spoofer)')
print(f'TX events: {len(tx)}, RX events: {len(rx)}')
print(f'Time range: {df["time"].min():.1f} - {df["time"].max():.1f}s')
print(f'Spoofer host(s): {sorted(spoofer_ids)}')

# %%
# Build per-transmission KF NIS scores (max across receivers)
# Uses raw kf_nis from CSV — available for every scenario without running score
kf_per_tx = (
    rx.dropna(subset=['kf_nis'])
    .groupby(['serial_number', 'rid_timestamp'])['kf_nis']
    .max()
    .reset_index()
    .rename(columns={'kf_nis': 'kf_max_nis'})
)

# Load MLAT scores if available
mlat_per_tx = None
if SCORES_DIR:
    mlat_path = Path(SCORES_DIR) / 'mlat_scores.parquet'
    if mlat_path.exists():
        mlat_all = pd.read_parquet(mlat_path)
        mlat_per_tx = mlat_all[mlat_all['scenario_id'] == scenario_id][
            ['serial_number', 'rid_timestamp', 'mlat_score']
        ].copy()
        print(f'Loaded {len(mlat_per_tx)} MLAT scores for {scenario_id}')
    else:
        print(f'No mlat_scores.parquet at {mlat_path}')

# Merge scores onto TX events
tx = tx.merge(kf_per_tx, on=['serial_number', 'rid_timestamp'], how='left')
if mlat_per_tx is not None and len(mlat_per_tx) > 0:
    tx = tx.merge(mlat_per_tx, on=['serial_number', 'rid_timestamp'], how='left')
else:
    tx['mlat_score'] = np.nan

# Spoofed TX events with scores
spoof_tx = tx[tx['is_spoofed'] == 1].copy()
print(f'Spoofed TX events: {len(spoof_tx)}')
print(f'  with KF NIS:  {spoof_tx["kf_max_nis"].notna().sum()}')
print(f'  with MLAT:    {spoof_tx["mlat_score"].notna().sum()}')

# %%
# Color palette
BENIGN_COLORS = ['#1f77b4', '#2ca02c', '#9467bd', '#8c564b', '#e377c2',
                 '#7f7f7f', '#bcbd22', '#17becf']
SPOOFER_ACTUAL_COLOR = '#ff7f0e'  # orange
SPOOFER_CLAIMED_COLOR = '#d62728'  # red

def get_host_color(host_id):
    if host_id in spoofer_ids:
        return SPOOFER_ACTUAL_COLOR
    idx = benign_ids.index(host_id) if host_id in benign_ids else 0
    return BENIGN_COLORS[idx % len(BENIGN_COLORS)]

# Build per-host TX timeseries (actual positions from TX events)
host_tx = {}
for hid in host_ids:
    ht = tx[tx['host_id'] == hid].sort_values('time')
    host_tx[hid] = ht

# Time grid for animation frames
t_min, t_max = tx['time'].min(), tx['time'].max()
frame_times = np.arange(t_min, t_max + FRAME_DT, FRAME_DT)
print(f'Animation: {len(frame_times)} frames from t={t_min:.1f} to t={t_max:.1f}s')

# %%
def interp_pos(ht, t):
    """Interpolate host position at time t from TX events."""
    times = ht['time'].values
    if len(times) == 0 or t < times[0]:
        return None
    if t >= times[-1]:
        return (ht['pos_x'].iloc[-1], ht['pos_y'].iloc[-1], ht['pos_z'].iloc[-1])
    idx = np.searchsorted(times, t, side='right') - 1
    idx = max(0, min(idx, len(times) - 2))
    t0, t1 = times[idx], times[idx + 1]
    if t1 - t0 < 1e-9:
        a = 0.0
    else:
        a = (t - t0) / (t1 - t0)
    x = ht['pos_x'].iloc[idx] + a * (ht['pos_x'].iloc[idx + 1] - ht['pos_x'].iloc[idx])
    y = ht['pos_y'].iloc[idx] + a * (ht['pos_y'].iloc[idx + 1] - ht['pos_y'].iloc[idx])
    z = ht['pos_z'].iloc[idx] + a * (ht['pos_z'].iloc[idx + 1] - ht['pos_z'].iloc[idx])
    return (x, y, z)


def score_text(row):
    """Build hover text for a spoofed beacon."""
    parts = [f"t={row['time']:.2f}s, SN={int(row['serial_number'])}"]
    parts.append(f"actual=({row['pos_x']:.0f}, {row['pos_y']:.0f}, {row['pos_z']:.0f})")
    parts.append(f"claimed=({row['rid_pos_x']:.0f}, {row['rid_pos_y']:.0f}, {row['rid_pos_z']:.0f})")
    dist = np.sqrt((row['pos_x']-row['rid_pos_x'])**2 +
                   (row['pos_y']-row['rid_pos_y'])**2 +
                   (row['pos_z']-row['rid_pos_z'])**2)
    parts.append(f"offset={dist:.1f}m")
    if not np.isnan(row.get('kf_max_nis', np.nan)):
        parts.append(f"KF NIS={row['kf_max_nis']:.3f}")
    if not np.isnan(row.get('mlat_score', np.nan)):
        parts.append(f"MLAT={row['mlat_score']:.1f}")
    return '<br>'.join(parts)

# %% [markdown]
'''
## Build Animation

Each frame shows:
- **Solid lines**: trajectory trails up to current time (blue=benign, orange=spoofer actual)
- **Large markers**: current drone positions
- **Diamond markers**: spoofed RID claimed positions (color: green=low score, yellow=medium, red=detected)
- **Red dashed lines**: connecting actual to claimed position for each spoofed beacon
- **Hover text**: detector scores on spoofed beacons
'''

# %%
# Fixed trace layout — plotly animation requires same number of traces per frame.
# Trace order:
#   0..N-1:  trajectory trail line per host (N = len(host_ids))
#   N..2N-1: current position marker per host
#   2N:      spoofed claimed position markers (diamonds)
#   2N+1:    actual-to-claimed connecting lines

N = len(host_ids)

# Pre-compute color scale range from all spoofed KF NIS values (same as static plot)
all_kf = spoof_tx['kf_max_nis'].fillna(0).values
COLOR_MAX = max(all_kf.max(), 1.0) if len(all_kf) > 0 else 1.0

def empty_scatter3d(**kwargs):
    return go.Scatter3d(x=[], y=[], z=[], **kwargs)

def build_initial_traces():
    """Create the fixed trace layout with empty data."""
    traces = []
    # Trail lines per host
    for hid in host_ids:
        color = get_host_color(hid)
        label = f'Host {hid}' + (' (spoofer)' if hid in spoofer_ids else '')
        traces.append(empty_scatter3d(
            mode='lines', line=dict(color=color, width=3),
            name=label, showlegend=True, hoverinfo='skip',
        ))
    # Current position markers per host
    for hid in host_ids:
        color = get_host_color(hid)
        traces.append(empty_scatter3d(
            mode='markers+text',
            marker=dict(size=6, color=color, symbol='circle'),
            textposition='top center', textfont=dict(size=9, color=color),
            showlegend=False, hoverinfo='text',
        ))
    # Spoofed claimed markers (use same colorscale as static plot)
    traces.append(go.Scatter3d(
        x=[], y=[], z=[],
        mode='markers',
        marker=dict(size=4, color=[], colorscale='RdYlGn_r',
                    cmin=0, cmax=COLOR_MAX,
                    colorbar=dict(title='KF NIS', x=1.0),
                    symbol='diamond', opacity=0.8),
        name='Spoofed RID', showlegend=True, hoverinfo='text',
    ))
    # Actual-to-claimed lines
    traces.append(empty_scatter3d(
        mode='lines', line=dict(color='rgba(214,39,40,0.3)', width=1, dash='dot'),
        name='Actual-to-claimed', showlegend=True, hoverinfo='skip',
    ))
    return traces


def build_frame_data(t):
    """Build trace data arrays for a given time (same order as initial traces)."""
    data = []

    # Trail lines per host (indices 0..N-1)
    for hid in host_ids:
        ht = host_tx[hid]
        trail = ht[ht['time'] <= t]
        if len(trail) > 1:
            data.append(dict(x=trail['pos_x'].tolist(), y=trail['pos_y'].tolist(),
                             z=trail['pos_z'].tolist()))
        else:
            data.append(dict(x=[], y=[], z=[]))

    # Current position markers per host (indices N..2N-1)
    for hid in host_ids:
        pos = interp_pos(host_tx[hid], t)
        if pos:
            data.append(dict(
                x=[pos[0]], y=[pos[1]], z=[pos[2]],
                text=[f'{hid}'],
                hovertext=[f'Host {hid}<br>({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})'],
            ))
        else:
            data.append(dict(x=[], y=[], z=[], text=[], hovertext=[]))

    # Spoofed claimed markers (index 2N) — use numeric KF NIS for colorscale
    visible_spoof = spoof_tx[spoof_tx['time'] <= t]
    if len(visible_spoof) > 0:
        kf_vals = visible_spoof['kf_max_nis'].fillna(0).tolist()
        hover_texts = [score_text(row) for _, row in visible_spoof.iterrows()]
        data.append(dict(
            x=visible_spoof['rid_pos_x'].tolist(),
            y=visible_spoof['rid_pos_y'].tolist(),
            z=visible_spoof['rid_pos_z'].tolist(),
            marker=dict(size=4, color=kf_vals, colorscale='RdYlGn_r',
                        cmin=0, cmax=COLOR_MAX,
                        symbol='diamond', opacity=0.8),
            hovertext=hover_texts,
        ))
    else:
        data.append(dict(x=[], y=[], z=[], hovertext=[]))

    # Actual-to-claimed lines (index 2N+1)
    if len(visible_spoof) > 0:
        lx, ly, lz = [], [], []
        for _, row in visible_spoof.iterrows():
            lx.extend([row['pos_x'], row['rid_pos_x'], None])
            ly.extend([row['pos_y'], row['rid_pos_y'], None])
            lz.extend([row['pos_z'], row['rid_pos_z'], None])
        data.append(dict(x=lx, y=ly, z=lz))
    else:
        data.append(dict(x=[], y=[], z=[]))

    return data


# Build initial traces and frames
initial_traces = build_initial_traces()

# Populate initial traces with first frame data
first_data = build_frame_data(frame_times[0])
for trace, d in zip(initial_traces, first_data):
    trace.update(d)

# Build animation frames
frames = []
for ft in frame_times:
    fd = build_frame_data(ft)
    frame_traces = []
    for d in fd:
        frame_traces.append(go.Scatter3d(**{k: v for k, v in d.items()}))
    frames.append(go.Frame(data=frame_traces, name=f'{ft:.1f}'))

print(f'Built {len(frames)} frames, {len(initial_traces)} traces per frame')
print(f'KF NIS color range: [0, {COLOR_MAX:.2f}]')

# %%
# Create figure with animation
fig = go.Figure(data=initial_traces, frames=frames)

# Slider steps
slider_steps = [
    dict(args=[[f'{ft:.1f}'], dict(frame=dict(duration=0, redraw=True), mode='immediate')],
         label=f'{ft:.0f}s', method='animate')
    for ft in frame_times[::max(1, len(frame_times) // 50)]  # ~50 slider ticks
]

fig.update_layout(
    title=dict(text=f'Scenario: {scenario_id}', font=dict(size=14)),
    scene=dict(
        xaxis_title='X (m)', yaxis_title='Y (m)', zaxis_title='Z (m)',
        aspectmode='data',
    ),
    width=900, height=700,
    updatemenus=[
        dict(type='buttons', showactive=False, x=0.05, y=0.02,
             buttons=[
                 dict(label='Play', method='animate',
                      args=[None, dict(frame=dict(duration=100, redraw=True),
                                       fromcurrent=True, mode='immediate')]),
                 dict(label='Pause', method='animate',
                      args=[[None], dict(frame=dict(duration=0, redraw=False),
                                         mode='immediate')]),
             ]),
    ],
    sliders=[dict(
        active=0, steps=slider_steps, x=0.05, len=0.9,
        currentvalue=dict(prefix='Time: ', suffix='s'),
    )],
)

fig.show()

# %% [markdown]
# ## Static Overview
#
# Full trajectory plot (all time) with spoofed beacons colored by KF NIS score.

# %%
# Static full-trajectory view
fig_static = go.Figure()

# Full trajectory lines per host
for hid in host_ids:
    ht = host_tx[hid]
    color = get_host_color(hid)
    label = f'Host {hid}' + (' (spoofer)' if hid in spoofer_ids else '')
    fig_static.add_trace(go.Scatter3d(
        x=ht['pos_x'], y=ht['pos_y'], z=ht['pos_z'],
        mode='lines', line=dict(color=color, width=3),
        name=label,
    ))

# Spoofed claimed positions with KF NIS colorscale
if len(spoof_tx) > 0:
    kf_vals = spoof_tx['kf_max_nis'].fillna(0).values

    fig_static.add_trace(go.Scatter3d(
        x=spoof_tx['rid_pos_x'], y=spoof_tx['rid_pos_y'], z=spoof_tx['rid_pos_z'],
        mode='markers',
        marker=dict(size=3, color=kf_vals, colorscale='RdYlGn_r',
                    cmin=0, cmax=max(kf_vals.max(), 1),
                    colorbar=dict(title='KF NIS', x=1.0),
                    symbol='diamond', opacity=0.7),
        name='Spoofed RID (claimed)',
        hovertext=[score_text(row) for _, row in spoof_tx.iterrows()],
        hoverinfo='text',
    ))

    # Connecting lines
    link_x, link_y, link_z = [], [], []
    for _, row in spoof_tx.iterrows():
        link_x.extend([row['pos_x'], row['rid_pos_x'], None])
        link_y.extend([row['pos_y'], row['rid_pos_y'], None])
        link_z.extend([row['pos_z'], row['rid_pos_z'], None])

    fig_static.add_trace(go.Scatter3d(
        x=link_x, y=link_y, z=link_z,
        mode='lines', line=dict(color='rgba(214,39,40,0.2)', width=1),
        name='Actual-to-claimed', showlegend=True, hoverinfo='skip',
    ))

fig_static.update_layout(
    title=f'Full Trajectories: {scenario_id}',
    scene=dict(xaxis_title='X (m)', yaxis_title='Y (m)', zaxis_title='Z (m)',
               aspectmode='data'),
    width=900, height=700,
    legend=dict(x=0.01, y=0.99),
)
fig_static.show()

# %% [markdown]
# ## Score Timeseries
#
# KF NIS and MLAT score over time for the spoofer's transmissions.

# %%
from plotly.subplots import make_subplots

has_mlat = spoof_tx['mlat_score'].notna().any()
n_rows = 2 if has_mlat else 1
subtitles = ['KF NIS (max across receivers)']
if has_mlat:
    subtitles.append('MLAT Score')

fig_ts = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
                       subplot_titles=subtitles, vertical_spacing=0.08)

# KF NIS timeseries
kf_valid = spoof_tx.dropna(subset=['kf_max_nis'])
fig_ts.add_trace(go.Scatter(
    x=kf_valid['time'], y=kf_valid['kf_max_nis'],
    mode='markers+lines', marker=dict(size=4, color='steelblue'),
    line=dict(width=1, color='steelblue'),
    name='KF NIS',
    hovertext=[f"SN={int(r['serial_number'])}, NIS={r['kf_max_nis']:.3f}" for _, r in kf_valid.iterrows()],
    hoverinfo='text+x',
), row=1, col=1)

# KF threshold line
fig_ts.add_hline(y=0.721, line=dict(color='red', dash='dash', width=1),
                 annotation_text='threshold', row=1, col=1)

# MLAT timeseries
if has_mlat:
    mlat_valid = spoof_tx.dropna(subset=['mlat_score'])
    fig_ts.add_trace(go.Scatter(
        x=mlat_valid['time'], y=mlat_valid['mlat_score'],
        mode='markers+lines', marker=dict(size=4, color='green'),
        line=dict(width=1, color='green'),
        name='MLAT Score',
        hovertext=[f"SN={int(r['serial_number'])}, MLAT={r['mlat_score']:.1f}" for _, r in mlat_valid.iterrows()],
        hoverinfo='text+x',
    ), row=2, col=1)
    fig_ts.add_hline(y=147.13, line=dict(color='red', dash='dash', width=1),
                     annotation_text='threshold', row=2, col=1)

fig_ts.update_layout(
    title=f'Detector Scores Over Time: {scenario_id}',
    height=300 * n_rows + 100, width=900,
    showlegend=True,
)
fig_ts.update_xaxes(title_text='Time (s)', row=n_rows, col=1)
fig_ts.show()
