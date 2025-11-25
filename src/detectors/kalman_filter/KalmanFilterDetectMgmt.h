//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
#ifndef __KALMAN_FILTER_DETECT_MGMT_H
#define __KALMAN_FILTER_DETECT_MGMT_H

#include "rid_beacon/RidBeaconMgmt.h"

#include <Eigen/Dense>
#include <unordered_map>

using namespace inet;
using namespace inet::ieee80211;

// 1D Kalman Filter per drone (Tx power estimation)
struct TxPowerKF {
    Eigen::VectorXd x;   // state vector (1x1) -> [Tx_power_dBm]
    Eigen::MatrixXd P;   // covariance (1x1)
    bool initialized = false;
    simtime_t lastUpdate = SIMTIME_ZERO;
};

class KalmanFilterDetectMgmt : public RidBeaconMgmt
{
  protected:
    // One Kalman filter per drone (keyed by serial number)
    std::unordered_map<int, TxPowerKF> drones;

    // Core filter functions
    void predict(TxPowerKF &kf, double Q);
    void update(TxPowerKF &kf, double z, double R, int serialNum);

    // Utility function: compute Tx power (measurement) from RSSI + FSPL
    double computeTxPower(const DetectionSample& sample, double pathLossExp, double fMHz);

    // Main detection logic
    virtual void runDetectionAlgo(const DetectionSample& sample);

    // Hook for processing received Remote ID messages
    virtual void hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm) override;
};

#endif
