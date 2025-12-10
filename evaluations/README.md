# Spoofing Detection Evaluation Framework

This package evaluates three spoofing detection methods on transmission-level classification:

1. **Kalman Filter (KF)** - Uses pre-computed KF NIS (Normalized Innovation Squared) from simulation. High NIS indicates RSSI inconsistent with claimed position.

2. **RSSI Multilateration (MLAT)** - Jointly estimates transmitter position and TX power from RSSI measurements at multiple federate receivers, compares to claimed position. Large discrepancy indicates spoofing.

3. **Multilayer Perceptron (MLP)** - Supervised learning on timeseries features extracted from RX events.

## Reproducing Paper Results

To reproduce the exact results presented in the SciTech26 paper:

```bash
cd /usr/uli-net-sim/uav_rid
. container/setenv
./evaluations/scitech26_eval.sh
```

This runs the full train+test pipeline on the `scitech26-1920-scenarios` dataset and produces:
- `evaluations/results/unified_results.json` - Numeric results (AUC, TPR, FPR)
- `evaluations/results/roc_curves.pdf` - ROC curve figure for the paper
- `evaluations/results/roc_curves.png` - ROC curve preview

## Quick Start

For development and testing with smaller datasets:

```bash
cd /usr/uli-net-sim/uav_rid
. container/setenv

# Unified evaluation comparing all three methods
python -m evaluations.unified_eval \
    --train-dir datasets/scitech26-mini/train \
    --test-dir datasets/scitech26-mini/test \
    --mlp-predictions datasets/mlp_test_predictions.csv \
    -o evaluations/results/

# Test-only mode with pre-trained thresholds
python -m evaluations.unified_eval \
    --test-dir datasets/scitech26-1920-scenarios/test \
    --mlp-predictions datasets/mlp_test_predictions.csv \
    --test-only \
    --kf-threshold 0.6254 \
    --mlat-threshold 114.3571 \
    --mlat-ple 1.6 \
    -o evaluations/results/
```

For individual detector evaluation (legacy):
```bash
python -m evaluations.run all datasets/scitech26/train datasets/scitech26/test -o evaluations/results/
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

**Detection pipeline:**
1. NLLS estimates transmitter position (x, y, z) and TX power jointly
2. Compute position error = |estimated_pos - claimed_pos|
3. Feed error to per-transmitter Kalman filter for smoothing
4. Return filtered error as detection score (large error = likely spoofing)

**Key features:**
- Groups RX events by `(serial_number, rid_timestamp)` to identify the same transmission
- Jointly solves for position (x,y,z) AND TX power using the measurement model:
  `RSSI_i = P_tx - 10*n*log10(|pos - receiver_i|)`
- Tracks position error over time with a per-transmitter Kalman Filter
- Returns KF-filtered error as detection score

**Parameters (line searched):**
- `path_loss_exp`: Path loss exponent n in the model P = P_tx / d^n. In free space n=2 (inverse square law). Called "exponent" because power falls as d^(-n); appears as multiplier in log domain.

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

=== Evaluation on Training Set ===
Evaluating KalmanFilter with threshold=0.6254...
  Total events: 768811, spoofed: 107460
  DetectionMetrics(AUC=0.8274, TPR=0.6906, FPR=0.1752)

=== Evaluation on Test Set ===
Loading test data from datasets/scitech26/test...
Evaluating KalmanFilter with threshold=0.6254...
  Total events: 209489, spoofed: 29535
  DetectionMetrics(AUC=0.8290, TPR=0.6929, FPR=0.1756)

============================================================
MULTILATERATION DETECTOR
============================================================
=== Line Search for Path Loss Exponent ===
Loaded 50 training scenarios
  path_loss_exp=1.6: AUC=0.8167
  path_loss_exp=1.8: AUC=0.8234
  path_loss_exp=2.0: AUC=0.8301
  path_loss_exp=2.2: AUC=0.8245
  path_loss_exp=2.4: AUC=0.8189

Best path_loss_exp: 2.0
Best AUC: 0.8301

=== Evaluation on Training Set ===
=== Evaluation on Test Set ===
Evaluating Multilateration with threshold=114.3571...
  DetectionMetrics(AUC=0.8872, TPR=0.7312, FPR=0.0791)

============================================================
COMPARISON (Train / Test)
============================================================
Detector     Split       AUC      TPR      FPR   Mean TTD
--------------------------------------------------------------------------------
kf           train    0.8274   0.6906   0.1752     3.100s
kf           test     0.8290   0.6929   0.1756     3.302s
--------------------------------------------------------------------------------
mlat         train    0.8301   0.6117   0.0478    55.000s
mlat         test     0.8872   0.7312   0.0791    66.010s
--------------------------------------------------------------------------------
```

## Optimization Strategy

1. **Training phase**: Find optimal detection threshold (and path loss exponent for MLAT)
   - Line search for thresholds (maximize Youden's J = TPR - FPR)
   - Line search for MLAT path loss exponent [1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0]

2. **Evaluation phase**: Evaluate on both training and test sets with optimized parameters
   - Results include both `train_evaluation` and `test_evaluation` in output JSON
