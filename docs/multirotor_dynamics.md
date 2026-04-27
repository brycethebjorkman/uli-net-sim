# MultirotorMobility Dynamics Model

This document describes the rigid-body dynamics implemented in
`src/mobility/MultirotorMobility.cc`.

## State and Control Vectors

The state vector $\mathbf{x} \in \mathbb{R}^{12}$ and control input
$\mathbf{u} \in \mathbb{R}^{4}$ are:

$$
\mathbf{x} = \begin{bmatrix}
x \\ y \\ z \\ \dot{x} \\ \dot{y} \\ \dot{z} \\
\phi \\ \theta \\ \psi \\ p \\ q \\ r
\end{bmatrix}, \qquad
\mathbf{u} = \begin{bmatrix}
T \\ \tau_\phi \\ \tau_\theta \\ \tau_\psi
\end{bmatrix}
$$

where $(x, y, z)$ is position in the world frame,
$(\dot{x}, \dot{y}, \dot{z})$ is velocity,
$(\phi, \theta, \psi)$ are Euler angles (roll, pitch, yaw in Z-Y'-X''
convention), $(p, q, r)$ are body-frame angular rates, $T$ is total
thrust (N), and $(\tau_\phi, \tau_\theta, \tau_\psi)$ are differential
rotor-thrust control inputs (N). The effective body-axis torque is
$L\,\tau$, where $L$ is the arm length — see the rotational dynamics
equations below.

## Equations of Motion

### Translational dynamics

The position derivatives are simply the velocities:

$$
\dot{x} = v_x, \quad \dot{y} = v_y, \quad \dot{z} = v_z
$$

The acceleration is determined by gravity and the thrust vector rotated
from the body frame into the world frame via the rotation matrix
$R(\phi, \theta, \psi)$:

$$
\begin{aligned}
\ddot{x} &= \frac{T}{m}(\sin\theta\,\cos\psi\,\cos\phi + \sin\phi\,\sin\psi) \\
\ddot{y} &= \frac{T}{m}(\sin\theta\,\sin\psi\,\cos\phi - \sin\phi\,\cos\psi) \\
\ddot{z} &= -g + \frac{T}{m}\cos\phi\,\cos\theta
\end{aligned}
$$

Here $m$ is the aircraft mass, $g = 9.81\;\text{m/s}^2$ is gravitational
acceleration, and thrust acts along the body $z$-axis (upward in the
body frame).

### Euler angle kinematics

The Euler angle rates relate to the body angular rates $(p, q, r)$
through the standard kinematic equations:

$$
\begin{aligned}
\dot{\phi}   &= p + q\,\sin\phi\,\tan\theta + r\,\cos\phi\,\tan\theta \\
\dot{\theta} &= q\,\cos\phi - r\,\sin\phi \\
\dot{\psi}   &= \frac{q\,\sin\phi + r\,\cos\phi}{\cos\theta}
\end{aligned}
$$

Note: these equations have a singularity at $\theta = \pm 90°$. The
model assumes small-to-moderate pitch angles typical of multirotor
flight.

### Rotational dynamics

The angular rate derivatives follow from Euler's rotational equations
for a rigid body with diagonal inertia tensor
$\text{diag}(I_{xx}, I_{yy}, I_{zz})$:

$$
\begin{aligned}
\dot{p} &= \frac{I_{yy} - I_{zz}}{I_{xx}}\,q\,r + \frac{L}{I_{xx}}\,\tau_\phi \\
\dot{q} &= \frac{I_{zz} - I_{xx}}{I_{yy}}\,p\,r + \frac{L}{I_{yy}}\,\tau_\theta \\
\dot{r} &= \frac{I_{xx} - I_{yy}}{I_{zz}}\,p\,q + \frac{L}{I_{zz}}\,\tau_\psi
\end{aligned}
$$

where $L$ is the arm length (distance from center of mass to each
rotor) and $I_{xx}, I_{yy}, I_{zz}$ are the principal moments of
inertia.

