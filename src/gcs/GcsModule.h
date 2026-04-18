//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __GCS_MODULE_H
#define __GCS_MODULE_H

#include <omnetpp.h>
#include <omnetpp/ccanvas.h>
#include <map>
#include <set>
#include <vector>
#include <string>
#include <array>

using namespace omnetpp;

class PyBridge;
class GcsReport;

//
// Ground Control Station: aggregates per-transmission RX reports,
// calls a Python decision algorithm, optionally sends control commands.
// OSG (3D) and Qtenv network-canvas overlay (2D): chance-constraint ellipsoid,
// claimed-RID trail, and optional follow framing for the spoofer host.
//
class GcsModule : public cSimpleModule, public cListener
{
  public:
    virtual ~GcsModule();

    // Record log entries as cOutVector
    void emitLogEntries(const std::map<std::string, double>& entries);

    // Forward a control command to a UAV's mobility module
    void sendCommand(int hostId, const std::string& commandJson);

    // OSG + Qtenv canvas: chance-constraint ellipsoid and claimed-RID trail
    void updateVisualization(const std::vector<double>& mu,
                             const std::vector<std::vector<double>>& sigma,
                             double alpha,
                             bool detected);
    void addClaimedTrailPoint(double x, double y, double z, bool detected);
    void resetClaimedTrail();

    int trackHostId = -1;

    // Written by static handlePyResult in GcsModule.cc (file scope); must stay public for access.
    std::set<int> benignInsideUnsafeFromPlanner;
    bool benignInsideUnsafePlannerActive = false;

  protected:
    // Federate host indices this GCS manages (empty = all)
    std::set<int> federateSet;
    bool allFederates = true;

    // Report aggregation: key = (serialNumber, ridTimestamp)
    using BeaconKey = std::pair<int, int64_t>;
    std::map<BeaconKey, std::vector<GcsReport*>> reportsByBeacon;

    // Radio medium for signal subscription
    cModule *radioMedium = nullptr;

    // Python bridge
    PyBridge *pyBridge = nullptr;
    int pyHandle = -1;
    bool sendControlCommands = false;

    // Periodic tick timer
    cMessage *tickTimer = nullptr;
    double tickInterval = 0;   // 0 = disabled
    int tickCount = 0;

    // Defer Qtenv canvas overlay refresh to end of same simTime (after mobility etc.)
    cMessage *canvasOverlayRefreshMsg = nullptr;
    void requestCanvasOverlayRefresh();

    // Dynamic vector registry: Python "log" keys → cOutVector (always recorded)
    std::map<std::string, cOutVector*> logVectors;
    // Cached per-host final goals parsed from mobility waypointScript (x,y,z).
    std::map<int, std::array<double, 3>> hostGoalsByHost;

    // OSG visualization state (opaque pointers to avoid OSG in header)
    void *ellipsoidTransform = nullptr;
    void *claimedTrailGeode = nullptr;
    std::vector<std::tuple<double, double, double>> claimedTrailPoints;
    std::vector<bool> claimedTrailDetected;

    // Last published unsafe ellipsoid (for 2D redraw / OSG-off builds)
    std::vector<double> lastEllipsoidMu;
    std::vector<std::vector<double>> lastEllipsoidSigma;
    double lastEllipsoidAlpha = 0.05;
    bool lastEllipsoidDetected = false;
    bool lastEllipsoidValid = false;

    class cGroupFigure *presentationRoot = nullptr;
    class cPolylineFigure *canvasEllipseFig = nullptr;
    class cPolylineFigure *canvasClaimedFig = nullptr;
    class cOvalFigure *canvasTruthFig = nullptr;
    class cOvalFigure *canvasClaimedHeadFig = nullptr;
    std::vector<cRectangleFigure *> canvasBenignRiskFigs;
    // Hollow ring: benign within 3D NMAC distance of spoofer truth (same test as orange box).
    std::vector<cOvalFigure *> canvasBenignSpooferNmacRings;
    std::vector<cOvalFigure *> canvasGoalDots;
    std::vector<cTextFigure *> canvasGoalLabels;

    // World XY distance scales (2D overlay)
    static constexpr int kMaxScaleTicks = 50;
    cPolylineFigure *canvasScaleLeftSpine = nullptr;
    cPolylineFigure *canvasScaleBottomSpine = nullptr;
    std::vector<cPolylineFigure *> canvasScaleLeftTickSegs;
    std::vector<cPolylineFigure *> canvasScaleBottomTickSegs;
    std::vector<cTextFigure *> canvasScaleLeftLabels;
    std::vector<cTextFigure *> canvasScaleBottomLabels;
    bool canvasScalePoolCreated = false;

    void ensurePresentationCanvas();
    void ensureBenignRiskMarkerCapacity(size_t need);
    void ensureBenignSpooferNmacRingCapacity(size_t need);
    void ensureGoalDotCapacity(size_t need);
    void tryCacheWaypointGoalForHost(int hid);
    void removePresentationCanvas();
    // World (m) → Qtenv network canvas pixels using INET's CanvasProjection (same as
    // MobilityCanvasVisualizer trails / position markers).
    void mapWorldToCanvas(double wx, double wy, double wz, double& outCx, double& outCy) const;
    bool queryHostPosition(int hostId, double& x, double& y, double& z) const;
    void refreshCanvasOverlay();
    void ensureCanvasDistanceScalePool();
    void updateCanvasDistanceScales();

    virtual void initialize() override;
    virtual void finish() override;
    virtual void handleMessage(cMessage *msg) override;

    // IRadioMedium::signalRemovedSignal handler
    virtual void receiveSignal(cComponent *source, simsignal_t signalID,
                               cObject *obj, cObject *details) override;

    // Process one transmission's worth of collected reports
    void processTransmission(const BeaconKey& key,
                             const std::vector<GcsReport*>& reports);

    // Call Python on_reports() with transmission data
    void pyOnReport(const BeaconKey& key,
                    const std::vector<GcsReport*>& reports);

    // Call Python on_tick() periodically
    void pyOnTick();

    // End of simulation: optional Python on_gcs_finish() → recordScalar
    void pyOnFinish();
};

#endif
