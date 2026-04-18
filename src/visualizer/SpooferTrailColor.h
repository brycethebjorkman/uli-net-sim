//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Shared helpers: scenario layout convention is spoofer = host[numHosts-1].
//

#ifndef __SPOOFER_TRAIL_COLOR_H
#define __SPOOFER_TRAIL_COLOR_H

#include <omnetpp.h>
#include "inet/visualizer/util/ColorSet.h"

namespace uav_rid {

/** True if this mobility module belongs to the designated spoofer host (last index). */
inline bool mobilityHostIsDesignatedSpoofer(const omnetpp::cModule *mobilityModule)
{
    if (!mobilityModule)
        return false;
    omnetpp::cModule *host = mobilityModule->getParentModule();
    if (!host)
        return false;
    omnetpp::cModule *network = host->getParentModule();
    if (!network || !network->hasPar("numHosts"))
        return false;
    int nh = network->par("numHosts").intValue();
    return host->getIndex() == nh - 1;
}

/** Movement trail color: fixed red for spoofer; otherwise INET ColorSet by host index (not getId()). */
inline omnetpp::cFigure::Color movementTrailColorForMobility(
    const omnetpp::cModule *mobilityModule,
    const inet::visualizer::ColorSet &movementTrailLineColorSet)
{
    using omnetpp::cFigure;
    if (mobilityHostIsDesignatedSpoofer(mobilityModule))
        return cFigure::parseColor("#ea4335");
    omnetpp::cModule *host = mobilityModule->getParentModule();
    const int hostIdx = host ? host->getIndex() : 0;
    return movementTrailLineColorSet.getColor(hostIdx);
}

} // namespace uav_rid

#endif
