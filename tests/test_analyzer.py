# -*- coding: utf-8 -*-
"""ImageAnalyzer 指標計算的單元測試（含邊界影像）。"""

from __future__ import annotations

import numpy as np

from acceptance_checker import ImageAnalyzer, RawImage
from tests.conftest import make_uniform


def _analyze(img: np.ndarray, max_pixels: int = 8_000_000):
    analyzer = ImageAnalyzer(max_pixels=max_pixels)
    m, sample, defect = analyzer.analyze(RawImage(img, "uint8"), "x.png")
    return m, sample, defect


def test_black_image_metrics():
    m, _, _ = _analyze(np.zeros((400, 600), dtype=np.uint8))
    assert m.mean_gray == 0.0
    assert m.low_clip_pct == 100.0
    assert m.high_clip_pct == 0.0
    assert m.hist_spread_p99_p01 == 0.0


def test_saturated_image_metrics():
    m, _, _ = _analyze(np.full((400, 600), 255, dtype=np.uint8))
    assert m.mean_gray == 255.0
    assert m.high_clip_pct == 100.0
    assert m.low_clip_pct == 0.0


def test_uniform_image_high_uniformity():
    m, _, _ = _analyze(make_uniform(150))
    assert m.uniformity_ratio == 1.0
    assert m.bg_std_est == 0.0
    assert m.signal_to_noise_ratio > 1_000_000


def test_signal_to_noise_ratio_uses_robust_noise(good_image):
    m, _, _ = _analyze(good_image)
    assert m.robust_noise_sigma > 0.0
    assert m.signal_to_noise_ratio == m.mean_gray / m.robust_noise_sigma


def test_good_image_detects_defect(good_image):
    m, sample, defect = _analyze(good_image)
    assert m.auto_defect_count >= 1
    assert defect.overlay is not None and defect.overlay.ndim == 3
    assert sample.shape == good_image.shape


def test_max_pixels_downsamples():
    img = make_uniform(120, shape=(2000, 2000))
    m, sample, _ = _analyze(img, max_pixels=100_000)
    assert m.analysis_step > 1
    assert sample.size < img.size


def test_file_name_recorded():
    analyzer = ImageAnalyzer()
    m, _, _ = analyzer.analyze(RawImage(make_uniform(100), "uint8"), "/tmp/foo/bar.bmp")
    assert m.file_name == "bar.bmp"
    assert m.width_px == 600 and m.height_px == 400
