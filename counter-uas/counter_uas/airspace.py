"""공역 모델 — 방어 자산, 침입 드론의 RF emitter 와 기동.

좌표계는 방어 자산을 원점으로 하는 로컬 ENU(동/북/상) 미터 프레임. 거리는 3D
유클리드. 침입자는 등속 직선 기동(접근/이탈)을 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class Allegiance(str, Enum):
    """침입 트랙의 적성 분류."""

    HOSTILE = "hostile"
    UNKNOWN = "unknown"
    FRIENDLY = "friendly"


class TrackState(str, Enum):
    """침입자 상태(교전 효과 반영)."""

    INBOUND = "inbound"      # 자산으로 접근 중
    TRANSIT = "transit"      # 통과/비접근
    JAMMED = "jammed"        # 재밍으로 링크 차단 → 정지
    RETREATING = "retreating"  # 링크 상실 후 이탈


@dataclass
class Emitter:
    """드론 탑재 RF 송신원.

    Attributes:
        center_mhz: 중심 주파수(MHz).
        bandwidth_mhz: 점유 대역폭(MHz).
        eirp_dbm: 유효등방복사전력(dBm).
        protocol: 추정 프로토콜/용도 라벨.
    """

    center_mhz: float
    bandwidth_mhz: float
    eirp_dbm: float
    protocol: str = "unknown"


@dataclass
class Intruder:
    """침입 드론 트랙.

    Attributes:
        track_id: 트랙 식별자.
        position: (x, y, z) 자산 기준 ENU 미터.
        velocity: (vx, vy, vz) m/s.
        emitter: 탑재 RF 송신원.
        allegiance: 적성 분류.
        state: 현재 상태.
        operator_rssi_dbm: 드론이 조종자로부터 수신하는 공칭 신호세기(J/S 분모).
    """

    track_id: str
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    emitter: Emitter
    allegiance: Allegiance = Allegiance.UNKNOWN
    state: TrackState = TrackState.INBOUND
    operator_rssi_dbm: float = -70.0
    _retreat_set: bool = field(default=False, repr=False)

    def range_m(self) -> float:
        """방어 자산(원점)까지의 3D 거리(m)."""
        x, y, z = self.position
        return math.sqrt(x * x + y * y + z * z)

    def bearing_deg(self) -> float:
        """자산 기준 방위각(도, 북=0, 시계방향)."""
        x, y, _ = self.position
        return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

    def advance(self, dt: float) -> None:
        """dt 초만큼 기동을 전진한다.

        JAMMED 는 정지, RETREATING 은 자산 반대 방향으로 가속 이탈한다.

        Args:
            dt: 시간 간격(초).
        """
        if self.state == TrackState.JAMMED:
            return  # 링크 차단 → 호버(정지)
        if self.state == TrackState.RETREATING and not self._retreat_set:
            # 자산에서 멀어지는 단위벡터로 이탈 속도 설정.
            x, y, z = self.position
            norm = max(self.range_m(), 1.0)
            speed = 18.0
            self.velocity = (x / norm * speed, y / norm * speed, z / norm * speed)
            self._retreat_set = True
        x, y, z = self.position
        vx, vy, vz = self.velocity
        self.position = (x + vx * dt, y + vy * dt, z + vz * dt)
