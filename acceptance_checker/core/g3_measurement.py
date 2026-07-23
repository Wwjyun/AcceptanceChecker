# -*- coding: utf-8 -*-
"""v4 G3 感測器雜訊、FPN、Golden 與壞點量測。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from .roi import RoiDefinition, RoiError
from .specification import V4Specification, load_default_v4_spec
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, Severity


class G3MeasurementError(ValueError):
    """G3 證據層級、樣本數或方法資訊不足。"""


@dataclass(frozen=True)
class SensorFrameSeries:
    frames: np.ndarray
    condition: str
    full_scale: int
    evidence_sources: Sequence[str]
    method_version: str
    image_level: ImageLevel = ImageLevel.L0

    def __post_init__(self) -> None:
        if self.frames.ndim != 3 or self.frames.shape[0] == 0:
            raise G3MeasurementError("SensorFrameSeries 必須是非空 (N,H,W)")
        if self.condition not in {"dark", "uniform"}:
            raise G3MeasurementError("condition 必須是 dark 或 uniform")
        if self.image_level != ImageLevel.L0:
            raise G3MeasurementError("DSNU/PRNU/FPN 只能使用 L0")
        if self.full_scale <= 0:
            raise G3MeasurementError("full_scale 必須為正數")
        if len(self.evidence_sources) != self.frames.shape[0]:
            raise G3MeasurementError("每張 sensor frame 都必須有 evidence source")
        if not self.method_version:
            raise G3MeasurementError("sensor series 必須記錄 method_version")
        if not np.all(np.isfinite(self.frames)):
            raise G3MeasurementError("sensor frames 包含 NaN 或 Inf")


@dataclass
class G3MeasurementInputs:
    temporal_snr: Optional[MeasurementResult] = None
    dark_series: Optional[SensorFrameSeries] = None
    uniform_series: Optional[SensorFrameSeries] = None
    sensor_roi: Optional[RoiDefinition] = None
    current_l1_image: Optional[np.ndarray] = None
    current_l1_evidence: str = ""
    golden_spatial_std: Optional[float] = None
    golden_evidence: str = ""
    golden_approved: bool = False
    baseline_bad_pixels: Set[Tuple[int, int]] = field(default_factory=set)
    current_bad_pixels: Set[Tuple[int, int]] = field(default_factory=set)
    fixed_mask_pixels: Set[Tuple[int, int]] = field(default_factory=set)
    effective_roi: Optional[RoiDefinition] = None
    golden_defect_rois: Sequence[RoiDefinition] = field(default_factory=list)
    bad_pixel_evidence_sources: Sequence[str] = field(default_factory=list)
    bad_pixel_method_version: str = ""


@dataclass
class G3MeasurementReport:
    measurements: List[MeasurementResult]
    warnings: List[str] = field(default_factory=list)


@dataclass
class _G3Value:
    value: Any
    severity: Optional[Severity]
    image_level: ImageLevel
    sample_count: int
    evidence_sources: List[str]
    roi_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class G3Measurer:
    """產生六項 G3，既有單張 proxy 不會流入本量測器。"""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()

    def measure(self, inputs: G3MeasurementInputs) -> G3MeasurementReport:
        results: List[MeasurementResult] = []
        for metric in self.specification.metrics:
            if metric.group != MetricGroup.G3:
                continue
            try:
                computed = self._compute(metric.metric_id, inputs)
                severity = computed.severity or metric.classify(float(computed.value))
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G3,
                        severity=severity,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=computed.image_level,
                        value=computed.value,
                        roi_id=computed.roi_id,
                        sample_count=computed.sample_count,
                        evidence_sources=list(dict.fromkeys(computed.evidence_sources)),
                        metadata={
                            "requirement_profile": metric.requirement_profile,
                            **computed.metadata,
                        },
                    )
                )
            except (G3MeasurementError, RoiError) as exc:
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G3,
                        severity=Severity.NOT_EVALUATED,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=self._level_for(metric.metric_id),
                        value=None,
                        sample_count=0,
                        missing_reason=str(exc),
                        metadata={"requirement_profile": metric.requirement_profile},
                    )
                )
        return G3MeasurementReport(measurements=results)

    def _compute(self, metric_id: str, inputs: G3MeasurementInputs) -> _G3Value:
        if metric_id == "g3.temporal_snr":
            return self._temporal(inputs)
        if metric_id == "g3.dsnu_pct_fs":
            return self._dsnu(inputs)
        if metric_id == "g3.prnu_pct":
            return self._prnu(inputs)
        if metric_id == "g3.vertical_fpn_pct_fs":
            return self._fpn(inputs)
        if metric_id == "g3.spatial_std_increase_vs_golden_pct":
            return self._golden_std(inputs)
        if metric_id == "g3.new_bad_hot_pixels":
            return self._bad_pixels(inputs)
        raise G3MeasurementError(f"未知 G3 metric：{metric_id}")

    @staticmethod
    def _temporal(inputs: G3MeasurementInputs) -> _G3Value:
        result = inputs.temporal_snr
        if result is None or result.metric_id != "g3.temporal_snr":
            raise G3MeasurementError("缺少 TemporalAcceptanceMeasurer 的時域 SNR 結果")
        if result.severity == Severity.NOT_EVALUATED:
            raise G3MeasurementError(f"時域 SNR 未評估：{result.missing_reason}")
        return _G3Value(
            value=result.value,
            severity=result.severity,
            image_level=result.image_level,
            sample_count=result.sample_count,
            evidence_sources=list(result.evidence_sources),
            roi_id=result.roi_id,
            metadata={"source_measurement": "TemporalAcceptanceMeasurer"},
        )

    @staticmethod
    def _stack(series: SensorFrameSeries, roi: RoiDefinition, minimum: int) -> np.ndarray:
        if series.frames.shape[0] < minimum:
            raise G3MeasurementError(
                f"{series.condition} series 至少需要 {minimum} 張，實得 {series.frames.shape[0]}"
            )
        height, width = series.frames.shape[1:]
        roi.validate_for_shape(width, height)
        return series.frames[:, roi.y : roi.y2, roi.x : roi.x2].astype(np.float64)

    @staticmethod
    def _require_series(
        series: Optional[SensorFrameSeries],
        condition: str,
    ) -> SensorFrameSeries:
        if series is None or series.condition != condition:
            raise G3MeasurementError(f"缺少 L0 {condition} series")
        return series

    @staticmethod
    def _require_sensor_roi(inputs: G3MeasurementInputs) -> RoiDefinition:
        if inputs.sensor_roi is None:
            raise G3MeasurementError("缺少 sensor ROI")
        return inputs.sensor_roi

    def _dsnu(self, inputs: G3MeasurementInputs) -> _G3Value:
        series = self._require_series(inputs.dark_series, "dark")
        roi = self._require_sensor_roi(inputs)
        stack = self._stack(series, roi, 30)
        mean_image = np.mean(stack, axis=0)
        value = float(np.std(mean_image, ddof=0) / series.full_scale * 100.0)
        return _G3Value(
            value=value,
            severity=None,
            image_level=ImageLevel.L0,
            sample_count=int(stack.size),
            evidence_sources=list(series.evidence_sources),
            roi_id=roi.roi_id,
            metadata={
                "frame_count": int(stack.shape[0]),
                "method_version": series.method_version,
                "calculation": "std(temporal_mean_dark_image)/FS",
            },
        )

    def _prnu(self, inputs: G3MeasurementInputs) -> _G3Value:
        uniform = self._require_series(inputs.uniform_series, "uniform")
        dark = self._require_series(inputs.dark_series, "dark")
        if uniform.full_scale != dark.full_scale:
            raise G3MeasurementError("uniform/dark full_scale 不一致")
        roi = self._require_sensor_roi(inputs)
        uniform_stack = self._stack(uniform, roi, 30)
        dark_stack = self._stack(dark, roi, 30)
        if uniform_stack.shape[1:] != dark_stack.shape[1:]:
            raise G3MeasurementError("uniform/dark ROI 尺寸不一致")
        response = np.mean(uniform_stack, axis=0) - np.mean(dark_stack, axis=0)
        response_mean = float(np.mean(response))
        if response_mean <= 0:
            raise G3MeasurementError("均勻照明響應扣除 dark 後 Mean 必須大於 0")
        spatial_variance = float(np.var(response, ddof=0))
        temporal_contribution = float(
            np.mean(np.var(uniform_stack, axis=0, ddof=1)) / uniform_stack.shape[0]
            + np.mean(np.var(dark_stack, axis=0, ddof=1)) / dark_stack.shape[0]
        )
        corrected_variance = max(spatial_variance - temporal_contribution, 0.0)
        value = math.sqrt(corrected_variance) / response_mean * 100.0
        return _G3Value(
            value=value,
            severity=None,
            image_level=ImageLevel.L0,
            sample_count=int(uniform_stack.size + dark_stack.size),
            evidence_sources=[
                *uniform.evidence_sources,
                *dark.evidence_sources,
            ],
            roi_id=roi.roi_id,
            metadata={
                "uniform_frame_count": int(uniform_stack.shape[0]),
                "dark_frame_count": int(dark_stack.shape[0]),
                "spatial_variance": spatial_variance,
                "temporal_variance_contribution": temporal_contribution,
                "corrected_spatial_variance": corrected_variance,
                "method_versions": [uniform.method_version, dark.method_version],
            },
        )

    def _fpn(self, inputs: G3MeasurementInputs) -> _G3Value:
        series = self._require_series(inputs.uniform_series, "uniform")
        roi = self._require_sensor_roi(inputs)
        stack = self._stack(series, roi, 100)
        mean_image = np.mean(stack, axis=0)
        column_means = np.mean(mean_image, axis=0)
        value = float(np.std(column_means, ddof=0) / series.full_scale * 100.0)
        return _G3Value(
            value=value,
            severity=None,
            image_level=ImageLevel.L0,
            sample_count=int(stack.size),
            evidence_sources=list(series.evidence_sources),
            roi_id=roi.roi_id,
            metadata={
                "frame_count": int(stack.shape[0]),
                "method_version": series.method_version,
                "calculation": "std(column_means(temporal_average))/FS",
            },
        )

    @staticmethod
    def _golden_std(inputs: G3MeasurementInputs) -> _G3Value:
        if not inputs.golden_approved or inputs.golden_spatial_std is None:
            raise G3MeasurementError("缺少書面核准 Golden spatial STD")
        if inputs.golden_spatial_std <= 0:
            raise G3MeasurementError("Golden spatial STD 必須大於 0")
        if inputs.current_l1_image is None or inputs.current_l1_image.ndim != 2:
            raise G3MeasurementError("缺少 current L1 image")
        if not inputs.current_l1_evidence or not inputs.golden_evidence:
            raise G3MeasurementError("current/Golden STD 缺少 evidence source")
        roi = G3Measurer._require_sensor_roi(inputs)
        height, width = inputs.current_l1_image.shape
        roi.validate_for_shape(width, height)
        values = inputs.current_l1_image[roi.y : roi.y2, roi.x : roi.x2]
        current_std = float(np.std(values.astype(np.float64), ddof=0))
        value = max(
            0.0,
            (current_std - inputs.golden_spatial_std)
            / inputs.golden_spatial_std
            * 100.0,
        )
        return _G3Value(
            value=value,
            severity=None,
            image_level=ImageLevel.L1,
            sample_count=int(values.size),
            evidence_sources=[inputs.current_l1_evidence, inputs.golden_evidence],
            roi_id=roi.roi_id,
            metadata={
                "current_spatial_std": current_std,
                "golden_spatial_std": inputs.golden_spatial_std,
                "golden_approved": True,
            },
        )

    @staticmethod
    def _bad_pixels(inputs: G3MeasurementInputs) -> _G3Value:
        if inputs.uniform_series is None or inputs.uniform_series.frames.shape[0] < 100:
            raise G3MeasurementError("壞點新增判定需要 L0 N≥100 series")
        if not inputs.bad_pixel_method_version or not inputs.bad_pixel_evidence_sources:
            raise G3MeasurementError("壞點判定缺少方法版本或 evidence")
        if inputs.effective_roi is None:
            raise G3MeasurementError("壞點判定缺少 effective inspection ROI")
        height, width = inputs.uniform_series.frames.shape[1:]
        inputs.effective_roi.validate_for_shape(width, height)
        for roi in inputs.golden_defect_rois:
            roi.validate_for_shape(width, height)
        new_pixels = sorted(inputs.current_bad_pixels - inputs.baseline_bad_pixels)
        for x, y in new_pixels:
            if not (0 <= x < width and 0 <= y < height):
                raise G3MeasurementError(f"壞點座標 {(x, y)} 超出 sensor frame")
        in_effective = [
            point for point in new_pixels if _point_in_roi(point, inputs.effective_roi)
        ]
        in_golden = [
            point
            for point in new_pixels
            if any(_point_in_roi(point, roi) for roi in inputs.golden_defect_rois)
        ]
        unmasked_effective = [
            point for point in in_effective if point not in inputs.fixed_mask_pixels
        ]
        if len(new_pixels) > 5 or in_golden:
            severity = Severity.S0
        elif not new_pixels:
            severity = Severity.S3
        elif not in_effective:
            severity = Severity.S2
        elif unmasked_effective:
            raise G3MeasurementError(
                "有效檢測區內新增壞點未全部建立固定遮罩座標"
            )
        else:
            severity = Severity.S1
        return _G3Value(
            value=len(new_pixels),
            severity=severity,
            image_level=ImageLevel.L0,
            sample_count=int(inputs.uniform_series.frames.shape[0]),
            evidence_sources=list(inputs.bad_pixel_evidence_sources),
            roi_id=inputs.effective_roi.roi_id,
            metadata={
                "new_bad_pixel_coordinates": [list(item) for item in new_pixels],
                "inside_effective_coordinates": [list(item) for item in in_effective],
                "inside_golden_coordinates": [list(item) for item in in_golden],
                "fixed_mask_coordinates": [
                    list(item) for item in sorted(inputs.fixed_mask_pixels)
                ],
                "method_version": inputs.bad_pixel_method_version,
            },
        )

    @staticmethod
    def _level_for(metric_id: str) -> ImageLevel:
        return ImageLevel.L1 if metric_id in {
            "g3.temporal_snr",
            "g3.spatial_std_increase_vs_golden_pct",
        } else ImageLevel.L0


def _point_in_roi(point: Tuple[int, int], roi: RoiDefinition) -> bool:
    x, y = point
    return roi.x <= x < roi.x2 and roi.y <= y < roi.y2
