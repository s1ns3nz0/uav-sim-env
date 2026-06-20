"""mps-stub — Mission Planning System digital control plane.

Models the operator-side decision surface that precedes a UAV sortie:

* Plan creation (waypoints, payload assignment, ROE)
* Two-person approval workflow
* Release of an approved plan to the UAS for execution

Every endpoint emits a structured NDJSON record to LOG_FILE_PATH for ingest
into UAVMissionPlan_CL. This is the substrate for OSCAL evidence collection
("who approved what, when") and for insider-threat rules ("planner != approver
verified", "plan released without approval").
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(
    title="mps-stub",
    version="0.1.0",
    description="Mission Planning System digital control plane (OSCAL evidence + insider threat surface).",
)

_plans: dict[str, dict[str, Any]] = {}
_log_file_handle = None


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


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


class Waypoint(BaseModel):
    seq: int
    lat: float
    lon: float
    alt_m: float
    action: str = Field(default="navigate", examples=["navigate", "loiter", "roi", "land"])


class PlanCreateRequest(BaseModel):
    uav_id: str = Field(..., examples=["MPD-001"])
    planner: str = Field(..., examples=["lt.kim"])
    callsign: str = Field(..., examples=["FALCON-1"])
    waypoints: list[Waypoint]
    roe: str = Field(..., examples=["recon-only", "engage-confirmed-hostile"])
    payload_config: str = Field(default="EO_IR", examples=["EO_IR", "SAR", "STRIKE_870G"])


class ApprovalRequest(BaseModel):
    approver: str
    comment: str = ""


class ReleaseRequest(BaseModel):
    released_by: str


class PlanRecord(BaseModel):
    plan_id: str
    uav_id: str
    planner: str
    callsign: str
    waypoints: list[Waypoint]
    roe: str
    payload_config: str
    status: str
    approved_by: str | None = None
    released_by: str | None = None


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plans", response_model=PlanRecord, tags=["plans"])
def create_plan(req: PlanCreateRequest) -> PlanRecord:
    """Register a new mission plan in DRAFT status."""
    plan_id = secrets.token_urlsafe(12)
    record = {
        "plan_id": plan_id,
        "uav_id": req.uav_id,
        "planner": req.planner,
        "callsign": req.callsign,
        "waypoints": [wp.model_dump() for wp in req.waypoints],
        "roe": req.roe,
        "payload_config": req.payload_config,
        "status": "DRAFT",
        "approved_by": None,
        "released_by": None,
    }
    _plans[plan_id] = record
    _emit({
        "EventType": "plan_created",
        "PlanId": plan_id,
        "UAVId": req.uav_id,
        "Planner": req.planner,
        "Callsign": req.callsign,
        "WaypointCount": len(req.waypoints),
        "Roe": req.roe,
        "PayloadConfig": req.payload_config,
        "Status": "DRAFT",
        "StatusCode": 200,
    })
    return PlanRecord(**record)


@app.get("/plans/{plan_id}", response_model=PlanRecord, tags=["plans"])
def get_plan(plan_id: str) -> PlanRecord:
    record = _plans.get(plan_id)
    if record is None:
        raise HTTPException(404, f"Plan {plan_id} not found")
    return PlanRecord(**record)


@app.post("/plans/{plan_id}/approve", response_model=PlanRecord, tags=["approval"])
def approve_plan(plan_id: str, req: ApprovalRequest) -> PlanRecord:
    """Two-person rule: approver must differ from planner."""
    record = _plans.get(plan_id)
    if record is None:
        raise HTTPException(404, f"Plan {plan_id} not found")
    if record["status"] != "DRAFT":
        _emit({
            "EventType": "plan_approve_rejected",
            "PlanId": plan_id,
            "UAVId": record["uav_id"],
            "Approver": req.approver,
            "Planner": record["planner"],
            "Status": record["status"],
            "FailReason": "not_in_draft",
            "StatusCode": 409,
        })
        raise HTTPException(409, f"Plan {plan_id} is {record['status']}, cannot approve")
    if req.approver == record["planner"]:
        _emit({
            "EventType": "plan_approve_rejected",
            "PlanId": plan_id,
            "UAVId": record["uav_id"],
            "Approver": req.approver,
            "Planner": record["planner"],
            "Status": record["status"],
            "FailReason": "planner_equals_approver",
            "StatusCode": 403,
        })
        raise HTTPException(403, "Two-person rule violation: approver must differ from planner")

    record["status"] = "APPROVED"
    record["approved_by"] = req.approver
    _emit({
        "EventType": "plan_approved",
        "PlanId": plan_id,
        "UAVId": record["uav_id"],
        "Approver": req.approver,
        "Planner": record["planner"],
        "Status": "APPROVED",
        "Comment": req.comment,
        "StatusCode": 200,
    })
    return PlanRecord(**record)


@app.post("/plans/{plan_id}/release", response_model=PlanRecord, tags=["release"])
def release_plan(plan_id: str, req: ReleaseRequest) -> PlanRecord:
    """Release an approved plan to the UAS. Refused if not approved."""
    record = _plans.get(plan_id)
    if record is None:
        raise HTTPException(404, f"Plan {plan_id} not found")
    if record["status"] != "APPROVED":
        _emit({
            "EventType": "plan_release_rejected",
            "PlanId": plan_id,
            "UAVId": record["uav_id"],
            "ReleasedBy": req.released_by,
            "Status": record["status"],
            "FailReason": "not_approved",
            "StatusCode": 403,
        })
        raise HTTPException(403, f"Plan {plan_id} is {record['status']}, must be APPROVED before release")

    record["status"] = "RELEASED"
    record["released_by"] = req.released_by
    _emit({
        "EventType": "plan_released",
        "PlanId": plan_id,
        "UAVId": record["uav_id"],
        "ReleasedBy": req.released_by,
        "Approver": record["approved_by"],
        "Planner": record["planner"],
        "Status": "RELEASED",
        "StatusCode": 200,
    })
    return PlanRecord(**record)
