//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "ImageMethodObstacleLoss.h"

#include "inet/common/geometry/object/LineSegment.h"
#include "inet/environment/contract/IPhysicalObject.h"

#include <cmath>

namespace inet {
namespace physicallayer {

Define_Module(ImageMethodObstacleLoss);

// ── Initialization ──────────────────────────────────────────────────────────

void ImageMethodObstacleLoss::initialize(int stage)
{
    TracingObstacleLossBase::initialize(stage);
    if (stage == INITSTAGE_LOCAL) {
        maxBounces = par("maxBounces");
        buildingPermittivity = par("buildingPermittivity");
        buildingConductivity = par("buildingConductivity");
        medium = check_and_cast<IRadioMedium *>(getParentModule());
        physicalEnvironment.reference(this, "physicalEnvironmentModule", true);
    }
    else if (stage == INITSTAGE_PHYSICAL_ENVIRONMENT) {
        extractBuildingFaces();
        EV_INFO << "ImageMethodObstacleLoss: extracted " << faces.size()
                << " building faces, maxBounces=" << maxBounces << endl;
    }
}

void ImageMethodObstacleLoss::finish()
{
    EV_INFO << "ImageMethodObstacleLoss: " << computationCount
            << " obstacle loss computations" << endl;
    recordScalar("imageMethodComputationCount", (double)computationCount);
}

// ── Extract building faces ──────────────────────────────────────────────────

void ImageMethodObstacleLoss::extractBuildingFaces()
{
    using namespace physicalenvironment;
    faces.clear();
    int n = physicalEnvironment->getNumObjects();

    for (int i = 0; i < n; i++) {
        const IPhysicalObject *obj = physicalEnvironment->getObject(i);
        const Coord& pos = obj->getPosition();
        const ShapeBase *shape = obj->getShape();

        // Probe the shape along each axis to find half-extents.
        // Works for axis-aligned cuboids (our building generator output).
        Coord i1, i2, n1, n2;
        double hx = 0, hy = 0, hz = 0;

        if (shape->computeIntersection(
                LineSegment(Coord(-1e6, 0, 0), Coord(1e6, 0, 0)),
                i1, i2, n1, n2)) {
            hx = std::max(std::abs(i1.x), std::abs(i2.x));
        }
        if (shape->computeIntersection(
                LineSegment(Coord(0, -1e6, 0), Coord(0, 1e6, 0)),
                i1, i2, n1, n2)) {
            hy = std::max(std::abs(i1.y), std::abs(i2.y));
        }
        if (shape->computeIntersection(
                LineSegment(Coord(0, 0, -1e6), Coord(0, 0, 1e6)),
                i1, i2, n1, n2)) {
            hz = std::max(std::abs(i1.z), std::abs(i2.z));
        }

        if (hx < 1e-3 || hy < 1e-3 || hz < 1e-3)
            continue;  // Degenerate shape

        // Create 6 faces for this cuboid (in world coordinates)
        auto addFace = [&](BuildingFace::Axis axis, double sign,
                           double planeLocal,
                           double t1Lo, double t1Hi,
                           double t2Lo, double t2Hi) {
            BuildingFace f;
            f.normalAxis = axis;
            f.normalSign = sign;
            switch (axis) {
                case BuildingFace::X:
                    f.planeCoord = pos.x + planeLocal;
                    f.tangent1Lo = pos.y + t1Lo;
                    f.tangent1Hi = pos.y + t1Hi;
                    f.tangent2Lo = pos.z + t2Lo;
                    f.tangent2Hi = pos.z + t2Hi;
                    break;
                case BuildingFace::Y:
                    f.planeCoord = pos.y + planeLocal;
                    f.tangent1Lo = pos.x + t1Lo;
                    f.tangent1Hi = pos.x + t1Hi;
                    f.tangent2Lo = pos.z + t2Lo;
                    f.tangent2Hi = pos.z + t2Hi;
                    break;
                case BuildingFace::Z:
                    f.planeCoord = pos.z + planeLocal;
                    f.tangent1Lo = pos.x + t1Lo;
                    f.tangent1Hi = pos.x + t1Hi;
                    f.tangent2Lo = pos.y + t2Lo;
                    f.tangent2Hi = pos.y + t2Hi;
                    break;
            }
            faces.push_back(f);
        };

        addFace(BuildingFace::X, +1, +hx, -hy, +hy, -hz, +hz);
        addFace(BuildingFace::X, -1, -hx, -hy, +hy, -hz, +hz);
        addFace(BuildingFace::Y, +1, +hy, -hx, +hx, -hz, +hz);
        addFace(BuildingFace::Y, -1, -hy, -hx, +hx, -hz, +hz);
        addFace(BuildingFace::Z, +1, +hz, -hx, +hx, -hy, +hy);
        addFace(BuildingFace::Z, -1, -hz, -hx, +hx, -hy, +hy);
    }
}

// ── Direct path loss ────────────────────────────────────────────────────────

double ImageMethodObstacleLoss::computePenetrationLoss(Hz frequency,
                                                       double thickness) const
{
    // Simplified dielectric penetration loss.
    // α ≈ 60π * σ / sqrt(εᵣ)  [Np/m, low-loss approximation]
    // Loss = exp(-2αd)
    double sigma = buildingConductivity;
    double eps_r = buildingPermittivity;
    double alpha = 60.0 * M_PI * sigma / std::sqrt(eps_r);
    return std::exp(-2.0 * alpha * thickness);
}

double ImageMethodObstacleLoss::computeDirectPathLoss(Hz frequency,
                                                      const Coord& tx,
                                                      const Coord& rx) const
{
    using namespace physicalenvironment;
    double totalLoss = 1.0;

    int nObj = physicalEnvironment->getNumObjects();
    for (int i = 0; i < nObj; i++) {
        const IPhysicalObject *obj = physicalEnvironment->getObject(i);
        const ShapeBase *shape = obj->getShape();
        const Coord& objPos = obj->getPosition();
        const Quaternion& objOri = obj->getOrientation();
        RotationMatrix rotation(objOri.toEulerAngles());

        Coord localTx = rotation.rotateVectorInverse(tx - objPos);
        Coord localRx = rotation.rotateVectorInverse(rx - objPos);

        Coord i1, i2, n1, n2;
        if (shape->computeIntersection(LineSegment(localTx, localRx),
                                       i1, i2, n1, n2)) {
            if (i1 != i2) {
                double thickness = i1.distance(i2);
                totalLoss *= computePenetrationLoss(frequency, thickness);
            }
        }
    }

    return totalLoss;
}

bool ImageMethodObstacleLoss::isLineOfSightBlocked(const Coord& from,
                                                    const Coord& to) const
{
    using namespace physicalenvironment;
    int nObj = physicalEnvironment->getNumObjects();
    for (int i = 0; i < nObj; i++) {
        const IPhysicalObject *obj = physicalEnvironment->getObject(i);
        const ShapeBase *shape = obj->getShape();
        const Coord& objPos = obj->getPosition();
        const Quaternion& objOri = obj->getOrientation();
        RotationMatrix rotation(objOri.toEulerAngles());

        Coord localFrom = rotation.rotateVectorInverse(from - objPos);
        Coord localTo = rotation.rotateVectorInverse(to - objPos);

        Coord i1, i2, n1, n2;
        if (shape->computeIntersection(LineSegment(localFrom, localTo),
                                       i1, i2, n1, n2)) {
            if (i1 != i2)
                return true;
        }
    }
    return false;
}

// ── Main entry point ────────────────────────────────────────────────────────

double ImageMethodObstacleLoss::computeObstacleLoss(
    Hz frequency,
    const Coord& transmissionPosition,
    const Coord& receptionPosition) const
{
    computationCount++;

    // Stage 1: direct path obstruction loss only.
    // Stages 2-3 will add reflected path contributions here.
    return computeDirectPathLoss(frequency, transmissionPosition,
                                 receptionPosition);
}

} // namespace physicallayer
} // namespace inet
