//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Based on inet/linklayer/ieee80211/mgmt/Ieee80211MgmtAp.h
//

#ifndef __RID_BEACON_MGMT_H
#define __RID_BEACON_MGMT_H

#include "inet/linklayer/ieee80211/mgmt/Ieee80211MgmtApBase.h"

#include "RidBeaconFrame_m.h"

using namespace inet;
using namespace inet::ieee80211;

class RidBeaconMgmt : public Ieee80211MgmtApBase, protected cListener
{
  protected:
    std::string ssid;
    int serialNumber;
    int channelNumber = -1;
    simtime_t beaconInterval;
    simtime_t startupJitter;
    bool transmitBeacon;
    bool oneOff;
    Ieee80211SupportedRatesElement supportedRates;
    cMessage *beaconTimer = nullptr;
    cMessage *terminateMsg = nullptr;
    cModule *medium = nullptr;

    struct OutputVectors {
        cOutVector power;
        cOutVector time;
        cOutVector timestamp;
        cOutVector packetId;
        cOutVector serialNumber;
        cOutVector txPosX;
        cOutVector txPosY;
        cOutVector txPosZ;
        cOutVector txPower;
        cOutVector rxPosX;
        cOutVector rxPosY;
        cOutVector rxPosZ;
        cOutVector txSpeedVertical;
        cOutVector txSpeedHorizontal;
        cOutVector txHeading;
        cOutVector rxSpeedVertical;
        cOutVector rxSpeedHorizontal;
        cOutVector rxHeading;
        cOutVector rxMyPosX;
        cOutVector rxMyPosY;
        cOutVector rxMyPosZ;
        cOutVector rxMySpeedVertical;
        cOutVector rxMySpeedHorizontal;
        cOutVector rxMyHeading;
    } recvec;

    struct DetectionSample {
        double power;
        double timestamp;
        int serialNumber;

        double txPosX;
        double txPosY;
        double txPosZ;

        double rxPosX;
        double rxPosY;
        double rxPosZ;

        double txSpeedVertical;
        double txSpeedHorizontal;
        double txHeading;

        double rxSpeedVertical;
        double rxSpeedHorizontal;
        double rxHeading;


    };

    std::vector<DetectionSample> detectVector;

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
    virtual void receiveSignal(cComponent *src, simsignal_t id, cObject *obj, cObject *details) override;

    /** Utility function: set fields in the given frame and send it out to the address */
    virtual void sendManagementFrame(const char *name, const Ptr<Ieee80211MgmtFrame>& body, int subtype, const MacAddress& destAddr);

    /** Utility function: creates and sends a beacon frame */
    virtual void sendBeacon();

    /** Utility function: fills in Remote ID message fields */
    virtual void fillRidMsg(const inet::Ptr<RidBeaconFrame> & body);

    /** Utility function: handles a received beacon frame */
    virtual void handleBeaconFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override;

    /** Utility function: hook for derived classes to process received Remote ID message */
    virtual void hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm) {};

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
