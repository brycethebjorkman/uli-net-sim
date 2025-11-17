//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __PY_CALLER_H
#define __PY_CALLER_H

#include <omnetpp.h>
#include <cstdio>
#include <array>
#include <string>
#include <stdexcept>

#define STR_HELPER(x) #x
#define STR(x) STR_HELPER(x)

using namespace omnetpp;

namespace utils
{
    const std::string proj_dir = STR(PROJ_DIR);
    const std::string py = proj_dir + "/.venv/bin/python3";

    static std::string py_call(const std::string script_and_args) {
        std::string cmd = py + " " + script_and_args;
        std::array<char, 4096> buf{};
        std::string out;
        FILE* pipe = popen(cmd.c_str(), "r");
        if (!pipe) throw cRuntimeError("popen() failed for: %s", cmd.c_str());
        while (fgets(buf.data(), (int)buf.size(), pipe)) {
            out.append(buf.data());
        }
        int rc = pclose(pipe);
        if (rc != 0)
            throw cRuntimeError("Python process returned nonzero status: %d", rc);
        EV_INFO << "Python output: " << out << endl;
        return out;
    }

}

#endif
