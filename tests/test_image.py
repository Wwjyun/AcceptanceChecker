# -*- coding: utf-8 -*-
"""RawImage 正規化與取樣的單元測試。"""

from __future__ import annotations

import numpy as np
import pytest

from acceptance_checker import MeasurementPlaneError, RawImage


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


@pytest.mark.parametrize("bit_depth", [8, 10, 12, 14, 16])
def test_percent_fs_uses_declared_original_bit_depth(bit_depth):
    dtype = np.uint8 if bit_depth == 8 else np.uint16
    full_scale = (1 << bit_depth) - 1
    img = np.full((4, 5), full_scale // 2, dtype=dtype)

    raw = RawImage.from_array(img, bit_depth=bit_depth)

    assert raw.bit_depth == bit_depth
    assert raw.full_scale == full_scale
    assert raw.raw_gray.dtype == dtype
    assert float(raw.percent_of_full_scale()[0, 0]) == pytest.approx(
        (full_scale // 2) / full_scale * 100.0
    )
    assert raw.threshold_at_percent_fs(98) == pytest.approx(full_scale * 0.98)


def test_percentile_preview_never_replaces_raw_measurement_plane():
    img = np.arange(400, dtype=np.uint16).reshape(20, 20) + 1000

    raw = RawImage.from_array(img, normalization="percentile", bit_depth=12)

    assert raw.preview_is_transformed
    assert np.array_equal(raw.raw_gray, img)
    assert raw.gray8.dtype == np.uint8
    assert raw.full_scale == 4095


def test_float_preview_has_no_formal_full_scale():
    raw = RawImage.from_array(np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32))

    assert raw.bit_depth is None
    assert raw.full_scale is None
    with pytest.raises(MeasurementPlaneError, match="%FS"):
        raw.percent_of_full_scale()


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_non_finite_image_is_rejected(bad_value):
    img = np.zeros((3, 3), dtype=np.float32)
    img[1, 1] = bad_value

    with pytest.raises(ValueError, match="NaN 或 Inf"):
        RawImage.from_array(img)


def test_declared_bit_depth_validates_container_values():
    img = np.array([[0, 1024]], dtype=np.uint16)

    with pytest.raises(ValueError, match="超過宣告"):
        RawImage.from_array(img, bit_depth=10)


def test_measurement_sample_preserves_raw_dtype_and_box_mapping():
    img = np.zeros((2000, 3000), dtype=np.uint16)
    raw = RawImage.from_array(img, bit_depth=12)

    sample, step = raw.measurement_sample(max_pixels=100_000)
    mapped = raw.sample_box_to_original((2, 3, 10, 20), step)

    assert sample.dtype == np.uint16
    assert step > 1
    assert mapped == (2 * step, 3 * step, 10 * step, 20 * step)


def test_uint16_color_to_gray_preserves_measurement_dtype():
    img = np.zeros((4, 5, 3), dtype=np.uint16)
    img[:, :, 1] = 2048

    raw = RawImage.from_array(img, bit_depth=12)

    assert raw.raw_gray.dtype == np.uint16
    assert raw.raw_gray.shape == (4, 5)
