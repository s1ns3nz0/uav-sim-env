"""counter-uas — 카운터 드론(RF 탐지 → 근접 → 자동 재밍) 시뮬 서비스.

방어 자산 1기에 배치된 수동 RF 탐지기 + 근접 트리거 재밍기를 모델링한다. 백그라운드
루프가 매 TICK_SEC 마다 공역을 전진시켜 탐지/교전 NDJSON 을 LOG_FILE_PATH 로
방출하고(→ UAVCounterUas_CL), FastAPI 제어면으로 침입자 주입·재밍 정책을 조정한다.

법적 고지: 실제 RF 송신은 하지 않는다. 재밍은 J/S 효과로 시뮬레이션만 하며 어떤
주파수도 방사하지 않는다. 실송신은 허가·차폐환경에서만 별도로 다룰 사안이다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from counter_uas.detector import RfDetector
from counter_uas.engagement import JamMode, Jammer, Roe
from counter_uas.engine import SimEngine

# ---- 환경 설정 (하드코딩 금지 — 전부 env) ----------------------------------

ASSET_ID = os.environ.get("ASSET_ID", "CUAS-SITE-1")
LOG_FILE_PATH = os.environ.get("LOG_FILE_PATH", "")
TICK_SEC = float(os.environ.get("TICK_SEC", "1.0"))
JAM_THRESHOLD_M = float(os.environ.get("JAM_THRESHOLD_M", "200"))
JAM_EIRP_DBM = float(os.environ.get("JAM_EIRP_DBM", "33"))
JAM_ROE = os.environ.get("JAM_ROE", "auto")
RX_SENSITIVITY_DBM = float(os.environ.get("RX_SENSITIVITY_DBM", "-95"))

app = FastAPI(
    title="counter-uas",
    version="0.1.0",
    description="카운터 드론 RF 탐지→근접→자동재밍 시뮬(송신 없음, UAVCounterUas_CL).",
)

_engine = SimEngine(
    asset_id=ASSET_ID,
    detector=RfDetector(rx_sensitivity_dbm=RX_SENSITIVITY_DBM),
    jammer=Jammer(
        roe=Roe(JAM_ROE),
        threshold_m=JAM_THRESHOLD_M,
        jam_eirp_dbm=JAM_EIRP_DBM,
        jam_mode=JamMode.SPOT,
    ),
)
_lock = threading.Lock()
_log_handle: Any = None


def _open_log() -> None:
    """LOG_FILE_PATH 로그 싱크를 연다(미지정 시 비활성)."""
    global _log_handle
    if not LOG_FILE_PATH:
        return
    if LOG_FILE_PATH == "/dev/stdout":
        import sys

        _log_handle = sys.stdout
    else:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        _log_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")  # noqa: SIM115


def _emit(record: dict[str, object]) -> None:
    """레코드 한 줄을 NDJSON 으로 방출한다."""
    if _log_handle is None:
        return
    _log_handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    _log_handle.flush()


def _loop() -> None:
    """백그라운드 시뮬 루프 — 매 TICK_SEC 마다 진행 후 NDJSON 방출."""
    while True:
        with _lock:
            result = _engine.tick(dt=TICK_SEC)
        for rec in result["detections"] + result["engagements"]:
            _emit(rec)
        time.sleep(TICK_SEC)


@app.on_event("startup")
def _startup() -> None:
    """로그 싱크를 열고 시뮬 루프 스레드를 띄운다."""
    _open_log()
    threading.Thread(target=_loop, daemon=True).start()


# ---- 제어면 모델 -----------------------------------------------------------


class SpawnRequest(BaseModel):
    """침입자 주입 요청."""

    track_id: str
    start_range_m: float = Field(default=600, gt=0)
    bearing_deg: float = 0.0
    speed_mps: float = Field(default=20, ge=0)
    center_mhz: float = 2440.0
    allegiance: str = "hostile"
    eirp_dbm: float = 20.0
    altitude_m: float = 80.0


class JammerConfig(BaseModel):
    """재밍 정책 갱신 요청(부분 갱신)."""

    armed: bool | None = None
    roe: str | None = None
    threshold_m: float | None = None
    jam_eirp_dbm: float | None = None
    engage_friendly: bool | None = None


# ---- 엔드포인트 ------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    """헬스 체크."""
    return {"status": "ok", "asset": ASSET_ID}


@app.get("/state")
def get_state() -> dict[str, object]:
    """현재 자산/재밍/트랙 상태."""
    with _lock:
        return _engine.state()


@app.post("/intruder/spawn")
def spawn(req: SpawnRequest) -> dict[str, str]:
    """접근 침입자를 주입한다."""
    with _lock:
        _engine.spawn_approach(
            track_id=req.track_id,
            start_range_m=req.start_range_m,
            bearing_deg=req.bearing_deg,
            speed_mps=req.speed_mps,
            center_mhz=req.center_mhz,
            allegiance=req.allegiance,
            eirp_dbm=req.eirp_dbm,
            altitude_m=req.altitude_m,
        )
    return {"spawned": req.track_id}


@app.delete("/intruder/{track_id}")
def despawn(track_id: str) -> dict[str, str]:
    """침입자를 제거한다."""
    with _lock:
        _engine.despawn(track_id)
    return {"despawned": track_id}


@app.post("/jammer/config")
def configure(cfg: JammerConfig) -> dict[str, object]:
    """재밍 정책을 갱신한다(arm/roe/임계/EIRP/아군교전)."""
    with _lock:
        j = _engine.jammer
        if cfg.armed is not None:
            j.armed = cfg.armed
        if cfg.roe is not None:
            j.roe = Roe(cfg.roe)
        if cfg.threshold_m is not None:
            j.threshold_m = cfg.threshold_m
        if cfg.jam_eirp_dbm is not None:
            j.jam_eirp_dbm = cfg.jam_eirp_dbm
        if cfg.engage_friendly is not None:
            j.engage_friendly = cfg.engage_friendly
        return _engine.state()["jammer"]
