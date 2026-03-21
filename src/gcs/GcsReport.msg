//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

//
// Report message sent from beacon management modules to GcsModule.
// One report per received beacon frame.
//
class GcsReport extends cMessage
{
    int receiverHostId;       // Index of the host that received the beacon
    int senderSerialNumber;   // Serial number from the received beacon
    int64_t ridTimestamp;     // RID message timestamp (ms since sim start)

    // Receiver's actual position
    double rxPosX;
    double rxPosY;
    double rxPosZ;

    // Claimed position from the beacon (may be spoofed)
    double claimedPosX;
    double claimedPosY;
    double claimedPosZ;

    // Claimed velocity from the beacon
    double claimedSpeedVertical;
    double claimedSpeedHorizontal;
    double claimedHeading;

    // RSSI at receiver
    double rssiDbm;

    // KF NIS from C++ Kalman filter (-1 = not available, i.e. host doesn't run KF)
    double kfNis = -1;
}
