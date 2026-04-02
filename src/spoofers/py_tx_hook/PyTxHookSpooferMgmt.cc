//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h must come BEFORE omnetpp.h to avoid macro conflicts.
//

#include "pybridge/PyBridgePy.h"
#include "PyTxHookSpooferMgmt.h"
#include "pybridge/PyBridge.h"

Define_Module(PyTxHookSpooferMgmt);

void PyTxHookSpooferMgmt::initialize(int stage)
{
    RidBeaconMgmt::initialize(stage);

    if (stage == INITSTAGE_SINGLE_MOBILITY) {
        std::string pyTxClassName = par("pyTxClass").stdstringValue();
        cModule *mod = getModuleByPath(par("pyBridgePath").stdstringValue().c_str());
        pyBridge = check_and_cast<PyBridge *>(mod);
        pyTxHandle = pyBridge->instantiateClass(pyTxClassName);
    }
}

void PyTxHookSpooferMgmt::fillRidMsg(const inet::Ptr<RidBeaconFrame>& body)
{
    // Fill with true position first
    RidBeaconMgmt::fillRidMsg(body);

    // Call Python hook to modify beacon fields
    PyBridgeImpl *impl = pyBridge->getImpl();
    py::gil_scoped_acquire gil;

    py::dict txState;
    txState["pos"]     = py::make_tuple(body->getPosX(), body->getPosY(), body->getPosZ());
    txState["vel"]     = py::make_tuple(body->getSpeedVertical(),
                                        body->getSpeedHorizontal(),
                                        body->getHeading());
    txState["serial"]  = body->getSerialNumber();
    txState["time"]    = simTime().dbl();

    // One-shot delivery of waypoints (parsed from mobility's XML script).
    // Works with both TurtleMobility (turtleScript) and MultirotorMobility
    // (waypointScript) since both use <set>/<moveto> XML format.
    if (!waypointsSent) {
        waypointsSent = true;
        py::list wpList;
        auto host = getContainingNode(this);
        auto mobility = host->getSubmodule("mobility");
        if (mobility) {
            cXMLElement *wpXml = nullptr;
            if (mobility->hasPar("waypointScript"))
                wpXml = mobility->par("waypointScript").xmlValue();
            else if (mobility->hasPar("turtleScript"))
                wpXml = mobility->par("turtleScript").xmlValue();

            if (wpXml) {
                double wpSpeed = 10.0;
                for (auto *child = wpXml->getFirstChild(); child;
                     child = child->getNextSibling()) {
                    const char *tag = child->getTagName();
                    if (strcmp(tag, "set") == 0 || strcmp(tag, "moveto") == 0) {
                        double x = child->getAttribute("x") ? atof(child->getAttribute("x")) : 0;
                        double y = child->getAttribute("y") ? atof(child->getAttribute("y")) : 0;
                        double z = child->getAttribute("z") ? atof(child->getAttribute("z")) : 0;
                        if (strcmp(tag, "set") == 0 && child->getAttribute("speed"))
                            wpSpeed = atof(child->getAttribute("speed"));
                        py::dict wp;
                        wp["x"] = x; wp["y"] = y; wp["z"] = z; wp["speed"] = wpSpeed;
                        wpList.append(wp);
                    }
                }
            }
        }
        txState["waypoints"] = wpList;
    }

    py::object result = impl->callMethod(pyTxHandle, "on_rid_tx", txState);

    if (!result.is_none() && py::isinstance<py::dict>(result)) {
        py::dict d = result.cast<py::dict>();
        if (d.contains("pos")) {
            py::tuple pos = d["pos"].cast<py::tuple>();
            body->setPosX(pos[0].cast<double>());
            body->setPosY(pos[1].cast<double>());
            body->setPosZ(pos[2].cast<double>());
        }
        if (d.contains("vel")) {
            py::tuple vel = d["vel"].cast<py::tuple>();
            body->setSpeedVertical(vel[0].cast<double>());
            body->setSpeedHorizontal(vel[1].cast<double>());
            body->setHeading(vel[2].cast<double>());
        }
    }
}
