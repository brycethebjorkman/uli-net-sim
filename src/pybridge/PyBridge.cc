//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h (which includes pybind11) must come BEFORE
// omnetpp.h to avoid macro conflicts between pybind11 and OMNeT++.
//

#include "PyBridgePy.h"
#include "PyBridge.h"
#include <sstream>
#include <filesystem>

#define STR_HELPER(x) #x
#define STR(x) STR_HELPER(x)

Define_Module(PyBridge);

// ── Process-global interpreter ───────────────────────────────────────────────
//
// Many C extension modules (numpy, scipy, torch, …) register global state
// that does not survive Py_Finalize + Py_Initialize.  Even calling
// Py_FinalizeEx at process exit segfaults once such modules are loaded
// (pybind11 internals cleanup accesses freed memory).
//
// We therefore initialize the interpreter once and intentionally never
// finalize it.  On network rebuild only the Python class instances are
// cleared.  The interpreter is leaked at process exit — this is safe
// because the OS reclaims all process memory anyway.

static bool interpreterReady = false;

void PyBridge::initialize()
{
    impl = std::make_unique<PyBridgeImpl>();

    // Start the interpreter once; keep it alive across network rebuilds.
    if (!interpreterReady) {
        py::initialize_interpreter();
        interpreterReady = true;

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

        // Discover the Python version directory dynamically
        std::string venvLib = venvPrefix + "/lib";
        std::string venvSitePackages;
        for (auto& entry : std::filesystem::directory_iterator(venvLib)) {
            if (entry.is_directory() && entry.path().filename().string().rfind("python", 0) == 0) {
                venvSitePackages = entry.path().string() + "/site-packages";
                break;
            }
        }
        if (venvSitePackages.empty())
            venvSitePackages = venvLib + "/python3.14/site-packages";
        py::module_ site = py::module_::import("site");
        site.attr("addsitedir")(venvSitePackages);
    }

    // (Re-)configure sys.path — user modules and extra paths must be at
    // the front so that stale module caches from a previous run don't
    // shadow updated sources.
    py::module_ sys = py::module_::import("sys");
    py::list path = sys.attr("path");

    std::string projDir = STR(PROJ_DIR);

    // Remove previous PROJ_DIR entries (from prior network setup)
    py::list cleanPath;
    for (auto item : path) {
        std::string s = item.cast<std::string>();
        if (s != projDir)
            cleanPath.append(item);
    }
    cleanPath.attr("insert")(0, projDir);
    sys.attr("path") = cleanPath;
    path = cleanPath;

    // Add user-specified paths
    std::string extraPaths = par("pythonPath").stdstringValue();
    if (!extraPaths.empty()) {
        std::istringstream ss(extraPaths);
        std::string token;
        int idx = 1;
        while (std::getline(ss, token, ':')) {
            if (!token.empty()) {
                path.attr("insert")(idx++, token);
            }
        }
    }

    // Reload user modules so that source edits take effect on network rebuild.
    // Only reload top-level packages under PROJ_DIR (pymodules).
    py::module_ importlib = py::module_::import("importlib");
    py::dict modules = sys.attr("modules");
    py::list toReload;
    for (auto item : modules) {
        std::string name = item.first.cast<std::string>();
        if (name.rfind("pymodules", 0) == 0)
            toReload.append(item.first);
    }
    // Delete cached modules so they get re-imported fresh
    for (auto key : toReload)
        PyDict_DelItem(modules.ptr(), key.ptr());

    EV_INFO << "PyBridge initialized. sys.path = " << py::str(path).cast<std::string>() << endl;
}

void PyBridge::handleMessage(cMessage *msg)
{
    throw cRuntimeError("PyBridge does not handle messages");
}

PyBridge::~PyBridge()
{
    // Clear Python instances but do NOT destroy the interpreter.
    // The interpreter lives for the entire process (see globalInterpreter).
    impl.reset();
}

int PyBridge::instantiateClass(const std::string& qualifiedName)
{
    int handle = impl->createInstance(qualifiedName);
    EV_INFO << "PyBridge: instantiated " << qualifiedName << " (handle=" << handle << ")" << endl;
    return handle;
}
