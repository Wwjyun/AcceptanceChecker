# -*- coding: utf-8 -*-
"""串接載入 -> 分析 -> 判定 的流程，供 GUI 或批次腳本共用。"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from .analyzer import ImageAnalyzer
from .config import Thresholds
from .detector import DefectResult
from .image import RawImage
from .judge import AcceptanceJudge
from .metrics import Metrics


@dataclass
class AnalysisResult:
    """一次完整分析的產物。"""

    metrics: Metrics
    gray8: np.ndarray
    sample: np.ndarray
    overlay: np.ndarray


class AcceptancePipeline:
    """一次呼叫完成：讀圖、算指標、判定，回傳 AnalysisResult。"""

    def __init__(
        self,
        thresholds: Optional[Thresholds] = None,
        analyzer: Optional[ImageAnalyzer] = None,
        judge: Optional[AcceptanceJudge] = None,
        max_pixels: int = 8_000_000,
        cache_size: int = 8,
        normalization: str = "linear",
        percentiles: Tuple[float, float] = (1.0, 99.0),
        bit_depth: Optional[int] = None,
    ):
        self.thresholds = thresholds or Thresholds()
        self.analyzer = analyzer or ImageAnalyzer(max_pixels=max_pixels)
        self.judge = judge or AcceptanceJudge(self.thresholds)
        self.normalization = normalization
        self.percentiles = percentiles
        self.bit_depth = bit_depth
        # 依 (絕對路徑, mtime_ns, 大小) 快取分析結果，避免重複開同一張圖時重算。
        self._cache_size = cache_size
        self._cache: "OrderedDict[Tuple[str, int, int], AnalysisResult]" = OrderedDict()

    def set_thresholds(self, thresholds: Thresholds) -> None:
        """更新門檻並同步到判定器（後續 run / 重判即生效）。

        門檻變動不影響已算的指標，但會影響判定，故清空快取以免回傳舊判定。
        """
        self.thresholds = thresholds
        self.judge.thresholds = thresholds
        self._cache.clear()

    def run(self, file_path: str) -> AnalysisResult:
        key = self._cache_key(file_path)
        if key is not None and key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        raw = RawImage.load(
            file_path,
            self.normalization,
            self.percentiles,
            bit_depth=self.bit_depth,
        )
        metrics, sample, defect = self.analyzer.analyze(raw, file_path)
        self.judge.judge(metrics)
        overlay = self._resolve_overlay(defect, sample)
        result = AnalysisResult(
            metrics=metrics,
            gray8=raw.gray8,
            sample=sample,
            overlay=overlay,
        )
        if key is not None and self._cache_size > 0:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    @staticmethod
    def _cache_key(file_path: str) -> Optional[Tuple[str, int, int]]:
        """以檔案的絕對路徑 + 修改時間 + 大小當快取鍵；取不到 stat 則不快取。"""
        try:
            st = os.stat(file_path)
        except OSError:
            return None
        return (os.path.abspath(file_path), st.st_mtime_ns, st.st_size)

    @staticmethod
    def _resolve_overlay(defect: DefectResult, sample: np.ndarray) -> np.ndarray:
        if defect.overlay is not None:
            return defect.overlay
        return cv2.cvtColor(sample, cv2.COLOR_GRAY2BGR)
