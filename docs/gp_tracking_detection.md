# GP-Tracking Spoofing Detection

A single detector drone monitors a target transmitter's Remote ID (RID)
beacons. Three components operate on each received beacon: a **Propagation
GP** that learns the geometry-to-RSSI mapping, a **CUSUM detector** that
tests for spoofing on the GP's prediction residuals, and an **active
planner** that steers the detector to positions that maximise the GP's
information gain. A secondary **Declaration GP** forecasts the target's
next declared position to support the planner.

## 1 Propagation GP

### 1.1 Feature space

Each beacon provides a claimed transmitter position
$\mathbf{p}_{\text{claim}}$ and the detector's own position
$\mathbf{p}_{\text{det}}$. The input feature is

$$
\mathbf{u} = \bigl(\log_{10} d,\; \Delta z\bigr),
\qquad
d = \lVert \mathbf{p}_{\text{claim}} - \mathbf{p}_{\text{det}} \rVert,
\quad
\Delta z = p_{\text{claim},z} - p_{\text{det},z}.
$$

Observations with $d < 1\,\text{m}$ are discarded.

### 1.2 Mean function

The mean encodes a log-distance path-loss model:

$$
m(\mathbf{u}) = P_0 - 10\,\gamma\,u_1,
$$

where $P_0$ (dBm) is a reference power and $\gamma$ is the path-loss
exponent. Both are free hyperparameters.

### 1.3 Kernel

The covariance function is a Matern-5/2 kernel with automatic relevance
determination (ARD) --- one length scale per input dimension:

