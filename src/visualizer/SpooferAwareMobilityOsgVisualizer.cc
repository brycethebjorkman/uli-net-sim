//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "SpooferAwareMobilityOsgVisualizer.h"
#include "SpooferTrailColor.h"

#include <osg/Geode>

#include "inet/mobility/contract/IMobility.h"
#include "inet/visualizer/osg/util/OsgUtils.h"

namespace uav_rid {

Define_Module(SpooferAwareMobilityOsgVisualizer);

using namespace inet::visualizer;
using namespace omnetpp;

MobilityVisualizerBase::MobilityVisualization *SpooferAwareMobilityOsgVisualizer::createMobilityVisualization(
    inet::IMobility *mobility)
{
    const auto *module = check_and_cast<const cModule *>(mobility);
    auto *trail = new osg::Geode();
    cFigure::Color lineColor = movementTrailColorForMobility(module, movementTrailLineColorSet);
    trail->setStateSet(inet::osg::createStateSet(lineColor, 1.0));
    trail->getOrCreateStateSet()->setMode(GL_LIGHTING, osg::StateAttribute::OFF | osg::StateAttribute::OVERRIDE);
    return new MobilityOsgVisualization(trail, mobility);
}

} // namespace uav_rid
