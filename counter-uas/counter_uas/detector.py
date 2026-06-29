"""RF 스펙트럼 스캔 탐지기 — 침입 emitter → 탐지 결과(거리 추정 포함).

수동 수신만 모델링한다(합법). 각 emitter 에 대해 참 거리로 RSSI 를 계산하고 측정
잡음을 더한 뒤, 수신감도 이상이면 탐지로 보고 거리/대역을 추정한다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from counter_uas import rf
from counter_uas.airspace import Allegiance, Intruder


@dataclass
class Detection:
    """탐지 1건.

    Attributes:
        track_id: 탐지된 트랙.
        center_mhz: 측정 중심 주파수.
        band_name: 분류된 대역명(미상이면 "unknown").
        rssi_dbm: 측정 RSSI.
        est_range_m: RSSI 기반 추정 거리.
        true_range_m: 시뮬 참값 거리(검증/디버그용).
        bearing_deg: 추정 방위각.
        allegiance: 적성 분류.
        protocol: 추정 프로토콜.
    """

    track_id: str
    center_mhz: float
    band_name: str
    rssi_dbm: float
    est_range_m: float
    true_range_m: float
    bearing_deg: float
    allegiance: str
    protocol: str


class RfDetector:
    """방어 자산에 배치된 수동 RF 탐지기.

    Args:
        rx_sensitivity_dbm: 탐지 임계(이보다 약하면 미탐).
        rx_gain_dbi: 수신 안테나 이득.
        path_loss_n: 경로손실 지수(추정에 사용).
        meas_noise_std_db: RSSI 측정 잡음 표준편차.
        seed: 난수 시드(재현용).
    """

    def __init__(
        self,
        rx_sensitivity_dbm: float = -95.0,
        rx_gain_dbi: float = 3.0,
        path_loss_n: float = 2.2,
        meas_noise_std_db: float = 2.5,
        seed: int | None = None,
    ) -> None:
        self._sens = rx_sensitivity_dbm
        self._rx_gain = rx_gain_dbi
        self._n = path_loss_n
        self._noise = meas_noise_std_db
        self._rng = random.Random(seed)

    def scan(self, intruders: list[Intruder]) -> list[Detection]:
        """현재 공역을 스캔해 탐지 목록을 반환한다.

        Args:
            intruders: 공역 내 침입 트랙 목록.

        Returns:
            수신감도 이상으로 잡힌 `Detection` 목록.
        """
        detections: list[Detection] = []
        for intr in intruders:
            em = intr.emitter
            true_range = intr.range_m()
            clean = rf.rssi_dbm(
                em.eirp_dbm, true_range, em.center_mhz, self._n, self._rx_gain
            )
            measured = clean + self._rng.gauss(0.0, self._noise)
            if measured < self._sens:
                continue  # 미탐(잡음/거리)
            band = rf.classify_band(em.center_mhz)
            assumed_eirp = band.ref_eirp_dbm if band else 20.0
            est_range = rf.estimate_distance_m(
                measured, em.center_mhz, assumed_eirp, self._n, self._rx_gain
            )
            detections.append(
                Detection(
                    track_id=intr.track_id,
                    center_mhz=em.center_mhz,
                    band_name=band.name if band else "unknown",
                    rssi_dbm=round(measured, 1),
                    est_range_m=round(est_range, 1),
                    true_range_m=round(true_range, 1),
                    bearing_deg=round(intr.bearing_deg(), 1),
                    allegiance=intr.allegiance.value
                    if isinstance(intr.allegiance, Allegiance)
                    else str(intr.allegiance),
                    protocol=em.protocol,
                )
            )
        return detections
