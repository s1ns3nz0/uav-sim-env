"""RF 물리 모델 — 경로손실, RSSI, 거리 추정, 드론 대역 분류.

log-distance 경로손실 모델(1m FSPL 기준 + 경로손실지수 n)을 사용한다. 모든 전력은
dBm, 이득은 dBi, 주파수는 MHz, 거리는 m 단위.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---- 드론에서 흔히 쓰는 RF 대역 (탐지/분류용 참조 테이블) -------------------


@dataclass(frozen=True)
class Band:
    """드론 RF 대역 정의.

    Attributes:
        name: 대역 식별자(예: "2.4GHz").
        low_mhz: 대역 하한.
        high_mhz: 대역 상한.
        typical_use: 일반 용도 설명.
        ref_eirp_dbm: 탐지기가 거리 추정 시 가정하는 기준 EIRP.
    """

    name: str
    low_mhz: float
    high_mhz: float
    typical_use: str
    ref_eirp_dbm: float

    @property
    def center_mhz(self) -> float:
        """대역 중심 주파수(MHz)."""
        return (self.low_mhz + self.high_mhz) / 2.0


# 일반적인 소형 무인기 통신 대역. GPS L1 은 항법 재밍 표적용으로 포함.
BANDS: tuple[Band, ...] = (
    Band("433MHz", 433.0, 434.8, "장거리 텔레메트리(LoRa/UHF)", 17.0),
    Band("915MHz", 902.0, 928.0, "장거리 제어/텔레메트리", 20.0),
    Band("1.5GHz", 1574.0, 1577.0, "GPS L1(항법) — 재밍 표적", 16.0),
    Band("2.4GHz", 2400.0, 2483.5, "제어/조종(가장 흔함)", 20.0),
    Band("5.8GHz", 5725.0, 5875.0, "FPV 영상 다운링크", 23.0),
)

_C = 299_792_458.0  # 광속 (m/s)


def fspl_1m_db(freq_mhz: float) -> float:
    """1m 기준 자유공간 경로손실(dB).

    Args:
        freq_mhz: 주파수(MHz).

    Returns:
        1m 거리에서의 FSPL(dB).
    """
    # FSPL(dB) = 20log10(4*pi*d*f/c). d=1m → 20log10(f_MHz) - 27.55.
    return 20.0 * math.log10(freq_mhz) + 20.0 * math.log10(1e6) + 20.0 * math.log10(
        4.0 * math.pi / _C
    )


def path_loss_db(distance_m: float, freq_mhz: float, n: float = 2.2) -> float:
    """log-distance 경로손실(dB) — 1m FSPL + 10*n*log10(d).

    Args:
        distance_m: 거리(m). 1m 미만은 1m 로 클램프.
        freq_mhz: 주파수(MHz).
        n: 경로손실 지수(자유공간 2.0, LOS 항공 2.0~2.5, 도심 2.7~3.5).

    Returns:
        총 경로손실(dB).
    """
    d = max(distance_m, 1.0)
    return fspl_1m_db(freq_mhz) + 10.0 * n * math.log10(d)


def rssi_dbm(
    eirp_dbm: float,
    distance_m: float,
    freq_mhz: float,
    n: float = 2.2,
    rx_gain_dbi: float = 3.0,
) -> float:
    """수신 신호세기(dBm) = EIRP - 경로손실 + 수신안테나 이득.

    Args:
        eirp_dbm: 송신원 유효등방복사전력(dBm).
        distance_m: 송신원-수신기 거리(m).
        freq_mhz: 주파수(MHz).
        n: 경로손실 지수.
        rx_gain_dbi: 수신 안테나 이득(dBi).

    Returns:
        수신기에서의 RSSI(dBm).
    """
    return eirp_dbm - path_loss_db(distance_m, freq_mhz, n) + rx_gain_dbi


def estimate_distance_m(
    measured_rssi_dbm: float,
    freq_mhz: float,
    assumed_eirp_dbm: float,
    n: float = 2.2,
    rx_gain_dbi: float = 3.0,
) -> float:
    """측정 RSSI 로부터 거리 역추정(m).

    탐지기는 송신원의 실제 EIRP 를 모르므로 대역별 기준 EIRP 를 가정한다. 따라서
    추정 거리는 가정 오차/측정 잡음만큼 참값과 어긋난다(실측 특성 재현).

    Args:
        measured_rssi_dbm: 측정된 RSSI(dBm).
        freq_mhz: 주파수(MHz).
        assumed_eirp_dbm: 가정 EIRP(dBm).
        n: 경로손실 지수.
        rx_gain_dbi: 수신 안테나 이득(dBi).

    Returns:
        추정 거리(m), 1m 이상.
    """
    excess = assumed_eirp_dbm + rx_gain_dbi - fspl_1m_db(freq_mhz) - measured_rssi_dbm
    return max(10.0 ** (excess / (10.0 * n)), 1.0)


def classify_band(freq_mhz: float) -> Band | None:
    """주파수를 알려진 드론 대역으로 분류한다.

    Args:
        freq_mhz: 중심 주파수(MHz).

    Returns:
        매칭되는 `Band`, 없으면 None.
    """
    for band in BANDS:
        if band.low_mhz <= freq_mhz <= band.high_mhz:
            return band
    return None
