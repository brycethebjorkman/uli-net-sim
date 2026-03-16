//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h must come BEFORE omnetpp.h to avoid macro conflicts.
//

#include "pybridge/PyBridgePy.h"
#include "MultirotorMobility.h"
#include "pybridge/PyBridge.h"
#include "gcs/GcsCommand_m.h"

#include "inet/common/INETMath.h"
#include "inet/common/geometry/common/Quaternion.h"

#ifdef WITH_OSG
#include <osg/Geode>
#include <osg/Geometry>
#include <osg/LineWidth>
#include <osg/Material>
#include <osg/ShapeDrawable>
#endif

#include <cmath>

Define_Module(MultirotorMobility);

static constexpr double GRAVITY = 9.81;  // m/s^2

#ifdef WITH_OSG
static constexpr bool hasOsg = true;
#else
static constexpr bool hasOsg = false;
#endif

// ── Dynamics ────────────────────────────────────────────────────────────────
// lumped-mass 6-DOF model
//
// State:   x = [x, y, z, vx, vy, vz, phi, theta, psi, p, q, r]
// Control: u = [T, tau_phi, tau_theta, tau_psi]

Eigen::Matrix<double, STATE_DIM, 1> MultirotorMobility::dynamics(
    const Eigen::Matrix<double, STATE_DIM, 1>& x,
    const Eigen::Matrix<double, CONTROL_DIM, 1>& u) const
{
    Eigen::Matrix<double, STATE_DIM, 1> dx;

    double phi   = x[PHI];
    double theta = x[THETA];
    // psi unused in derivatives directly but used in acceleration
    double psi   = x[PSI];
    double p     = x[OMEGA_P];
    double q     = x[OMEGA_Q];
    double r     = x[OMEGA_R];

    double T        = u[THRUST];
    double tau_phi   = u[TAU_PHI];
    double tau_theta = u[TAU_THETA];
    double tau_psi   = u[TAU_PSI];

    double sp = std::sin(phi),   cp = std::cos(phi);
    double st = std::sin(theta), ct = std::cos(theta);
    double tt = std::tan(theta);
    double spsi = std::sin(psi), cpsi = std::cos(psi);

    double T_over_m = T / mass;

    // Position derivatives = velocity
    dx[POS_X] = x[VEL_X];
    dx[POS_Y] = x[VEL_Y];
    dx[POS_Z] = x[VEL_Z];

    // Velocity derivatives (translational acceleration from thrust)
    dx[VEL_X] = (st * cpsi * cp + sp * spsi) * T_over_m;
    dx[VEL_Y] = (st * spsi * cp - sp * cpsi) * T_over_m;
    dx[VEL_Z] = -GRAVITY + cp * ct * T_over_m;

    // Translational drag (quadratic, body-frame)
    if (dragCoeff > 0) {
        double vx = x[VEL_X], vy = x[VEL_Y], vz = x[VEL_Z];

        // World-to-body rotation (R^T): columns of R become rows
        double vb_x =  ct*cpsi*vx          + ct*spsi*vy          - st*vz;
        double vb_y = (sp*st*cpsi-cp*spsi)*vx + (sp*st*spsi+cp*cpsi)*vy + sp*ct*vz;
        double vb_z = (cp*st*cpsi+sp*spsi)*vx + (cp*st*spsi-sp*cpsi)*vy + cp*ct*vz;

        // Quadratic drag per axis in body frame: D = dragCoeff * v * |v|
        double db_x = dragCoeff * vb_x * std::abs(vb_x);
        double db_y = dragCoeff * vb_y * std::abs(vb_y);
        double db_z = dragCoeff * vb_z * std::abs(vb_z);

        // Body-to-world rotation (R)
        double dw_x = ct*cpsi*db_x + (sp*st*cpsi-cp*spsi)*db_y + (cp*st*cpsi+sp*spsi)*db_z;
        double dw_y = ct*spsi*db_x + (sp*st*spsi+cp*cpsi)*db_y + (cp*st*spsi-sp*cpsi)*db_z;
        double dw_z =    -st*db_x  +              sp*ct  *db_y +              cp*ct  *db_z;

        dx[VEL_X] -= dw_x / mass;
        dx[VEL_Y] -= dw_y / mass;
        dx[VEL_Z] -= dw_z / mass;
    }

    // Euler angle derivatives (kinematic equations)
    dx[PHI]   = p + q * sp * tt + r * cp * tt;
    dx[THETA] = q * cp - r * sp;
    dx[PSI]   = q * sp / ct + r * cp / ct;

    // Angular rate derivatives (rotational dynamics)
    dx[OMEGA_P] = (Iyy - Izz) / Ixx * q * r + armLength / Ixx * tau_phi;
    dx[OMEGA_Q] = (Izz - Ixx) / Iyy * p * r + armLength / Iyy * tau_theta;
    dx[OMEGA_R] = (Ixx - Iyy) / Izz * p * r + armLength / Izz * tau_psi;

    // Rotational drag (linear damping, ArduPilot-style)
    dx[OMEGA_P] -= rotationalDrag * p;
    dx[OMEGA_Q] -= rotationalDrag * q;
    dx[OMEGA_R] -= rotationalDrag * r;

    return dx;
}

