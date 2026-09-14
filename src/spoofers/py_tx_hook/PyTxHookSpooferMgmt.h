//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __PY_TX_HOOK_SPOOFER_MGMT_H
#define __PY_TX_HOOK_SPOOFER_MGMT_H

#include "rid_beacon/RidBeaconMgmt.h"

class PyBridge;

class PyTxHookSpooferMgmt : public RidBeaconMgmt
{
  protected:
    PyBridge *pyBridge = nullptr;
    int pyTxHandle = -1;
    bool waypointsSent = false;

    virtual void initialize(int stage) override;
    virtual bool fillRidMsg(const inet::Ptr<RidBeaconFrame>& body) override;
};

#endif
