"""교전 엔진 — 근접 임계 정책 + 시뮬 재밍 + J/S 효과 모델.

중요: 실제 RF 송신은 하지 않는다. 재밍은 J/S(jam-to-signal) 비로 효과만 계산하고
NDJSON 으로 기록한다. 실송신은 법적 허가·차폐환경에서만 별도로 다룰 사안이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from counter_uas import rf
from counter_uas.airspace import Allegiance, Intruder, TrackState
from counter_uas.detector import Detection


class Roe(str, Enum):
    """교전수칙(Rules of Engagement)."""

    AUTO = "auto"      # 근접 시 자동 재밍(시뮬)
    MANUAL = "manual"  # 탐지·권고만, 작동 안 함


class JamMode(str, Enum):
    """재밍 파형 모드."""

    SPOT = "spot"        # 탐지 대역 협대역 집중
    BARRAGE = "barrage"  # 대역 전체 광대역


@dataclass
class Engagement:
    """교전(재밍) 판정/작동 1건.

    Attributes:
        track_id: 대상 트랙.
        target_band: 표적 대역명.
        jam_freq_mhz: 재밍 중심 주파수.
        jam_mode: 파형 모드.
        jam_eirp_dbm: 재밍 EIRP(시뮬).
        js_ratio_db: 드론 수신단 J/S 비(dB).
        effect: 효과("denied"/"degraded"/"none").
        status: 작동 상태("fired"/"recommended"/"ceased"/"hold").
        reason: 판정 사유 코드.
    """

    track_id: str
    target_band: str
    jam_freq_mhz: float
    jam_mode: str
    jam_eirp_dbm: float
    js_ratio_db: float
    effect: str
    status: str
    reason: str


class Jammer:
    """근접 트리거 기반 카운터-UAS 재밍기(시뮬 전용).

    Args:
        roe: 교전수칙(auto=자동작동, manual=권고만).
        threshold_m: 재밍 작동 근접 임계(추정 거리 기준).
        jam_eirp_dbm: 재밍 EIRP(시뮬).
        jam_mode: 파형 모드.
        js_deny_db: 링크 차단으로 보는 J/S 임계(dB).
        path_loss_n: 경로손실 지수.
        engage_friendly: True 면 아군도 교전(기본 False — 아군 보호).
        drone_rx_gain_dbi: 드론 수신 안테나 이득(J/S 계산).
    """

    def __init__(
        self,
        roe: Roe = Roe.AUTO,
        threshold_m: float = 200.0,
        jam_eirp_dbm: float = 30.0,
        jam_mode: JamMode = JamMode.SPOT,
        js_deny_db: float = 6.0,
        path_loss_n: float = 2.2,
        engage_friendly: bool = False,
        drone_rx_gain_dbi: float = 2.0,
    ) -> None:
        self.armed = True
        self.roe = roe
        self.threshold_m = threshold_m
        self.jam_eirp_dbm = jam_eirp_dbm
        self.jam_mode = jam_mode
        self.js_deny_db = js_deny_db
        self._n = path_loss_n
        self.engage_friendly = engage_friendly
        self._drone_rx_gain = drone_rx_gain_dbi

    def _js_ratio_db(self, intr: Intruder) -> float:
        """드론 수신단에서의 J/S 비(dB) — 재밍기는 자산(원점)에 동치.

        Args:
            intr: 대상 침입자.

        Returns:
            J/S(dB). 양수 클수록 링크 차단 유리.
        """
        jam_rx = rf.rssi_dbm(
            self.jam_eirp_dbm,
            intr.range_m(),
            intr.emitter.center_mhz,
            self._n,
            self._drone_rx_gain,
        )
        return jam_rx - intr.operator_rssi_dbm

    def evaluate(
        self, detections: list[Detection], intruders: dict[str, Intruder]
    ) -> list[Engagement]:
        """탐지 결과로 교전을 판정하고, AUTO 면 효과를 트랙에 적용한다.

        Args:
            detections: 이번 스캔 탐지 목록.
            intruders: track_id → Intruder 맵(효과 적용 대상).

        Returns:
            교전 판정/작동 `Engagement` 목록.
        """
        out: list[Engagement] = []
        for det in detections:
            intr = intruders.get(det.track_id)
            if intr is None:
                continue
            friendly = det.allegiance == Allegiance.FRIENDLY.value
            in_range = det.est_range_m <= self.threshold_m

            if not in_range:
                continue
            if friendly and not self.engage_friendly:
                out.append(
                    self._mk(det, js=0.0, effect="none", status="hold",
                             reason="friendly_protected")
                )
                continue
            if not self.armed:
                out.append(
                    self._mk(det, js=0.0, effect="none", status="hold",
                             reason="jammer_disarmed")
                )
                continue

            js = self._js_ratio_db(intr)
            denied = js >= self.js_deny_db
            effect = "denied" if denied else ("degraded" if js >= 0 else "none")

            if self.roe == Roe.MANUAL:
                out.append(
                    self._mk(det, js, effect="none", status="recommended",
                             reason="roe_manual")
                )
                continue

            # AUTO — 시뮬 작동 + 효과 적용.
            if denied and intr.state in (TrackState.INBOUND, TrackState.TRANSIT):
                intr.state = TrackState.JAMMED
            out.append(
                self._mk(det, js, effect=effect, status="fired",
                         reason="proximity_auto")
            )
        return out

    def _mk(
        self, det: Detection, js: float, effect: str, status: str, reason: str
    ) -> Engagement:
        """`Engagement` 레코드 헬퍼."""
        return Engagement(
            track_id=det.track_id,
            target_band=det.band_name,
            jam_freq_mhz=det.center_mhz,
            jam_mode=self.jam_mode.value,
            jam_eirp_dbm=self.jam_eirp_dbm,
            js_ratio_db=round(js, 1),
            effect=effect,
            status=status,
            reason=reason,
        )
