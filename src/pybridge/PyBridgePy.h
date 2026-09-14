//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Include this header ONLY from .cc files that need direct pybind11 access.
// It must be included BEFORE omnetpp.h or any OMNeT++ headers to avoid
// macro conflicts.
//

#ifndef __PYBRIDGE_PY_H
#define __PYBRIDGE_PY_H

#include <pybind11/embed.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>
#include <string>

namespace py = pybind11;

struct PyBridgeImpl {
    std::vector<py::object> instances;  // Python class instances by handle

    py::object& getInstance(int handle) {
        return instances.at(handle);
    }

    // Import module, instantiate class, return handle
    int createInstance(const std::string& qualifiedName) {
        py::gil_scoped_acquire gil;

        auto lastDot = qualifiedName.rfind('.');
        if (lastDot == std::string::npos)
            throw std::runtime_error(
                "PyBridge: qualifiedName must be 'module.ClassName', got '" + qualifiedName + "'");

        std::string modulePath = qualifiedName.substr(0, lastDot);
        std::string className = qualifiedName.substr(lastDot + 1);

        py::module_ mod = py::module_::import(modulePath.c_str());
        py::object cls = mod.attr(className.c_str());
        py::object instance = cls();

        int handle = static_cast<int>(instances.size());
        instances.push_back(std::move(instance));
        return handle;
    }

    // Call a method on an instance, passing a py::dict, returning py::object
    template<typename... Args>
    py::object callMethod(int handle, const char* method, Args&&... args) {
        py::gil_scoped_acquire gil;
        return instances.at(handle).attr(method)(std::forward<Args>(args)...);
    }
};

#endif
