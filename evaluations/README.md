# Spoofing Detection Evaluation Framework

This package evaluates two spoofing detection methods on RX event classification:

1. **Kalman Filter (KF)** - Uses pre-computed KF NIS (Normalized Innovation Squared) from simulation. High NIS indicates RSSI inconsistent with claimed position.

2. **RSSI Multilateration (MLAT)** - Jointly estimates transmitter position and TX power from RSSI measurements at multiple federate receivers, compares to claimed position. Large discrepancy indicates spoofing.

## Quick Start

Run full evaluation on the scitech26 dataset:

```bash
cd /usr/uli-net-sim/uav_rid
. container/setenv

# Run both detectors with full dataset
python -m evaluations.run all datasets/scitech26/train datasets/scitech26/test -o evaluations/results/

# Or run individually:
python -m evaluations.run kf datasets/scitech26/train datasets/scitech26/test -o evaluations/results/
python -m evaluations.run mlat datasets/scitech26/train datasets/scitech26/test -o evaluations/results/
```

For quick testing with limited scenarios:
```bash
python -m evaluations.run all datasets/scitech26/train datasets/scitech26/test \
    --train-limit 10 --test-limit 10 -o evaluations/results/
```

## Task

**Binary classification of RX events**: Given an RX event (a receiver getting a Remote ID beacon), classify it as `spoofed` or `benign`.

- **Ground truth**: `is_spoofed` column in CSV (1 if the transmitter is a spoofer)
- **Detection score**: Higher = more likely spoofed
- **Threshold**: Score >= threshold → predict spoofed

## Dataset Structure

The scitech26 dataset has the following structure:
```
datasets/scitech26/
├── manifest.json          # Generation parameters and scenario metadata
├── train/                  # Training CSVs (~80% of scenarios)
│   ├── 872368be-b.csv
│   ├── 872368be-o.csv
│   └── ...
└── test/                   # Test CSVs (~20% of scenarios)
    ├── e2cda6b5-b.csv
    └── ...
```

Each CSV contains RX events with columns:
- `time`, `event_type`, `host_id`, `serial_number`, `rid_timestamp`
- `pos_x/y/z` (receiver position), `rid_pos_x/y/z` (claimed TX position)
- `rssi`, `kf_nis`, `is_spoofed`, `host_type`

## Metrics

1. **AUC** - Area under ROC curve (threshold-independent accuracy)
2. **TPR/FPR** - True/false positive rates at operating threshold
3. **Time-to-detection** - Seconds from first spoofed RX to first correct detection

## Detectors

### KalmanFilterDetector

Uses `kf_nis` column from CSV (pre-computed in simulation). No parameters to tune - just finds optimal threshold.

The KF estimates TX power from RSSI given claimed distance. When a spoofer claims a false position, the RSSI doesn't match the claimed distance, causing high innovation (NIS).

### MultilatDetector

Uses fixed federate receivers (first 4 benign hosts) to jointly estimate transmitter position and TX power via nonlinear least squares.

**Key features:**
- Groups RX events by `(serial_number, rid_timestamp)` to identify the same transmission
- Jointly solves for position (x,y,z) AND TX power using the measurement model:
  `RSSI_i = P_tx - 10*n*log10(|pos - receiver_i|)`
- Tracks position error over time with a per-transmitter Kalman Filter
- Returns filtered error (or NIS) as detection score

**Parameters (grid searched):**
- `path_loss_exp`: Path loss exponent (default 2.0 for free space)
- `use_filtered_error`: If True, return filtered error. If False, return NIS.

## Files

| File | Purpose |
|------|---------|
| `data.py` | Load CSVs, extract RX events with ground truth |
| `metrics.py` | Compute AUC, TPR, FPR, time-to-detection |
| `detectors.py` | Detector interface + KF/MLAT implementations |
| `optimize.py` | Threshold line search, parameter grid search |
| `evaluate.py` | Run train→test evaluation pipeline |
| `run.py` | CLI entry point |
| `notebooks/` | Jupyter notebooks explaining each detector |

