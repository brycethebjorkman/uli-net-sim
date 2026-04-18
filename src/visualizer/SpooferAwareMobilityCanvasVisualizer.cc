//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "SpooferAwareMobilityCanvasVisualizer.h"
#include "SpooferTrailColor.h"

#include "inet/common/figures/TrailFigure.h"

#include <string>

namespace uav_rid {

Define_Module(SpooferAwareMobilityCanvasVisualizer);

using namespace inet::visualizer;
using namespace omnetpp;

void SpooferAwareMobilityCanvasVisualizer::extendMovementTrail(const inet::IMobility *mobility,
    inet::TrailFigure *trailFigure, cFigure::Point position) const
{
    cFigure::Point startPosition;
    cFigure::Point endPosition = position;
    if (trailFigure->getNumFigures() == 0)
        startPosition = position;
    else
        startPosition = static_cast<cLineFigure *>(trailFigure->getFigure(trailFigure->getNumFigures() - 1))->getEnd();
    double dx = startPosition.x - endPosition.x;
    double dy = startPosition.y - endPosition.y;
    if (trailFigure->getNumFigures() == 0 || dx * dx + dy * dy > 1) {
        auto *movementLine = new cLineFigure("movementTrail");
        movementLine->setTags((std::string("movement_trail recent_history ") + tags).c_str());
        movementLine->setTooltip("This line represents the recent movement trail of the mobility model");
        movementLine->setStart(startPosition);
        movementLine->setEnd(endPosition);
        const auto *module = check_and_cast<const cModule *>(mobility);
        movementLine->setLineColor(movementTrailColorForMobility(module, movementTrailLineColorSet));
        movementLine->setLineStyle(movementTrailLineStyle);
        movementLine->setLineWidth(movementTrailLineWidth);
        movementLine->setZoomLineWidth(false);
        trailFigure->addFigure(movementLine);
    }
}

} // namespace uav_rid
