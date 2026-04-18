//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __SPOOFER_AWARE_MOBILITY_OSG_VISUALIZER_H
#define __SPOOFER_AWARE_MOBILITY_OSG_VISUALIZER_H

#include "inet/visualizer/osg/mobility/MobilityOsgVisualizer.h"

namespace uav_rid {

class SpooferAwareMobilityOsgVisualizer : public inet::visualizer::MobilityOsgVisualizer
{
  protected:
    virtual inet::visualizer::MobilityVisualizerBase::MobilityVisualization *createMobilityVisualization(
        inet::IMobility *mobility) override;
};

} // namespace uav_rid

#endif
