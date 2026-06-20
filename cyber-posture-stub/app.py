"""cyber-posture-stub — cyber threat posture control plane.

Models the Korean public-sector "사이버위협태세" levels (CT-3 / CT-2 / CT-1)
that gate the strictness of SOC detection rules and the sensitivity of UAV
mission constraints. A posture change is the kind of low-volume but
high-importance event that OSCAL control evidence is built around: "control
strength elevated at 09:12 by capt.park because of CT-2 declaration".

Endpoints:
* GET  /posture                   current level
* POST /posture                   transition to new level (audited)
* GET  /history                   recent transitions

Each state change emits NDJSON to LOG_FILE_PATH for UAVCyberPosture_CL.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(
    title="cyber-posture-stub",
    version="0.1.0",
    description="Cyber threat posture (CT-3/CT-2/CT-1) control plane.",
)

POSTURE_LEVELS = ("CT-3", "CT-2", "CT-1")

_state: dict[str, Any] = {"level": "CT-3", "since": None, "changed_by": "system"}
_history: list[dict[str, Any]] = []
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
    _state["since"] = _now_iso()
    _emit({
        "EventType": "posture_baseline",
        "PreviousLevel": "",
        "Level": _state["level"],
        "ChangedBy": _state["changed_by"],
        "Reason": "initial-boot",
        "StatusCode": 200,
    })


class PostureChange(BaseModel):
    level: Literal["CT-3", "CT-2", "CT-1"]
    changed_by: str = Field(..., examples=["capt.park"])
    reason: str = Field(..., examples=["intel-warning-2026-06-21"])
    source: str = Field(default="국정원", examples=["국정원", "사이버사", "internal"])


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/posture", tags=["posture"])
def get_posture() -> dict[str, Any]:
    return dict(_state)


@app.post("/posture", tags=["posture"])
def set_posture(change: PostureChange) -> dict[str, Any]:
    previous = _state["level"]
    _state["level"] = change.level
    _state["since"] = _now_iso()
    _state["changed_by"] = change.changed_by

    transition = {
        "TimeGenerated": _state["since"],
        "EventType": "posture_changed",
        "PreviousLevel": previous,
        "Level": change.level,
        "ChangedBy": change.changed_by,
        "Reason": change.reason,
        "Source": change.source,
        "StatusCode": 200,
    }
    _history.append(transition)
    _emit(transition)
    return dict(_state)


@app.get("/history", tags=["posture"])
def get_history(limit: int = 50) -> list[dict[str, Any]]:
    return _history[-limit:]
