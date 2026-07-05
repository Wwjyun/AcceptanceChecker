# -*- coding: utf-8 -*-
"""DefectDetector 與 roi_cnr 的單元測試。"""

from __future__ import annotations

import cv2
import numpy as np

from acceptance_checker.core.detector import DefectDetector, roi_cnr
from tests.conftest import make_uniform


def test_empty_sample_returns_default():
    result = DefectDetector().detect(np.zeros((0, 0), dtype=np.uint8))
    assert result.candidate_count == 0
    assert result.best_cnr == 0.0


def test_uniform_sample_has_no_candidates():
    result = DefectDetector().detect(make_uniform(150))
    assert result.candidate_count == 0


def test_single_defect_detected():
    img = make_uniform(150)
    cv2.circle(img, (300, 200), 12, 80, -1)
    result = DefectDetector().detect(img)
    assert result.candidate_count >= 1
    assert result.best_cnr > 0.0
    assert result.best_area_px > 0


def test_roi_cnr_on_defect_higher_than_flat():
    img = np.full((400, 600), 150, dtype=np.uint8)
    cv2.rectangle(img, (300, 200), (330, 230), 60, -1)
    # 讓背景有一點雜訊，避免 std=0
    noise = np.random.default_rng(1).integers(-2, 3, img.shape)
    img = (img.astype(np.int16) + noise).clip(0, 255).astype(np.uint8)

    on_defect = roi_cnr(img, (300, 200, 30, 30))
    on_flat = roi_cnr(img, (50, 50, 30, 30))
    assert on_defect.cnr > on_flat.cnr
    assert on_defect.defect_area_px == 900


def test_roi_cnr_out_of_bounds_is_empty():
    img = make_uniform(150)
    r = roi_cnr(img, (10_000, 10_000, 20, 20))
    assert r.defect_area_px == 0
    assert r.cnr == 0.0


def test_roi_cnr_clamps_to_image():
    img = make_uniform(150)
    r = roi_cnr(img, (-50, -50, 100, 100))
    # 夾回後仍有有效區域
    assert r.defect_area_px == 50 * 50


def test_robust_noise_sigma_positive():
    img = make_uniform(150)
    sigma = DefectDetector().robust_noise_sigma(img)
    assert sigma > 0.0
