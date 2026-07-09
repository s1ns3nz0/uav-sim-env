"""c4i-stub — ATCIS / MIMS digital control plane (operational picture).

Mirrors the slice of the Korean Army C4I systems that touches UAV operations:

* ATCIS operation orders (mission objective, ROE, target priority, area of
  operations).
* MIMS target intelligence updates (new target, confidence change, removal).
* Friendly unit position updates (so the UAV stays out of fratricide zones).
* Current operational picture snapshot.

Every endpoint emits NDJSON to LOG_FILE_PATH. Feeds UAVC4I_CL so the SOC and
LangGraph agents can correlate UAV behaviour with the operational tempo:
"Operation X received -> waypoint Y deviated", "friendly position published ->
UAV ROI lingered inside fratricide buffer" etc.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(
    title="c4i-stub",
    version="0.1.0",
    description="ATCIS / MIMS modelled control plane for UAV operations.",
)

_orders: dict[str, dict[str, Any]] = {}
_targets: dict[str, dict[str, Any]] = {}
_friendly_positions: list[dict[str, Any]] = []
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


class OperationOrder(BaseModel):
    order_id: str | None = None
    callsign: str = Field(..., examples=["FALCON-1"])
    operation_name: str = Field(..., examples=["WHITE_TIGER"])
    objective: str = Field(..., examples=["recon-north-bridge"])
    roe: str = Field(..., examples=["recon-only", "engage-confirmed-hostile"])
    area_lat: float
    area_lon: float
    area_radius_m: float
    target_priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    issued_by: str = Field(..., examples=["maj.cho"])


class TargetIntel(BaseModel):
    target_id: str | None = None
    lat: float
    lon: float
    classification: Literal["UNKNOWN", "FRIENDLY", "NEUTRAL", "HOSTILE", "SUSPECT"]
    confidence_pct: int = Field(ge=0, le=100)
    source: str = Field(..., examples=["sigint", "humint", "uav-eoir"])
    reported_by: str


class FriendlyPosition(BaseModel):
    unit_callsign: str = Field(..., examples=["RAVEN-3"])
    lat: float
    lon: float
    alt_m: float
    timestamp: str | None = None


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/atcis/orders", tags=["atcis"])
def post_order(order: OperationOrder) -> dict[str, Any]:
    """Issue a new operation order from ATCIS. Idempotent if order_id provided."""
    order_id = order.order_id or secrets.token_urlsafe(8)
    payload = order.model_dump()
    payload["order_id"] = order_id
    _orders[order_id] = payload
    _emit({
        "EventType": "atcis_order_issued",
        "OrderId": order_id,
        "Callsign": order.callsign,
        "OperationName": order.operation_name,
        "Objective": order.objective,
        "Roe": order.roe,
        "AreaLat": order.area_lat,
        "AreaLon": order.area_lon,
        "AreaRadiusM": order.area_radius_m,
        "TargetPriority": order.target_priority,
        "IssuedBy": order.issued_by,
        "StatusCode": 200,
    })
    return payload


@app.post("/mims/targets", tags=["mims"])
def post_target(target: TargetIntel) -> dict[str, Any]:
    """Push or update a target intel record from MIMS."""
    target_id = target.target_id or secrets.token_urlsafe(8)
    payload = target.model_dump()
    payload["target_id"] = target_id
    _targets[target_id] = payload
    _emit({
        "EventType": "mims_target_update",
        "TargetId": target_id,
        "Lat": target.lat,
        "Lon": target.lon,
        "Classification": target.classification,
        "ConfidencePct": target.confidence_pct,
        "Source": target.source,
        "ReportedBy": target.reported_by,
        "StatusCode": 200,
    })
    return payload


@app.post("/atcis/friendly-positions", tags=["atcis"])
def post_friendly(pos: FriendlyPosition) -> dict[str, Any]:
    """Append a friendly unit position. Used to validate fratricide buffers."""
    record = pos.model_dump()
    record["timestamp"] = record.get("timestamp") or _now_iso()
    _friendly_positions.append(record)
    _emit({
        "EventType": "atcis_friendly_position",
        "UnitCallsign": pos.unit_callsign,
        "Lat": pos.lat,
        "Lon": pos.lon,
        "AltM": pos.alt_m,
        "StatusCode": 200,
    })
    return record


@app.get("/current-operation", tags=["meta"])
def current_operation(request: Request) -> dict[str, Any]:
    """Full operational-picture snapshot (orders, targets, friendly positions).

    T1567(Exfiltration Over Web Service) — this is exactly the "legitimate
    channel" the matrix flags: a read-only endpoint that returns the whole
    operational picture in one response. Every other endpoint here logs on
    write; this one previously logged nothing on read, so a large recon
    pull looked identical to normal polling. Now audited by response size.
    """
    payload = {
        "orders_active": len(_orders),
        "targets_known": len(_targets),
        "friendly_positions_history": len(_friendly_positions),
        "latest_order": next(reversed(_orders.values()), None) if _orders else None,
    }
    body_bytes = len(json.dumps(payload, default=str).encode("utf-8"))
    _emit({
        "EventType": "current_operation_read",
        "ClientIp": request.client.host if request.client else "",
        "ResponseBytes": body_bytes,
        "StatusCode": 200,
    })
    return payload
