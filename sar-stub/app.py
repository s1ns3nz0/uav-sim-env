"""sar-stub — SAR (Synthetic Aperture Radar) payload digital surface.

Models the KUS-FS (MUAV, UAS Group 4) SAR/EO-IR collection plane. Each capture
request records SAR frame metadata (target coords, sensor mode, resolution,
frame size) as NDJSON to LOG_FILE_PATH. Feeds UAVSarPayload_CL so the SOC can
detect:

* 표적 조작 / 비정상 수집 — capture coords outside the tasked area of operations
* 영상 유출 정황 — abnormal frame-size spikes (SizeBytes)
* GMTI 오남용 — moving-target mode used where not authorised

Unlike telemetry-tap (which parses MAVLink), this stub is the payload's own
application surface, mirroring the other FastAPI stubs (c4i/mps/weapon/...).
"""
from __future__ import annotations

import json
import os
import random
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(
    title="sar-stub",
    version="0.1.0",
    description="SAR payload modelled surface for KUS-FS (MUAV) ISR collection.",
)

_frames: dict[str, dict[str, Any]] = {}
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


# Rough frame-size model (bytes) per sensor mode. Real SAR frame size depends on
# swath/resolution/bit-depth; here we approximate so size-spike detection rules
# have a baseline to deviate from.
_MODE_BASE_BYTES: dict[str, int] = {
    "spot": 2_400_000,    # high-res small scene
    "strip": 9_000_000,   # wide swath
    "gmti": 350_000,      # moving-target dots, light
}


class CaptureRequest(BaseModel):
    uav_id: str = Field(..., examples=["MUAV-001"])
    target_lat: float
    target_lon: float
    sensor_mode: Literal["spot", "strip", "gmti"] = "spot"
    resolution: str = Field("0.3m", examples=["0.3m", "1m", "3m"])
    size_bytes: int | None = Field(None, description="Override; else modelled from mode.")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sar/capture", tags=["sar"])
def capture(req: CaptureRequest) -> dict[str, Any]:
    """Record a SAR frame capture and emit its metadata to UAVSarPayload_CL."""
    frame_id = "F-" + secrets.token_hex(3).upper()
    base = _MODE_BASE_BYTES.get(req.sensor_mode, 2_000_000)
    size = req.size_bytes if req.size_bytes is not None else int(base * random.uniform(0.8, 1.3))
    record = {
        "frame_id": frame_id,
        "uav_id": req.uav_id,
        "target_lat": req.target_lat,
        "target_lon": req.target_lon,
        "sensor_mode": req.sensor_mode,
        "resolution": req.resolution,
        "size_bytes": size,
    }
    _frames[frame_id] = record
    _emit({
        "EventType": "sar_frame_captured",
        "UAVId": req.uav_id,
        "FrameId": frame_id,
        "TargetLat": req.target_lat,
        "TargetLon": req.target_lon,
        "Resolution": req.resolution,
        "SensorMode": req.sensor_mode,
        "SizeBytes": size,
        "StatusCode": 200,
    })
    return record


@app.get("/sar/frames/{frame_id}", tags=["sar"])
def get_frame(frame_id: str) -> dict[str, Any]:
    frame = _frames.get(frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="frame not found")
    return frame


@app.get("/sar/frames", tags=["sar"])
def list_frames() -> dict[str, Any]:
    return {"count": len(_frames), "frames": list(_frames.values())[-20:]}
