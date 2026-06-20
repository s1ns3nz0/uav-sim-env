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


def _emit(record: dict[str, Any]) -> None:
    """Serialize a record as a single-line JSON document on stdout."""
    sys.stdout.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    sys.stdout.flush()


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
