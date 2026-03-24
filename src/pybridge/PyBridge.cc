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

    // Activate the .venv inside the embedded interpreter.
    //
    // pybind11's scoped_interpreter inherits the system Python's prefix
    // (/usr), so sys.prefix == sys.base_prefix == "/usr".  Packages
    // installed in the venv (numpy, scipy) need sys.prefix pointing at
    // the venv so that their C extensions resolve correctly.
    //
    // We replicate what the venv's activate_this.py does:
    //   1. Set sys.prefix / sys.exec_prefix to the venv root.
    //   2. Re-run site.addsitedir() to pick up .venv/lib/.../site-packages.
    // sys.base_prefix stays at /usr so the stdlib is still found.
    py::module_ sys = py::module_::import("sys");
    std::string projDir = STR(PROJ_DIR);
    std::string venvPrefix = projDir + "/.venv";
    sys.attr("prefix") = venvPrefix;
    sys.attr("exec_prefix") = venvPrefix;

    // Add .venv site-packages via site.addsitedir() which also processes
    // .pth files (e.g. for editable pip installs).
    std::string venvSitePackages = venvPrefix + "/lib/python3.10/site-packages";
    py::module_ site = py::module_::import("site");
    site.attr("addsitedir")(venvSitePackages);

    // Configure sys.path
    py::list path = sys.attr("path");

    // Add project directory at the front (for user modules like pymodules/)
    path.attr("insert")(0, projDir);

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
