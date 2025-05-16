//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Based on inet/linklayer/ieee80211/mgmt/Ieee80211MgmtAp.h
//

#ifndef __RID_BEACON_MGMT_H
#define __RID_BEACON_MGMT_H

#include "inet/linklayer/ieee80211/mgmt/Ieee80211MgmtApBase.h"

using namespace inet;
using namespace inet::ieee80211;

class RidBeaconMgmt : public Ieee80211MgmtApBase, protected cListener
{
  protected:
    std::string ssid;
    int serialNumber;
    int channelNumber = -1;
    simtime_t beaconInterval;
    Ieee80211SupportedRatesElement supportedRates;
    cMessage *beaconTimer = nullptr;

    struct OutputVectors {
        cOutVector power;
        cOutVector time;
        cOutVector timestamp;
        cOutVector packetId;
        cOutVector serialNumber;
        cOutVector txPosX;
        cOutVector txPosY;
        cOutVector txPosZ;
        cOutVector rxPosX;
        cOutVector rxPosY;
        cOutVector rxPosZ;
    } recvec;

  public:
    RidBeaconMgmt() {}
    virtual ~RidBeaconMgmt();

  protected:
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void initialize(int) override;

    /** Implements abstract Ieee80211MgmtBase method */
    virtual void handleTimer(cMessage *msg) override;

    /** Called by the signal handler whenever a change occurs we're interested in */
    virtual void receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details) override;

    /** Utility function: set fields in the given frame and send it out to the address */
    virtual void sendManagementFrame(const char *name, const Ptr<Ieee80211MgmtFrame>& body, int subtype, const MacAddress& destAddr);

    /** Utility function: creates and sends a beacon frame */
    virtual void sendBeacon();

    /** Utility function: handles a received beacon frame */
    virtual void handleBeaconFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override;

    /** lifecycle support */
    //@{
    virtual void start() override;
    virtual void stop() override;
    //@}

    /** Unused overrides of base class */
    //@{
    virtual void handleAssociationRequestFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleAssociationResponseFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleAuthenticationFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleCommand(int msgkind, cObject *ctrl) override {};
    virtual void handleDeauthenticationFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleDisassociationFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleReassociationRequestFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleReassociationResponseFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleProbeRequestFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    virtual void handleProbeResponseFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override {};
    //@}
};

#endif
