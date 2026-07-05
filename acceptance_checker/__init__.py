# -*- coding: utf-8 -*-
"""
AOI Raw Image 光學驗收檢查工具 (OOP 版)

套件依功能分為子資料夾：
- core      : 領域邏輯（門檻、指標、影像、分析、偵測、判定、流程）
- reporting : 文字報告與 CSV 匯出
- gui       : PySide6 桌面介面
- cli       : 命令列批次工具
"""

from .core import (
    AcceptanceJudge,
    AcceptancePipeline,
    AnalysisResult,
    DefectDetector,
    DefectResult,
    ImageAnalyzer,
    Metrics,
    RawImage,
    Thresholds,
)
from .reporting import CsvExporter, ReportBuilder

__all__ = [
    "Thresholds",
    "Metrics",
    "RawImage",
    "ImageAnalyzer",
    "DefectDetector",
    "DefectResult",
    "AcceptanceJudge",
    "ReportBuilder",
    "CsvExporter",
    "AcceptancePipeline",
    "AnalysisResult",
]
