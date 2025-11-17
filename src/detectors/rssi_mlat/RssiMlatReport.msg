//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

//
// Report message sent from RssiMlatMgmt to RssiMlatGcs
// Contains information about a received beacon
//
class RssiMlatReport extends cMessage
{
    int receiverHostId;       // ID of the host that received the beacon
    int senderSerialNumber;   // Serial number from the received beacon
    double rssi;              // Received signal strength (dBm)
    double txPosX;            // Transmitted position X
    double txPosY;            // Transmitted position Y
    double txPosZ;            // Transmitted position Z
    double rxPosX;            // Receiver position X
    double rxPosY;            // Receiver position Y
    double rxPosZ;            // Receiver position Z
    int64_t timestamp;        // Timestamp from the beacon
}