## Physical Parameters

| Parameter | NED name | Default | Unit |
|-----------|----------|---------|------|
| Mass | `mass` | 5 | kg |
| Arm length | `armLength` | 0.5 | m |
| Roll inertia | `Ixx` | 0.5 | kg m^2 |
| Pitch inertia | `Iyy` | 0.5 | kg m^2 |
| Yaw inertia | `Izz` | 0.8 | kg m^2 |
| Drag coefficient | `dragCd` | 1.0 | — |
| Drag reference area | `dragArea` | 0.2 | m^2 |
| Air density | `airDensity` | 1.225 | kg/m^3 |
| Rotational drag | `rotationalDrag` | 3.0 | 1/s |

## Aerodynamic Drag

### Translational drag

A quadratic drag force is applied in the body frame and rotated to
the world frame, matching the model used by [NASA ProgPy](https://github.com/nasa/progpy/blob/master/src/progpy/models/aircraft_model/small_rotorcraft.py) for small rotorcraft:

$$
D_{\text{body},i} = \tfrac{1}{2}\,\rho\,C_d\,A\,v_{\text{body},i}\,|v_{\text{body},i}|
$$

where $\rho$ is air density, $C_d$ is the drag coefficient, $A$ is
the reference frontal area, and $v_{\text{body}}$ is velocity in the
body frame obtained by rotating the world-frame velocity with $R^T$.
The drag force is rotated back to the world frame and subtracted from
the translational acceleration:

$$
\ddot{\mathbf{p}} \mathrel{-}= \frac{R\,\mathbf{D}_{\text{body}}}{m}
$$

Setting `dragArea = 0` disables translational drag entirely.

### Rotational drag

A linear damping term is subtracted from the angular rate derivatives,
following the [ArduPilot SITL](https://github.com/ArduPilot/ardupilot/blob/master/libraries/SITL/SIM_Frame.cpp) approach:

$$
\dot{p} \mathrel{-}= k_{\text{rot}}\,p, \quad
\dot{q} \mathrel{-}= k_{\text{rot}}\,q, \quad
\dot{r} \mathrel{-}= k_{\text{rot}}\,r
$$

where $k_{\text{rot}}$ (`rotationalDrag`, default $3.0 s^{-1}$)
represents the combined aerodynamic damping on the airframe.
ArduPilot uses $\approx 3.33 s^{-1}$
(derived from a $400\,°/s^2$ reference angular acceleration and a
$120\,°/s$ terminal rotation rate: at steady state
$\alpha_{\text{ref}} = k_{\text{rot}}\,\omega_{ss}$).

## Numerical Integration

The equations of motion are integrated using a fourth-order Runge-Kutta
(RK4) scheme. Two time-step parameters control the integration:

- **`dynamicsDt`** (default 1 ms) -- the RK4 sub-step size. Between
  INET `move()` calls, the elapsed time is divided into sub-steps of
  this size.
- **`controlDt`** (default 10 ms) -- the interval at which the Python
  controller is called to update $\mathbf{u}$. The control input is
  held constant between controller calls (zero-order hold).

## Limitations

### No aerodynamic coupling

There are no velocity-dependent torques. On a real quadrotor, horizontal
airflow across the rotor disk creates asymmetric lift (blade flapping)
that produces a pitching/rolling moment opposing the direction of
flight. This means a real quadrotor moving sideways at speed would
experience a restoring torque tending to tilt the vehicle -- an effect
absent from this model.

### No wind or turbulence

The model assumes still air. There is no external wind field or
stochastic turbulence disturbance.

### Euler angle singularity

The kinematic equations use Euler angles with a singularity at
$\theta = \pm 90°$ (gimbal lock). This is acceptable for typical
multirotor operation where pitch angles remain moderate, but the model
will produce numerical errors if pitch approaches $\pm 90°$.

### No ground interaction

There is no ground plane or contact model. The drone can descend to
negative $z$ without constraint. The INET `constraintArea` parameters
are not enforced during dynamics integration.
