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

// VENV_PREFIX is injected by src/makefrag (-DVENV_PREFIX=<path>). If it is
// undefined here, makefrag did not run for this compile — meaning the IDE
// Makefile is stale and the binary is also being linked against the default
// (system) libpython rather than the venv's. Fail loudly: regenerate the IDE
// Makefile via Project → Clean → Build All (or rerun scripts/build.sh).
#ifndef VENV_PREFIX
#error "VENV_PREFIX undefined: src/makefrag was not processed during build. " \
       "Regenerate the Makefile (IDE: Project → Clean → Build All) or rerun scripts/build.sh."
#endif

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
        // Tell CPython where the venv's python3 lives. CPython's startup
        // logic reads pyvenv.cfg next to that executable and configures
        // sys.prefix / sys.base_prefix / sys.path itself, then site.py adds
        // <venv>/lib/pythonX.Y/site-packages — exactly like running
        // `<venv>/bin/python` from a shell. No manual prefix patching.
        //
        // VENV_PREFIX is baked at compile time by src/makefrag from the
        // same python3 whose libpython is linked into this binary, so the
        // executable path and libpython cannot disagree.
        std::string venvPython = std::string(STR(VENV_PREFIX)) + "/bin/python3";

        PyConfig config;
        PyConfig_InitPythonConfig(&config);
        config.parse_argv = 0;
        PyStatus status = PyConfig_SetBytesString(&config, &config.executable, venvPython.c_str());
        if (PyStatus_Exception(status)) {
            PyConfig_Clear(&config);
            throw cRuntimeError("PyBridge: PyConfig_SetBytesString(executable=%s) failed: %s",
                                venvPython.c_str(), status.err_msg ? status.err_msg : "unknown");
        }
        py::initialize_interpreter(&config);
        interpreterReady = true;
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

    // Qtenv draws red sendDirect line animations for WirelessSignal deliveries between
    // hosts; that is independent of INET's mediumVisualizer. Disable at the network
    // root when BasicUav (or any network) sets suppressQtenvWirelessAnimations.
    cModule *root = getSimulation()->getSystemModule();
    if (root->hasPar("suppressQtenvWirelessAnimations")
        && root->par("suppressQtenvWirelessAnimations").boolValue()) {
        root->setBuiltinAnimationsAllowed(false);
    }

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
