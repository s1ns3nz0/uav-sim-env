"""weapon-stub — onboard weapon control plane stub.

Models the digital decision surface around the 870g self-destruct payload that
the MPD persona carries. Three states tracked: SAFETY (ARMED|SAFE), LOCK
(target_id or None), and AUTHORIZED (boolean, set by /fire after authority
check). Two-person rule applied: operator requesting fire must differ from
operator that issued the latest weapon ARM.

Endpoints emit NDJSON to LOG_FILE_PATH so the SOC can detect "fire request
without lock", "lock-to-fire under 2 seconds", "ROE engage-confirmed-hostile
absent" and other rules.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(title="weapon-stub", version="0.1.0",
              description="Onboard weapon safety/lock/fire control plane.")

_state: dict[str, Any] = {
    "safety": "SAFE",
    "armed_by": None,
    "armed_at": None,
    "lock_target_id": None,
    "locked_by": None,
    "locked_at": None,
}
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


class SafetySet(BaseModel):
    state: Literal["ARMED", "SAFE"]
    operator: str


class Lock(BaseModel):
    target_id: str
    operator: str


class Unlock(BaseModel):
    operator: str
    reason: str = ""


class FireRequest(BaseModel):
    operator: str
    target_id: str


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/weapon/state", tags=["meta"])
def get_state() -> dict[str, Any]:
    return dict(_state)


@app.post("/weapon/safety", tags=["safety"])
def safety_set(req: SafetySet) -> dict[str, Any]:
    previous = _state["safety"]
    _state["safety"] = req.state
    if req.state == "ARMED":
        _state["armed_by"] = req.operator
        _state["armed_at"] = _now_iso()
    _emit({
        "EventType": "safety_set",
        "WeaponId": "MPD-001-PAYLOAD",
        "Operator": req.operator,
        "SafetyStateBefore": previous,
        "SafetyState": req.state,
        "Status": "OK",
        "StatusCode": 200,
    })
    return dict(_state)


@app.post("/weapon/lock", tags=["lock"])
def weapon_lock(req: Lock) -> dict[str, Any]:
    if _state["safety"] != "ARMED":
        _emit({
            "EventType": "lock_rejected",
            "WeaponId": "MPD-001-PAYLOAD",
            "Operator": req.operator,
            "TargetId": req.target_id,
            "FailReason": "safety_not_armed",
            "Status": "REJECTED",
            "StatusCode": 409,
        })
        raise HTTPException(409, "Cannot lock — safety is SAFE")
    _state["lock_target_id"] = req.target_id
    _state["locked_by"] = req.operator
    _state["locked_at"] = _now_iso()
    _emit({
        "EventType": "lock",
        "WeaponId": "MPD-001-PAYLOAD",
        "Operator": req.operator,
        "TargetId": req.target_id,
        "Status": "LOCKED",
        "StatusCode": 200,
    })
    return dict(_state)


@app.post("/weapon/unlock", tags=["lock"])
def weapon_unlock(req: Unlock) -> dict[str, Any]:
    previous = _state["lock_target_id"]
    _state["lock_target_id"] = None
    _state["locked_by"] = None
    _state["locked_at"] = None
    _emit({
        "EventType": "unlock",
        "WeaponId": "MPD-001-PAYLOAD",
        "Operator": req.operator,
        "TargetId": previous or "",
        "Status": "UNLOCKED",
        "StatusCode": 200,
    })
    return dict(_state)


@app.post("/weapon/fire", tags=["fire"])
def weapon_fire(req: FireRequest) -> dict[str, Any]:
    """Two-person rule: requester must differ from arming operator."""
    if _state["safety"] != "ARMED":
        _emit({"EventType": "fire_rejected", "WeaponId": "MPD-001-PAYLOAD",
               "Operator": req.operator, "TargetId": req.target_id,
               "FailReason": "safety_not_armed", "Status": "REJECTED", "StatusCode": 403})
        raise HTTPException(403, "Cannot fire — safety is SAFE")
    if _state["lock_target_id"] != req.target_id:
        _emit({"EventType": "fire_rejected", "WeaponId": "MPD-001-PAYLOAD",
               "Operator": req.operator, "TargetId": req.target_id,
               "FailReason": "target_mismatch_or_unlocked", "Status": "REJECTED", "StatusCode": 403})
        raise HTTPException(403, "Cannot fire — target not locked")
    if req.operator == _state["armed_by"]:
        _emit({"EventType": "fire_rejected", "WeaponId": "MPD-001-PAYLOAD",
               "Operator": req.operator, "TargetId": req.target_id,
               "FailReason": "two_person_rule_violation", "Status": "REJECTED", "StatusCode": 403})
        raise HTTPException(403, "Two-person rule: requester must differ from arming operator")
    _emit({
        "EventType": "fire_authorized",
        "WeaponId": "MPD-001-PAYLOAD",
        "Operator": req.operator,
        "TargetId": req.target_id,
        "ArmedBy": _state["armed_by"],
        "Status": "AUTHORIZED",
        "StatusCode": 200,
    })
    return {"authorized": True, "target_id": req.target_id, "operator": req.operator}
