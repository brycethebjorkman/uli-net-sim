//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "DynamicTrajectorySpooferMgmt.h"

#include "inet/common/ModuleAccess.h"

Define_Module(DynamicTrajectorySpooferMgmt);

void DynamicTrajectorySpooferMgmt::initialize(int stage)
{
    RidBeaconMgmt::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        targetHostIndex = par("targetHostIndex");

        // Build path to target host's mobility module
        // Module hierarchy: network.host[X].wlan[0].mgmt (we are here)
        // So we need ^.^.^ to get to network, then .host[N].mobility
        std::string targetPath = "^.^.^.host[" + std::to_string(targetHostIndex) + "].mobility";

        cModule *targetMobilityModule = getModuleByPath(targetPath.c_str());
        if (!targetMobilityModule) {
            throw cRuntimeError("Cannot find target host mobility at path '%s'. "
                                "Ensure targetHostIndex=%d refers to a valid host.",
                                targetPath.c_str(), targetHostIndex);
        }

        targetMobility = check_and_cast<IMobility*>(targetMobilityModule);
        EV << "DynamicTrajectorySpooferMgmt: will spoof position of host[" << targetHostIndex << "]" << endl;
    }
}

void DynamicTrajectorySpooferMgmt::fillRidMsg(const inet::Ptr<RidBeaconFrame> & body)
{
    // Set timestamp and our own serial number (spoofer's identity)
    auto currentTime = simTime();
    body->setTimestamp(currentTime.inUnit(SimTimeUnit::SIMTIME_MS));
    body->setSerialNumber(serialNumber);

    // Get position and velocity from TARGET drone (spoofed position)
    Coord pos = targetMobility->getCurrentPosition();
    Coord velocity = targetMobility->getCurrentVelocity();

    double posX = pos.getX();
    double posY = pos.getY();
    double posZ = pos.getZ();

    // Compute velocity components (assume X,Y,Z = East,North,Up)
    double speedVertical = velocity.getZ();
    auto horizontal = Coord(velocity.getX(), velocity.getY(), 0.0);
    double speedHorizontal = horizontal.length();
    auto north = Coord(0, 1, 0);
    double heading = north.angle(horizontal) * (180.0 / M_PI);

    body->setPosX(posX);
    body->setPosY(posY);
    body->setPosZ(posZ);
    body->setSpeedVertical(speedVertical);
    body->setSpeedHorizontal(speedHorizontal);
    body->setHeading(heading);

    EV << "DynamicTrajectorySpooferMgmt: broadcasting spoofed position ("
       << posX << ", " << posY << ", " << posZ << ") from host["
       << targetHostIndex << "]" << endl;
}
