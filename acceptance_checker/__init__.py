# -*- coding: utf-8 -*-
"""
AOI Raw Image 光學驗收檢查工具 (OOP 版)

套件依功能分為子資料夾：
- core      : 領域邏輯（門檻、指標、影像、分析、偵測、判定、流程）
- reporting : 文字報告與 CSV 匯出
- gui       : PySide6 桌面介面
- cli       : 命令列批次工具
"""

__version__ = "0.1.0"

from .core import (
    AcceptanceJudge,
    AcceptanceManifest,
    AcceptancePipeline,
    AcceptanceSession,
    AnalysisResult,
    DefectDetector,
    DefectResult,
    ImageAnalyzer,
    ImageLevel,
    LegacyMetricsAdapter,
    MeasurementResult,
    MetricGroup,
    Metrics,
    MetricSpecification,
    OpticalMode,
    OverallResult,
    RawImage,
    Severity,
    SpecificationError,
    Thresholds,
    V4Specification,
    legacy_metrics_to_measurements,
    load_default_v4_spec,
    load_v4_spec,
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
    "AcceptanceManifest",
    "AcceptanceSession",
    "ImageLevel",
    "LegacyMetricsAdapter",
    "MetricSpecification",
    "MeasurementResult",
    "MetricGroup",
    "OpticalMode",
    "OverallResult",
    "Severity",
    "SpecificationError",
    "V4Specification",
    "legacy_metrics_to_measurements",
    "load_default_v4_spec",
    "load_v4_spec",
    "ReportBuilder",
    "CsvExporter",
    "AcceptancePipeline",
    "AnalysisResult",
]
