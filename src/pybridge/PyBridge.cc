//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h (which includes pybind11) must come BEFORE
// omnetpp.h to avoid macro conflicts between pybind11 and OMNeT++.
//

#include "PyBridgePy.h"
#include "PyBridge.h"
#include <sstream>

#define STR_HELPER(x) #x
#define STR(x) STR_HELPER(x)

Define_Module(PyBridge);

void PyBridge::initialize()
{
    impl = std::make_unique<PyBridgeImpl>();

    // Start the Python interpreter
    impl->interpreter = std::make_unique<py::scoped_interpreter>();

    // Configure sys.path
    py::module_ sys = py::module_::import("sys");
    py::list path = sys.attr("path");

    // Add project directory (for user modules)
    std::string projDir = STR(PROJ_DIR);
    path.attr("insert")(0, projDir);

    // Add .venv site-packages so users can import pip packages
    std::string venvSitePackages = projDir + "/.venv/lib/python3.10/site-packages";
    path.attr("insert")(1, venvSitePackages);

    // Add user-specified paths
    std::string extraPaths = par("pythonPath").stdstringValue();
    if (!extraPaths.empty()) {
        std::istringstream ss(extraPaths);
        std::string token;
        int idx = 2;
        while (std::getline(ss, token, ':')) {
            if (!token.empty()) {
                path.attr("insert")(idx++, token);
            }
        }
    }

    EV_INFO << "PyBridge initialized. sys.path = " << py::str(path).cast<std::string>() << endl;
}

void PyBridge::handleMessage(cMessage *msg)
{
    throw cRuntimeError("PyBridge does not handle messages");
}

PyBridge::~PyBridge()
{
    impl.reset();
}

int PyBridge::instantiateClass(const std::string& qualifiedName)
{
    int handle = impl->createInstance(qualifiedName);
    EV_INFO << "PyBridge: instantiated " << qualifiedName << " (handle=" << handle << ")" << endl;
    return handle;
}
