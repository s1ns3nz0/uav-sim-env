"""rc-link-stub — WiFi telemetry AP + RC control-link attack surface (S25~S31).

Neither this repo's MAVLink/LOS datalink nor the SATCOM link model the
short-range physical links a small recon UAV actually carries alongside
them: a WiFi AP for companion-computer/telemetry access, and a dedicated
2.4GHz RC control link for the safety pilot. Both are outside the UAV
Sentinel telemetry plane today — this stub gives them a detectable
signature the same way `web-stub`/`counter-uas` do for their surfaces.

Safety note — same convention as every other attack-surface stub in this
repo: each endpoint simulates the technique's detectable signature via an
explicit control call. No real 802.11 or RC-protocol traffic is sent.

Feeds one table: UAVRcLink_CL
  wifi_associate     — T0860(Wireless Compromise)/T1552(Unsecured/default creds)
  rc_bind            — T1555(Credentials from Password Stores — bind-code reuse)
  rc_override        — T0855(Unauthorized Command Message — RC channel override)
  protocol_negotiate — T1600(Weaken Encryption — protocol downgrade)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

# Fleet-wide known-good state — a real deployment would back these with a
# per-device provisioning registry (unique creds/bind codes per airframe).
KNOWN_BSSID: dict[str, str] = {"UAS-TELEM-AP": "AA:BB:CC:00:11:22"}
DEFAULT_CREDENTIALS: frozenset[str] = frozenset({"admin", "12345678", "uavsim123"})
KNOWN_BIND_CODES: dict[str, str] = {"MPD-001": "bind-7f3a9c", "MUAV-001": "bind-2e81b0"}
# Descending strength — anything weaker than what was requested is a downgrade.
PROTOCOL_STRENGTH: dict[str, int] = {
    "fhss-aes128": 3, "fhss-plain": 2, "fixed-freq-plain": 1,
}

app = FastAPI(
    title="rc-link-stub",
    version="0.1.0",
    description="WiFi telemetry AP + RC control-link attack-surface simulation (S25~S31).",
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


# ---- S25/S26/S28: WiFi 텔레메트리 AP 연결 (evil twin / 기본 자격증명) ----------

class WifiAssociateRequest(BaseModel):
    device_id: str = Field(..., examples=["companion-01"])
    ssid: str = Field(..., examples=["UAS-TELEM-AP"])
    bssid: str = Field(..., examples=["AA:BB:CC:00:11:22"])
    credential: str = Field(..., examples=["admin"])


@app.post("/wifi/associate", tags=["wifi"])
def wifi_associate(req: WifiAssociateRequest) -> dict[str, Any]:
    """Associate to the telemetry WiFi AP.

    S26(evil twin) — a known SSID advertised from an unknown BSSID.
    S28(기본 자격증명) — credential matches a well-known default rather than
    a per-device provisioned one.
    """
    known_bssid = KNOWN_BSSID.get(req.ssid)
    bssid_mismatch = known_bssid is not None and known_bssid != req.bssid
    default_credential_used = req.credential in DEFAULT_CREDENTIALS
    _emit({
        "EventType": "wifi_associate",
        "DeviceId": req.device_id,
        "Ssid": req.ssid,
        "BssidMismatch": bssid_mismatch,
        "DefaultCredentialUsed": default_credential_used,
        "StatusCode": 200,
    })
    return {"ssid": req.ssid, "associated": True, "bssid_mismatch": bssid_mismatch}


# ---- S27: WiFi 재밍은 counter-uas(rf_detection/jam_engagement)에서 이미 RF ---
# ---- 계층으로 커버 — 여기선 802.11 연결/자격증명 계층만 다룬다. -------------


# ---- S29: RC 바인딩 자격 탈취 -----------------------------------------------

class RcBindRequest(BaseModel):
    uav_id: str = Field(..., examples=["MPD-001"])
    receiver_id: str = Field(..., examples=["RX-9981"])
    bind_code: str = Field(..., examples=["bind-7f3a9c"])


@app.post("/rc/bind", tags=["rc"])
def rc_bind(req: RcBindRequest) -> dict[str, Any]:
    """Bind an RC receiver using a per-airframe bind code.

    T1555 — a bind code that matches a *different* UAV's provisioned code
    (reused/stolen from another airframe's password store) still succeeds
    here (no code is actually rejected, matching this repo's IDOR/webshell
    convention: detection via audit trail, not blocking) but is flagged.
    """
    expected = KNOWN_BIND_CODES.get(req.uav_id)
    bind_code_reused = expected is not None and expected != req.bind_code and req.bind_code in KNOWN_BIND_CODES.values()
    _emit({
        "EventType": "rc_bind",
        "DeviceId": req.receiver_id,
        "UavId": req.uav_id,
        "BindCodeReused": bind_code_reused,
        "StatusCode": 200,
    })
    return {"uav_id": req.uav_id, "receiver_id": req.receiver_id, "bind_code_reused": bind_code_reused}


# ---- S30: RC 채널 오버라이드(비인가 명령 주입) -------------------------------

class RcOverrideRequest(BaseModel):
    uav_id: str = Field(..., examples=["MPD-001"])
    channel: int = Field(..., ge=1, le=18, examples=[3])
    channel_value: int = Field(..., ge=0, le=2200, examples=[1900])
    authorized: bool = Field(False, description="true only if issued by the bound safety-pilot TX")


@app.post("/rc/override", tags=["rc"])
def rc_override(req: RcOverrideRequest) -> dict[str, Any]:
    """Inject an RC channel value directly (bypassing the bound TX).

    T0855(Unauthorized Command Message) — `authorized=false` is the attack
    case: a channel value arriving outside the bound transmitter's session.
    """
    _emit({
        "EventType": "rc_override",
        "UavId": req.uav_id,
        "Channel": req.channel,
        "ChannelValue": req.channel_value,
        "OverrideAuthorized": req.authorized,
        "StatusCode": 200,
    })
    return {"uav_id": req.uav_id, "channel": req.channel, "authorized": req.authorized}


# ---- S31: RC 프로토콜 다운그레이드 -------------------------------------------

class ProtocolNegotiateRequest(BaseModel):
    uav_id: str = Field(..., examples=["MPD-001"])
    protocol_requested: str = Field("fhss-aes128", examples=list(PROTOCOL_STRENGTH))
    protocol_negotiated: str = Field(..., examples=list(PROTOCOL_STRENGTH))


@app.post("/rc/protocol-negotiate", tags=["rc"])
def protocol_negotiate(req: ProtocolNegotiateRequest) -> dict[str, Any]:
    """Negotiate the RC link protocol/encryption level for a session.

    T1600(Weaken Encryption) — negotiated protocol weaker than requested
    (e.g. AES128-hopping downgraded to a fixed-frequency plaintext legacy
    mode) is the downgrade-attack signature.
    """
    req_strength = PROTOCOL_STRENGTH.get(req.protocol_requested, 0)
    neg_strength = PROTOCOL_STRENGTH.get(req.protocol_negotiated, 0)
    downgrade_detected = neg_strength < req_strength
    _emit({
        "EventType": "protocol_negotiate",
        "UavId": req.uav_id,
        "ProtocolRequested": req.protocol_requested,
        "ProtocolNegotiated": req.protocol_negotiated,
        "DowngradeDetected": downgrade_detected,
        "StatusCode": 200,
    })
    return {"uav_id": req.uav_id, "protocol": req.protocol_negotiated, "downgrade_detected": downgrade_detected}
