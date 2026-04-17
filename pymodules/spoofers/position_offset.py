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
        self.offset = (0.0, 50, -50.0)
