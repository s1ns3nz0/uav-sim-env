"""MAVLink → NDJSON telemetry tap.

Subscribes to a MAVLink UDP stream forwarded by mavlink-router and emits one
JSON line per decoded message to stdout. Phase 2 will plug this stdout into the
Azure Monitor Agent so that Sentinel can ingest into a custom table consumed by
the SOC LangGraph agents (project: pollack-ai).

Field naming mirrors the schema referenced by the Sigma analytic rules
(uav_gps_spoof_residual.yml, uav_satcom_integrity_fail.yml,
uav_fw_signature_mismatch.yml) — UAVId, TimeGenerated, MsgType.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from pymavlink import mavutil


UAV_ID: str = os.environ.get("UAV_ID", "MPD-001")
LISTEN_HOST: str = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT: int = int(os.environ.get("LISTEN_PORT", "14552"))

# Optional file sink for Azure Monitor Agent / Fluent Bit tail consumption.
# If set, every NDJSON record is also appended to this file (one JSON per line).
LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

# Optional secondary sink — only operator-relevant records (commands, mission
# lifecycle, mode changes). Designed to feed UAVOperator_CL for forensic and
# insider-threat rules.
OPERATOR_FILE_PATH: str = os.environ.get("OPERATOR_FILE_PATH", "")

# Optional tertiary sink — high-level mission lifecycle events derived from the
# raw stream (takeoff_initiated, waypoint_reached, roi_set, land_initiated...).
# Feeds UAVMissionEvent_CL for timeline rules and after-action review.
MISSION_FILE_PATH: str = os.environ.get("MISSION_FILE_PATH", "")

# Failsafe sink — STATUSTEXT severity <= warning OR mode transitions to a
# failsafe mode (RTL/QRTL/LAND/QLAND).
FAILSAFE_FILE_PATH: str = os.environ.get("FAILSAFE_FILE_PATH", "")

# Config audit sink — PARAM_VALUE rows whose value differs from the last seen.
CONFIG_AUDIT_FILE_PATH: str = os.environ.get("CONFIG_AUDIT_FILE_PATH", "")

# Imagery / payload sink — camera trigger, image captured, video stream info.
IMAGERY_FILE_PATH: str = os.environ.get("IMAGERY_FILE_PATH", "")

# MAVSec sink — signing summary every MAVSEC_INTERVAL_SEC.
MAVSEC_FILE_PATH: str = os.environ.get("MAVSEC_FILE_PATH", "")
MAVSEC_INTERVAL_SEC: int = int(os.environ.get("MAVSEC_INTERVAL_SEC", "30"))

# Fleet-state sink — swarm-level summary every FLEET_STATE_INTERVAL_SEC.
# Only meaningful in fleet mode (UAV_ID starts with "MUAV-AKS", multiple
# SystemIds multiplexed through this one process — see uav_id derivation in
# _record_for). S101(leader-spoof)/S102(consensus poison)/S107(command
# replay) surface here as divergence/anomaly, not as their own event stream.
FLEET_STATE_FILE_PATH: str = os.environ.get("FLEET_STATE_FILE_PATH", "")
FLEET_STATE_INTERVAL_SEC: int = int(os.environ.get("FLEET_STATE_INTERVAL_SEC", "30"))
FLEET_ID: str = os.environ.get("FLEET_ID", "MUAV-FLT-1")
FLEET_DIVERGE_THRESHOLD_DEG: float = float(os.environ.get("FLEET_DIVERGE_THRESHOLD_DEG", "0.01"))
# S103(상대항법 스푸핑→충돌유도) — 편대원 쌍(pairwise) 최소거리가 이 아래로 붙으면 위험.
FLEET_COLLISION_THRESHOLD_DEG: float = float(os.environ.get("FLEET_COLLISION_THRESHOLD_DEG", "0.0005"))
# S105(Sybil 가짜노드) — 알려진 편대 명단(콤마구분). 비우면 검사 생략(명단 모름=플래그 불가).
EXPECTED_FLEET_MEMBERS: frozenset[str] = frozenset(
    m.strip() for m in os.environ.get("EXPECTED_FLEET_MEMBERS", "").split(",") if m.strip()
)

# MAVLink message types that represent operator-initiated control actions.
OPERATOR_MSG_TYPES: frozenset[str] = frozenset({
    "COMMAND_LONG",
    "COMMAND_ACK",
    "MISSION_CURRENT",
    "MISSION_ITEM_REACHED",
})

# MAV_CMD numeric ids worth labelling explicitly. Anything else gets
# "command_<id>" so downstream rules can still match on Command.
_MAV_CMD_ACTION: dict[int, str] = {
    20: "rtl",
    21: "land",
    22: "takeoff",
    84: "vtol_takeoff",
    85: "vtol_land",
    176: "mode_change",
    195: "set_roi_location",
    197: "set_roi_none",
    400: "arm_disarm",
}

# Messages worth forwarding to the SOC pipeline. Anything else is dropped to
# keep ingest volume bounded.
FORWARDED_MSG_TYPES: frozenset[str] = frozenset({
    "HEARTBEAT",
    "GLOBAL_POSITION_INT",
    "GPS_RAW_INT",
    "GPS2_RAW",
    "ATTITUDE",
    "VFR_HUD",
    "SYS_STATUS",
    "BATTERY_STATUS",
    "LOCAL_POSITION_NED",
    "EKF_STATUS_REPORT",
    "VIBRATION",
    "MISSION_CURRENT",
    "MISSION_ITEM_REACHED",
    "STATUSTEXT",
    "COMMAND_LONG",
    "COMMAND_ACK",
    "PARAM_VALUE",
    "CAMERA_TRIGGER",
    "CAMERA_IMAGE_CAPTURED",
    "VIDEO_STREAM_INFORMATION",
    "MOUNT_ORIENTATION",
    "CAMERA_INFORMATION",
})


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 with millisecond precision."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _log(line: str) -> None:
    """Write a diagnostic line to stderr (stdout is reserved for NDJSON)."""
    sys.stderr.write(f"[telemetry-tap] {line}\n")
    sys.stderr.flush()


_log_file_handle = None
_operator_file_handle = None
_mission_file_handle = None
_failsafe_file_handle = None
_config_audit_file_handle = None
_imagery_file_handle = None
_mavsec_file_handle = None
_fleet_state_file_handle = None

# Stateful trackers used to derive named mission events from the message stream.
_last_mode: int | None = None
_last_mission_seq: int | None = None
_last_heartbeat_epoch: float | None = None
HEARTBEAT_GAP_THRESHOLD_SEC = 5.0  # ArduPilot HEARTBEAT ~1Hz — 이보다 긴 공백은 이상
_last_position: dict[str, float | None] = {"Lat": None, "Lon": None, "AltMSL_m": None}
_param_state: dict[str, float] = {}
_mavsec_signed = 0
_mavsec_unsigned = 0
_mavsec_last_emit_ts: float = 0.0

# Per-UAVId fleet state, keyed by uav_id. Reset (command tally) each window.
_fleet_positions: dict[str, dict[str, float]] = {}
_fleet_command_tally: dict[str, int] = {}
_fleet_state_last_emit_ts: float = 0.0

# Failsafe-flavoured ArduPilot modes (custom_mode int). Mirrors mode_change
# numbers we are most interested in (ArduPlane + Quadplane).
FAILSAFE_MODES: frozenset[int] = frozenset({
    11, # RTL (ArduPlane)
    25, # QRTL
    21, # QLand
})

# MAVLink message types that represent operator-initiated control actions.
IMAGERY_MSG_TYPES: frozenset[str] = frozenset({
    "CAMERA_TRIGGER",
    "CAMERA_IMAGE_CAPTURED",
    "VIDEO_STREAM_INFORMATION",
    "MOUNT_ORIENTATION",
    "CAMERA_INFORMATION",
})


def _derive_action(record: dict[str, Any]) -> str:
    """Map a forwarded record to a normalised operator action name."""
    msg_type = record.get("MsgType", "")
    if msg_type == "COMMAND_LONG":
        command = record.get("Command")
        if isinstance(command, int):
            return _MAV_CMD_ACTION.get(command, f"command_{command}")
        return "command_unknown"
    if msg_type == "COMMAND_ACK":
        command = record.get("Command")
        if isinstance(command, int):
            return f"ack_{_MAV_CMD_ACTION.get(command, str(command))}"
        return "ack_unknown"
    if msg_type == "MISSION_CURRENT":
        return "mission_current_changed"
    if msg_type == "MISSION_ITEM_REACHED":
        return "mission_waypoint_reached"
    return msg_type.lower()


def _emit_mission_event(event_name: str, record: dict[str, Any], **extras: Any) -> None:
    """Append a named mission lifecycle event to the mission sink."""
    if _mission_file_handle is None:
        return
    payload = {
        "TimeGenerated": record.get("TimeGenerated"),
        "UAVId": record.get("UAVId"),
        "EventName": event_name,
        "MsgType": record.get("MsgType"),
        "Command": record.get("Command"),
        "Seq": record.get("Seq"),
        "Lat": _last_position["Lat"],
        "Lon": _last_position["Lon"],
        "AltMSL_m": _last_position["AltMSL_m"],
        "StreamMission": "mission",
        **extras,
    }
    _mission_file_handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    _mission_file_handle.flush()


def _maybe_derive_mission_events(record: dict[str, Any]) -> None:
    """Update stateful trackers and emit named mission events when triggers fire."""
    global _last_mode, _last_mission_seq

    msg_type = record.get("MsgType")

    # Update last-known position from telemetry — used to attach geo to events.
    if msg_type == "GLOBAL_POSITION_INT":
        _last_position["Lat"] = record.get("Lat")
        _last_position["Lon"] = record.get("Lon")
        _last_position["AltMSL_m"] = record.get("AltMSL_m")
        return

    if _mission_file_handle is None:
        return

    if msg_type == "HEARTBEAT":
        current_mode = record.get("CustomMode")
        if isinstance(current_mode, int) and current_mode != _last_mode:
            _emit_mission_event(
                "mode_change",
                record,
                CustomModeBefore=_last_mode,
                CustomModeAfter=current_mode,
            )
            _last_mode = current_mode
        return

    if msg_type == "MISSION_CURRENT":
        seq = record.get("Seq")
        if isinstance(seq, int) and seq != _last_mission_seq:
            if seq == 0 and _last_mission_seq is not None and _last_mission_seq > 0:
                _emit_mission_event("mission_reset", record)
            elif _last_mission_seq is None or seq > (_last_mission_seq or 0):
                _emit_mission_event("mission_seq_advanced", record)
            _last_mission_seq = seq
        return

    if msg_type == "MISSION_ITEM_REACHED":
        _emit_mission_event("waypoint_reached", record)
        return

    if msg_type == "COMMAND_LONG":
        command = record.get("Command")
        named = _MAV_CMD_ACTION.get(command if isinstance(command, int) else -1)
        if named is None:
            return
        _emit_mission_event(named, record)


def _emit_failsafe(payload: dict[str, Any]) -> None:
    _failsafe_file_handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    _failsafe_file_handle.flush()


def _maybe_emit_failsafe(record: dict[str, Any]) -> None:
    global _last_heartbeat_epoch
    if _failsafe_file_handle is None:
        return
    msg_type = record.get("MsgType")
    payload: dict[str, Any] | None = None
    if msg_type == "STATUSTEXT":
        severity = record.get("Severity")
        if isinstance(severity, int) and severity <= 4:
            payload = {
                "TimeGenerated": record.get("TimeGenerated"),
                "UAVId": record.get("UAVId"),
                "EventType": "statustext_warning",
                "Severity": severity,
                "Text": record.get("Text"),
                "StreamFailsafe": "failsafe",
            }
    elif msg_type == "HEARTBEAT":
        current = record.get("CustomMode")
        if isinstance(current, int) and current in FAILSAFE_MODES and current != _last_mode:
            payload = {
                "TimeGenerated": record.get("TimeGenerated"),
                "UAVId": record.get("UAVId"),
                "EventType": "mode_failsafe_transition",
                "ModeBefore": _last_mode,
                "ModeAfter": current,
                "Severity": 4,
                "StreamFailsafe": "failsafe",
            }

        # T0878(Alarm Suppression) — 경보 자체를 "변조"하는 게 아니라 링크 상에서
        # 가로채/드롭하는 억제는 그 억제 행위 자체를 직접 기록할 방법이 없다(수신 못한
        # 메시지는 로그할 수 없음). 대신 ArduPilot HEARTBEAT(~1Hz) 주기의 비정상 공백을
        # 대리 신호로 잡는다 — 활성 비행 중(SystemStatus=4) 공백은 링크 억제/차단 정황.
        now_epoch = time.time()
        system_status = record.get("SystemStatus")
        if (
            _last_heartbeat_epoch is not None
            and system_status == 4
            and now_epoch - _last_heartbeat_epoch > HEARTBEAT_GAP_THRESHOLD_SEC
        ):
            _emit_failsafe({
                "TimeGenerated": record.get("TimeGenerated"),
                "UAVId": record.get("UAVId"),
                "EventType": "heartbeat_gap_suspected",
                "GapSec": round(now_epoch - _last_heartbeat_epoch, 1),
                "Severity": 3,
                "StreamFailsafe": "failsafe",
            })
        _last_heartbeat_epoch = now_epoch
    if payload is None:
        return
    _emit_failsafe(payload)


def _maybe_emit_config_audit(record: dict[str, Any]) -> None:
    if _config_audit_file_handle is None or record.get("MsgType") != "PARAM_VALUE":
        return
    param_id = record.get("ParamId")
    new_value = record.get("ParamValue")
    if not isinstance(param_id, str) or new_value is None:
        return
    previous = _param_state.get(param_id)
    if previous is not None and previous == new_value:
        return  # no change
    payload = {
        "TimeGenerated": record.get("TimeGenerated"),
        "UAVId": record.get("UAVId"),
        "EventType": "param_changed" if previous is not None else "persona_loaded",
        "ParamId": param_id,
        "ParamValueBefore": previous,
        "ParamValueAfter": new_value,
        "Source": "sitl",
        "StreamConfigAudit": "config-audit",
    }
    _param_state[param_id] = new_value
    _config_audit_file_handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    _config_audit_file_handle.flush()


def _maybe_emit_imagery(record: dict[str, Any]) -> None:
    if _imagery_file_handle is None or record.get("MsgType") not in IMAGERY_MSG_TYPES:
        return
    payload = {
        "TimeGenerated": record.get("TimeGenerated"),
        "UAVId": record.get("UAVId"),
        "EventType": record.get("MsgType", "").lower(),
        "MsgType": record.get("MsgType"),
        "StreamImagery": "imagery",
    }
    _imagery_file_handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    _imagery_file_handle.flush()


def _maybe_emit_mavsec(msg: Any, record: dict[str, Any]) -> None:
    global _mavsec_signed, _mavsec_unsigned, _mavsec_last_emit_ts
    if _mavsec_file_handle is None:
        return
    is_signed = bool(getattr(msg, "_signed", False))
    if is_signed:
        _mavsec_signed += 1
    else:
        _mavsec_unsigned += 1
    now = time.time()
    if now - _mavsec_last_emit_ts < MAVSEC_INTERVAL_SEC:
        return
    payload = {
        "TimeGenerated": record.get("TimeGenerated"),
        "UAVId": record.get("UAVId"),
        "EventType": "signing_check_summary",
        "SignedCount": _mavsec_signed,
        "UnsignedCount": _mavsec_unsigned,
        "FailedCount": 0,
        "WindowSec": MAVSEC_INTERVAL_SEC,
        "StreamMavsec": "mavsec",
    }
    _mavsec_file_handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    _mavsec_file_handle.flush()
    _mavsec_signed = 0
    _mavsec_unsigned = 0
    _mavsec_last_emit_ts = now


def _fleet_track(record: dict[str, Any]) -> None:
    """Update per-UAVId fleet state from a forwarded record. Cheap, always runs."""
    uav_id = record.get("UAVId")
    if not isinstance(uav_id, str):
        return
    msg_type = record.get("MsgType")
    if msg_type == "GLOBAL_POSITION_INT":
        lat, lon = record.get("Lat"), record.get("Lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            _fleet_positions[uav_id] = {"Lat": lat, "Lon": lon, "ts": time.time()}
    elif msg_type == "COMMAND_LONG":
        action = _derive_action(record)
        _fleet_command_tally[action] = _fleet_command_tally.get(action, 0) + 1


def _maybe_emit_fleet_state(now_epoch: float) -> None:
    """Periodically summarise fleet-wide state — S101/S102/S107 surface here
    as divergence/anomaly since none of them get their own event stream
    (leader-spoof/consensus-poison/command-replay are collective-behaviour
    attacks, not single-message signatures)."""
    global _fleet_state_last_emit_ts
    if _fleet_state_file_handle is None:
        return
    if now_epoch - _fleet_state_last_emit_ts < FLEET_STATE_INTERVAL_SEC:
        return
    _fleet_state_last_emit_ts = now_epoch

    # Drop stale members (no position update within 3 windows — vehicle went dark).
    stale_cutoff = now_epoch - 3 * FLEET_STATE_INTERVAL_SEC
    active = {uid: p for uid, p in _fleet_positions.items() if p["ts"] >= stale_cutoff}
    active_count = len(active)

    diverging = 0
    min_pair_dist: float | None = None
    collision_risk_pair = ""
    if active_count >= 2:
        centroid_lat = sum(p["Lat"] for p in active.values()) / active_count
        centroid_lon = sum(p["Lon"] for p in active.values()) / active_count
        for p in active.values():
            dist = ((p["Lat"] - centroid_lat) ** 2 + (p["Lon"] - centroid_lon) ** 2) ** 0.5
            if dist > FLEET_DIVERGE_THRESHOLD_DEG:
                diverging += 1

        # S103(상대위치 스푸핑→충돌유도) — 편대원 쌍의 최소거리. 진짜 상대항법이면
        # 절대 이 임계 아래로 안 붙으므로, 붙었다면 둘 중 하나(또는 둘 다)의
        # 상대위치가 스푸핑됐다는 뜻.
        items = list(active.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (uid_a, pa), (uid_b, pb) = items[i], items[j]
                pair_dist = ((pa["Lat"] - pb["Lat"]) ** 2 + (pa["Lon"] - pb["Lon"]) ** 2) ** 0.5
                if min_pair_dist is None or pair_dist < min_pair_dist:
                    min_pair_dist = pair_dist
                    collision_risk_pair = f"{uid_a}|{uid_b}"

    # S105(Sybil 가짜노드) — 알려진 편대 명단 밖의 UAVId가 활성으로 보이면 가짜 노드 의심.
    unknown_uav_detected = bool(EXPECTED_FLEET_MEMBERS) and any(
        uid not in EXPECTED_FLEET_MEMBERS for uid in active
    )

    common_command = max(_fleet_command_tally, key=_fleet_command_tally.get) if _fleet_command_tally else ""
    # S107(command replay/amplification) — same command hitting most/all of the
    # fleet in one window is itself the anomaly signature, independent of divergence.
    replay_ratio = (_fleet_command_tally.get(common_command, 0) / active_count) if active_count else 0.0
    diverge_ratio = (diverging / active_count) if active_count else 0.0
    collision_ratio = 1.0 if (
        min_pair_dist is not None and min_pair_dist < FLEET_COLLISION_THRESHOLD_DEG
    ) else 0.0
    anomaly_score = round(min(1.0, max(
        diverge_ratio, min(1.0, replay_ratio / 3), collision_ratio,
        1.0 if unknown_uav_detected else 0.0,
    )), 2)

    payload = {
        "TimeGenerated": _now_iso(),
        "WindowStart": datetime.fromtimestamp(
            now_epoch - FLEET_STATE_INTERVAL_SEC, tz=timezone.utc
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "FleetId": FLEET_ID,
        "ActiveUAVCount": active_count,
        "DivergingCount": diverging,
        "CommonCommand": common_command,
        "AnomalyScore": anomaly_score,
        "MinPairDistanceDeg": min_pair_dist,
        "CollisionRiskPair": collision_risk_pair,
        "UnknownUavIdDetected": unknown_uav_detected,
        "StreamFleetState": "fleet-state",
    }
    _fleet_state_file_handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    _fleet_state_file_handle.flush()
    _fleet_command_tally.clear()


def _emit(record: dict[str, Any]) -> None:
    """Serialize a record as a single-line JSON document on stdout (and file sinks)."""
    record["StreamTelemetry"] = "telemetry"
    line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    if _log_file_handle is not None:
        _log_file_handle.write(line)
        _log_file_handle.flush()
    _maybe_derive_mission_events(record)
    _maybe_emit_failsafe(record)
    _maybe_emit_config_audit(record)
    _maybe_emit_imagery(record)
    _fleet_track(record)
    if _operator_file_handle is not None and record.get("MsgType") in OPERATOR_MSG_TYPES:
        op_record = {
            "TimeGenerated": record.get("TimeGenerated"),
            "UAVId": record.get("UAVId"),
            "ActionName": _derive_action(record),
            "MsgType": record.get("MsgType"),
            "SourceSystemId": record.get("SystemId"),
            "SourceComponentId": record.get("ComponentId"),
            "TargetSystemId": record.get("TargetSystem"),
            "TargetComponentId": record.get("TargetComponent"),
            "Command": record.get("Command"),
            "Confirmation": record.get("Confirmation"),
            "Param1": record.get("Param1"),
            "Param2": record.get("Param2"),
            "Param3": record.get("Param3"),
            "Param4": record.get("Param4"),
            "Result": record.get("Result"),
            "Seq": record.get("Seq"),
            "StreamOperator": "operator",
        }
        op_line = json.dumps(op_record, separators=(",", ":"), default=str) + "\n"
        _operator_file_handle.write(op_line)
        _operator_file_handle.flush()


def _record_for(msg: Any) -> dict[str, Any]:
    """Project a pymavlink message onto a flat dict for NDJSON emission.

    Args:
        msg: A decoded pymavlink message instance.

    Returns:
        A dict with TimeGenerated, UAVId, MsgType, plus message-specific fields.
    """
    msg_type = msg.get_type()
    sys_id = msg.get_srcSystem()
    # 편대 모드: UAV_ID 가 prefix("MUAV-AKS") 면 SysId 별로 suffix(-SYS00N) 박아
    # 같은 telemetry-tap 가 다중 vehicle 의 NDJSON 을 UAVId 로 구분 가능하게.
    # 단일 vehicle 시절 호환: UAV_ID 가 그대로 "MUAV-001" 같은 완전체면 suffix X.
    if UAV_ID.startswith("MUAV-AKS") and "-SYS" not in UAV_ID:
        uav_id = f"{UAV_ID}-SYS{sys_id:03d}"
    else:
        uav_id = UAV_ID
    record: dict[str, Any] = {
        "TimeGenerated": _now_iso(),
        "UAVId": uav_id,
        "MsgType": msg_type,
        "SystemId": sys_id,
        "ComponentId": msg.get_srcComponent(),
    }

    if msg_type == "HEARTBEAT":
        record.update({
            "SystemStatus": msg.system_status,
            "BaseMode": msg.base_mode,
            "CustomMode": msg.custom_mode,
            "MavlinkVersion": msg.mavlink_version,
        })
    elif msg_type == "GLOBAL_POSITION_INT":
        record.update({
            "Lat": msg.lat / 1e7,
            "Lon": msg.lon / 1e7,
            "AltMSL_m": msg.alt / 1000.0,
            "AltRel_m": msg.relative_alt / 1000.0,
            "VxNorth_cms": msg.vx,
            "VyEast_cms": msg.vy,
            "VzDown_cms": msg.vz,
            "Heading_cdeg": msg.hdg,
        })
    elif msg_type in ("GPS_RAW_INT", "GPS2_RAW"):
        record.update({
            "FixType": msg.fix_type,
            "Lat": msg.lat / 1e7,
            "Lon": msg.lon / 1e7,
            "AltMSL_m": msg.alt / 1000.0,
            "Eph_cm": msg.eph,
            "Epv_cm": msg.epv,
            "VelGround_cms": msg.vel,
            "CourseOverGround_cdeg": msg.cog,
            "SatellitesVisible": msg.satellites_visible,
        })
    elif msg_type == "GPS_INPUT":
        # GPS_INPUT는 외부 주입 API 메시지 — 실제 온보드 GPS 수신기는 스스로
        # 이 메시지를 만들지 않는다. 존재 자체가 GNSS 스푸핑/주입 신호
        # (S1 GNSS 스푸핑, S61 GNSS 나포). EKF_STATUS_REPORT 분산치와 상관하면
        # 주입 시점→EKF 이상 반응까지 인과관계로 추적 가능.
        record.update({
            "GpsInputInjected": True,
            "Lat": msg.lat / 1e7,
            "Lon": msg.lon / 1e7,
            "AltMSL_m": msg.alt,
            "FixType": msg.fix_type,
            "Hdop": msg.hdop,
            "Vdop": msg.vdop,
            "SatellitesVisible": msg.satellites_visible,
            "IgnoreFlags": msg.ignore_flags,
        })
    elif msg_type == "ATTITUDE":
        record.update({
            "Roll_rad": msg.roll,
            "Pitch_rad": msg.pitch,
            "Yaw_rad": msg.yaw,
            "RollSpeed_rads": msg.rollspeed,
            "PitchSpeed_rads": msg.pitchspeed,
            "YawSpeed_rads": msg.yawspeed,
        })
    elif msg_type == "VFR_HUD":
        record.update({
            "Airspeed_ms": msg.airspeed,
            "Groundspeed_ms": msg.groundspeed,
            "Heading_deg": msg.heading,
            "Throttle_pct": msg.throttle,
            "AltMSL_m": msg.alt,
            "ClimbRate_ms": msg.climb,
        })
    elif msg_type == "SYS_STATUS":
        record.update({
            "BatteryVoltage_mV": msg.voltage_battery,
            "BatteryCurrent_cA": msg.current_battery,
            "BatteryRemaining_pct": msg.battery_remaining,
            "OnboardCpuLoad_pct": msg.load / 10.0,
            "ErrorsComm": msg.errors_comm,
            "DropRateComm_pct": msg.drop_rate_comm / 100.0,
        })
    elif msg_type == "BATTERY_STATUS":
        record.update({
            "BatteryId": msg.id,
            "CurrentBattery_cA": msg.current_battery,
            "EnergyConsumed_hJ": msg.energy_consumed,
            "BatteryRemaining_pct": msg.battery_remaining,
            "Voltages_mV": list(msg.voltages),
        })
    elif msg_type == "LOCAL_POSITION_NED":
        record.update({
            "X_m": msg.x,
            "Y_m": msg.y,
            "Z_m": msg.z,
            "Vx_ms": msg.vx,
            "Vy_ms": msg.vy,
            "Vz_ms": msg.vz,
        })
    elif msg_type == "EKF_STATUS_REPORT":
        # Direct input for S1 GNSS-spoofing rule (residual ratios).
        record.update({
            "EkfFlags": msg.flags,
            "VelocityVariance": msg.velocity_variance,
            "PosHorizVariance": msg.pos_horiz_variance,
            "PosVertVariance": msg.pos_vert_variance,
            "CompassVariance": msg.compass_variance,
            "TerrainAltVariance": msg.terrain_alt_variance,
        })
    elif msg_type == "VIBRATION":
        record.update({
            "VibrationX": msg.vibration_x,
            "VibrationY": msg.vibration_y,
            "VibrationZ": msg.vibration_z,
            "Clipping0": msg.clipping_0,
            "Clipping1": msg.clipping_1,
            "Clipping2": msg.clipping_2,
        })
    elif msg_type == "STATUSTEXT":
        record.update({
            "Severity": msg.severity,
            "Text": msg.text,
        })
    elif msg_type == "MISSION_CURRENT":
        record["Seq"] = msg.seq
    elif msg_type == "MISSION_ITEM_REACHED":
        record["Seq"] = msg.seq
    elif msg_type == "COMMAND_LONG":
        record.update({
            "Command": msg.command,
            "Confirmation": msg.confirmation,
            "Param1": msg.param1,
            "Param2": msg.param2,
            "Param3": msg.param3,
            "Param4": msg.param4,
            "TargetSystem": msg.target_system,
            "TargetComponent": msg.target_component,
        })
    elif msg_type == "COMMAND_ACK":
        record.update({
            "Command": msg.command,
            "Result": msg.result,
        })
    elif msg_type == "PARAM_VALUE":
        record.update({
            "ParamId": msg.param_id,
            "ParamValue": msg.param_value,
            "ParamType": msg.param_type,
            "ParamCount": msg.param_count,
            "ParamIndex": msg.param_index,
        })

    return record


def main() -> None:
    """Run the UDP subscriber loop and emit NDJSON to stdout."""
    global _log_file_handle, _operator_file_handle, _mission_file_handle
    global _failsafe_file_handle, _config_audit_file_handle, _imagery_file_handle, _mavsec_file_handle
    global _fleet_state_file_handle
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        _log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
        _log(f"file sink active: {LOG_FILE_PATH}")
    if OPERATOR_FILE_PATH:
        os.makedirs(os.path.dirname(OPERATOR_FILE_PATH) or ".", exist_ok=True)
        _operator_file_handle = open(OPERATOR_FILE_PATH, "a", encoding="utf-8")
        _log(f"operator sink active: {OPERATOR_FILE_PATH}")
    if MISSION_FILE_PATH:
        os.makedirs(os.path.dirname(MISSION_FILE_PATH) or ".", exist_ok=True)
        _mission_file_handle = open(MISSION_FILE_PATH, "a", encoding="utf-8")
        _log(f"mission sink active: {MISSION_FILE_PATH}")
    if FAILSAFE_FILE_PATH:
        os.makedirs(os.path.dirname(FAILSAFE_FILE_PATH) or ".", exist_ok=True)
        _failsafe_file_handle = open(FAILSAFE_FILE_PATH, "a", encoding="utf-8")
        _log(f"failsafe sink active: {FAILSAFE_FILE_PATH}")
    if CONFIG_AUDIT_FILE_PATH:
        os.makedirs(os.path.dirname(CONFIG_AUDIT_FILE_PATH) or ".", exist_ok=True)
        _config_audit_file_handle = open(CONFIG_AUDIT_FILE_PATH, "a", encoding="utf-8")
        _log(f"config-audit sink active: {CONFIG_AUDIT_FILE_PATH}")
    if IMAGERY_FILE_PATH:
        os.makedirs(os.path.dirname(IMAGERY_FILE_PATH) or ".", exist_ok=True)
        _imagery_file_handle = open(IMAGERY_FILE_PATH, "a", encoding="utf-8")
        _log(f"imagery sink active: {IMAGERY_FILE_PATH}")
    if MAVSEC_FILE_PATH:
        os.makedirs(os.path.dirname(MAVSEC_FILE_PATH) or ".", exist_ok=True)
        _mavsec_file_handle = open(MAVSEC_FILE_PATH, "a", encoding="utf-8")
        _log(f"mavsec sink active: {MAVSEC_FILE_PATH}")
    if FLEET_STATE_FILE_PATH:
        os.makedirs(os.path.dirname(FLEET_STATE_FILE_PATH) or ".", exist_ok=True)
        _fleet_state_file_handle = open(FLEET_STATE_FILE_PATH, "a", encoding="utf-8")
        _log(f"fleet-state sink active: {FLEET_STATE_FILE_PATH} (fleet={FLEET_ID})")

    conn_str = f"udpin:{LISTEN_HOST}:{LISTEN_PORT}"
    _log(f"binding {conn_str}, UAVId={UAV_ID}")
    conn = mavutil.mavlink_connection(conn_str, source_system=254)
    _log("ready, awaiting MAVLink frames")

    msg_count = 0
    last_log = 0.0
    while True:
        msg = conn.recv_match(blocking=True, timeout=5.0)
        if msg is None:
            continue
        msg_type = msg.get_type()
        if msg_type == "BAD_DATA":
            continue
        if msg_type not in FORWARDED_MSG_TYPES:
            continue

        try:
            record = _record_for(msg)
        except (AttributeError, TypeError, ValueError) as exc:
            _log(f"projection error on {msg_type}: {exc}")
            continue

        _emit(record)
        _maybe_emit_mavsec(msg, record)
        _maybe_emit_fleet_state(time.time())
        msg_count += 1

        # Heartbeat log every ~500 records so operators see liveness on stderr.
        if msg_count % 500 == 0:
            _log(f"emitted {msg_count} records")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("interrupted, exiting")
        sys.exit(0)