$$
k(\mathbf{u}, \mathbf{u}')
= \sigma_f^2
  \Bigl(1 + \sqrt{5}\,r + \tfrac{5}{3}\,r^2\Bigr)
  \exp\!\bigl(-\sqrt{5}\,r\bigr),
\qquad
r = \sqrt{\sum_{j=1}^{2} \frac{(u_j - u_j')^2}{\ell_j^2}}.
$$

The hyperparameter vector is therefore
$\boldsymbol{\theta} = (P_0,\,\gamma,\,\sigma_f^2,\,\ell_1,\,\ell_2,\,\sigma_n^2)$,
where $\sigma_n^2$ is the observation noise variance.

### 1.4 Posterior prediction

Given $n$ training pairs $\{(\mathbf{u}_i, y_i)\}$ with
$\mathbf{K}_{ij} = k(\mathbf{u}_i, \mathbf{u}_j)$ and
$\mathbf{A} = \mathbf{K} + \sigma_n^2 \mathbf{I}$:

$$
\mu_* = m(\mathbf{u}_*) + \mathbf{k}_*^\top \mathbf{A}^{-1}(\mathbf{y} - \mathbf{m}),
$$

$$
\sigma_*^2 = k(\mathbf{u}_*, \mathbf{u}_*) + \sigma_n^2 - \mathbf{k}_*^\top \mathbf{A}^{-1} \mathbf{k}_*,
$$

where $\mathbf{k}_* = [k(\mathbf{u}_i, \mathbf{u}_*)]_{i=1}^n$.
The predictive variance $\sigma_*^2$ includes the noise term because the
detection statistic compares a *noisy observation* against the predictive
distribution.

### 1.5 Hyperparameter optimisation

All six hyperparameters are jointly optimised by maximising the log
marginal likelihood

$$
\log p(\mathbf{y} \mid \mathbf{U}, \boldsymbol{\theta})
= -\tfrac{1}{2}\mathbf{r}^\top \mathbf{A}^{-1}\mathbf{r}
  - \tfrac{1}{2}\log|\mathbf{A}|
  - \tfrac{n}{2}\log 2\pi,
\qquad
\mathbf{r} = \mathbf{y} - \mathbf{m},
$$

via L-BFGS-B with box constraints. Optimisation runs after every new
observation, warm-starting from the previous solution.

### 1.6 Sliding window

To bound computation at $O(W^3)$ per beacon, only the most recent $W$
observations are retained (default $W = 200$). Older observations are
discarded when a new one is added.


## 2 CUSUM Spoofing Detector

### 2.1 Standardised squared residual

For each beacon $k$ (after a warm-up of $k_{\min}$ observations), the GP
predicts mean $\mu_k$ and variance $\sigma_k^2$ *before* the observation
is incorporated. The standardised squared residual is

$$
s_k = \frac{(y_k - \mu_k)^2}{\sigma_k^2}.
$$

Under the null hypothesis (honest transmitter with a well-specified
model), $s_k \sim \chi^2(1)$ with $\mathbb{E}[s_k] = 1$.

To guard against single-observation spikes from model mismatch, the
statistic is capped:

$$
\bar{s}_k = \min(s_k,\; s_{\max}).
$$

### 2.2 CUSUM recursion

The one-sided CUSUM accumulates evidence of a persistent mean shift:

$$
C_k = \max\!\bigl(0,\; C_{k-1} + \bar{s}_k - \beta\bigr),
\qquad C_0 = 0.
$$

The allowance $\beta > 1$ ensures that, under the null, the expected
increment $\mathbb{E}[\bar{s}_k] - \beta < 0$ keeps $C_k$ near zero.

### 2.3 Detection rule

Spoofing is declared the first time

$$
C_k > h.
$$

The threshold $h$ controls the trade-off between detection delay and
false-alarm rate.  Larger $h$ tolerates more accumulated evidence before
declaring, reducing false alarms at the cost of slower detection.

### 2.4 Default parameters

| Symbol | Default | Role |
|--------|---------|------|
| $k_{\min}$ | 8 | Warm-up observations before detection begins |
| $\beta$ | 2.0 | Per-step allowance (null drift $= 1 - \beta = -1$) |
| $s_{\max}$ | 8.0 | Cap on individual $s_k$ |
| $h$ | 25.0 | CUSUM detection threshold |


## 3 Active Trajectory Planning

After each beacon the planner selects the detector's next position to
maximise the propagation GP's information gain, accelerating the rate at
which the GP can distinguish honest from spoofed transmissions.

### 3.1 Candidate generation

A set of candidate positions is generated within the detector's
reachable ball $\Delta_{\max} = v_{\text{cruise}} \cdot T_b$, where
$T_b$ is the beacon interval. The candidates are the current position
(hold) plus 8 compass headings at distance $\Delta_{\max}$, each
replicated at several altitude offsets.

### 3.2 Predicted next declared position

A Declaration GP (Section 4) predicts the target's next declared
position $\hat{\mathbf{p}}_{\text{claim}}(t + T_b)$. For each candidate
detector position $\mathbf{p}_c$, the corresponding propagation-GP
feature is

$$
\mathbf{u}_c = \bigl(\log_{10}\lVert\hat{\mathbf{p}}_{\text{claim}} - \mathbf{p}_c\rVert,\;
\hat{p}_{\text{claim},z} - p_{c,z}\bigr).
$$

### 3.3 Integrated variance reduction

The score for candidate $\mathbf{u}_c$ measures how much the posterior
variance of the propagation GP would decrease across a fixed reference
grid $\mathcal{R} = \{\mathbf{u}_r^{(j)}\}_{j=1}^M$ if an observation
were taken at $\mathbf{u}_c$:

$$
\text{IVR}(\mathbf{u}_c)
= \sum_{j=1}^{M}
  \frac{\text{Cov}(\mathbf{u}_r^{(j)},\, \mathbf{u}_c \mid \mathcal{D})^2}
       {\text{Var}(\mathbf{u}_c \mid \mathcal{D})}.
$$

This is a closed-form quantity depending only on the current GP
posterior, not on the (unknown) observation value. The candidate with the
highest IVR is selected and a steering command is issued to the detector.


## 4 Declaration GP

The Declaration GP forecasts the target's future claimed position so the
planner can anticipate where the next beacon will originate.

Three independent scalar GPs (one per spatial axis) regress position
against time using a sliding window of the $N_g$ most recent declared
positions. Each uses:

- **Mean function:** linear extrapolation from the last two observations,

$$
m_j(t) = p_j^{(n)} + \frac{p_j^{(n)} - p_j^{(n-1)}}{t_n - t_{n-1}}(t - t_n).
$$

- **Kernel:** squared exponential (RBF), $k(t, t') = \sigma_g^2 \exp\!\bigl(-\frac{(t-t')^2}{2\ell_g^2}\bigr)$.

The one-step-ahead prediction $\hat{\mathbf{p}}_{\text{claim}}(t + T_b)$
provides the mean; the variance is not currently used by the planner.


## 5 Per-Beacon Processing Order

Each received beacon triggers the following steps in order:

1. **Predict** --- query the propagation GP at the new feature $\mathbf{u}_k$ (before updating).
2. **Detect** --- compute $s_k$, cap it, update the CUSUM $C_k$, check against $h$.
3. **Update propagation GP** --- add $(\mathbf{u}_k, y_k)$ and reoptimise hyperparameters.
4. **Update declaration GP** --- record the new claimed position.
5. **Plan** --- generate candidates, score by IVR, issue steering command.

Predicting before updating ensures that the detection statistic tests
each observation against a model that has not yet seen it.
