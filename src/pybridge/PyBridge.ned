//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.pybridge;

//
// Owns the embedded Python interpreter (via pybind11).
// One instance per network. Other modules use this to instantiate
// Python classes and call methods for control/detection/spoofing.
//
simple PyBridge
{
    parameters:
        @class(PyBridge);
        @display("i=misc/globe");
        string pythonPath = default("");  // additional sys.path entries (colon-separated)
}
