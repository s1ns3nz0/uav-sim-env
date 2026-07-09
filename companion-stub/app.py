"""companion-stub — ground-segment GCS application + companion-computer/ROS
attack surface (S41~S47, S50 — fried-pollack-ai groundseg catalogue).

`gcs-qgc` runs the real QGroundControl binary behind noVNC — a GUI app with
no REST surface, so there is no application-level hook point for mission-
file parsing, QML injection, or auto-update MITM. Likewise this repo has no
companion computer / ROS master at all. Both were therefore complete blind
spots (fried-pollack-ai extended/groundseg catalogue, S41~S47/S50) — this
stub gives them the same kind of detectable-signature producer every other
IT-adjacent surface in this repo already has.

Safety note — same convention as `web-stub`: each endpoint simulates the
technique's detectable signature via an explicit control call. No real QGC
mission file is parsed, no real ROS master runs, no real MAVROS command
reaches a vehicle.

Feeds one table: UAVCompanion_CL
  mission_upload     — T1203(GCS mission-file parser exploit)
  plugin_inject       — T1059(QML/plugin injection)
  update_check        — T1195.002(GCS auto-update MITM)
  config_tamper       — T1565(GCS config/log tamper)
  ros_master_access   — T1190(unauthenticated ROS master)
  ros_topic_publish   — T0855(ROS topic/service injection)
  mavros_command      — T0831(MAVROS command injection)
  ntp_check           — T1195(GDT NTP timeserver spoof)
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"Component\.onCompleted", r"exec\s*\(", r"Qt\.createQmlObject", r"eval\s*\(",
    )
)
TRUSTED_APPCAST_SIGNERS: frozenset[str] = frozenset({"key:qgc-release-2026"})
KNOWN_NTP_SERVER: str = "ntp.uav-sim-env.internal"
NTP_OFFSET_ABNORMAL_SEC: float = 5.0

app = FastAPI(
    title="companion-stub",
    version="0.1.0",
    description="GCS application + companion-computer/ROS attack-surface simulation (S41~S47/S50).",
)

_log_file_handle = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(event: dict[str, Any]) -> None:
    if _log_file_handle is None:
        return
    enriched = {"TimeGenerated": _now_iso(), **event}
    _log_file_handle.write(json.dumps(enriched, separators=(",", ":"), default=str) + "\n")
    _log_file_handle.flush()


@app.on_event("startup")
def _open_sink() -> None:
    global _log_file_handle
    if not LOG_FILE_PATH:
        return
    os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
    _log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---- S41: 악성 미션파일 파싱 -------------------------------------------------

class MissionUploadRequest(BaseModel):
    filename: str = Field(..., examples=["recon-north.plan"])
    raw_content: str = Field("", max_length=8192)


@app.post("/gcs/mission-upload", tags=["gcs"])
def mission_upload(req: MissionUploadRequest) -> dict[str, Any]:
    """Upload a QGC .plan mission file for parsing.

    T1203 — path-traversal sequences inside a mission-file field (e.g. a
    payload/asset reference) are the same parser-overflow-adjacent signature
    used by the killchain C14 example, reused here for the GCS parser itself.
    """
    path_traversal = ".." in Path(req.raw_content.split()[0] if req.raw_content else "").parts
    _emit({
        "EventType": "mission_upload",
        "Target": req.filename,
        "ContentSnippet": req.raw_content[:200],
        "PathTraversalDetected": path_traversal,
        "StatusCode": 200,
    })
    return {"filename": req.filename, "accepted": True}


# ---- S42: QML/플러그인 인젝션 ------------------------------------------------

class PluginInjectRequest(BaseModel):
    plugin_name: str = Field(..., examples=["custom-widget.qml"])
    code: str = Field("", max_length=4096, examples=["import Qt; Component.onCompleted: exec('rt')"])


@app.post("/gcs/plugin-inject", tags=["gcs"])
def plugin_inject(req: PluginInjectRequest) -> dict[str, Any]:
    """Load a QML widget/plugin into the GCS UI. T1059 — pattern-matched only, never evaluated."""
    matched = next((p.pattern for p in INJECTION_PATTERNS if p.search(req.code)), None)
    _emit({
        "EventType": "plugin_inject",
        "Target": req.plugin_name,
        "ContentSnippet": req.code[:200],
        "InjectionSignatureDetected": matched is not None,
        "StatusCode": 200,
    })
    return {"plugin_name": req.plugin_name, "injection_detected": matched is not None}


# ---- S43: GCS 자동업데이트 MITM ----------------------------------------------

class UpdateCheckRequest(BaseModel):
    component: str = Field("qgc-desktop", examples=["qgc-desktop"])
    served_binary_hash: str = Field(..., examples=["sha256:deadbeef"])
    signer_key: str = Field(..., examples=["key:qgc-release-2026"])
    appcast_url: str = Field("https://updates.uav-sim-env.internal/appcast.xml")


@app.post("/gcs/update-check", tags=["gcs"])
def update_check(req: UpdateCheckRequest) -> dict[str, Any]:
    """Check for a GCS auto-update. T1195.002 — unsigned/rogue appcast served as MITM."""
    mitm_suspected = req.signer_key not in TRUSTED_APPCAST_SIGNERS
    _emit({
        "EventType": "update_check",
        "Target": req.component,
        "ContentSnippet": req.served_binary_hash,
        "MitmSuspected": mitm_suspected,
        "StatusCode": 200,
    })
    return {"component": req.component, "mitm_suspected": mitm_suspected}


# ---- S44: GCS 설정/로그 변조 -------------------------------------------------

class ConfigTamperRequest(BaseModel):
    field: str = Field(..., examples=["MAVLINK_COMM", "log_retention_days"])
    value_before: str = ""
    value_after: str = ""
    changed_by: str = Field("", examples=["operator-01"])


@app.post("/gcs/config-tamper", tags=["gcs"])
def config_tamper(req: ConfigTamperRequest) -> dict[str, Any]:
    """Change a GCS runtime config field. T1565 — e.g. redirecting MAVLINK_COMM or shrinking log retention."""
    _emit({
        "EventType": "config_tamper",
        "ConfigField": req.field,
        "ValueBefore": req.value_before,
        "ValueAfter": req.value_after,
        "ChangedBy": req.changed_by,
        "StatusCode": 200,
    })
    return {"field": req.field, "value_after": req.value_after}


# ---- S45: 무인증 ROS 마스터 접근 ---------------------------------------------

class RosMasterAccessRequest(BaseModel):
    caller_id: str = Field(..., examples=["/rogue_node"])
    action: str = Field("getSystemState", examples=["getSystemState", "lookupNode"])


@app.post("/ros/master-access", tags=["ros"])
def ros_master_access(req: RosMasterAccessRequest) -> dict[str, Any]:
    """Query the ROS master (roscore XML-RPC, port 11311 in a real deployment).

    T1190 — no authentication check is performed here at all (that's the
    vulnerability: ROS1 master has none by default), matching this repo's
    "don't block, audit" convention.
    """
    _emit({
        "EventType": "ros_master_access",
        "Target": req.caller_id,
        "ContentSnippet": req.action,
        "Authorized": False,
        "StatusCode": 200,
    })
    return {"caller_id": req.caller_id, "action": req.action}


# ---- S46: ROS 토픽/서비스 인젝션 ---------------------------------------------

class RosTopicPublishRequest(BaseModel):
    topic: str = Field(..., examples=["/cmd_vel"])
    message_type: str = Field("geometry_msgs/Twist")
    payload: str = Field("", max_length=1024)
    authorized: bool = False


@app.post("/ros/topic-publish", tags=["ros"])
def ros_topic_publish(req: RosTopicPublishRequest) -> dict[str, Any]:
    """Publish onto a ROS topic. T0855 — unauthorized publish onto a control topic."""
    _emit({
        "EventType": "ros_topic_publish",
        "Topic": req.topic,
        "ContentSnippet": req.payload[:200],
        "Authorized": req.authorized,
        "StatusCode": 200,
    })
    return {"topic": req.topic, "authorized": req.authorized}


# ---- S47: MAVROS 명령 주입 ---------------------------------------------------

class MavrosCommandRequest(BaseModel):
    command: str = Field(..., examples=["/mavros/setpoint_velocity/cmd_vel"])
    params: str = Field("", examples=["vx=5,vy=0,vz=0"])
    authorized: bool = False


@app.post("/mavros/command", tags=["ros"])
def mavros_command(req: MavrosCommandRequest) -> dict[str, Any]:
    """Publish a MAVROS setpoint/command topic. T0831 — bridges ROS injection straight to flight control."""
    _emit({
        "EventType": "mavros_command",
        "Command": req.command,
        "ContentSnippet": req.params,
        "Authorized": req.authorized,
        "StatusCode": 200,
    })
    return {"command": req.command, "authorized": req.authorized}


# ---- S50: GDT NTP 타임서버 스푸핑 --------------------------------------------

class NtpCheckRequest(BaseModel):
    ntp_server: str = Field(..., examples=["ntp.uav-sim-env.internal"])
    offset_reported_sec: float = Field(0.0, examples=[0.02])


@app.post("/gdt/ntp-check", tags=["gdt"])
def ntp_check(req: NtpCheckRequest) -> dict[str, Any]:
    """Report the GDT's NTP sync check. T1195 — rogue timeserver or abnormal offset
    (used to skew log correlation and cert-expiry checks, per killchain notes)."""
    spoof_suspected = (
        req.ntp_server != KNOWN_NTP_SERVER or abs(req.offset_reported_sec) > NTP_OFFSET_ABNORMAL_SEC
    )
    _emit({
        "EventType": "ntp_check",
        "NtpServer": req.ntp_server,
        "OffsetReportedSec": req.offset_reported_sec,
        "MitmSuspected": spoof_suspected,
        "StatusCode": 200,
    })
    return {"ntp_server": req.ntp_server, "spoof_suspected": spoof_suspected}