## Notebooks

Interactive explanations of the detection methods:

- `notebooks/kalman_filter_detection.ipynb` - KF-based TX power estimation and NIS detection
- `notebooks/multilateration_detection.ipynb` - RSSI multilateration with joint position/TX power estimation

To run notebooks:
```bash
cd /usr/uli-net-sim/uav_rid
. container/setenv
jupyter notebook evaluations/notebooks/
```

## Example Output

```
============================================================
KALMAN FILTER DETECTOR
============================================================
=== Training Phase ===
Loading training data from datasets/scitech26/train...
Loaded 50 training scenarios
Optimizing threshold for KalmanFilter...
  Total events: 768811, spoofed: 107460
  AUC: 0.8274
  Best threshold: 0.6254
  At threshold: TPR=0.6906, FPR=0.1752

=== Evaluation Phase ===
Loading test data from datasets/scitech26/test...
Evaluating KalmanFilter with threshold=0.6254...
  Total events: 209489, spoofed: 29535
  DetectionMetrics(
  AUC=0.8290, TPR=0.6929, FPR=0.1756
  Threshold=0.6254, Time-to-Detection=0.971s
  TP=20466, TN=148352, FP=31602, FN=9069
)

Results saved to results/kf_results.json

============================================================
MULTILATERATION DETECTOR
============================================================
=== Grid Search for Multilateration Parameters ===
Loaded 50 training scenarios
Grid search over 10 parameter combinations...
  [1/10] {'path_loss_exp': 1.6, 'use_filtered_error': True}
    New best AUC: 0.8167
  [2/10] {'path_loss_exp': 1.6, 'use_filtered_error': False}
  [3/10] {'path_loss_exp': 1.8, 'use_filtered_error': True}
  [4/10] {'path_loss_exp': 1.8, 'use_filtered_error': False}
  [5/10] {'path_loss_exp': 2.0, 'use_filtered_error': True}
  [6/10] {'path_loss_exp': 2.0, 'use_filtered_error': False}
  [7/10] {'path_loss_exp': 2.2, 'use_filtered_error': True}
  [8/10] {'path_loss_exp': 2.2, 'use_filtered_error': False}
  [9/10] {'path_loss_exp': 2.4, 'use_filtered_error': True}
  [10/10] {'path_loss_exp': 2.4, 'use_filtered_error': False}
Best params: {'path_loss_exp': 1.6, 'use_filtered_error': True}
Best AUC: 0.8167

Best parameters: {'path_loss_exp': 1.6, 'use_filtered_error': True}
Best AUC: 0.8167
=== Training Phase ===
Loading training data from datasets/scitech26/train...
Loaded 50 training scenarios
Optimizing threshold for Multilateration...
  Total events: 768811, spoofed: 107460
  AUC: 0.8167
  Best threshold: 114.3571
  At threshold: TPR=0.6117, FPR=0.0478

=== Evaluation Phase ===
Loading test data from datasets/scitech26/test...
Evaluating Multilateration with threshold=114.3571...
  Total events: 209489, spoofed: 29535
  DetectionMetrics(
  AUC=0.8872, TPR=0.7312, FPR=0.0791
  Threshold=114.3571, Time-to-Detection=50.492s
  TP=21596, TN=165725, FP=14229, FN=7939
)

Results saved to results/mlat_results.json

Combined results saved to results/all_results.json

============================================================
COMPARISON
============================================================
Detector             AUC      TPR      FPR   Mean TTD
------------------------------------------------------------
kf                0.8290   0.6929   0.1756     3.302s
mlat              0.8872   0.7312   0.0791    66.010s
```

## Optimization Strategy

1. **Training phase**: Find optimal detection threshold (and parameters for MLAT)
   - Line search for thresholds (maximize Youden's J = TPR - FPR)
   - Grid search for MLAT path loss exponent

2. **Test phase**: Evaluate on held-out test set with optimized parameters
