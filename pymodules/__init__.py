"""
Simulation-time Python modules for the UAV RID simulator.

These modules are loaded by PyBridge at simulation time and implement:
- Flight controllers (MultirotorMobility compute() hook)
- Detection algorithms (GcsModule on_reports() hook)
- Spoofing strategies (RidBeaconMgmt on_tx() hook)

Classes are referenced in INI files using qualified names, e.g.:
    *.host[*].mobility.pyClass = "pymodules.controllers.hover.HoverController"
    *.gcs[0].pyClass = "pymodules.detectors.rssi_anomaly.RssiAnomalyDetector"
    *.host[1].wlan[0].mgmt.pyTxClass = "pymodules.spoofers.position_offset.PositionOffsetSpoofer"
"""
