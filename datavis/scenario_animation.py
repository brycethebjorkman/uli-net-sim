# %% [markdown]
'''
# Scenario Animation

Interactive 3D replay of a single simulation scenario showing:
- Each drone's trajectory (actual position over time)
- Spoofed RID claimed positions colored by detection score
- Per-transmission detection score timeseries

Automatically detects which detector scores are available (KF NIS, MLAT,
CUSUM, etc.) and adapts the colorscale and timeseries panels accordingly.

**Usage:** Set `SCENARIO_PATH` below (or via environment variable), then Run All.

    # Generate the parquet from a .vec file:
    python datagen/vec2parquet.py simulation.vec -o scenario.parquet

    # Or run a scenario and convert in one step:
    python datagen/run_scenario.py simulations/gp_tracking_test/ --config GpTrackingSpoofed
'''

# %%
import os

SCENARIO_PATH = os.environ.get(
    'NOTEBOOK_SCENARIO',
    '../datasets/current/test/e9897d1b-o.parquet',
)
FRAME_DT = 0.5

# %%
import sys
sys.path.insert(0, '..')

from datavis.scenario_data import load_scenario
from datavis.plots_3d import build_animation, build_static_overview
from datavis.plots_timeseries import build_score_timeseries

sd = load_scenario(SCENARIO_PATH)

print(f'Scenario: {sd.scenario_id}')
print(f'Hosts: {len(sd.host_ids)} ({len(sd.benign_ids)} benign, {len(sd.spoofer_ids)} spoofer)')
print(f'TX: {len(sd.tx)}, RX: {len(sd.rx)}, GCS: {len(sd.gcs)}')
print(f'Spoofed TX: {len(sd.spoof_tx)}')
print(f'Time range: {sd.t_min:.1f} - {sd.t_max:.1f}s')
print(f'Detected scores: {[sc.label for sc in sd.scores]}')
if sd.primary_score:
    print(f'Primary score (colorscale): {sd.primary_score.label} ({sd.primary_score.column})')

# %% [markdown]
'''
## 3D Animation
'''

# %%
fig_anim = build_animation(sd, frame_dt=FRAME_DT)
fig_anim.show()

# %% [markdown]
'''
## Static Overview
'''

# %%
fig_static = build_static_overview(sd)
fig_static.show()

# %% [markdown]
'''
## Score Timeseries
'''

# %%
fig_ts = build_score_timeseries(sd)
if fig_ts:
    fig_ts.show()
else:
    print('No detection scores available for this scenario.')
