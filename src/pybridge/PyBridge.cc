//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h (which includes pybind11) must come BEFORE
// omnetpp.h to avoid macro conflicts between pybind11 and OMNeT++.
//

#include "PyBridgePy.h"
#include "PyBridge.h"
#include <cstdlib>
#include <filesystem>
#include <sstream>
#include <vector>

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

        // site-packages must match the *embedded* interpreter (linked libpython),
        // not the first pythonX.Y directory under lib/ — lexical / FS order can
        // pick e.g. python3.10 before python3.14 when a stale venv layout exists.
        py::tuple version_info = sys.attr("version_info");
        int pyMajor = version_info[0].cast<int>();
        int pyMinor = version_info[1].cast<int>();
        std::vector<std::string> venvPrefixes;
        auto addPrefix = [&](const std::string& p) {
            if (!p.empty())
                venvPrefixes.push_back(p);
        };

        // Priority:
        // 1) explicit env override, 2) derive from ULI_PYTHON, 3) legacy .venv.
        if (const char* env = std::getenv("ULI_VENV_PREFIX")) {
            addPrefix(env);
        }
        if (const char* envPy = std::getenv("ULI_PYTHON")) {
            std::filesystem::path p(envPy);
            if (p.has_parent_path() && p.parent_path().has_parent_path()) {
                addPrefix(p.parent_path().parent_path().string());
            }
        }
        addPrefix(projDir + "/.venv");

        std::string venvPrefix;
        std::string venvSitePackages;
        std::ostringstream expectedSuffix;
        expectedSuffix << "/lib/python" << pyMajor << "." << pyMinor << "/site-packages";
        for (const auto& prefix : venvPrefixes) {
            std::string candidate = prefix + expectedSuffix.str();
            if (std::filesystem::exists(candidate)) {
                venvPrefix = prefix;
                venvSitePackages = candidate;
                break;
            }
        }
        if (venvSitePackages.empty()) {
            std::ostringstream tried;
            for (size_t i = 0; i < venvPrefixes.size(); ++i) {
                if (i > 0) tried << ", ";
                tried << venvPrefixes[i] << expectedSuffix.str();
            }
            throw cRuntimeError(
                "PyBridge: expected venv site-packages for embedded Python %d.%d. "
                "Tried: %s. "
                "Set ULI_VENV_PREFIX, set ULI_PYTHON, or recreate .venv with matching interpreter.",
                pyMajor, pyMinor, tried.str().c_str());
        }

        sys.attr("prefix") = venvPrefix;
        sys.attr("exec_prefix") = venvPrefix;
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