void MultirotorMobility::rk4Step(double dt)
{
    auto k1 = dynamics(state, control);
    auto k2 = dynamics(state + 0.5 * dt * k1, control);
    auto k3 = dynamics(state + 0.5 * dt * k2, control);
    auto k4 = dynamics(state + dt * k3, control);

    state += (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4);
}

// ── Initialization ──────────────────────────────────────────────────────────

void MultirotorMobility::initialize(int stage)
{
    MovingMobilityBase::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        // Read physical parameters
        mass      = par("mass").doubleValueInUnit("kg");
        armLength = par("armLength").doubleValueInUnit("m");
        Ixx       = par("Ixx").doubleValue();
        Iyy       = par("Iyy").doubleValue();
        Izz       = par("Izz").doubleValue();
        dynamicsDt = par("dynamicsDt").doubleValueInUnit("s");
        controlDt  = par("controlDt").doubleValueInUnit("s");

        // Aerodynamic drag
        double dragCd  = par("dragCd").doubleValue();
        double dragArea = par("dragArea").doubleValue();
        double airDensity = par("airDensity").doubleValue();
        dragCoeff = 0.5 * airDensity * dragCd * dragArea;
        rotationalDrag = par("rotationalDrag").doubleValue();

        EV_WARN << "MultirotorMobility: dragCoeff=" << dragCoeff
                << " (Cd=" << dragCd << " A=" << dragArea << " rho=" << airDensity << ")"
                << " rotDrag=" << rotationalDrag << endl;

        // Initialize state to zero; position will be set in initializePosition()
        state.setZero();

        // Initial velocity
        state[VEL_X] = par("initialVx").doubleValue();
        state[VEL_Y] = par("initialVy").doubleValue();
        state[VEL_Z] = par("initialVz").doubleValue();

        // Initial Euler angles and angular rates
        state[PHI]     = par("initialPhi").doubleValue();
        state[THETA]   = par("initialTheta").doubleValue();
        state[PSI]     = par("initialPsi").doubleValue();
        state[OMEGA_P] = par("initialP").doubleValue();
        state[OMEGA_Q] = par("initialQ").doubleValue();
        state[OMEGA_R] = par("initialR").doubleValue();

        // Default control
        control.setZero();
        double defaultThrust = par("defaultThrust").doubleValue();
        control[THRUST] = (defaultThrust < 0) ? mass * GRAVITY : defaultThrust;

        nextControlTick = simTime();

        // Parse waypoint script (TurtleMobility-compatible XML)
        cXMLElement *wpXml = par("waypointScript").xmlValue();
        double wpSpeed = 10.0;  // default speed
        for (cXMLElement *child = wpXml->getFirstChild(); child; child = child->getNextSibling()) {
            const char *tag = child->getTagName();
            double x = atof(child->getAttribute("x") ? child->getAttribute("x") : "0");
            double y = atof(child->getAttribute("y") ? child->getAttribute("y") : "0");
            double z = atof(child->getAttribute("z") ? child->getAttribute("z") : "0");
            if (strcmp(tag, "set") == 0) {
                if (child->getAttribute("speed"))
                    wpSpeed = atof(child->getAttribute("speed"));
                waypoints.push_back({x, y, z, wpSpeed});
            }
            else if (strcmp(tag, "moveto") == 0) {
                waypoints.push_back({x, y, z, wpSpeed});
            }
        }

        // Register signals for vector recording
        thrustSignal   = registerSignal("thrust");
        tauPhiSignal   = registerSignal("tauPhi");
        tauThetaSignal = registerSignal("tauTheta");
        tauPsiSignal   = registerSignal("tauPsi");
        phiSignal      = registerSignal("phi");
        thetaSignal    = registerSignal("theta");
        psiSignal      = registerSignal("psi");
        omegaPSignal   = registerSignal("omegaP");
        omegaQSignal   = registerSignal("omegaQ");
        omegaRSignal   = registerSignal("omegaR");
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        // Position was set by MobilityBase::initializePosition() via setInitialPosition().
        // Sync it into our state vector.
        state[POS_X] = lastPosition.x;
        state[POS_Y] = lastPosition.y;
        state[POS_Z] = lastPosition.z;

        // Initialize Python controller if configured
        std::string pyClassName = par("pyClass").stdstringValue();
        if (!pyClassName.empty()) {
            cModule *mod = getModuleByPath(par("pyBridgePath").stdstringValue().c_str());
            pyBridge = check_and_cast<PyBridge *>(mod);
            pyHandle = pyBridge->instantiateClass(pyClassName);
        }

        // Draw waypoint path in the 3D OSG scene (Qtenv only)
        if constexpr (hasOsg) {
            if (waypoints.size() >= 2 && getEnvir()->isGUI()) {
                auto *osgCanvas = getSystemModule()->getOsgCanvas();
                auto *scene = osgCanvas ? dynamic_cast< ::osg::Group*>(osgCanvas->getScene()) : nullptr;
                if (scene) {
                    static const ::osg::Vec4 osgColors[] = {
                        {66/255.0f, 133/255.0f, 244/255.0f, 1.0f},   // blue
                        {234/255.0f, 67/255.0f, 53/255.0f, 1.0f},    // red
                        {52/255.0f, 168/255.0f, 83/255.0f, 1.0f},    // green
                        {251/255.0f, 188/255.0f, 4/255.0f, 1.0f},    // amber
                    };
                    int hostIdx = getParentModule()->getIndex();
                    auto colorVec = osgColors[hostIdx % 4];

                    // Polyline geometry for the path
                    auto *geometry = new ::osg::Geometry();
                    auto *vertices = new ::osg::Vec3Array();
                    for (const auto& wp : waypoints)
                        vertices->push_back(::osg::Vec3d(wp.x, wp.y, wp.z));
                    geometry->setVertexArray(vertices);
                    geometry->addPrimitiveSet(
                        new ::osg::DrawArrays(::osg::PrimitiveSet::LINE_STRIP, 0, vertices->size()));

                    auto *geode = new ::osg::Geode();
                    geode->addDrawable(geometry);

                    auto *stateSet = geode->getOrCreateStateSet();
                    auto *material = new ::osg::Material();
                    material->setDiffuse(::osg::Material::FRONT_AND_BACK, colorVec);
                    material->setAmbient(::osg::Material::FRONT_AND_BACK, colorVec);
                    material->setEmission(::osg::Material::FRONT_AND_BACK, colorVec);
                    stateSet->setAttributeAndModes(material, ::osg::StateAttribute::ON);
                    stateSet->setAttributeAndModes(
                        new ::osg::LineWidth(3.0f), ::osg::StateAttribute::ON);
                    stateSet->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);

                    scene->addChild(geode);

                    // Sphere markers at each waypoint
                    for (const auto& wp : waypoints) {
                        auto *sphere = new ::osg::ShapeDrawable(
                            new ::osg::Sphere(::osg::Vec3d(wp.x, wp.y, wp.z), 2.0));
                        sphere->setColor(colorVec);
                        auto *marker = new ::osg::Geode();
                        marker->addDrawable(sphere);
                        marker->getOrCreateStateSet()->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);
                        scene->addChild(marker);
                    }
                }
            }
        }
    }
}

