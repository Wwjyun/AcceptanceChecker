# -*- coding: utf-8 -*-
"""指標計算：把一張 RawImage 轉成 Metrics。"""

from __future__ import annotations

import os
from typing import List, Tuple

import cv2
import numpy as np

from .detector import DefectDetector, DefectResult
from .image import RawImage
from .metrics import Metrics


class ImageAnalyzer:
    """計算單張影像的所有驗收指標（不做判定）。"""

    def __init__(self, zone_count: int = 5, detector: DefectDetector | None = None):
        self.zone_count = zone_count
        self.detector = detector or DefectDetector()

    def analyze(self, raw: RawImage, file_path: str) -> Tuple[Metrics, np.ndarray, DefectResult]:
        """回傳 (metrics, sample, defect_result)。"""
        sample, step = raw.analysis_sample()

        m = Metrics()
        m.file_name = os.path.basename(file_path)
        m.file_path = file_path
        m.width_px = raw.width
        m.height_px = raw.height
        m.dtype = raw.original_dtype
        m.analysis_step = int(step)

        self._fill_gray_stats(m, sample)
        self._fill_zone_uniformity(m, sample)

        defect = self.detector.detect(sample)
        m.auto_defect_cnr_est = defect.best_cnr
        m.auto_defect_contrast_est = defect.best_contrast
        m.auto_defect_area_px_sampled = defect.best_area_px
        m.auto_defect_count = defect.candidate_count
        m.robust_noise_sigma = defect.robust_noise_sigma

        vs, hs = self._stripe_scores(sample)
        m.vertical_stripe_score = vs
        m.horizontal_stripe_score = hs

        lap = cv2.Laplacian(sample, cv2.CV_64F)
        m.sharpness_laplacian_var = float(lap.var())

        return m, sample, defect

    def _fill_gray_stats(self, m: Metrics, sample: np.ndarray) -> None:
        arr = sample.astype(np.float32)
        m.mean_gray = float(np.mean(arr))
        m.std_gray = float(np.std(arr))
        m.min_gray = float(np.min(arr))
        m.max_gray = float(np.max(arr))
        m.p01_gray = float(np.percentile(arr, 1))
        m.p99_gray = float(np.percentile(arr, 99))
        m.hist_spread_p99_p01 = float(m.p99_gray - m.p01_gray)

        total = arr.size
        m.low_clip_pct = float(np.sum(arr <= 0) / total * 100.0)
        m.high_clip_pct = float(np.sum(arr >= 255) / total * 100.0)

        # 背景 std proxy：材料本身紋理重時 std 會偏大，這正是誤判風險
        m.bg_std_est = float(np.std(arr))

    def _fill_zone_uniformity(self, m: Metrics, sample: np.ndarray) -> None:
        zones, ratio = self._zone_means(sample)
        while len(zones) < 5:
            zones.append(0.0)
        (
            m.zone_1_left_mean,
            m.zone_2_left_mid_mean,
            m.zone_3_center_mean,
            m.zone_4_right_mid_mean,
            m.zone_5_right_mean,
        ) = [float(x) for x in zones[:5]]
        m.uniformity_ratio = float(ratio)

    def _zone_means(self, sample: np.ndarray) -> Tuple[List[float], float]:
        h, w = sample.shape[:2]
        means: List[float] = []
        for i in range(self.zone_count):
            x1 = int(round(i * w / self.zone_count))
            x2 = int(round((i + 1) * w / self.zone_count))
            roi = sample[:, x1:x2]
            means.append(float(np.mean(roi)) if roi.size else 0.0)
        mn = min(means) if means else 0.0
        mx = max(means) if means else 0.0
        ratio = mn / mx if mx > 1e-6 else 0.0
        return means, ratio

    def _stripe_scores(self, sample: np.ndarray) -> Tuple[float, float]:
        """條紋 proxy。

        vertical_stripe_score  : column mean 的 std / 全圖 std
        horizontal_stripe_score: row mean 的 std / 全圖 std

        數值越高，代表固定方向亮度變化越強（FPN / 條紋 / 照明不均）。
        """
        img = sample.astype(np.float32)
        global_std = float(np.std(img))
        if global_std < 1e-6:
            return 0.0, 0.0
        col_mean = np.mean(img, axis=0)
        row_mean = np.mean(img, axis=1)
        vertical = float(np.std(col_mean) / global_std)
        horizontal = float(np.std(row_mean) / global_std)
        return vertical, horizontal
