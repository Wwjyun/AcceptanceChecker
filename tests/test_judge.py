# -*- coding: utf-8 -*-
"""AcceptanceJudge 判定邏輯的單元測試。"""

from __future__ import annotations

from acceptance_checker import AcceptanceJudge, Metrics, Thresholds


def _healthy_metrics() -> Metrics:
    """建立一組所有指標都在 PASS 範圍內的 Metrics。"""
    m = Metrics()
    m.mean_gray = 150.0
    m.uniformity_ratio = 0.95
    m.low_clip_pct = 0.0
    m.high_clip_pct = 0.0
    m.hist_spread_p99_p01 = 40.0
    m.auto_defect_count = 1
    m.auto_defect_cnr_est = 10.0
    m.signal_to_noise_ratio = 50.0
    m.bg_std_est = 3.0
    m.sharpness_laplacian_var = 100.0
    return m


def test_healthy_metrics_pass():
    m = AcceptanceJudge().judge(_healthy_metrics())
    assert m.overall_status == "PASS"
    assert m.fail_reasons == ""
    assert m.warn_reasons == ""


def test_low_mean_gray_fails():
    m = _healthy_metrics()
    m.mean_gray = 10.0
    AcceptanceJudge().judge(m)
    assert m.overall_status == "FAIL"
    assert "平均灰階" in m.fail_reasons


def test_mean_gray_warning_band():
    m = _healthy_metrics()
    m.mean_gray = 45.0  # 介於 fail(30) 與 warn(50)
    AcceptanceJudge().judge(m)
    assert m.overall_status == "WARNING"


def test_no_defect_candidate_is_warning_not_fail():
    m = _healthy_metrics()
    m.auto_defect_count = 0
    AcceptanceJudge().judge(m)
    assert m.overall_status == "WARNING"


def test_low_cnr_with_candidate_fails():
    m = _healthy_metrics()
    m.auto_defect_count = 2
    m.auto_defect_cnr_est = 1.0
    AcceptanceJudge().judge(m)
    assert m.overall_status == "FAIL"
    assert "CNR" in m.fail_reasons


def test_low_snr_fails():
    m = _healthy_metrics()
    m.signal_to_noise_ratio = 5.0
    AcceptanceJudge().judge(m)
    assert m.overall_status == "FAIL"
    assert "SNR" in m.fail_reasons


def test_snr_warning_band():
    m = _healthy_metrics()
    m.signal_to_noise_ratio = 15.0
    AcceptanceJudge().judge(m)
    assert m.overall_status == "WARNING"
    assert "SNR" in m.warn_reasons


def test_high_bg_std_fails():
    m = _healthy_metrics()
    m.bg_std_est = 20.0
    AcceptanceJudge().judge(m)
    assert m.overall_status == "FAIL"


def test_loose_thresholds_avoid_fail():
    m = _healthy_metrics()
    m.mean_gray = 10.0
    loose = Thresholds(mean_gray_fail=0, mean_gray_warn=0)
    AcceptanceJudge(loose).judge(m)
    assert "平均灰階" not in m.fail_reasons


def test_fail_takes_precedence_over_warning():
    m = _healthy_metrics()
    m.mean_gray = 45.0       # WARNING 來源
    m.bg_std_est = 20.0      # FAIL 來源
    AcceptanceJudge().judge(m)
    assert m.overall_status == "FAIL"
    assert m.warn_reasons  # warning 原因仍記錄