// ── Message handling ────────────────────────────────────────────────────────

void MultirotorMobility::handleMessage(cMessage *msg)
{
    if (msg->isSelfMessage()) {
        handleSelfMessage(msg);
    }
    else if (msg->arrivedOn("commandIn")) {
        // GCS command — store the JSON payload for the next Python controller call.
        GcsCommand *cmd = check_and_cast<GcsCommand *>(msg);
        latestGcsCommand = cmd->getCommandJson();
        delete msg;
    }
    else {
        throw cRuntimeError("MultirotorMobility received unexpected message '%s'", msg->getName());
    }
}

// ── Python controller ───────────────────────────────────────────────────────

void MultirotorMobility::callPythonController()
{
    if (pyHandle < 0)
        return;

    PyBridgeImpl *impl = pyBridge->getImpl();
    py::gil_scoped_acquire gil;

    // Build state dict
    py::dict stateDict;
    stateDict["pos"]   = py::make_tuple(state[POS_X], state[POS_Y], state[POS_Z]);
    stateDict["vel"]   = py::make_tuple(state[VEL_X], state[VEL_Y], state[VEL_Z]);
    stateDict["euler"] = py::make_tuple(state[PHI], state[THETA], state[PSI]);
    stateDict["omega"] = py::make_tuple(state[OMEGA_P], state[OMEGA_Q], state[OMEGA_R]);
    stateDict["time"]  = simTime().dbl();

    // Include waypoints and mass on first call (one-shot delivery)
    if (!waypointsSent) {
        py::list wpList;
        for (const auto& wp : waypoints) {
            py::dict wpDict;
            wpDict["x"] = wp.x;
            wpDict["y"] = wp.y;
            wpDict["z"] = wp.z;
            wpDict["speed"] = wp.speed;
            wpList.append(wpDict);
        }
        stateDict["waypoints"] = wpList;
        stateDict["mass"] = mass;
        stateDict["arm_length"] = armLength;
        stateDict["Ixx"] = Ixx;
        stateDict["Iyy"] = Iyy;
        stateDict["Izz"] = Izz;
        waypointsSent = true;
    }

    // Include GCS command if present, then clear it (one-shot delivery)
    if (!latestGcsCommand.empty()) {
        stateDict["gcs_command"] = latestGcsCommand;
        latestGcsCommand.clear();
    }
    else {
        stateDict["gcs_command"] = py::none();
    }

    // Call controller.compute(state)
    py::object result = impl->callMethod(pyHandle, "compute", stateDict);

    // Parse result dict
    if (!result.is_none() && py::isinstance<py::dict>(result)) {
        py::dict d = result.cast<py::dict>();
        if (d.contains("thrust"))
            control[THRUST] = d["thrust"].cast<double>();
        if (d.contains("torque_phi"))
            control[TAU_PHI] = d["torque_phi"].cast<double>();
        if (d.contains("torque_theta"))
            control[TAU_THETA] = d["torque_theta"].cast<double>();
        if (d.contains("torque_psi"))
            control[TAU_PSI] = d["torque_psi"].cast<double>();
    }
}

