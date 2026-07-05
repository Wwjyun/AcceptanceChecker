# -*- coding: utf-8 -*-
"""RawImage 正規化與取樣的單元測試。"""

from __future__ import annotations

import numpy as np

from acceptance_checker import RawImage


def test_uint8_is_copied_unchanged():
    img = np.full((10, 10), 123, dtype=np.uint8)
    gray8, dtype, method = RawImage._normalize_to_8bit(img)
    assert dtype == "uint8"
    assert method == "uint8-copy"
    assert np.array_equal(gray8, img)
    assert gray8 is not img  # 是複本


def test_uint16_linear_divides_by_257():
    img = np.full((5, 5), 25700, dtype=np.uint16)
    gray8, _, method = RawImage._normalize_to_8bit(img, "linear")
    assert "linear" in method
    assert int(gray8[0, 0]) == 100  # 25700/257 = 100


def test_uint16_percentile_stretches_contrast():
    rng = np.random.default_rng(0)
    img = rng.normal(2000, 300, (200, 200)).clip(0, 65535).astype(np.uint16)
    lin, _, _ = RawImage._normalize_to_8bit(img, "linear")
    pct, _, method = RawImage._normalize_to_8bit(img, "percentile", (1.0, 99.0))
    assert "percentile" in method
    assert pct.std() > lin.std() * 3


def test_percentile_zero_range_falls_back_to_linear():
    img = np.full((5, 5), 1000, dtype=np.uint16)
    _, _, method = RawImage._normalize_to_8bit(img, "percentile")
    assert "linear" in method  # 動態範圍為 0 → 退回 linear


def test_float_minmax():
    img = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
    gray8, dtype, method = RawImage._normalize_to_8bit(img)
    assert method == "float-minmax"
    assert gray8.min() == 0 and gray8.max() == 255


def test_analysis_sample_downsamples_when_over_budget():
    raw = RawImage(np.zeros((2000, 2000), dtype=np.uint8), "uint8")
    sample, step = raw.analysis_sample(max_pixels=100_000)
    assert step > 1
    assert sample.size < raw.gray8.size


def test_analysis_sample_keeps_full_when_small():
    raw = RawImage(np.zeros((100, 100), dtype=np.uint8), "uint8")
    sample, step = raw.analysis_sample()
    assert step == 1
    assert sample.shape == (100, 100)
