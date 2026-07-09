"""datalink-satcom — BLOS (SATCOM) link emulation + integrity tagging layer.

KUS-FS (MUAV, UAS Group 4) gains a second data link: Ku/Ka SATCOM via ANASIS-II
(GEO, ~600ms RTT). This service models that BLOS link's *link-layer signal* and
the security metadata the SOC needs for S3 detection, emitting it as NDJSON to
LOG_FILE_PATH -> UAVSatcomLink_CL.

Scope (Phase B / tagging-first): this is the integrity/session/seq/RTT/jam
tagging layer described in docs/uas-detail-6-satcom.md §2.3. The OpenSAND
DVB-S2/RCS2 physical-layer emulation (ST/SAT/GW) is layered in afterwards; here
we model the link characteristics and expose a control surface to drive the S3
(SATCOM MITM) scenario:

    integrity -> IntegrityStatus = signature_mismatch    (S3-satcom-integrity-fail)
    replay    -> IntegrityStatus = replay + Seq regress   (replay / MITM)
    hijack    -> SessionId changes mid-stream on same LinkId (S3-satcom-session-hijack)
    jam       -> JamIndicator high + RttMs anomaly        (jamming)
    covert    -> Encoding=tunnel/obfuscated, PayloadEntropy 급등, 규칙적 BeaconIntervalSec
                 (S65 C2 은닉 — 터널링/암호화/난독화/인코딩. UAVOperator_CL의 평문 명령
                 트래픽과 달리, 은닉 C2는 링크 계층 자체의 엔트로피·비콘 규칙성으로만 드러남)
    exfil     -> PayloadBytes 급증(T1011 — SATCOM 별도 매체로 정찰영상/SAR 대량 유출)

A background thread emits one link-status record every EMIT_INTERVAL_SEC.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field


UAV_ID = os.environ.get("UAV_ID", "MUAV-001")
LINK_ID = os.environ.get("LINK_ID", "KU-LINK-1")
LOG_FILE_PATH = os.environ.get("LOG_FILE_PATH", "")
GEO_RTT_MS = float(os.environ.get("GEO_RTT_MS", "600"))
EMIT_INTERVAL_SEC = float(os.environ.get("EMIT_INTERVAL_SEC", "5"))
SRC_ADDR = os.environ.get("SRC_ADDR", "10.60.0.10")   # AV-side satellite terminal (ST)
DST_ADDR = os.environ.get("DST_ADDR", "10.60.0.20")   # teleport gateway (GW)

app = FastAPI(
    title="datalink-satcom",
    version="0.1.0",
    description="BLOS SATCOM link emulation + integrity tagging (UAVSatcomLink_CL).",
)

_log_file_handle = None
_lock = threading.Lock()

# Mutable link state shared between the emitter thread and the control API.
_state: dict[str, Any] = {
    "session_id": "S-1001",
    "seq": 0,
    "mode": "normal",     # normal | integrity | replay | jam | covert
    "mode_until": 0.0,    # epoch seconds; 0 = persistent (normal)
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(event: dict[str, Any]) -> None:
    if _log_file_handle is None:
        return
    enriched = {"TimeGenerated": _now_iso(), **event}
    _log_file_handle.write(json.dumps(enriched, separators=(",", ":"), default=str) + "\n")
    _log_file_handle.flush()


def _build_record() -> dict[str, Any]:
    """Compute one link-status record from current state, applying any attack mode."""
    with _lock:
        # Expire a timed attack mode.
        if _state["mode"] != "normal" and _state["mode_until"] and time.time() > _state["mode_until"]:
            _state["mode"] = "normal"
            _state["mode_until"] = 0.0

        mode = _state["mode"]
        _state["seq"] += 1
        seq = _state["seq"]
        session_id = _state["session_id"]

        integrity = "ok"
        jam = round(random.uniform(0.0, 0.05), 3)
        rtt = round(GEO_RTT_MS + random.uniform(-8, 8), 1)
        # 은닉 C2(S65) 지표 — 평문 MAVLink 근사 기본값(낮은 엔트로피, 불규칙 비콘).
        encoding = "none"
        payload_entropy = round(random.uniform(3.5, 5.0), 2)
        beacon_jitter_sec = round(random.uniform(0.5, 4.0), 2)
        # T1011(Exfiltration Over Other Network Medium) — 링크 상태 틱당 페이로드
        # 바이트량. 종전엔 SATCOM 링크에 용량 컬럼이 아예 없어 이 기법이 미포착이었음.
        payload_bytes = random.randint(2_000, 8_000)

        if mode == "integrity":
            integrity = "signature_mismatch"
        elif mode == "replay":
            integrity = "replay"
            seq = max(1, seq - random.randint(3, 8))   # reported sequence regresses
        elif mode == "jam":
            jam = round(random.uniform(0.6, 0.95), 3)
            rtt = round(GEO_RTT_MS + random.uniform(200, 1200), 1)
        elif mode == "covert":
            # S65 C2 은닉(터널링/암호화/난독화/인코딩): 페이로드 엔트로피 급등 +
            # 규칙적(저지터) 비콘 — 링크 자체는 정상(재밍·무결성 이상 없음)이라
            # UAVOperator_CL 명령 감사로는 안 잡히고 이 링크계층 지표로만 드러난다.
            encoding = random.choice(["base64_tunnel", "xor_obfuscated", "dns_like_encode"])
            payload_entropy = round(random.uniform(7.5, 7.99), 2)
            beacon_jitter_sec = round(random.uniform(0.0, 0.15), 2)
        elif mode == "exfil":
            # T1011 — 정찰영상/SAR 표적을 SATCOM 별도 매체로 대량 유출. 정상 하트비트
            # (2~8KB) 대비 페이로드가 두 자릿수 배 급증하는 것으로 모사.
            payload_bytes = random.randint(200_000, 2_000_000)

        return {
            "UAVId": UAV_ID,
            "LinkId": LINK_ID,
            "SessionId": session_id,
            "Seq": seq,
            "IntegrityStatus": integrity,
            "RttMs": rtt,
            "JamIndicator": jam,
            "SrcAddr": SRC_ADDR,
            "DstAddr": DST_ADDR,
            "Mode": mode,
            "Encoding": encoding,
            "PayloadEntropy": payload_entropy,
            "BeaconJitterSec": beacon_jitter_sec,
            "PayloadBytes": payload_bytes,
        }


def _emitter_loop() -> None:
    while True:
        _emit(_build_record())
        time.sleep(EMIT_INTERVAL_SEC)


@app.on_event("startup")
def _startup() -> None:
    global _log_file_handle
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        _log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
    threading.Thread(target=_emitter_loop, daemon=True).start()


class InjectRequest(BaseModel):
    type: Literal["integrity", "replay", "hijack", "jam", "covert", "exfil"]
    duration_sec: int = Field(30, ge=1, le=3600)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/satcom/state", tags=["satcom"])
def state() -> dict[str, Any]:
    with _lock:
        return dict(_state)


@app.post("/satcom/inject", tags=["satcom"])
def inject(req: InjectRequest) -> dict[str, Any]:
    """Drive an S3 (SATCOM MITM) or S65 (C2 concealment) condition.

    hijack is a one-shot session change; the others (including covert) are
    timed link modes.
    """
    with _lock:
        if req.type == "hijack":
            old = _state["session_id"]
            _state["session_id"] = "S-" + str(random.randint(9000, 9999))
            return {"injected": "hijack", "old_session": old, "new_session": _state["session_id"]}
        _state["mode"] = req.type
        _state["mode_until"] = time.time() + req.duration_sec
        return {"injected": req.type, "duration_sec": req.duration_sec}


@app.post("/satcom/reset", tags=["satcom"])
def reset() -> dict[str, Any]:
    with _lock:
        _state["mode"] = "normal"
        _state["mode_until"] = 0.0
    return {"mode": "normal"}
