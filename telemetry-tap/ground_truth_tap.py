"""ground-truth-tap — direct-to-SITL flight-mode observer (S121 defense).

`tap.py`'s CustomMode reading comes entirely from the MAVLink stream relayed
through `datalink-los` — if that relay path is compromised (e.g. a rogue
mavlink-router config, T1557), an attacker can rewrite the HEARTBEAT's
CustomMode field in transit and the SOC never sees the discrepancy, because
it has no independent source to compare against (S121, grilling-session
finding: "텔레메트리 채널 자체가 변조 대상이라 아웃오브밴드 진실값 없이는
원리적으로 로그 불가능").

This script is that out-of-band source: it connects **directly** to the
vehicle's own ArduPilot SITL TCP server (port 5760/5770), bypassing
`datalink-los` entirely — the exact same TCP endpoint `datalink-los` itself
attaches to as a client (see av-mpd/entrypoint.sh), which SITL supports
multiple simultaneous readers on. Whatever CustomMode this script observes
is what the FCC actually reports at the source, before any relay-path
tampering could occur.

Deliberately minimal (grilling-session decision: "가장 lean 한 형태") — this
does not duplicate the other 6 telemetry-tap sinks, only HEARTBEAT ->
CustomMode, emitted on every value change.

Feeds one table: UAVGroundTruth_CL. Correlate against UAVTelemetry_CL by
UAVId + nearest TimeGenerated: a mismatch between GroundTruthCustomMode here
and CustomMode there, with no explainable delay, is S121 mode-report spoofing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from pymavlink import mavutil


UAV_ID: str = os.environ.get("UAV_ID", "MPD-001")
SITL_TCP_ADDR: str = os.environ.get("SITL_TCP_ADDR", "tcp:av-mpd:5760")
LOG_FILE_PATH: str = os.environ.get("GROUND_TRUTH_FILE_PATH", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _log(line: str) -> None:
    sys.stderr.write(f"[ground-truth-tap] {line}\n")
    sys.stderr.flush()


def _emit(handle, uav_id: str, custom_mode: int) -> None:
    rec = {
        "TimeGenerated": _now_iso(),
        "UAVId": uav_id,
        "GroundTruthCustomMode": custom_mode,
        "Source": "direct-sitl-tap",
    }
    line = json.dumps(rec, separators=(",", ":")) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    if handle is not None:
        handle.write(line)
        handle.flush()


def main() -> None:
    handle = None
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
        _log(f"file sink active: {LOG_FILE_PATH}")

    _log(f"connecting directly to SITL at {SITL_TCP_ADDR} (bypassing datalink-los), UAVId={UAV_ID}")
    conn = mavutil.mavlink_connection(SITL_TCP_ADDR, source_system=253)
    conn.wait_heartbeat(timeout=60)
    _log("heartbeat ok, ground-truth tap ready")

    last_mode: int | None = None
    idle_since = None
    while True:
        # 배포 후 recv_match(type="HEARTBEAT", ...)가 조용히 매칭 안 되는 현상이
        # 있어(진단 중), tap.py 의 검증된 패턴(무필터 수신 후 get_type() 확인)으로
        # 통일 — 매칭 안 되고 그냥 블로킹만 되는 경로를 없앤다.
        msg = conn.recv_match(blocking=True, timeout=10.0)
        if msg is None:
            import time as _t
            now = _t.time()
            if idle_since is None or now - idle_since > 30:
                _log(f"no message in last 10s (last_mode={last_mode})")
                idle_since = now
            continue
        if msg.get_type() != "HEARTBEAT":
            continue
        idle_since = None
        current_mode = msg.custom_mode
        if current_mode != last_mode:
            _emit(handle, UAV_ID, current_mode)
            last_mode = current_mode


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("interrupted, exiting")
        sys.exit(0)
