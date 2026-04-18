//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __SPOOFER_AWARE_MOBILITY_CANVAS_VISUALIZER_H
#define __SPOOFER_AWARE_MOBILITY_CANVAS_VISUALIZER_H

#include "inet/visualizer/canvas/mobility/MobilityCanvasVisualizer.h"

namespace uav_rid {

class SpooferAwareMobilityCanvasVisualizer : public inet::visualizer::MobilityCanvasVisualizer
{
  protected:
    virtual void extendMovementTrail(const inet::IMobility *mobility, inet::TrailFigure *trailFigure,
        omnetpp::cFigure::Point position) const override;
};

} // namespace uav_rid

#endif
