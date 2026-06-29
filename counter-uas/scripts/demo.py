#!/usr/bin/env python3
"""counter-uas 콘솔 데모 — 하드웨어 없이 탐지→근접→자동재밍(시뮬)을 시각화.

3개 침입 트랙으로 시나리오를 구성한다:
  - HOSTILE-1  : 2.4GHz 조종링크, 600m 에서 자산으로 정면 접근 → 임계 통과 시 자동 재밍
  - UNKNOWN-2  : 915MHz, 측면에서 천천히 접근
  - FRIENDLY-3 : 5.8GHz, 근접하지만 아군으로 분류되어 보호(미교전)

실행:
    python scripts/demo.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from counter_uas.detector import RfDetector
from counter_uas.engagement import JamMode, Jammer, Roe
from counter_uas.engine import SimEngine

# ANSI 색 (터미널).
_RED, _YEL, _GRN, _CYN, _DIM, _RST = (
    "\033[91m", "\033[93m", "\033[92m", "\033[96m", "\033[2m", "\033[0m"
)


def _state_color(state: str) -> str:
    return {
        "inbound": _YEL,
        "transit": _CYN,
        "jammed": _RED,
        "retreating": _GRN,
    }.get(state, "")


def main() -> None:
    """데모 시나리오를 구성하고 tick 루프를 돌리며 콘솔에 출력한다."""
    engine = SimEngine(
        asset_id="CUAS-SITE-1",
        detector=RfDetector(rx_sensitivity_dbm=-95.0, seed=7),
        jammer=Jammer(
            roe=Roe.AUTO,
            threshold_m=200.0,
            jam_eirp_dbm=33.0,
            jam_mode=JamMode.SPOT,
            js_deny_db=6.0,
        ),
    )

    engine.spawn_approach("HOSTILE-1", start_range_m=600, bearing_deg=20,
                          speed_mps=25, center_mhz=2440.0, allegiance="hostile",
                          eirp_dbm=20.0, protocol="ctrl-2.4g")
    engine.spawn_approach("UNKNOWN-2", start_range_m=520, bearing_deg=290,
                          speed_mps=12, center_mhz=915.0, allegiance="unknown",
                          eirp_dbm=20.0, protocol="lr-915")
    engine.spawn_approach("FRIENDLY-3", start_range_m=300, bearing_deg=160,
                          speed_mps=14, center_mhz=5800.0, allegiance="friendly",
                          eirp_dbm=23.0, protocol="fpv-5.8g")

    print(f"{_CYN}━━ counter-uas 시뮬 데모 (송신 없음 · 재밍은 시뮬) ━━{_RST}")
    print(f"방어 자산: {engine.asset_id} | ROE=AUTO | 재밍 임계={engine.jammer.threshold_m:.0f}m"
          f" | J/S 차단={engine.jammer.js_deny_db:.0f}dB\n")

    for _ in range(26):
        result = engine.tick(dt=1.0)
        st = engine.state()
        fired = {e["TrackId"]: e for e in result["engagements"]
                 if e["Status"] == "fired"}

        print(f"{_DIM}── tick {st['tick']:02d} "
              f"─────────────────────────────────────────────{_RST}")
        det_by_track = {d["TrackId"]: d for d in result["detections"]}
        for trk in st["tracks"]:
            tid = trk["track_id"]
            col = _state_color(trk["state"])
            det = det_by_track.get(tid)
            if det:
                line = (f"  {col}{tid:<11}{_RST} {trk['allegiance']:<8} "
                        f"{det['Band']:<7} 추정 {det['EstRange_m']:6.0f}m "
                        f"(참 {det['TrueRange_m']:6.0f}m) "
                        f"RSSI {det['Rssi_dBm']:6.1f}dBm "
                        f"방위 {det['Bearing_deg']:5.1f}° "
                        f"[{col}{trk['state']}{_RST}]")
            else:
                line = f"  {_DIM}{tid:<11} (미탐){_RST}"
            print(line)
            if tid in fired:
                e = fired[tid]
                print(f"      {_RED}▶ 재밍 작동{_RST} {e['TargetBand']} "
                      f"{e['JamFreqMHz']:.0f}MHz {e['JamMode']} "
                      f"J/S={e['JsRatio_dB']:.1f}dB → 효과={_RED}{e['Effect']}{_RST} "
                      f"({e['ReasonCode']})")
        print()
        time.sleep(0.35)

    print(f"{_GRN}데모 종료 — HOSTILE 은 근접 시 자동 재밍으로 링크 차단→이탈, "
          f"FRIENDLY 는 근접해도 보호(미교전).{_RST}")


if __name__ == "__main__":
    main()
