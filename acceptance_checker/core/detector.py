# -*- coding: utf-8 -*-
"""疑似缺陷偵測與 CNR 估算。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class DefectResult:
    """自動缺陷估算的結果。"""

    best_cnr: float = 0.0
    best_contrast: float = 0.0
    best_area_px: int = 0
    candidate_count: int = 0
    overlay: Optional[np.ndarray] = None
    robust_noise_sigma: float = 0.0


class DefectDetector:
    """自動估算疑似缺陷 CNR。

    方法：
    1. 用大 Gaussian blur 估背景
    2. residual = 原圖 - 背景
    3. 用 MAD 估 noise sigma
    4. 找 residual 明顯異常的 connected components
    5. 取前幾個區域，估缺陷 mean vs 周邊背景 mean

    注意：這不是最終檢測演算法，只是 raw image 是否有可分離訊號的 proxy。
    """

    def __init__(self, max_candidates_drawn: int = 10):
        self.max_candidates_drawn = max_candidates_drawn

    @staticmethod
    def _safe_odd_kernel(base: int, min_k: int = 31, max_k: int = 201) -> int:
        k = max(min_k, min(max_k, int(base)))
        if k % 2 == 0:
            k += 1
        return k

    def _background(self, img: np.ndarray) -> np.ndarray:
        """以與影像尺寸相關的核大小估背景。"""
        h, w = img.shape[:2]
        k = self._safe_odd_kernel(min(h, w) // 40, min_k=31, max_k=151)
        return cv2.GaussianBlur(img, (k, k), 0)

    def robust_noise_sigma(self, sample: np.ndarray) -> float:
        """用 residual 的 MAD 估 robust noise sigma。"""
        img = sample.astype(np.float32)
        residual = img - self._background(img)
        med = float(np.median(residual))
        mad = float(np.median(np.abs(residual - med)))
        return float(max(1.4826 * mad, 1e-6))

    def detect(self, sample: np.ndarray) -> DefectResult:
        if sample.size == 0:
            return DefectResult()

        img = sample.astype(np.float32)
        h, w = img.shape[:2]

        bg = self._background(img)
        residual = img - bg

        med = float(np.median(residual))
        mad = float(np.median(np.abs(residual - med)))
        sigma = max(1.4826 * mad, 1e-6)

        # 門檻不要太低，避免材料紋理全部被當缺陷
        thr = max(8.0, 3.0 * sigma)
        mask = (np.abs(residual - med) > thr).astype(np.uint8) * 255

        # 去掉孤立雜點
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        candidates = self._collect_candidates(img, mask, h, w)
        candidates.sort(key=lambda c: c[0], reverse=True)

        overlay = self._draw_overlay(sample, candidates)

        result = DefectResult(
            overlay=overlay,
            candidate_count=len(candidates),
            robust_noise_sigma=float(max(1.4826 * mad, 1e-6)),
        )
        if candidates:
            best_cnr, best_contrast, best_area, _ = candidates[0]
            result.best_cnr = float(best_cnr)
            result.best_contrast = float(best_contrast)
            result.best_area_px = int(best_area)
        return result

    def _collect_candidates(
        self, img: np.ndarray, mask: np.ndarray, h: int, w: int
    ) -> List[Tuple[float, float, int, Tuple[int, int, int, int]]]:
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

        candidates: List[Tuple[float, float, int, Tuple[int, int, int, int]]] = []
        min_area = max(5, int(0.000001 * h * w))
        max_area = int(0.05 * h * w)

        for label in range(1, num_labels):
            x, y, ww, hh, area = stats[label]
            if area < min_area or area > max_area:
                continue
            # 排除太靠邊的大塊影像不均
            if x <= 1 or y <= 1 or x + ww >= w - 1 or y + hh >= h - 1:
                continue

            comp_mask = labels[y:y + hh, x:x + ww] == label
            comp_vals = img[y:y + hh, x:x + ww][comp_mask]
            if comp_vals.size == 0:
                continue

            # 外擴背景 ring
            pad = int(max(8, min(50, max(ww, hh) * 1.5)))
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + ww + pad)
            y2 = min(h, y + hh + pad)

            local = img[y1:y2, x1:x2]
            local_labels = labels[y1:y2, x1:x2]
            bg_vals = local[local_labels != label]
            if bg_vals.size < 20:
                bg_vals = img.reshape(-1)

            defect_mean = float(np.mean(comp_vals))
            bg_mean = float(np.mean(bg_vals))
            bg_std = float(np.std(bg_vals))
            contrast = abs(defect_mean - bg_mean)
            cnr = contrast / max(bg_std, 1e-6)

            candidates.append((cnr, contrast, int(area), (x, y, ww, hh)))

        return candidates

    def _draw_overlay(self, sample: np.ndarray, candidates) -> np.ndarray:
        overlay = cv2.cvtColor(sample, cv2.COLOR_GRAY2BGR)
        for cnr, _contrast, _area, box in candidates[: self.max_candidates_drawn]:
            x, y, ww, hh = box
            cv2.rectangle(overlay, (x, y), (x + ww, y + hh), (0, 0, 255), 2)
            cv2.putText(
                overlay,
                f"CNR {cnr:.1f}",
                (x, max(15, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )
        return overlay
