//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __PYBRIDGE_H
#define __PYBRIDGE_H

#include <omnetpp.h>
#include <memory>
#include <string>

using namespace omnetpp;

// Forward declaration — pybind11 types stay out of this header to avoid
// conflicts with OMNeT++ macros.
struct PyBridgeImpl;

//
// Owns the embedded Python interpreter (via pybind11). One per network.
// Provides API for other modules to instantiate Python classes and call methods.
//
// Other modules include PyBridge.h (no pybind11 dependency) and call
// methods that return opaque handles. The actual pybind11 types are only
// visible inside PyBridge.cc and to callers that explicitly include pybind11.
//
class PyBridge : public cSimpleModule
{
  protected:
    std::unique_ptr<PyBridgeImpl> impl;

    virtual void initialize() override;
    virtual void handleMessage(cMessage *msg) override;
    virtual ~PyBridge();

  public:
    // Import a module and instantiate a class (no-arg constructor).
    // qualifiedName is "package.module.ClassName"
    // Returns an opaque handle (index into internal table).
    int instantiateClass(const std::string& qualifiedName);

    // Call a method on a Python object identified by handle.
    // Takes a JSON-like dict as input, returns a dict.
    // The actual pybind11 call happens inside the .cc file.
    //
    // For callers that include pybind11 directly, use the pybind11 API below.
    // (Declared in PyBridgePy.h)

    // Get the impl for direct pybind11 access (only include from .cc files
    // that also include pybind11 headers).
    PyBridgeImpl* getImpl() { return impl.get(); }
};

#endif
