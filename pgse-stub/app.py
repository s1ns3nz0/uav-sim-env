"""pgse-stub — Payload & Ground Support Equipment digital control plane.

Real PGSE (per FMI 3-04.155) is a hardware system: launch catapult, recovery
nets, ground maintenance equipment. This stub models the *digital* subset that
red-team / SOC scenarios will exercise:

* Firmware hash registry (approved images per UAV)
* Pre-flight integrity check (image hash + SBOM allowlist)
* Launch authorization tokens (require recent successful pre-flight)

S4 (firmware / supply-chain tampering) hooks exposed here. A real deployment
would back the registry with cosign signatures and a CycloneDX SBOM verifier;
this stub keeps the same request/response shape so the SOC analytic rule
(uav_fw_signature_mismatch.yml) can be authored against it unchanged.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APPROVED_DB: Path = Path(os.environ.get("APPROVED_DB", "/data/approved_firmware.json"))
TOKEN_TTL_SEC: int = int(os.environ.get("TOKEN_TTL_SEC", "300"))
FORBIDDEN_SBOM_PREFIXES: tuple[str, ...] = ("unsigned/", "untrusted/")
LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(
    title="pgse-stub",
    version="0.1.0",
    description="Payload & Ground Support Equipment digital control plane (S4 attack surface).",
)

_launch_tokens: dict[str, dict[str, Any]] = {}
_last_preflight: dict[str, dict[str, Any]] = {}
_log_file_handle = None


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _emit_event(event: dict[str, Any]) -> None:
    """Append one NDJSON decision record to the audit sink (Sentinel ingest)."""
    if _log_file_handle is None:
        return
    enriched = {"TimeGenerated": _now_iso(), **event}
    _log_file_handle.write(json.dumps(enriched, separators=(",", ":"), default=str) + "\n")
    _log_file_handle.flush()


@app.on_event("startup")
def _open_log_sink() -> None:
    global _log_file_handle
    if not LOG_FILE_PATH:
        return
    os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
    _log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")


def _load_approved() -> dict[str, str]:
    """Return mapping of uav_id -> approved firmware hash. Empty if DB missing."""
    if not APPROVED_DB.exists():
        return {}
    try:
        return json.loads(APPROVED_DB.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Approved firmware DB malformed: {exc}") from exc


class PreflightRequest(BaseModel):
    """Payload submitted by an operator before authorising a launch."""

    uav_id: str = Field(..., examples=["MPD-001"])
    image_hash: str = Field(..., examples=["sha256:0000...0001"])
    sbom_components: list[str] = Field(default_factory=list)
    operator: str = Field(..., examples=["sgt.kim"])
    serial: str = Field(..., examples=["MPD-AC-0001"])


class PreflightResult(BaseModel):
    uav_id: str
    checked_at: str
    image_hash_match: bool
    expected_hash: str
    submitted_hash: str
    sbom_forbidden_components: list[str]
    passed: bool


class LaunchAuthorizeRequest(BaseModel):
    uav_id: str
    operator: str


class LaunchToken(BaseModel):
    token: str
    uav_id: str
    operator: str
    issued_at: str
    expires_at: float


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/armory/firmware/{uav_id}", tags=["armory"])
def get_approved_firmware(uav_id: str) -> dict[str, str]:
    """Return the currently-approved firmware hash for the given UAV.

    Raises:
        HTTPException 404: if the UAV has no registered approved image.
    """
    approved = _load_approved()
    expected = approved.get(uav_id)
    _emit_event({
        "EventType": "firmware_query",
        "UAVId": uav_id,
        "Found": expected is not None,
        "ImageHashExpected": expected or "",
        "StatusCode": 200 if expected else 404,
    })
    if expected is None:
        raise HTTPException(404, f"No approved firmware registered for {uav_id}")
    return {"uav_id": uav_id, "expected_hash": expected}


@app.post("/preflight/check", response_model=PreflightResult, tags=["preflight"])
def preflight_check(req: PreflightRequest) -> PreflightResult:
    """Verify a UAV's firmware hash and SBOM against the approved registry.

    A failing result is **recorded** but not raised so the SOC pipeline can
    observe the discrepancy via telemetry.
    """
    approved = _load_approved()
    expected = approved.get(req.uav_id)
    if expected is None:
        raise HTTPException(404, f"Unknown UAV {req.uav_id}")

    image_match = expected == req.image_hash
    forbidden = [
        component for component in req.sbom_components
        if any(component.startswith(prefix) for prefix in FORBIDDEN_SBOM_PREFIXES)
    ]

    result = PreflightResult(
        uav_id=req.uav_id,
        checked_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        image_hash_match=image_match,
        expected_hash=expected,
        submitted_hash=req.image_hash,
        sbom_forbidden_components=forbidden,
        passed=image_match and not forbidden,
    )
    _last_preflight[req.uav_id] = result.model_dump()
    _emit_event({
        "EventType": "preflight_check",
        "UAVId": req.uav_id,
        "Operator": req.operator,
        "Serial": req.serial,
        "ImageHashSubmitted": req.image_hash,
        "ImageHashExpected": expected,
        "HashMatch": image_match,
        "SbomForbidden": ",".join(forbidden),
        "SbomForbiddenCount": len(forbidden),
        "Passed": result.passed,
        "StatusCode": 200,
    })
    return result


@app.post("/launch/authorize", response_model=LaunchToken, tags=["launch"])
def launch_authorize(req: LaunchAuthorizeRequest) -> LaunchToken:
    """Issue a short-lived launch token if the latest preflight passed."""
    last = _last_preflight.get(req.uav_id)
    if last is None:
        _emit_event({
            "EventType": "launch_authorize",
            "UAVId": req.uav_id,
            "Operator": req.operator,
            "Passed": False,
            "FailReason": "no_preflight_on_record",
            "StatusCode": 409,
        })
        raise HTTPException(409, f"No preflight on record for {req.uav_id}")
    if not last["passed"]:
        _emit_event({
            "EventType": "launch_authorize",
            "UAVId": req.uav_id,
            "Operator": req.operator,
            "Passed": False,
            "FailReason": "preflight_failed",
            "StatusCode": 403,
        })
        raise HTTPException(403, f"Preflight failed for {req.uav_id} — cannot authorise launch")

    token = secrets.token_urlsafe(24)
    issued_at = time.time()
    expires_at = issued_at + TOKEN_TTL_SEC
    _launch_tokens[token] = {
        "uav_id": req.uav_id,
        "operator": req.operator,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    _emit_event({
        "EventType": "launch_authorize",
        "UAVId": req.uav_id,
        "Operator": req.operator,
        "Passed": True,
        "TokenExpiresAt": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(timespec="milliseconds"),
        "StatusCode": 200,
    })
    return LaunchToken(
        token=token,
        uav_id=req.uav_id,
        operator=req.operator,
        issued_at=datetime.fromtimestamp(issued_at, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        ),
        expires_at=expires_at,
    )


@app.get("/launch/token/{token}", tags=["launch"])
def launch_token_status(token: str) -> dict[str, Any]:
    """Validate a launch token. Used by downstream actuator services."""
    info = _launch_tokens.get(token)
    if info is None:
        raise HTTPException(404, "Token not found")
    if time.time() > info["expires_at"]:
        raise HTTPException(410, "Token expired")
    return info
