"""fleet-infra-stub — fleet-management API + video-relay + swarm-coordination
attack surface (S81, S83, S106, S108).

Grilling-session decisions this stub embodies:
  - S81(fleet API)/S83(RTSP) are a genuinely new "ground infra backend"
    surface, kept separate from `companion-stub`(GCS/ROS) to avoid
    overloading one container with unrelated domains.
  - S106(flocking-rule tamper)/S108(mesh partition) have **no underlying
    simulated capability in this repo** — there is no real flocking
    control loop or inter-vehicle mesh network, only independent SITL
    instances (verified: no `flocking`/`mesh` implementation anywhere in
    this repo before this stub). These two endpoints are therefore pure
    self-report — a caller declares the tamper/partition occurred and the
    stub only records it, same as every other "confessed" IT-layer stub.
    Detection value comes from downstream anomaly correlation (fleet
    behaviour actually going erratic in `UAVFleetState_CL`), not from any
    real swarm-control instrumentation.

Safety note — no real HTTP fleet API, RTSP session, flocking controller, or
mesh network exists to be exploited; every endpoint is a detectable-
signature simulation identical in spirit to `web-stub`.

Feeds one table: UAVFleetInfra_CL
  fleet_api_access  — S81(T1190, fleet-management API IDOR/auth-bypass)
  rtsp_hijack       — S83(T1557, video-stream RTSP session hijack)
  flocking_tamper   — S106(T0836, flocking rule parameter tamper — self-report)
  mesh_link_status  — S108(T0814, inter-vehicle mesh partition — self-report)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

_FLEET_OWNERS: dict[str, str] = {"MUAV-FLT-1": "maj.cho", "MUAV-FLT-2": "capt.park"}
_RTSP_STREAM_OWNERS: dict[str, str] = {}  # stream_id -> current session_id, set on first DESCRIBE

app = FastAPI(
    title="fleet-infra-stub",
    version="0.1.0",
    description="Fleet-management API + RTSP relay + swarm-coordination attack-surface simulation.",
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


# ---- S81: 함대관리 API 인증우회(IDOR) ----------------------------------------

@app.get("/api/fleet/{fleet_id}", tags=["fleet"])
def get_fleet(fleet_id: str, requester_id: str = "") -> dict[str, Any]:
    """Return a fleet's roster/status. T1190 — same IDOR pattern as web-stub's
    `/weapon/{operator_id}`: no ownership check against the caller's identity."""
    owner = _FLEET_OWNERS.get(fleet_id)
    idor_suspected = bool(requester_id) and requester_id != owner
    _emit({
        "EventType": "fleet_api_access",
        "FleetId": fleet_id,
        "RequesterId": requester_id,
        "TargetId": owner or "",
        "IdorSuspected": idor_suspected,
        "StatusCode": 200 if owner else 404,
    })
    if owner is None:
        return {"fleet_id": fleet_id, "found": False}
    return {"fleet_id": fleet_id, "owner": owner, "idor_suspected": idor_suspected}


# ---- S83: 영상스트림 RTSP 하이재킹 -------------------------------------------

class RtspSessionRequest(BaseModel):
    stream_id: str = Field(..., examples=["MPD-001-EOIR"])
    session_id: str = Field(..., examples=["sess-rtsp-9f3a"])
    client_ip: str = Field(..., examples=["10.50.0.55"])
    action: str = Field("PLAY", examples=["DESCRIBE", "PLAY"])


@app.post("/rtsp/session", tags=["rtsp"])
def rtsp_session(req: RtspSessionRequest) -> dict[str, Any]:
    """Open/continue an RTSP session against a video stream.

    T1557 — the first DESCRIBE for a stream establishes its owning session;
    any later PLAY/DESCRIBE against the same stream from a *different*
    session_id is a hijack (takeover of an in-progress relay).
    """
    current_owner = _RTSP_STREAM_OWNERS.get(req.stream_id)
    hijack_suspected = current_owner is not None and current_owner != req.session_id
    if current_owner is None:
        _RTSP_STREAM_OWNERS[req.stream_id] = req.session_id
    _emit({
        "EventType": "rtsp_hijack",
        "StreamId": req.stream_id,
        "SessionId": req.session_id,
        "ClientIp": req.client_ip,
        "HijackSuspected": hijack_suspected,
        "StatusCode": 200,
    })
    return {"stream_id": req.stream_id, "hijack_suspected": hijack_suspected}


# ---- S106: flocking 규칙 변조(자진신고 — 실 제어루프 없음) --------------------

class FlockingTamperRequest(BaseModel):
    fleet_id: str = Field(..., examples=["MUAV-FLT-1"])
    rule: str = Field(..., examples=["separation", "alignment", "cohesion"])
    value_before: float = 0.0
    value_after: float = 0.0
    changed_by: str = Field("", examples=["unknown"])


@app.post("/fleet/flocking-params", tags=["swarm"])
def flocking_tamper(req: FlockingTamperRequest) -> dict[str, Any]:
    """Declare a flocking-rule parameter change. T0836 — self-report: this repo has
    no real flocking controller, so this records the *claimed* tamper for downstream
    correlation against `UAVFleetState_CL` anomaly scores."""
    _emit({
        "EventType": "flocking_tamper",
        "FleetId": req.fleet_id,
        "Rule": req.rule,
        "ValueBefore": req.value_before,
        "ValueAfter": req.value_after,
        "ChangedBy": req.changed_by,
        "StatusCode": 200,
    })
    return {"fleet_id": req.fleet_id, "rule": req.rule, "logged": True}


# ---- S108: 메시 파티션(자진신고 — 실 메시망 없음) -----------------------------

class MeshLinkRequest(BaseModel):
    fleet_id: str = Field(..., examples=["MUAV-FLT-1"])
    link_a: str = Field(..., examples=["MUAV-001"])
    link_b: str = Field(..., examples=["MUAV-002"])
    status: str = Field("down", examples=["up", "down"])
    reason: str = Field("", examples=["ew_jam", "unknown"])


@app.post("/fleet/mesh-link", tags=["swarm"])
def mesh_link_status(req: MeshLinkRequest) -> dict[str, Any]:
    """Declare a mesh-link status change between two fleet members. T0814 — self-report:
    this repo has no real inter-vehicle mesh network, so this records the *claimed*
    partition for downstream correlation against `UAVFleetState_CL.ActiveUAVCount`."""
    _emit({
        "EventType": "mesh_link_status",
        "FleetId": req.fleet_id,
        "LinkA": req.link_a,
        "LinkB": req.link_b,
        "LinkStatus": req.status,
        "Reason": req.reason,
        "StatusCode": 200,
    })
    return {"fleet_id": req.fleet_id, "link_a": req.link_a, "link_b": req.link_b, "status": req.status}
