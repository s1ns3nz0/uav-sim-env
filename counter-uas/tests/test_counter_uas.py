"""counter-uas 단위 테스트 — RF 모델, 탐지, 근접 재밍 판정."""

from __future__ import annotations

import math

import pytest

from counter_uas import rf
from counter_uas.detector import RfDetector
from counter_uas.engagement import JamMode, Jammer, Roe
from counter_uas.engine import SimEngine


class TestRfModel:
    """RF 물리 모델 검증."""

    def test_path_loss_increases_with_distance(self) -> None:
        """거리가 멀수록 경로손실이 커진다."""
        near = rf.path_loss_db(100, 2440)
        far = rf.path_loss_db(400, 2440)
        assert far > near

    def test_distance_estimation_roundtrip(self) -> None:
        """잡음 없는 RSSI → 거리 역추정이 참값에 근접한다(±5%)."""
        true_d = 250.0
        band = rf.classify_band(2440.0)
        assert band is not None
        rssi = rf.rssi_dbm(band.ref_eirp_dbm, true_d, 2440.0)
        est = rf.estimate_distance_m(rssi, 2440.0, band.ref_eirp_dbm)
        assert math.isclose(est, true_d, rel_tol=0.05)

    def test_classify_known_bands(self) -> None:
        """알려진 드론 대역이 올바르게 분류된다."""
        assert rf.classify_band(2440.0).name == "2.4GHz"
        assert rf.classify_band(5800.0).name == "5.8GHz"
        assert rf.classify_band(915.0).name == "915MHz"
        assert rf.classify_band(3000.0) is None


class TestDetector:
    """수동 RF 탐지기 검증."""

    def test_close_emitter_detected(self) -> None:
        """근거리 emitter 는 탐지된다."""
        eng = SimEngine(detector=RfDetector(seed=1))
        eng.spawn_approach("T1", start_range_m=150, bearing_deg=0,
                           speed_mps=0, center_mhz=2440.0)
        dets = eng.detector.scan(list(eng._intruders.values()))
        assert any(d.track_id == "T1" for d in dets)

    def test_far_weak_emitter_not_detected(self) -> None:
        """멀고 약한 emitter 는 수신감도 미달로 미탐."""
        det = RfDetector(rx_sensitivity_dbm=-95.0, meas_noise_std_db=0.0, seed=1)
        eng = SimEngine(detector=det)
        eng.spawn_approach("FAR", start_range_m=50000, bearing_deg=0,
                           speed_mps=0, center_mhz=5800.0, eirp_dbm=10.0)
        dets = det.scan(list(eng._intruders.values()))
        assert all(d.track_id != "FAR" for d in dets)


class TestEngagement:
    """근접 재밍 정책 검증."""

    def test_hostile_within_threshold_is_jammed(self) -> None:
        """임계 내 적성 트랙은 자동 재밍으로 차단된다."""
        eng = SimEngine(
            detector=RfDetector(meas_noise_std_db=0.0, seed=2),
            jammer=Jammer(roe=Roe.AUTO, threshold_m=200, jam_eirp_dbm=33),
        )
        eng.spawn_approach("H", start_range_m=150, bearing_deg=0,
                           speed_mps=0, center_mhz=2440.0, allegiance="hostile")
        res = eng.tick(dt=1.0)
        fired = [e for e in res["engagements"] if e["Status"] == "fired"]
        assert fired and fired[0]["Effect"] == "denied"
        assert eng._intruders["H"].state.value == "jammed"

    def test_friendly_is_protected(self) -> None:
        """아군 트랙은 임계 내라도 교전하지 않는다."""
        eng = SimEngine(
            detector=RfDetector(meas_noise_std_db=0.0, seed=2),
            jammer=Jammer(roe=Roe.AUTO, threshold_m=200, engage_friendly=False),
        )
        eng.spawn_approach("F", start_range_m=120, bearing_deg=0,
                           speed_mps=0, center_mhz=5800.0, allegiance="friendly")
        res = eng.tick(dt=1.0)
        assert all(e["Status"] != "fired" for e in res["engagements"])
        assert eng._intruders["F"].state.value != "jammed"

    def test_manual_roe_recommends_only(self) -> None:
        """MANUAL 교전수칙은 권고만 하고 작동하지 않는다."""
        eng = SimEngine(
            detector=RfDetector(meas_noise_std_db=0.0, seed=2),
            jammer=Jammer(roe=Roe.MANUAL, threshold_m=200),
        )
        eng.spawn_approach("M", start_range_m=120, bearing_deg=0,
                           speed_mps=0, center_mhz=2440.0, allegiance="hostile")
        res = eng.tick(dt=1.0)
        statuses = {e["Status"] for e in res["engagements"]}
        assert "recommended" in statuses and "fired" not in statuses
        assert eng._intruders["M"].state.value != "jammed"

    def test_out_of_range_no_engagement(self) -> None:
        """임계 밖 트랙은 교전 레코드를 만들지 않는다."""
        eng = SimEngine(
            detector=RfDetector(meas_noise_std_db=0.0, seed=2),
            jammer=Jammer(roe=Roe.AUTO, threshold_m=200),
        )
        eng.spawn_approach("O", start_range_m=500, bearing_deg=0,
                           speed_mps=0, center_mhz=2440.0, allegiance="hostile")
        res = eng.tick(dt=1.0)
        assert res["engagements"] == []


class TestEvents:
    """NDJSON 레코드 마커/스키마 검증."""

    def test_marker_values_are_strings(self) -> None:
        """EventType 마커는 항상 문자열(rewrite_tag 매칭 보장)."""
        eng = SimEngine(detector=RfDetector(meas_noise_std_db=0.0, seed=3))
        eng.spawn_approach("X", start_range_m=150, bearing_deg=0,
                           speed_mps=0, center_mhz=2440.0, allegiance="hostile")
        res = eng.tick(dt=1.0)
        for rec in res["detections"] + res["engagements"]:
            assert isinstance(rec["EventType"], str)
            assert isinstance(rec["UAVId"], str)
            assert "TimeGenerated" in rec


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
