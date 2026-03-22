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

// ── Image method helpers ────────────────────────────────────────────────────

Coord ImageMethodObstacleLoss::mirrorAcrossFace(const Coord& point,
                                                 const BuildingFace& face) const
{
    Coord mirrored = point;
    switch (face.normalAxis) {
        case BuildingFace::X:
            mirrored.x = 2.0 * face.planeCoord - point.x;
            break;
        case BuildingFace::Y:
            mirrored.y = 2.0 * face.planeCoord - point.y;
            break;
        case BuildingFace::Z:
            mirrored.z = 2.0 * face.planeCoord - point.z;
            break;
    }
    return mirrored;
}

bool ImageMethodObstacleLoss::intersectFace(const Coord& from, const Coord& to,
                                             const BuildingFace& face,
                                             Coord& hit) const
{
    // Ray-plane intersection for axis-aligned face.
    // The face lies at normalAxis = planeCoord.
    double fromCoord, toCoord;
    switch (face.normalAxis) {
        case BuildingFace::X: fromCoord = from.x; toCoord = to.x; break;
        case BuildingFace::Y: fromCoord = from.y; toCoord = to.y; break;
        case BuildingFace::Z: fromCoord = from.z; toCoord = to.z; break;
    }

    double denom = toCoord - fromCoord;
    if (std::abs(denom) < 1e-9)
        return false;  // Ray parallel to face

    double t = (face.planeCoord - fromCoord) / denom;
    if (t < 0.0 || t > 1.0)
        return false;  // Intersection outside segment

    hit = from + (to - from) * t;

    // Check if intersection is within the face's bounding rectangle.
    double t1, t2;  // coordinates on the two tangent axes
    switch (face.normalAxis) {
        case BuildingFace::X: t1 = hit.y; t2 = hit.z; break;
        case BuildingFace::Y: t1 = hit.x; t2 = hit.z; break;
        case BuildingFace::Z: t1 = hit.x; t2 = hit.y; break;
    }

    return (t1 >= face.tangent1Lo && t1 <= face.tangent1Hi &&
            t2 >= face.tangent2Lo && t2 <= face.tangent2Hi);
}

double ImageMethodObstacleLoss::computeReflectionCoefficient(
    Hz frequency, double incidenceAngle) const
{
    // Fresnel reflection for TE+TM averaged (unpolarized).
    // n2 = sqrt(εᵣ - j*σ/(ω*ε₀))  ≈ sqrt(εᵣ) for low conductivity
    double n1 = 1.0;  // air
    double n2 = std::sqrt(buildingPermittivity);

    double cosI = std::cos(incidenceAngle);
    double sinI = std::sin(incidenceAngle);
    double sinT2 = (n1 / n2) * sinI;
    sinT2 *= sinT2;

    if (sinT2 >= 1.0)
        return 1.0;  // Total internal reflection

    double cosT = std::sqrt(1.0 - sinT2);

    // TE (s-polarization): rs = (n1*cosI - n2*cosT) / (n1*cosI + n2*cosT)
    double rs = (n1 * cosI - n2 * cosT) / (n1 * cosI + n2 * cosT);
    // TM (p-polarization): rp = (n2*cosI - n1*cosT) / (n2*cosI + n1*cosT)
    double rp = (n2 * cosI - n1 * cosT) / (n2 * cosI + n1 * cosT);

    // Average power reflection coefficient
    return (rs * rs + rp * rp) / 2.0;
}

bool ImageMethodObstacleLoss::isOnOutwardSide(const Coord& point,
                                               const BuildingFace& face) const
{
    double side;
    switch (face.normalAxis) {
        case BuildingFace::X: side = point.x - face.planeCoord; break;
        case BuildingFace::Y: side = point.y - face.planeCoord; break;
        case BuildingFace::Z: side = point.z - face.planeCoord; break;
    }
    return side * face.normalSign >= 0;
}

double ImageMethodObstacleLoss::computeIncidenceAngle(
    const Coord& from, const Coord& reflPt, const BuildingFace& face) const
{
    Coord faceNormal(0, 0, 0);
    switch (face.normalAxis) {
        case BuildingFace::X: faceNormal.x = face.normalSign; break;
        case BuildingFace::Y: faceNormal.y = face.normalSign; break;
        case BuildingFace::Z: faceNormal.z = face.normalSign; break;
    }
    Coord incoming = reflPt - from;
    double len = incoming.length();
    if (len < 1e-9) return 0;
    incoming = incoming / len;
    double cosAngle = std::abs(incoming * faceNormal);
    return std::acos(std::min(cosAngle, 1.0));
}

