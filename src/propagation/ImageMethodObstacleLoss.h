//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Raytracing-based obstacle loss using the image method.
//
// Computes received power as the incoherent sum of contributions from
// the direct path plus specular reflections off axis-aligned building
// surfaces.  Returns the total power relative to free-space as a loss
// factor that the radio medium applies multiplicatively.
//

#ifndef __IMAGE_METHOD_OBSTACLE_LOSS_H
#define __IMAGE_METHOD_OBSTACLE_LOSS_H

#include "inet/common/ModuleRefByPar.h"
#include "inet/environment/contract/IPhysicalEnvironment.h"
#include "inet/physicallayer/wireless/common/base/packetlevel/TracingObstacleLossBase.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/IRadioMedium.h"

namespace inet {
namespace physicallayer {

/// Axis-aligned rectangular face of a building (one of 6 cuboid faces).
struct BuildingFace {
    enum Axis { X, Y, Z };

    Axis   normalAxis;     // which axis the outward normal points along
    double normalSign;     // +1 or -1
    double planeCoord;     // coordinate of the face on the normal axis

    // Bounding rectangle on the two tangent axes (sorted: lo < hi)
    double tangent1Lo, tangent1Hi;  // first tangent axis bounds
    double tangent2Lo, tangent2Hi;  // second tangent axis bounds
};

class ImageMethodObstacleLoss : public TracingObstacleLossBase
{
  protected:
    int maxBounces = 0;
    double buildingPermittivity = 5.31;
    double buildingConductivity = 0.0326;

    const IRadioMedium *medium = nullptr;
    ModuleRefByPar<physicalenvironment::IPhysicalEnvironment> physicalEnvironment;

    // Pre-extracted building faces (populated at initialize)
    std::vector<BuildingFace> faces;

    // Statistics
    mutable long computationCount = 0;

    virtual void initialize(int stage) override;
    virtual void finish() override;

    void extractBuildingFaces();
    double computeDirectPathLoss(Hz frequency,
                                 const Coord& tx, const Coord& rx) const;
    bool isLineOfSightBlocked(const Coord& from, const Coord& to) const;
    double computePenetrationLoss(Hz frequency, double thickness) const;

    /// Mirror a point across a building face (image method).
    Coord mirrorAcrossFace(const Coord& point, const BuildingFace& face) const;

    /// Find where the line from→to intersects a building face.
    /// Returns true and sets 'hit' if the intersection is within the face bounds.
    bool intersectFace(const Coord& from, const Coord& to,
                       const BuildingFace& face, Coord& hit) const;

    /// Fresnel reflection coefficient (power) for the building material.
    double computeReflectionCoefficient(Hz frequency, double incidenceAngle) const;

    /// Compute power contribution from single-bounce reflections.
    double computeSingleBounceContribution(Hz frequency,
                                           const Coord& tx, const Coord& rx,
                                           double directDist) const;

    /// Compute power contribution from two-bounce reflections.
    double computeDoubleBounceContribution(Hz frequency,
                                           const Coord& tx, const Coord& rx,
                                           double directDist) const;

    /// Check that a point is on the outward-normal side of a face.
    bool isOnOutwardSide(const Coord& point, const BuildingFace& face) const;

    /// Compute incidence angle between an incoming ray and a face normal.
    double computeIncidenceAngle(const Coord& from, const Coord& reflPt,
                                 const BuildingFace& face) const;

  public:
    virtual double computeObstacleLoss(Hz frequency,
                                       const Coord& transmissionPosition,
                                       const Coord& receptionPosition) const override;
};

} // namespace physicallayer
} // namespace inet

#endif
