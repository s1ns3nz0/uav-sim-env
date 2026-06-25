"""Post-boot SITL bootstrap.

Runs after ArduPilot SITL boots and the datalink-los mavlink-router has
attached to TCP 5760. Connects through the router's TCP 5790 server and forces
runtime parameters that the persona parm file cannot reliably set:

* ARMING_CHECK = 0 — ArduPlane silently restores this to 1 when loaded via
  --defaults, so a runtime PARAM_SET is required.
* MISSION_CURRENT = 0 — guarantees a fresh mission run after every restart so
  the vehicle never wakes up "in landing sequence" from a prior session.
"""
from __future__ import annotations

import os
import sys
import time

from pymavlink import mavutil


# Target MAVLink endpoint for the post-boot PARAM_SET. Env-selectable so a second
# airframe (av-muav, INSTANCE=1 → SITL TCP 5770) can bootstrap against its own
# local SITL instead of the LOS router. Default keeps MPD behavior.
ROUTER_TCP = os.environ.get("BOOTSTRAP_ROUTER_TCP", "tcp:10.50.0.20:5790")
WAIT_BEFORE_CONNECT_SEC = 35
HEARTBEAT_TIMEOUT_SEC = 30
MAX_ATTEMPTS = 5


def _log(line: str) -> None:
    sys.stderr.write(f"[bootstrap] {line}\n")
    sys.stderr.flush()


def main() -> int:
    _log(f"sleeping {WAIT_BEFORE_CONNECT_SEC}s for SITL + router to come up")
    time.sleep(WAIT_BEFORE_CONNECT_SEC)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        _log(f"attempt {attempt}/{MAX_ATTEMPTS}: connecting {ROUTER_TCP}")
        try:
            conn = mavutil.mavlink_connection(ROUTER_TCP)
            hb = conn.wait_heartbeat(timeout=HEARTBEAT_TIMEOUT_SEC)
            if hb is None:
                _log("no heartbeat, retrying")
                time.sleep(5)
                continue

            _log(f"heartbeat ok sys={conn.target_system} comp={conn.target_component}")
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                b"ARMING_CHECK",
                0.0,
                mavutil.mavlink.MAV_PARAM_TYPE_INT32,
            )
            conn.mav.mission_set_current_send(
                conn.target_system, conn.target_component, 0
            )
            _log("PARAM_SET ARMING_CHECK=0 + MISSION_CURRENT=0 sent")
            return 0
        except (ConnectionRefusedError, OSError) as exc:
            _log(f"connect error: {exc}, retrying in 5s")
            time.sleep(5)

    _log("giving up after exhausting attempts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
