//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h must come BEFORE omnetpp.h to avoid macro conflicts.
//

#include "pybridge/PyBridgePy.h"
#include "MultirotorMobility.h"
#include "pybridge/PyBridge.h"

#include "inet/common/INETMath.h"
#include "inet/common/geometry/common/Quaternion.h"

#include <cmath>

Define_Module(MultirotorMobility);

static constexpr double GRAVITY = 9.81;  // m/s^2

// ── Dynamics ────────────────────────────────────────────────────────────────
// lumped-mass 6-DOF model
//
// State:   x = [x, y, z, vx, vy, vz, phi, theta, psi, p, q, r]
// Control: u = [T, tau_phi, tau_theta, tau_psi]

Eigen::Matrix<double, STATE_DIM, 1> MultirotorMobility::dynamics(
    const Eigen::Matrix<double, STATE_DIM, 1>& x,
    const Eigen::Matrix<double, CONTROL_DIM, 1>& u) const
{
    Eigen::Matrix<double, STATE_DIM, 1> dx;

    double phi   = x[PHI];
    double theta = x[THETA];
    // psi unused in derivatives directly but used in acceleration
    double psi   = x[PSI];
    double p     = x[OMEGA_P];
    double q     = x[OMEGA_Q];
    double r     = x[OMEGA_R];

    double T        = u[THRUST];
    double tau_phi   = u[TAU_PHI];
    double tau_theta = u[TAU_THETA];
    double tau_psi   = u[TAU_PSI];

    double sp = std::sin(phi),   cp = std::cos(phi);
    double st = std::sin(theta), ct = std::cos(theta);
    double tt = std::tan(theta);
    double spsi = std::sin(psi), cpsi = std::cos(psi);

    double T_over_m = T / mass;

    // Position derivatives = velocity
    dx[POS_X] = x[VEL_X];
    dx[POS_Y] = x[VEL_Y];
    dx[POS_Z] = x[VEL_Z];

    // Velocity derivatives (translational acceleration)
    dx[VEL_X] = (st * cpsi * cp + sp * spsi) * T_over_m;
    dx[VEL_Y] = (st * spsi * cp - sp * cpsi) * T_over_m;
    dx[VEL_Z] = -GRAVITY + cp * ct * T_over_m;

    // Euler angle derivatives (kinematic equations)
    dx[PHI]   = p + q * sp * tt + r * cp * tt;
    dx[THETA] = q * cp - r * sp;
    dx[PSI]   = q * sp / ct + r * cp / ct;

    // Angular rate derivatives (rotational dynamics)
    dx[OMEGA_P] = (Iyy - Izz) / Ixx * q * r + armLength / Ixx * tau_phi;
    dx[OMEGA_Q] = (Izz - Ixx) / Iyy * p * r + armLength / Iyy * tau_theta;
    dx[OMEGA_R] = (Ixx - Iyy) / Izz * p * r + armLength / Izz * tau_psi;

    return dx;
}

void MultirotorMobility::rk4Step(double dt)
{
    auto k1 = dynamics(state, control);
    auto k2 = dynamics(state + 0.5 * dt * k1, control);
    auto k3 = dynamics(state + 0.5 * dt * k2, control);
    auto k4 = dynamics(state + dt * k3, control);

    state += (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4);
}

// ── Initialization ──────────────────────────────────────────────────────────

void MultirotorMobility::initialize(int stage)
{
    MovingMobilityBase::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        // Read physical parameters
        mass      = par("mass").doubleValueInUnit("kg");
        armLength = par("armLength").doubleValueInUnit("m");
        Ixx       = par("Ixx").doubleValue();
        Iyy       = par("Iyy").doubleValue();
        Izz       = par("Izz").doubleValue();
        dynamicsDt = par("dynamicsDt").doubleValueInUnit("s");
        controlDt  = par("controlDt").doubleValueInUnit("s");

        // Initialize state to zero; position will be set in initializePosition()
        state.setZero();

        // Initial velocity
        state[VEL_X] = par("initialVx").doubleValue();
        state[VEL_Y] = par("initialVy").doubleValue();
        state[VEL_Z] = par("initialVz").doubleValue();

        // Initial Euler angles and angular rates
        state[PHI]     = par("initialPhi").doubleValue();
        state[THETA]   = par("initialTheta").doubleValue();
        state[PSI]     = par("initialPsi").doubleValue();
        state[OMEGA_P] = par("initialP").doubleValue();
        state[OMEGA_Q] = par("initialQ").doubleValue();
        state[OMEGA_R] = par("initialR").doubleValue();

        // Default control
        control.setZero();
        double defaultThrust = par("defaultThrust").doubleValue();
        control[THRUST] = (defaultThrust < 0) ? mass * GRAVITY : defaultThrust;

        nextControlTick = simTime();

        // Register signals for vector recording
        thrustSignal   = registerSignal("thrust");
        tauPhiSignal   = registerSignal("tauPhi");
        tauThetaSignal = registerSignal("tauTheta");
        tauPsiSignal   = registerSignal("tauPsi");
        phiSignal      = registerSignal("phi");
        thetaSignal    = registerSignal("theta");
        psiSignal      = registerSignal("psi");
        omegaPSignal   = registerSignal("omegaP");
        omegaQSignal   = registerSignal("omegaQ");
        omegaRSignal   = registerSignal("omegaR");
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        // Position was set by MobilityBase::initializePosition() via setInitialPosition().
        // Sync it into our state vector.
        state[POS_X] = lastPosition.x;
        state[POS_Y] = lastPosition.y;
        state[POS_Z] = lastPosition.z;

        // Initialize Python controller if configured
        std::string pyClassName = par("pyClass").stdstringValue();
        if (!pyClassName.empty()) {
            cModule *mod = getModuleByPath(par("pyBridgePath").stdstringValue().c_str());
            pyBridge = check_and_cast<PyBridge *>(mod);
            pyHandle = pyBridge->instantiateClass(pyClassName);
        }
    }
}

