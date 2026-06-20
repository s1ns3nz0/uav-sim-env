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

# Stateful trackers used to derive named mission events from the message stream.
_last_mode: int | None = None
_last_mission_seq: int | None = None
_last_position: dict[str, float | None] = {"Lat": None, "Lon": None, "AltMSL_m": None}


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


def _emit(record: dict[str, Any]) -> None:
    """Serialize a record as a single-line JSON document on stdout (and file sinks)."""
    line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    if _log_file_handle is not None:
        _log_file_handle.write(line)
        _log_file_handle.flush()
    _maybe_derive_mission_events(record)
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
    record: dict[str, Any] = {
        "TimeGenerated": _now_iso(),
        "UAVId": UAV_ID,
        "MsgType": msg_type,
        "SystemId": msg.get_srcSystem(),
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
