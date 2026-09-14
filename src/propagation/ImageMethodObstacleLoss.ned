//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.propagation;

import inet.physicallayer.wireless.common.base.packetlevel.TracingObstacleLossBase;

//
// Raytracing-based obstacle loss using the image method for multipath
// radio propagation.  Computes power contributions from the direct
// path plus specular reflections off building surfaces.
//
// Stage 1 (skeleton): direct-path obstruction loss only.
// Stage 2: single-bounce specular reflections.
// Stage 3: two-bounce reflections.
//
module ImageMethodObstacleLoss extends TracingObstacleLossBase
{
    parameters:
        // Maximum number of reflection bounces (0 = direct path only)
        int maxBounces = default(0);

        // Material properties for reflection loss
        double buildingPermittivity = default(5.31);   // relative permittivity (concrete)
        double buildingConductivity = default(0.0326);  // S/m (concrete at 2.4 GHz)

        @class(ImageMethodObstacleLoss);
}
