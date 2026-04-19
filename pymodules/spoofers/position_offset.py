"""
TX hook that offsets the claimed RID position by a fixed delta.

Simulates a simple spoofing attack where the attacker reports a position
shifted from their actual location.

INI usage:
    *.host[1].wlan[0].mgmt.pyTxClass = "pymodules.spoofers.position_offset.PositionOffsetSpoofer"
"""


class PositionOffsetSpoofer:
    """Adds a fixed offset to the beacon claimed position."""

    def __init__(self):
        self.offset = (50.0, 50.0, 0.0)  # meters: east, north, up

    def on_rid_tx(self, state):
        pos = state['pos']
        return {
            'pos': (
                pos[0] + self.offset[0],
                pos[1] + self.offset[1],
                pos[2] + self.offset[2],
            ),
        }


class PositionOffsetSpooferNegZ(PositionOffsetSpoofer):
    """Adds a fixed negative-Z offset to claimed beacon position."""

    def __init__(self):
        # Downward-only spoof in local ENU frame: east=0, north=0, up=-50 m.
        self.offset = (0.0, 0, 50.0)


class PositionOffsetSpooferClaimOffset150m(PositionOffsetSpoofer):
    """Fixed ENU beacon bias with Euclidean norm 150 m (paired TrustRID / SpoofingAware runs)."""

    def __init__(self):
        self.offset = (100.0, 100.0, 50.0)


class PositionOffsetSpooferTrustRidCollisionBias(PositionOffsetSpoofer):
    """
    Moderate constant offset intended for TrustRID collision stress tests.

    Biases the claimed RID broadcast toward busy shared corridors so baseline
    TrustRID is more likely to induce unsafe separation decisions.
    """

    def __init__(self):
        # Fixed ENU bias: east=+140 m, north=+140 m, up=-50 m.
        self.offset = (140.0, 140.0, -50.0)


class PositionOffsetSpooferTrustRidAggressive(PositionOffsetSpooferTrustRidCollisionBias):
    """Backward-compatible alias for older config names."""


class PositionOffsetSpooferTrustRidMaxStress(PositionOffsetSpoofer):
    """
    Large fixed offset for TrustRidGcs baseline stress tests.

    TrustRid broadcasts this shifted track as ``other_positions``; MDP repulsion
    only applies within ``agent_radius`` (~150 m) of the *claimed* point. A
    ~400+ m lateral/vertical displacement moves the ghost far from the physical
    aircraft so benign agents often **do not** activate repulsion while passing
    the true spoofer — maximizing benign-vs-truth proximity / NMAC exposure.
    Spoofing-aware scenarios should keep a milder offset class for localization.
    """

    def __init__(self):
        # ENU meters; |horizontal| ~560 m from truth typical positions in DepotCity / hub runs.
        self.offset = (420.0, -380.0, -65.0)