// ── Message handling ────────────────────────────────────────────────────────

void MultirotorMobility::handleMessage(cMessage *msg)
{
    if (msg->isSelfMessage()) {
        handleSelfMessage(msg);
    }
    else if (msg->arrivedOn("commandIn")) {
        // GCS command — store the command data for the next Python controller call.
        // For now, store as the message name (a JSON string set by GCS).
        latestGcsCommand = msg->getName();
        delete msg;
    }
    else {
        throw cRuntimeError("MultirotorMobility received unexpected message '%s'", msg->getName());
    }
}

// ── Python controller ───────────────────────────────────────────────────────

void MultirotorMobility::callPythonController()
{
    if (pyHandle < 0)
        return;

    PyBridgeImpl *impl = pyBridge->getImpl();
    py::gil_scoped_acquire gil;

    // Build state dict
    py::dict stateDict;
    stateDict["pos"]   = py::make_tuple(state[POS_X], state[POS_Y], state[POS_Z]);
    stateDict["vel"]   = py::make_tuple(state[VEL_X], state[VEL_Y], state[VEL_Z]);
    stateDict["euler"] = py::make_tuple(state[PHI], state[THETA], state[PSI]);
    stateDict["omega"] = py::make_tuple(state[OMEGA_P], state[OMEGA_Q], state[OMEGA_R]);
    stateDict["time"]  = simTime().dbl();

    // Include GCS command if present
    if (!latestGcsCommand.empty()) {
        // Parse the JSON command string from Python side
        stateDict["gcs_command"] = latestGcsCommand;
    }
    else {
        stateDict["gcs_command"] = py::none();
    }

    // Call controller.compute(state)
    py::object result = impl->callMethod(pyHandle, "compute", stateDict);

    // Parse result dict
    if (!result.is_none() && py::isinstance<py::dict>(result)) {
        py::dict d = result.cast<py::dict>();
        if (d.contains("thrust"))
            control[THRUST] = d["thrust"].cast<double>();
        if (d.contains("torque_phi"))
            control[TAU_PHI] = d["torque_phi"].cast<double>();
        if (d.contains("torque_theta"))
            control[TAU_THETA] = d["torque_theta"].cast<double>();
        if (d.contains("torque_psi"))
            control[TAU_PSI] = d["torque_psi"].cast<double>();
    }
}

// ── Recording ───────────────────────────────────────────────────────────────

void MultirotorMobility::recordState()
{
    emit(thrustSignal,   control[THRUST]);
    emit(tauPhiSignal,   control[TAU_PHI]);
    emit(tauThetaSignal, control[TAU_THETA]);
    emit(tauPsiSignal,   control[TAU_PSI]);
    emit(phiSignal,      state[PHI]);
    emit(thetaSignal,    state[THETA]);
    emit(psiSignal,      state[PSI]);
    emit(omegaPSignal,   state[OMEGA_P]);
    emit(omegaQSignal,   state[OMEGA_Q]);
    emit(omegaRSignal,   state[OMEGA_R]);
}

// ── Core movement ───────────────────────────────────────────────────────────

void MultirotorMobility::move()
{
    double elapsed = (simTime() - lastUpdate).dbl();
    if (elapsed <= 0)
        return;

    // Check if a control tick is due
    if (simTime() >= nextControlTick) {
        callPythonController();
        nextControlTick = simTime() + SimTime(controlDt, SIMTIME_S);
    }

    // Integrate dynamics with RK4 sub-steps
    int steps = static_cast<int>(std::ceil(elapsed / dynamicsDt));
    double dt = elapsed / steps;  // actual sub-step size
    for (int i = 0; i < steps; i++) {
        rk4Step(dt);
    }

    // Sync state back to INET fields
    lastPosition.x = state[POS_X];
    lastPosition.y = state[POS_Y];
    lastPosition.z = state[POS_Z];

    lastVelocity.x = state[VEL_X];
    lastVelocity.y = state[VEL_Y];
    lastVelocity.z = state[VEL_Z];

    // Set orientation from Euler angles (INET uses Z-Y'-X" convention)
    lastOrientation = Quaternion(EulerAngles(
        rad(state[PSI]),    // heading (yaw)
        rad(-state[THETA]), // elevation (negative pitch, per INET convention)
        rad(state[PHI])     // bank (roll)
    ));

    // Schedule next change at the next control tick
    nextChange = nextControlTick;

    // Record vectors
    recordState();
}

double MultirotorMobility::getMaxSpeed() const
{
    // Conservative upper bound: max thrust / mass gives max acceleration,
    // but we don't know how long it's been accelerating.
    // Return NaN (unknown) to disable radio medium caching optimization.
    return NaN;
}
