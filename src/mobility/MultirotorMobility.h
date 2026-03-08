//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __MULTIROTOR_MOBILITY_H
#define __MULTIROTOR_MOBILITY_H

#include <omnetpp.h>
#include "inet/mobility/base/MovingMobilityBase.h"
#include <Eigen/Dense>

using namespace omnetpp;
using namespace inet;

class PyBridge;

// State vector indices
enum StateIdx {
    POS_X = 0, POS_Y, POS_Z,       // position (m)
    VEL_X, VEL_Y, VEL_Z,           // velocity (m/s)
    PHI, THETA, PSI,                // Euler angles (rad): roll, pitch, yaw
    OMEGA_P, OMEGA_Q, OMEGA_R,     // angular rates (rad/s)
    STATE_DIM = 12
};

// Control input indices
enum ControlIdx {
    THRUST = 0,                     // N
    TAU_PHI, TAU_THETA, TAU_PSI,   // Nm
    CONTROL_DIM = 4
};

//
// 6-DoF multirotor mobility with RK4 integration and optional Python control.
//
class MultirotorMobility : public MovingMobilityBase
{
  protected:
    // Physical parameters
    double mass;
    double armLength;
    double Ixx, Iyy, Izz;

    // Integration
    double dynamicsDt;
    double controlDt;
    simtime_t nextControlTick;

    // State and control
    Eigen::Matrix<double, STATE_DIM, 1> state;
    Eigen::Matrix<double, CONTROL_DIM, 1> control;

    // Latest GCS command (stored as raw JSON string, passed to Python)
    std::string latestGcsCommand;

    // Python bridge
    PyBridge *pyBridge = nullptr;
    int pyHandle = -1;  // handle into PyBridge instance table

    // Vector recording
    simsignal_t thrustSignal;
    simsignal_t tauPhiSignal, tauThetaSignal, tauPsiSignal;
    simsignal_t phiSignal, thetaSignal, psiSignal;
    simsignal_t omegaPSignal, omegaQSignal, omegaRSignal;

    // Dynamics: compute state derivative dx/dt = f(x, u)
    Eigen::Matrix<double, STATE_DIM, 1> dynamics(
        const Eigen::Matrix<double, STATE_DIM, 1>& x,
        const Eigen::Matrix<double, CONTROL_DIM, 1>& u) const;

    // RK4 integration step
    void rk4Step(double dt);

    // Call Python controller to get new control inputs
    void callPythonController();

    // Record state and control vectors
    void recordState();

    virtual void initialize(int stage) override;
    virtual void handleMessage(cMessage *msg) override;
    virtual void move() override;
    virtual void orient() override {} // orientation set from dynamics in move()

  public:
    MultirotorMobility() {}
    virtual double getMaxSpeed() const override;
};

#endif