// ── Recording ───────────────────────────────────────────────────────────────

void MultirotorMobility::recordState()
{
    emit(thrustSignal,   control[THRUST]);
    emit(tauPhiSignal,   control[TAU_PHI]);
    emit(tauThetaSignal, control[TAU_THETA]);
    emit(tauPsiSignal,   control[TAU_PSI]);
    emit(phiSignal,      state[PHI]);
    emit(thetaSignal,    state[THETA]);
    emit(psiSignal,      state[PSI]);
    emit(omegaPSignal,   state[OMEGA_P]);
    emit(omegaQSignal,   state[OMEGA_Q]);
    emit(omegaRSignal,   state[OMEGA_R]);
}

// ── Core movement ───────────────────────────────────────────────────────────

void MultirotorMobility::move()
{
    double elapsed = (simTime() - lastUpdate).dbl();
    if (elapsed <= 0)
        return;

    // Check if a control tick is due
    if (simTime() >= nextControlTick) {
        callPythonController();
        nextControlTick = simTime() + SimTime(controlDt, SIMTIME_S);
    }

    // Integrate dynamics with RK4 sub-steps
    int steps = static_cast<int>(std::ceil(elapsed / dynamicsDt));
    double dt = elapsed / steps;  // actual sub-step size
    for (int i = 0; i < steps; i++) {
        rk4Step(dt);
    }

    // Sync state back to INET fields
    lastPosition.x = state[POS_X];
    lastPosition.y = state[POS_Y];
    lastPosition.z = state[POS_Z];

    lastVelocity.x = state[VEL_X];
    lastVelocity.y = state[VEL_Y];
    lastVelocity.z = state[VEL_Z];

    // Set orientation from Euler angles (INET uses Z-Y'-X" convention).
    // INET's beta = "descending" = positive means nose down / lean forward.
    // Our dynamics: positive theta = sin(theta)*T/m gives +X accel = lean forward.
    // Same convention — no sign flip needed.
    lastOrientation = Quaternion(EulerAngles(
        rad(state[PSI]),    // heading (yaw)
        rad(state[THETA]),  // elevation (positive = nose down, matches dynamics)
        rad(state[PHI])     // bank (roll)
    ));

    // Schedule next change at the next control tick
    nextChange = nextControlTick;

    // Record vectors
    recordState();
}

double MultirotorMobility::getMaxSpeed() const
{
    // Conservative upper bound: max thrust / mass gives max acceleration,
    // but we don't know how long it's been accelerating.
    // Return NaN (unknown) to disable radio medium caching optimization.
    return NaN;
}