double ImageMethodObstacleLoss::computeSingleBounceContribution(
    Hz frequency,
    const Coord& tx, const Coord& rx,
    double directDist) const
{
    double totalReflectedPower = 0.0;

    for (const auto& face : faces) {
        Coord txImage = mirrorAcrossFace(tx, face);

        Coord reflPt;
        if (!intersectFace(txImage, rx, face, reflPt))
            continue;
        if (!isOnOutwardSide(tx, face))
            continue;
        if (isLineOfSightBlocked(tx, reflPt) || isLineOfSightBlocked(reflPt, rx))
            continue;

        double totalPathLen = tx.distance(reflPt) + reflPt.distance(rx);
        if (totalPathLen < 1e-3) continue;

        double angle = computeIncidenceAngle(tx, reflPt, face);
        double reflCoeff = computeReflectionCoefficient(frequency, angle);
        double pathRatio = directDist / totalPathLen;
        totalReflectedPower += pathRatio * pathRatio * reflCoeff;
    }

    return totalReflectedPower;
}

double ImageMethodObstacleLoss::computeDoubleBounceContribution(
    Hz frequency,
    const Coord& tx, const Coord& rx,
    double directDist) const
{
    double totalReflectedPower = 0.0;
    size_t nFaces = faces.size();

    // For each pair of faces (A, B): TX reflects off A then B to reach RX.
    // Image method: mirror TX across A → TX_A, then mirror TX_A across B → TX_AB.
    // If TX_AB→RX hits face B at point P2, and TX_A→P2 hits face A at P1,
    // the path is TX→P1→P2→RX.
    for (size_t ia = 0; ia < nFaces; ia++) {
        const auto& faceA = faces[ia];

        if (!isOnOutwardSide(tx, faceA))
            continue;

        Coord txA = mirrorAcrossFace(tx, faceA);

        for (size_t ib = 0; ib < nFaces; ib++) {
            if (ib == ia) continue;
            const auto& faceB = faces[ib];

            // TX_A must be on outward side of face B for valid 2nd reflection
            if (!isOnOutwardSide(txA, faceB))
                continue;

            Coord txAB = mirrorAcrossFace(txA, faceB);

            // Find where TX_AB→RX hits face B (second reflection point P2)
            Coord p2;
            if (!intersectFace(txAB, rx, faceB, p2))
                continue;

            // Find where TX_A→P2 hits face A (first reflection point P1)
            Coord p1;
            if (!intersectFace(txA, p2, faceA, p1))
                continue;

            // Verify all legs are unblocked
            if (isLineOfSightBlocked(tx, p1) ||
                isLineOfSightBlocked(p1, p2) ||
                isLineOfSightBlocked(p2, rx))
                continue;

            double totalPathLen = tx.distance(p1) + p1.distance(p2) + p2.distance(rx);
            if (totalPathLen < 1e-3) continue;

            double angleA = computeIncidenceAngle(tx, p1, faceA);
            double angleB = computeIncidenceAngle(p1, p2, faceB);
            double reflA = computeReflectionCoefficient(frequency, angleA);
            double reflB = computeReflectionCoefficient(frequency, angleB);

            double pathRatio = directDist / totalPathLen;
            totalReflectedPower += pathRatio * pathRatio * reflA * reflB;
        }
    }

    return totalReflectedPower;
}

// ── Main entry point ────────────────────────────────────────────────────────

double ImageMethodObstacleLoss::computeObstacleLoss(
    Hz frequency,
    const Coord& transmissionPosition,
    const Coord& receptionPosition) const
{
    computationCount++;

    double directDist = transmissionPosition.distance(receptionPosition);
    if (directDist < 1e-3)
        return 1.0;

    // Direct path: obstruction loss through buildings
    double directLoss = computeDirectPathLoss(frequency,
                                              transmissionPosition,
                                              receptionPosition);

    if (maxBounces == 0)
        return directLoss;

    // Add power from reflected paths (incoherent sum).
    // Each contribution is relative to free-space direct power.
    double reflectedContribution = 0.0;

    if (maxBounces >= 1) {
        reflectedContribution += computeSingleBounceContribution(
            frequency, transmissionPosition, receptionPosition, directDist);
    }
    if (maxBounces >= 2) {
        reflectedContribution += computeDoubleBounceContribution(
            frequency, transmissionPosition, receptionPosition, directDist);
    }

    // Total factor: direct loss + reflected power contributions.
    // Clamped to [0, 1] since incoherent sum shouldn't exceed free-space.
    double totalFactor = directLoss + reflectedContribution;
    return std::min(totalFactor, 1.0);
}

} // namespace physicallayer
} // namespace inet
