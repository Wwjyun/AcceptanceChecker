# -*- coding: utf-8 -*-
"""核心領域邏輯：影像載入、指標計算、缺陷偵測、判定與流程串接。"""

from .analyzer import ImageAnalyzer
from .config import Thresholds
from .detector import DefectDetector, DefectResult, RoiCnrResult, roi_cnr
from .image import MeasurementPlaneError, RawImage
from .judge import AcceptanceJudge
from .legacy_adapter import LegacyMetricsAdapter, legacy_metrics_to_measurements
from .metrics import Metrics
from .pipeline import AcceptancePipeline, AnalysisResult
from .roi import (
    RoiCollection,
    RoiCreationMethod,
    RoiDefinition,
    RoiError,
    RoiType,
    RoiValidationIssue,
    ZoneMeasurement,
    apply_fixed_rois,
    extract_rois,
    measure_16_zones,
    measure_raw_16_zones,
)
from .specification import (
    MetricSpecification,
    SpecificationError,
    V4Specification,
    load_default_v4_spec,
    load_v4_spec,
)
from .v4_domain import (
    AcceptanceManifest,
    AcceptanceSession,
    ImageLevel,
    MeasurementResult,
    MetricGroup,
    OpticalMode,
    OverallResult,
    Severity,
)
from .v4_judge import (
    S0PriorityEvent,
    S0PriorityEventType,
    V4AcceptanceJudge,
    V4Decision,
)

__all__ = [
    "ImageAnalyzer",
    "Thresholds",
    "DefectDetector",
    "DefectResult",
    "RoiCnrResult",
    "roi_cnr",
    "RawImage",
    "MeasurementPlaneError",
    "AcceptanceJudge",
    "LegacyMetricsAdapter",
    "legacy_metrics_to_measurements",
    "Metrics",
    "AcceptancePipeline",
    "AnalysisResult",
    "RoiCollection",
    "RoiCreationMethod",
    "RoiDefinition",
    "RoiError",
    "RoiType",
    "RoiValidationIssue",
    "ZoneMeasurement",
    "apply_fixed_rois",
    "extract_rois",
    "measure_16_zones",
    "measure_raw_16_zones",
    "MetricSpecification",
    "SpecificationError",
    "V4Specification",
    "load_default_v4_spec",
    "load_v4_spec",
    "AcceptanceManifest",
    "AcceptanceSession",
    "ImageLevel",
    "MeasurementResult",
    "MetricGroup",
    "OpticalMode",
    "OverallResult",
    "Severity",
    "S0PriorityEvent",
    "S0PriorityEventType",
    "V4AcceptanceJudge",
    "V4Decision",
]
