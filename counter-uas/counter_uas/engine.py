"""시뮬 엔진 — 공역 전진 → 스캔 → 교전 판정 → NDJSON 레코드 생성.

방어 자산 1기를 원점에 두고, 등록된 침입 트랙을 매 tick 전진시킨 뒤 수동 탐지와
근접 재밍(시뮬)을 수행한다. 출력 NDJSON 은 `UAVCounterUas_CL` 스키마(EventType
마커는 항상 문자열)와 일치한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from counter_uas.airspace import (
    Allegiance,
    Emitter,
    Intruder,
    TrackState,
)
from counter_uas.detector import Detection, RfDetector
from counter_uas.engagement import Engagement, JamMode, Jammer, Roe

# JAMMED 상태 유지 tick 수 → 이후 RETREATING(링크 상실 후 이탈) 전이.
_JAMMED_HOLD_TICKS = 3


def _now_iso() -> str:
    """현재 UTC ISO8601(ms) 타임스탬프."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class SimEngine:
    """카운터-UAS 시뮬 엔진.

    Args:
        asset_id: 방어 자산 식별자(레코드 UAVId).
        detector: RF 탐지기(미지정 시 기본값).
        jammer: 재밍기(미지정 시 기본값).
    """

    def __init__(
        self,
        asset_id: str = "CUAS-SITE-1",
        detector: RfDetector | None = None,
        jammer: Jammer | None = None,
    ) -> None:
        self.asset_id = asset_id
        self.detector = detector or RfDetector()
        self.jammer = jammer or Jammer()
        self._intruders: dict[str, Intruder] = {}
        self._jammed_ticks: dict[str, int] = {}
        self.tick_count = 0
        self._seq = 0

    # ---- 공역 제어 -------------------------------------------------------

    def spawn_intruder(
        self,
        track_id: str,
        position: tuple[float, float, float],
        velocity: tuple[float, float, float],
        center_mhz: float,
        eirp_dbm: float = 20.0,
        bandwidth_mhz: float = 20.0,
        protocol: str = "unknown",
        allegiance: str = "unknown",
        operator_rssi_dbm: float = -70.0,
    ) -> None:
        """침입 트랙을 등록한다.

        Args:
            track_id: 트랙 식별자.
            position: (x, y, z) 자산 기준 ENU 미터.
            velocity: (vx, vy, vz) m/s.
            center_mhz: emitter 중심 주파수(MHz).
            eirp_dbm: emitter EIRP(dBm).
            bandwidth_mhz: emitter 대역폭(MHz).
            protocol: 추정 프로토콜 라벨.
            allegiance: "hostile"/"unknown"/"friendly".
            operator_rssi_dbm: 드론의 조종링크 공칭 RSSI(J/S 분모).
        """
        self._intruders[track_id] = Intruder(
            track_id=track_id,
            position=position,
            velocity=velocity,
            emitter=Emitter(center_mhz, bandwidth_mhz, eirp_dbm, protocol),
            allegiance=Allegiance(allegiance),
            state=TrackState.INBOUND,
            operator_rssi_dbm=operator_rssi_dbm,
        )

    def spawn_approach(
        self,
        track_id: str,
        start_range_m: float,
        bearing_deg: float,
        speed_mps: float,
        center_mhz: float,
        allegiance: str = "hostile",
        altitude_m: float = 80.0,
        **kwargs: Any,
    ) -> None:
        """자산을 향해 직선 접근하는 침입자를 생성하는 편의 함수.

        Args:
            track_id: 트랙 식별자.
            start_range_m: 시작 수평 거리(m).
            bearing_deg: 자산 기준 시작 방위(도, 북=0 시계방향).
            speed_mps: 접근 속도(m/s).
            center_mhz: emitter 중심 주파수(MHz).
            allegiance: 적성 분류.
            altitude_m: 고도(m).
            **kwargs: spawn_intruder 로 전달되는 추가 emitter 인자.
        """
        import math

        rad = math.radians(bearing_deg)
        x = start_range_m * math.sin(rad)
        y = start_range_m * math.cos(rad)
        norm = max(math.sqrt(x * x + y * y), 1.0)
        vx, vy = -x / norm * speed_mps, -y / norm * speed_mps  # 자산 방향
        self.spawn_intruder(
            track_id=track_id,
            position=(x, y, altitude_m),
            velocity=(vx, vy, 0.0),
            center_mhz=center_mhz,
            allegiance=allegiance,
            **kwargs,
        )

    def despawn(self, track_id: str) -> None:
        """트랙을 제거한다."""
        self._intruders.pop(track_id, None)
        self._jammed_ticks.pop(track_id, None)

    # ---- 한 tick 진행 ----------------------------------------------------

    def tick(self, dt: float = 1.0) -> dict[str, list[dict[str, object]]]:
        """공역을 한 스텝 진행하고 탐지·교전 NDJSON 레코드를 반환한다.

        Args:
            dt: 시간 간격(초).

        Returns:
            {"detections": [...], "engagements": [...]} — 각 값은 NDJSON dict 목록.
        """
        self.tick_count += 1
        for intr in self._intruders.values():
            intr.advance(dt)
            if intr.state == TrackState.JAMMED:
                self._jammed_ticks[intr.track_id] = (
                    self._jammed_ticks.get(intr.track_id, 0) + 1
                )
                if self._jammed_ticks[intr.track_id] >= _JAMMED_HOLD_TICKS:
                    intr.state = TrackState.RETREATING

        detections = self.detector.scan(list(self._intruders.values()))
        engagements = self.jammer.evaluate(detections, self._intruders)

        det_records = [self._detection_record(d) for d in detections]
        eng_records = [self._engagement_record(e) for e in engagements]
        return {"detections": det_records, "engagements": eng_records}

    # ---- NDJSON 직렬화 ---------------------------------------------------

    def _detection_record(self, d: Detection) -> dict[str, object]:
        """`Detection` → NDJSON dict(UAVCounterUas_CL)."""
        self._seq += 1
        return {
            "TimeGenerated": _now_iso(),
            "EventType": "rf_detection",  # 마커(문자열)
            "UAVId": self.asset_id,
            "Seq": self._seq,
            "TrackId": d.track_id,
            "Band": d.band_name,
            "CenterFreqMHz": d.center_mhz,
            "Rssi_dBm": d.rssi_dbm,
            "EstRange_m": d.est_range_m,
            "TrueRange_m": d.true_range_m,
            "Bearing_deg": d.bearing_deg,
            "Classification": d.allegiance,
            "Protocol": d.protocol,
        }

    def _engagement_record(self, e: Engagement) -> dict[str, object]:
        """`Engagement` → NDJSON dict(UAVCounterUas_CL)."""
        self._seq += 1
        return {
            "TimeGenerated": _now_iso(),
            "EventType": "jam_engagement",  # 마커(문자열)
            "UAVId": self.asset_id,
            "Seq": self._seq,
            "TrackId": e.track_id,
            "TargetBand": e.target_band,
            "JamFreqMHz": e.jam_freq_mhz,
            "JamMode": e.jam_mode,
            "JamEirp_dBm": e.jam_eirp_dbm,
            "JsRatio_dB": e.js_ratio_db,
            "Effect": e.effect,
            "Status": e.status,
            "ReasonCode": e.reason,
        }

    # ---- 조회 ------------------------------------------------------------

    def state(self) -> dict[str, object]:
        """현재 자산/재밍/트랙 상태 요약."""
        return {
            "asset_id": self.asset_id,
            "tick": self.tick_count,
            "jammer": {
                "armed": self.jammer.armed,
                "roe": self.jammer.roe.value,
                "threshold_m": self.jammer.threshold_m,
                "jam_eirp_dbm": self.jammer.jam_eirp_dbm,
                "mode": self.jammer.jam_mode.value,
            },
            "tracks": [
                {
                    "track_id": i.track_id,
                    "range_m": round(i.range_m(), 1),
                    "bearing_deg": round(i.bearing_deg(), 1),
                    "band_mhz": i.emitter.center_mhz,
                    "allegiance": i.allegiance.value,
                    "state": i.state.value,
                }
                for i in self._intruders.values()
            ],
        }


__all__ = ["SimEngine", "RfDetector", "Jammer", "Roe", "JamMode"]
