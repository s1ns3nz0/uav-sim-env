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

    # 이 tap 은 TCP 클라이언트로 능동 접속(datalink-los 처럼 서버가 push 해주는
    # udpin 방식이 아님) — 진단 결과 첫 heartbeat 이후 스트림이 조용해지는 현상
    # 확인. 표준 MAVLink GCS 클라이언트처럼 자체 heartbeat 를 1Hz 로 송신해
    # "활성 GCS" 로 등록시킨다(REQUEST_DATA_STREAM 없이도 HEARTBEAT 는 보통
    # 항상 브로드캐스트되지만, 클라이언트 쪽 무응답으로 링크가 유휴/정리되는
    # 경로를 배제하기 위한 방어적 조치).
    import time as _t

    last_mode: int | None = None
    idle_since = None
    last_hb_sent = 0.0
    while True:
        now = _t.time()
        if now - last_hb_sent >= 1.0:
            conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0,
            )
            last_hb_sent = now
        msg = conn.recv_match(blocking=True, timeout=2.0)
        if msg is None:
            if idle_since is None or now - idle_since > 30:
                _log(f"no message in last 2s (last_mode={last_mode})")
                idle_since = now
            continue
        if msg.get_type() != "HEARTBEAT" or msg.get_srcSystem() == 253:
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
