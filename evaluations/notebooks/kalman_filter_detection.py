# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.1
#   kernelspec:
#     display_name: Python (uav_rid)
#     language: python
#     name: uav_rid
# ---

# %% [markdown]
# # Spoofing Detection: Kalman Filter Approach
#
# This notebook explains the Kalman Filter-based spoofing detection method.
#
# ## Intuition
#
# A receiver measures RSSI (signal strength) from a transmitter claiming to be at position $\mathbf{p}_{claimed}$. If we know the receiver's position $\mathbf{p}_{rx}$, we can:
#
# 1. Compute the claimed distance: $d_{claimed} = |\mathbf{p}_{claimed} - \mathbf{p}_{rx}|$
# 2. Use a path loss model to predict what RSSI we *should* see at that distance
# 3. Compare predicted vs actual RSSI
#
# For an **honest transmitter**, the claimed position is true, so RSSI matches prediction.
#
# For a **spoofer**, the claimed position is fake. The actual RSSI depends on the *real* distance, which differs from claimed distance. This creates a mismatch.
#
# The Kalman Filter tracks this mismatch over time, building confidence about whether the transmitter is honest or spoofing.

# %%
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

np.set_printoptions(precision=4, suppress=True)


# %% [markdown]
# ## Step 1: Path Loss Model
#
# RSSI decreases with distance according to the log-distance path loss model:
#
# $$RSSI = P_{tx} - 10 \cdot n \cdot \log_{10}(d)$$
#
# Where:
# - $P_{tx}$ = transmit power (dBm)
# - $n$ = path loss exponent (2.0 for free space, higher with obstacles)
# - $d$ = distance (meters)
#
# Rearranging to estimate TX power from RSSI and distance:
#
# $$\hat{P}_{tx} = RSSI + 10 \cdot n \cdot \log_{10}(d)$$

# %%
def estimate_tx_power(rssi, distance, path_loss_exp=2.0):
    """Estimate TX power from RSSI and distance."""
    return rssi + 10 * path_loss_exp * np.log10(distance)

def expected_rssi(tx_power, distance, path_loss_exp=2.0):
    """Expected RSSI given TX power and distance."""
    return tx_power - 10 * path_loss_exp * np.log10(distance)

# Example: honest transmitter
true_tx_power = 15  # dBm
true_distance = 100  # meters
true_rssi = expected_rssi(true_tx_power, true_distance)

print(f"Honest transmitter at {true_distance}m with TX power {true_tx_power} dBm")
print(f"Expected RSSI: {true_rssi:.2f} dBm")
print(f"Estimated TX power from RSSI: {estimate_tx_power(true_rssi, true_distance):.2f} dBm")

# %%
# Example: spoofer
# Spoofer is actually at 50m but claims to be at 200m
actual_distance = 50
claimed_distance = 200
spoofer_tx_power = 15

# RSSI is based on ACTUAL distance
actual_rssi = expected_rssi(spoofer_tx_power, actual_distance)

# But receiver uses CLAIMED distance to estimate TX power
estimated_tx = estimate_tx_power(actual_rssi, claimed_distance)

print(f"Spoofer: actual distance={actual_distance}m, claims {claimed_distance}m")
print(f"Actual RSSI: {actual_rssi:.2f} dBm")
print(f"Estimated TX power (using claimed distance): {estimated_tx:.2f} dBm")
print(f"True TX power: {spoofer_tx_power} dBm")
print(f"\nMismatch: {estimated_tx - spoofer_tx_power:.2f} dB")
print("The estimated TX power is way too high - this is suspicious!")


# %% [markdown]
# ## Step 2: The Kalman Filter
#
# Instead of detecting on a single measurement (which is noisy), we use a Kalman Filter to:
# 1. Track the estimated TX power over time
# 2. Build confidence in our estimate
# 3. Detect anomalies via the **Normalized Innovation Squared (NIS)**
#
# ### State Model
#
# - **State**: $x = P_{tx}$ (estimated transmit power)
# - **Measurement**: $z = RSSI + 10n\log_{10}(d_{claimed})$ (TX power estimate from single measurement)
#
# ### KF Equations
#
# **Prediction** (TX power is constant):
# $$\hat{x}^- = \hat{x}$$
# $$P^- = P + Q$$
#
# **Update**:
# $$K = P^- / (P^- + R)$$
# $$\nu = z - \hat{x}^- \quad \text{(innovation)}$$
# $$\hat{x} = \hat{x}^- + K \nu$$
# $$P = (1-K) P^-$$
#
# **Normalized Innovation Squared (NIS)**:
# $$\text{NIS} = \frac{\nu^2}{P^- + R}$$
#
# For a correctly-specified model, NIS follows a $\chi^2(1)$ distribution. Large NIS values indicate model mismatch → spoofing!

