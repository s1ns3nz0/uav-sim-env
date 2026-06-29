"""counter-uas — 순수 시뮬 카운터 드론(RF 탐지 → 근접 → 자동 재밍) 엔진.

하드웨어 없이 RF 물리(경로손실/RSSI/거리추정)와 교전 정책(근접 임계 → 재밍)을
모델링한다. 실제 송신은 하지 않으며, 재밍은 J/S 효과로 시뮬레이션만 한다.
"""

from counter_uas.engine import SimEngine

__all__ = ["SimEngine"]
