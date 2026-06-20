"""auth-stub — operator authentication audit stub.

Models the operator login surface for the GCS / MPS / weapon panels. Every
login attempt, success, logout and token validation generates a UAVOpAudit_CL
row. SOC rules can detect "brute force on operator X", "session reuse from
two IPs" or "weapon arm by operator whose token expired".
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")
SESSION_TTL_SEC: int = int(os.environ.get("SESSION_TTL_SEC", "3600"))

# Mock credential store — operator -> password. Production: never store
# plaintext, replace with hash + IdP delegation.
USERS: dict[str, str] = {
    "sgt.yang": "uav-pw-1",
    "lt.kim": "uav-pw-2",
    "capt.park": "uav-pw-3",
    "maj.cho": "uav-pw-4",
    "col.lee": "uav-pw-5",
}

app = FastAPI(title="auth-stub", version="0.1.0",
              description="Operator authentication audit stub.")

_sessions: dict[str, dict[str, Any]] = {}
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


class LoginRequest(BaseModel):
    username: str
    password: str
    client_ip: str = Field(default="0.0.0.0", examples=["192.168.10.42"])
    user_agent: str = Field(default="qgc-desktop")


class TokenRequest(BaseModel):
    session_id: str


class LogoutRequest(BaseModel):
    session_id: str
    operator: str = ""


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login", tags=["auth"])
def login(req: LoginRequest) -> dict[str, Any]:
    expected = USERS.get(req.username)
    if expected is None or expected != req.password:
        _emit({
            "EventType": "login_failure",
            "Operator": req.username,
            "ClientIp": req.client_ip,
            "UserAgent": req.user_agent,
            "FailReason": "invalid_credentials" if expected is None else "wrong_password",
            "StatusCode": 401,
        })
        raise HTTPException(401, "Invalid credentials")

    session_id = secrets.token_urlsafe(24)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=SESSION_TTL_SEC)
    _sessions[session_id] = {
        "operator": req.username,
        "client_ip": req.client_ip,
        "user_agent": req.user_agent,
        "issued_at": issued_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    _emit({
        "EventType": "login_success",
        "Operator": req.username,
        "ClientIp": req.client_ip,
        "UserAgent": req.user_agent,
        "SessionId": session_id,
        "StatusCode": 200,
    })
    return {"session_id": session_id, "expires_at": _sessions[session_id]["expires_at"]}


@app.post("/auth/validate", tags=["auth"])
def validate(req: TokenRequest) -> dict[str, Any]:
    session = _sessions.get(req.session_id)
    if session is None:
        _emit({
            "EventType": "token_validation_failed",
            "SessionId": req.session_id,
            "FailReason": "unknown_session",
            "StatusCode": 404,
        })
        raise HTTPException(404, "Unknown session")
    _emit({
        "EventType": "token_validated",
        "Operator": session["operator"],
        "ClientIp": session["client_ip"],
        "SessionId": req.session_id,
        "StatusCode": 200,
    })
    return session


@app.post("/auth/logout", tags=["auth"])
def logout(req: LogoutRequest) -> dict[str, Any]:
    session = _sessions.pop(req.session_id, None)
    if session is None:
        _emit({
            "EventType": "logout_unknown",
            "SessionId": req.session_id,
            "Operator": req.operator,
            "FailReason": "unknown_session",
            "StatusCode": 404,
        })
        raise HTTPException(404, "Unknown session")
    _emit({
        "EventType": "logout",
        "Operator": session["operator"],
        "ClientIp": session["client_ip"],
        "SessionId": req.session_id,
        "StatusCode": 200,
    })
    return {"ok": True, "operator": session["operator"]}


@app.get("/auth/sessions", tags=["auth"])
def list_sessions() -> list[dict[str, Any]]:
    return [{"session_id": sid, **info} for sid, info in _sessions.items()]