# %%
class TxPowerKalmanFilter:
    """Kalman Filter for tracking TX power and detecting anomalies."""
    
    def __init__(self, process_noise=0.1, measurement_noise=9.0, initial_estimate=13.0, initial_covariance=100.0):
        self.Q = process_noise      # Process noise variance
        self.R = measurement_noise  # Measurement noise variance (RSSI noise ~3dB std → 9 var)
        self.x = initial_estimate   # State estimate
        self.P = initial_covariance # State covariance
        
    def update(self, measurement):
        """Process a measurement and return NIS."""
        # Prediction (TX power is constant, so x_pred = x)
        x_pred = self.x
        P_pred = self.P + self.Q
        
        # Innovation
        innovation = measurement - x_pred
        S = P_pred + self.R  # Innovation covariance
        
        # NIS (our detection statistic)
        nis = (innovation ** 2) / S
        
        # Kalman gain and update
        K = P_pred / S
        self.x = x_pred + K * innovation
        self.P = (1 - K) * P_pred
        
        return nis, innovation, self.x, self.P

# Demonstrate with honest transmitter
kf = TxPowerKalmanFilter()
true_tx = 15.0
distance = 100.0

print("Honest transmitter (TX=15dBm, distance=100m):")
print(f"{'Meas#':>5} {'RSSI':>8} {'z (est TX)':>10} {'NIS':>8} {'x_hat':>8} {'P':>8}")
print("-" * 55)

np.random.seed(42)
for i in range(10):
    # Simulate noisy RSSI measurement
    rssi = expected_rssi(true_tx, distance) + np.random.randn() * 3  # 3dB noise
    z = estimate_tx_power(rssi, distance)  # Measurement
    
    nis, innov, x_hat, P = kf.update(z)
    print(f"{i+1:>5} {rssi:>8.2f} {z:>10.2f} {nis:>8.3f} {x_hat:>8.2f} {P:>8.2f}")

# %%
# Now demonstrate with a spoofer
kf = TxPowerKalmanFilter()
true_tx = 15.0
actual_distance = 50.0
claimed_distance = 200.0

print("Spoofer (TX=15dBm, actual=50m, claims 200m):")
print(f"{'Meas#':>5} {'RSSI':>8} {'z (est TX)':>10} {'NIS':>8} {'x_hat':>8} {'P':>8}")
print("-" * 55)

np.random.seed(42)
for i in range(10):
    # RSSI based on ACTUAL distance
    rssi = expected_rssi(true_tx, actual_distance) + np.random.randn() * 3
    # But we use CLAIMED distance to estimate TX power
    z = estimate_tx_power(rssi, claimed_distance)
    
    nis, innov, x_hat, P = kf.update(z)
    print(f"{i+1:>5} {rssi:>8.2f} {z:>10.2f} {nis:>8.3f} {x_hat:>8.2f} {P:>8.2f}")

print("\nNotice the high NIS values! The filter detects inconsistency.")

# %% [markdown]
# ## Step 3: Detection Threshold
#
# Under the null hypothesis (honest transmitter), NIS ~ $\chi^2(1)$.
#
# We set a threshold to achieve a desired false positive rate:
# - 95th percentile of $\chi^2(1)$ ≈ 3.84 → 5% FPR
# - 99th percentile of $\chi^2(1)$ ≈ 6.63 → 1% FPR
#
# In practice, we optimize the threshold on training data to maximize AUC.

# %%
from scipy import stats

# Chi-squared thresholds
for fpr in [0.10, 0.05, 0.01]:
    thresh = stats.chi2.ppf(1 - fpr, df=1)
    print(f"FPR={fpr:.0%}: threshold={thresh:.2f}")

# %% [markdown]
# ## Step 4: Load Real Data
#
# Let's look at the pre-computed KF NIS values from our simulation.

# %%
# Load a scenario
import os
import sys
sys.path.insert(0, '../..')
from evaluations.data import load_scenario

