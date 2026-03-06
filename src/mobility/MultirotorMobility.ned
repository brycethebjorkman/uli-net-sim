//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.mobility;

import inet.mobility.base.MovingMobilityBase;

//
// 6-DoF multirotor dynamics model with optional Python-based control.
//
// Implements the lumped-mass dynamics from Eq 3.2 of the reference paper:
//   state  x = [pos, vel, euler, omega]  (12 elements)
//   control u = {T, tau_phi, tau_theta, tau_psi}
//
// Integrates with RK4 at dynamicsDt resolution.  A Python controller class
// (if configured) is called every controlDt to produce new control inputs.
// Between Python calls, the last control input is held constant.
//
// Without a Python controller, the module applies a default hover thrust
// (T = mass * g, zero torques) so the aircraft stays at its initial position.
//
simple MultirotorMobility extends MovingMobilityBase
{
    parameters:
        @class(MultirotorMobility);

        // Signal declarations and vector recording
        @signal[thrust](type=double);
        @signal[tauPhi](type=double);
        @signal[tauTheta](type=double);
        @signal[tauPsi](type=double);
        @signal[phi](type=double);
        @signal[theta](type=double);
        @signal[psi](type=double);
        @signal[omegaP](type=double);
        @signal[omegaQ](type=double);
        @signal[omegaR](type=double);

        @statistic[thrust](title="Thrust"; source=thrust; record=vector);
        @statistic[tauPhi](title="Torque phi"; source=tauPhi; record=vector);
        @statistic[tauTheta](title="Torque theta"; source=tauTheta; record=vector);
        @statistic[tauPsi](title="Torque psi"; source=tauPsi; record=vector);
        @statistic[phi](title="Roll angle"; source=phi; record=vector);
        @statistic[theta](title="Pitch angle"; source=theta; record=vector);
        @statistic[psi](title="Yaw angle"; source=psi; record=vector);
        @statistic[omegaP](title="Roll rate"; source=omegaP; record=vector);
        @statistic[omegaQ](title="Pitch rate"; source=omegaQ; record=vector);
        @statistic[omegaR](title="Yaw rate"; source=omegaR; record=vector);

        // Initial position (required when initFromDisplayString=false)
        double initialX @unit(m) = default(0m);
        double initialY @unit(m) = default(0m);
        double initialZ @unit(m) = default(0m);

        // Dynamics integration step (should be small for RK4 stability)
        double dynamicsDt @unit(s) = default(0.001s);

        // Python controller call interval
        double controlDt @unit(s) = default(0.01s);

        // Physical parameters
        double mass @unit(kg) = default(5kg);
        double armLength @unit(m) = default(0.5m);
        double Ixx = default(0.5);  // kg*m^2 — moment of inertia about body x-axis
        double Iyy = default(0.5);  // kg*m^2 — moment of inertia about body y-axis
        double Izz = default(0.8);  // kg*m^2 — moment of inertia about body z-axis

        // Initial Euler angles (rad) — phi (roll), theta (pitch), psi (yaw)
        double initialPhi = default(0);
        double initialTheta = default(0);
        double initialPsi = default(0);

        // Initial velocity (m/s)
        double initialVx = default(0);
        double initialVy = default(0);
        double initialVz = default(0);

        // Initial angular rates (rad/s)
        double initialP = default(0);
        double initialQ = default(0);
        double initialR = default(0);

        // Default thrust (N). Use -1 for hover (mass * g). Set to 0 for freefall.
        double defaultThrust = default(-1);

        // Python controller class (empty = hover, no Python)
        string pyClass = default("");

        // Path to PyBridge module
        string pyBridgePath = default("^.^.pyBridge");

        // Accept external messages (GCS commands)
        gates:
            input commandIn @directIn;
}
