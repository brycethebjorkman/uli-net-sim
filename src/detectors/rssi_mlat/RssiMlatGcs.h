//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef _RSSI_MLAT_GCS_H
#define _RSSI_MLAT_GCS_H

#include <omnetpp.h>
#include <map>
#include <vector>

using namespace omnetpp;

class RssiMlatReport;

class RssiMlatGcs : public cSimpleModule, public cListener
{
  protected:
    // Map to store reports: key = (senderSerialNumber, timestamp), value = vector of reports
    std::map<std::pair<int, int64_t>, std::vector<RssiMlatReport*>> reportsByBeacon;

    // Radio medium module
    cModule *radioMedium;

    virtual void initialize() override;
    virtual void handleMessage(cMessage *msg) override;
    virtual void receiveSignal(cComponent *source, simsignal_t signalID, cObject *obj, cObject *details) override;

    // Helper method to call multilateration script
    void runMultilateration(const std::vector<RssiMlatReport*>& reports);
};

#endif