_scenario_path = os.environ.get('NOTEBOOK_SCENARIO', '../../datasets/scitech26/train/0a293ed9-b.csv')
scenario = load_scenario(_scenario_path)
print(f"Scenario: {scenario.scenario_id}")
print(f"Total RX events: {scenario.n_events}")
print(f"Spoofed events: {scenario.n_spoofed}")
print(f"Benign events: {scenario.n_benign}")

# %%
# Look at KF NIS distribution
nis_benign = scenario.kf_nis[~scenario.is_spoofed]
nis_spoofed = scenario.kf_nis[scenario.is_spoofed]

# Remove NaN (KF not yet initialized)
nis_benign = nis_benign[~np.isnan(nis_benign)]
nis_spoofed = nis_spoofed[~np.isnan(nis_spoofed)]

print(f"Benign NIS: mean={np.mean(nis_benign):.2f}, median={np.median(nis_benign):.2f}")
print(f"Spoofed NIS: mean={np.mean(nis_spoofed):.2f}, median={np.median(nis_spoofed):.2f}")

# %%
# Plot NIS distributions
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

# Histogram
ax = axes[0]
bins = np.linspace(0, 20, 50)
ax.hist(nis_benign, bins=bins, alpha=0.5, label='Benign', density=True)
ax.hist(nis_spoofed, bins=bins, alpha=0.5, label='Spoofed', density=True)
ax.axvline(x=3.84, color='red', linestyle='--', label='χ²(1) 95th pct')
ax.set_xlabel('NIS')
ax.set_ylabel('Density')
ax.set_title('NIS Distribution')
ax.legend()
ax.set_xlim(0, 20)

# CDF (for ROC intuition)
ax = axes[1]
nis_range = np.linspace(0, 50, 200)
benign_cdf = [np.mean(nis_benign <= t) for t in nis_range]
spoofed_cdf = [np.mean(nis_spoofed <= t) for t in nis_range]
ax.plot(nis_range, benign_cdf, label='Benign (want high = TN)')
ax.plot(nis_range, spoofed_cdf, label='Spoofed (want low = TP)')
ax.set_xlabel('Threshold')
ax.set_ylabel('Fraction below threshold')
ax.set_title('CDF by Class')
ax.legend()

plt.tight_layout()
plt.show()

# %% [markdown]
# ## Step 5: ROC Curve and Threshold Selection

# %%
from evaluations.metrics import compute_roc_auc

# Use all non-NaN NIS values
valid = ~np.isnan(scenario.kf_nis)
y_true = scenario.is_spoofed[valid]
scores = scenario.kf_nis[valid]

auc, fpr, tpr, thresholds = compute_roc_auc(y_true, scores)

print(f"AUC: {auc:.4f}")

# Plot ROC curve
plt.figure(figsize=(6, 6))
plt.plot(fpr, tpr, 'b-', linewidth=2, label=f'KF Detector (AUC={auc:.3f})')
plt.plot([0, 1], [0, 1], 'k--', label='Random')
plt.xlabel('False Positive Rate')
plt.ylabel('True Positive Rate')
plt.title('ROC Curve: Kalman Filter Detection')
plt.legend()
plt.grid(True, alpha=0.3)
plt.axis('equal')
plt.xlim(-0.02, 1.02)
plt.ylim(-0.02, 1.02)
plt.show()

# %%
# Find optimal threshold (maximize TPR - FPR)
j_statistic = tpr - fpr
best_idx = np.argmax(j_statistic)
best_threshold = thresholds[best_idx]

print(f"Optimal threshold: {best_threshold:.3f}")
print(f"At this threshold: TPR={tpr[best_idx]:.3f}, FPR={fpr[best_idx]:.3f}")

# %% [markdown]
# ## Summary
#
# **The Kalman Filter detection approach:**
#
# 1. Each receiver maintains a KF per transmitter (identified by serial number)
# 2. For each RX event, compute TX power estimate: $z = RSSI + 10n\log_{10}(d_{claimed})$
# 3. Update KF and compute NIS
# 4. High NIS indicates claimed position inconsistent with RSSI → likely spoofing
#
# **Strengths:**
# - Works with a single receiver
# - Tracks state over time (builds confidence)
# - Principled statistical framework
#
# **Weaknesses:**
# - Requires good path loss model
# - Sensitive to multipath/shadowing
# - Spoofer could adapt TX power to match claimed distance
