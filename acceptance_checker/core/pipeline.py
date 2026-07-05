# -*- coding: utf-8 -*-
"""串接載入 -> 分析 -> 判定 的流程，供 GUI 或批次腳本共用。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
    ):
        self.thresholds = thresholds or Thresholds()
        self.analyzer = analyzer or ImageAnalyzer()
        self.judge = judge or AcceptanceJudge(self.thresholds)

    def run(self, file_path: str) -> AnalysisResult:
        raw = RawImage.load(file_path)
        metrics, sample, defect = self.analyzer.analyze(raw, file_path)
        self.judge.judge(metrics)
        overlay = self._resolve_overlay(defect, sample)
        return AnalysisResult(
            metrics=metrics,
            gray8=raw.gray8,
            sample=sample,
            overlay=overlay,
        )

    @staticmethod
    def _resolve_overlay(defect: DefectResult, sample: np.ndarray) -> np.ndarray:
        if defect.overlay is not None:
            return defect.overlay
        return cv2.cvtColor(sample, cv2.COLOR_GRAY2BGR)
