//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "KalmanFilterDetectMgmt.h"

#include <cmath>

using namespace inet;

Define_Module(KalmanFilterDetectMgmt);

// ---------------------------------------------------------------------
// Predict: constant transmit power model
// ---------------------------------------------------------------------
void KalmanFilterDetectMgmt::predict(TxPowerKF &kf, double Q)
{
    // State transition: x_k = x_{k-1}
    Eigen::MatrixXd F(1,1);
    F(0,0) = 1.0;

    // Process noise covariance
    Eigen::MatrixXd Qm(1,1);
    Qm(0,0) = Q;

    // Predict next state and covariance
    kf.x = F * kf.x;
    kf.P = F * kf.P * F.transpose() + Qm;
}

// ---------------------------------------------------------------------
// Update: measurement z = true_tx_power + noise
// ---------------------------------------------------------------------
void KalmanFilterDetectMgmt::update(TxPowerKF &kf, double z, double R, int serialNum)
{
    // Measurement model: z = H * x + v, where H = 1
    Eigen::MatrixXd H(1,1);
    H(0,0) = 1.0;

    Eigen::MatrixXd Rm(1,1);
    Rm(0,0) = R;

    // Innovation (residual)
    Eigen::VectorXd y = Eigen::VectorXd::Constant(1, z) - H * kf.x;

    // Innovation covariance
    Eigen::MatrixXd S = H * kf.P * H.transpose() + Rm;

    // Kalman gain
    Eigen::MatrixXd K = kf.P * H.transpose() * S.inverse();

    // Update state estimate
    kf.x = kf.x + K * y;

    // Update covariance
    Eigen::MatrixXd I = Eigen::MatrixXd::Identity(1,1);
    kf.P = (I - K * H) * kf.P;

    // ---- Spoof detection logic ----
    double innov = y(0);
    double appliedCorrection = std::abs(K(0,0) * innov);
    double NIS = (innov * innov) / S(0,0);

    EV_INFO << "[Drone " << serialNum << "] "
            << "z=" << z << " dBm, x_est=" << kf.x(0) << " dBm, "
            << "K=" << K(0,0) << ", innov=" << innov
            << ", corr=" << appliedCorrection
            << ", NIS=" << NIS << "\n";

    // Thresholds
    const double CORR_THRESH = 6.0;   // dB
    const double NIS_THRESH = 6.63;   // 99% chi-square (1 dof)

    if (appliedCorrection > CORR_THRESH || NIS > NIS_THRESH) {
        EV_WARN << "⚠️ Potential spoof detected for drone " << serialNum
                << " | Correction=" << appliedCorrection
                << " dB | NIS=" << NIS << std::endl;
    }
}

// ---------------------------------------------------------------------
// Compute "calculated" transmit power using FSPL model
// ---------------------------------------------------------------------
double KalmanFilterDetectMgmt::computeTxPower(const DetectionSample& sample, double pathLossExp, double fMHz)
{
    double dx = sample.txPosX - sample.rxPosX;
    double dy = sample.txPosY - sample.rxPosY;
    double dz = sample.txPosZ - sample.rxPosZ;
    double distance = std::max(std::sqrt(dx * dx + dy * dy + dz * dz), 1e-3);

    // FSPL (in dB): P_tx = P_rx + 32.44 + 20log10(f_MHz) + 10nlog10(d_km)
    double txPowerDbm = sample.power
                      + 32.44
                      + 20.0 * std::log10(fMHz)
                      + 10.0 * pathLossExp * std::log10(distance / 1000.0);

    return txPowerDbm;
}

// ---------------------------------------------------------------------
// Hook for processing received Remote ID messages
// ---------------------------------------------------------------------
void KalmanFilterDetectMgmt::hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm)
{
    // The base class has already collected the sample in detectVector
    // We can use the most recent sample (the one just added)
    if (detectVector.empty())
        return;

    const DetectionSample& sample = detectVector.back();
    runDetectionAlgo(sample);
}

// ---------------------------------------------------------------------
// Main detection logic
// ---------------------------------------------------------------------
void KalmanFilterDetectMgmt::runDetectionAlgo(const DetectionSample& sample)
{
    const double pathLossExp = 2.0;
    const double fMHz = 2400.0;
    const double Q = 0.01; // process noise (dB²)
    const double R = 4.0;  // measurement noise (RSSI variance)

    double z = computeTxPower(sample, pathLossExp, fMHz);

    // Retrieve or initialize this drone's filter
    TxPowerKF &kf = drones[sample.serialNumber];

    if (!kf.initialized) {
        kf.x = Eigen::VectorXd::Constant(1, z);
        kf.P = Eigen::MatrixXd::Constant(1, 1, 10.0);
        kf.initialized = true;
        EV_INFO << "Initialized TxPowerKF for drone " << sample.serialNumber
                << " with initial Tx=" << z << " dBm\n";
        return;
    }

    // KF cycle
    predict(kf, Q);
    update(kf, z, R, sample.serialNumber);
}
