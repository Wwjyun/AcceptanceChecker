# -*- coding: utf-8 -*-
"""共用測試夾具與合成影像工具。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest


def make_uniform(value: int, shape=(400, 600)) -> np.ndarray:
    """回傳指定灰階的均勻影像。"""
    return np.full(shape, value, dtype=np.uint8)


def make_good_with_defect(shape=(600, 900)) -> np.ndarray:
    """亮度足夠、含一個清楚缺陷的影像。"""
    rng = np.random.default_rng(0)
    img = rng.normal(150, 3, shape).clip(0, 255).astype(np.uint8)
    cv2.circle(img, (shape[1] // 2, shape[0] // 2), 14, 90, -1)
    return img


@pytest.fixture
def good_image() -> np.ndarray:
    return make_good_with_defect()


@pytest.fixture
def black_image() -> np.ndarray:
    return np.zeros((400, 600), dtype=np.uint8)


@pytest.fixture
def saturated_image() -> np.ndarray:
    return np.full((400, 600), 255, dtype=np.uint8)
