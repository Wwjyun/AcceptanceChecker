# -*- coding: utf-8 -*-
"""工程建議產生器的單元測試。"""

from __future__ import annotations

from acceptance_checker import Metrics, ReportBuilder, Thresholds
from acceptance_checker.reporting import RecommendationBuilder


def _healthy_metrics() -> Metrics:
    m = Metrics()
    m.mean_gray = 150.0
    m.uniformity_ratio = 0.95
    m.low_clip_pct = 0.0
    m.high_clip_pct = 0.0
    m.hist_spread_p99_p01 = 40.0
    m.zone_1_left_mean = 150.0
    m.zone_2_left_mid_mean = 150.0
    m.zone_3_center_mean = 150.0
    m.zone_4_right_mid_mean = 150.0
    m.zone_5_right_mean = 150.0
    m.auto_defect_count = 1
    m.auto_defect_cnr_est = 10.0
    m.signal_to_noise_ratio = 50.0
    m.bg_std_est = 3.0
    m.sharpness_laplacian_var = 100.0
    return m


def test_report_includes_recommendation_section():
    text = ReportBuilder().build(_healthy_metrics())
    assert "【建議處置】" in text
    assert "維持現有光源、曝光、鏡頭與治具設定" in text


def test_low_brightness_recommends_light_or_exposure():
    m = _healthy_metrics()
    m.mean_gray = 40.0
    text = RecommendationBuilder().build(m, Thresholds())
    assert "整體亮度不足" in text
    assert "提高光源亮度" in text
    assert "延長曝光時間" in text


def test_high_clipping_recommends_reducing_exposure_first():
    m = _healthy_metrics()
    m.high_clip_pct = 2.0
    text = RecommendationBuilder().build(m, Thresholds())
    assert "亮部 clipping 偏高" in text
    assert "降低曝光時間" in text
    assert "降低相機 gain" in text


def test_uniformity_recommendation_points_to_dark_and_bright_sides():
    m = _healthy_metrics()
    m.uniformity_ratio = 0.6
    m.zone_1_left_mean = 90.0
    m.zone_5_right_mean = 180.0
    text = RecommendationBuilder().build(m, Thresholds())
    assert "分區均勻性不足" in text
    assert "左側偏暗" in text
    assert "右側偏亮" in text


def test_noise_and_snr_recommendations_include_gain_and_strobe_checks():
    m = _healthy_metrics()
    m.signal_to_noise_ratio = 12.0
    m.bg_std_est = 12.0
    text = RecommendationBuilder().build(m, Thresholds())
    assert "整體 SNR 偏低" in text
    assert "降低 gain" in text
    assert "光源閃爍" in text


def test_low_cnr_recommends_lighting_geometry_or_wavelength():
    m = _healthy_metrics()
    m.auto_defect_cnr_est = 4.0
    text = RecommendationBuilder().build(m, Thresholds())
    assert "缺陷 CNR 偏低" in text
    assert "打光角度" in text
    assert "光源波長" in text


def test_low_sharpness_recommends_focus_and_vibration_actions():
    m = _healthy_metrics()
    m.sharpness_laplacian_var = 40.0
    text = RecommendationBuilder().build(m, Thresholds())
    assert "清晰度偏低" in text
    assert "重新對焦" in text
    assert "降低輸送或治具震動" in text
