# -*- coding: utf-8 -*-
"""v4 G2 解析力、掃描幾何與 encoder 客觀量測。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np

from .roi import RoiDefinition, RoiError
from .specification import V4Specification, load_default_v4_spec
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, Severity


class G2MeasurementError(ValueError):
    """G2 標靶、方法版本或樣本品質不足。"""


@dataclass(frozen=True)
class SlantedEdgeEvidence:
    image: np.ndarray
    roi: RoiDefinition
    measured_direction: str
    edge_orientation: str
    full_scale: int
    evidence_source: str
    method_version: str
    target_id: str

    def __post_init__(self) -> None:
        if self.measured_direction not in {"scan", "sensor"}:
            raise G2MeasurementError("measured_direction 必須是 scan 或 sensor")
        if self.edge_orientation not in {"vertical", "horizontal"}:
            raise G2MeasurementError("edge_orientation 必須是 vertical 或 horizontal")
        if self.image.ndim != 2:
            raise G2MeasurementError("slanted-edge image 必須是二維灰階")
        if self.full_scale <= 0:
            raise G2MeasurementError("full_scale 必須為正數")
        if not self.evidence_source or not self.method_version or not self.target_id:
            raise G2MeasurementError("slanted-edge 證據、方法版本與 target_id 不得為空")


@dataclass(frozen=True)
class ScaleEvidence:
    region: str
    measured_units_per_pixel: float
    nominal_units_per_pixel: float
    evidence_source: str
    method_version: str

    def __post_init__(self) -> None:
        if self.measured_units_per_pixel <= 0 or self.nominal_units_per_pixel <= 0:
            raise G2MeasurementError("scale 必須為正數")
        if not self.region or not self.evidence_source or not self.method_version:
            raise G2MeasurementError("scale region、證據與方法版本不得為空")


@dataclass
class G2MeasurementInputs:
    slanted_edges: Sequence[SlantedEdgeEvidence]
    defect_image: Optional[np.ndarray] = None
    defect_mask: Optional[np.ndarray] = None
    defect_full_scale: int = 0
    defect_evidence_source: str = ""
    defect_method_version: str = ""
    scale_scan: Optional[float] = None
    scale_sensor: Optional[float] = None
    scale_evidence: Sequence[ScaleEvidence] = field(default_factory=list)
    encoder_positions_px: Sequence[float] = field(default_factory=list)
    encoder_evidence_sources: Sequence[str] = field(default_factory=list)
    encoder_method_version: str = ""
    requires_stitch_region: bool = False
    image_level: ImageLevel = ImageLevel.L1


@dataclass
class G2MeasurementReport:
    measurements: List[MeasurementResult]
    warnings: List[str] = field(default_factory=list)


@dataclass
class _G2Value:
    value: float
    sample_count: int
    evidence_sources: List[str]
    roi_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    forced_severity: Optional[Severity] = None


class G2Measurer:
    """依 v4 規格產生七項 G2 結果。"""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()

    def measure(self, inputs: G2MeasurementInputs) -> G2MeasurementReport:
        metrics = [
            item for item in self.specification.metrics if item.group == MetricGroup.G2
        ]
        results: List[MeasurementResult] = []
        edge_results: Dict[str, Dict[str, Any]] = {}
        edge_errors: Dict[str, str] = {}
        if inputs.image_level == ImageLevel.L1:
            for edge in inputs.slanted_edges:
                if edge.measured_direction in edge_results:
                    continue
                try:
                    edge_results[edge.measured_direction] = _measure_slanted_edge(edge)
                except (G2MeasurementError, RoiError) as exc:
                    edge_errors[edge.measured_direction] = str(exc)
        for metric in metrics:
            if inputs.image_level != ImageLevel.L1:
                results.append(self._missing(metric, inputs, "G2 正式量測必須使用固定 L1 影像"))
                continue
            try:
                value = self._compute(
                    metric.metric_id, inputs, edge_results, edge_errors
                )
                severity = value.forced_severity or metric.classify(value.value)
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G2,
                        severity=severity,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=inputs.image_level,
                        value=value.value,
                        roi_id=value.roi_id,
                        sample_count=value.sample_count,
                        evidence_sources=list(dict.fromkeys(value.evidence_sources)),
                        metadata={
                            "requirement_profile": metric.requirement_profile,
                            **value.metadata,
                        },
                    )
                )
            except (G2MeasurementError, RoiError) as exc:
                results.append(self._missing(metric, inputs, str(exc)))
        return G2MeasurementReport(measurements=results)

    def _compute(
        self,
        metric_id: str,
        inputs: G2MeasurementInputs,
        edges: Dict[str, Dict[str, Any]],
        edge_errors: Dict[str, str],
    ) -> _G2Value:
        if metric_id == "g2.mtf_nyquist_half":
            self._require_edges(edges, edge_errors)
            values = [edges[key]["mtf_nyquist_half"] for key in ("scan", "sensor")]
            return self._edge_value(min(values), inputs, edges)
        if metric_id == "g2.mtf_direction_asymmetry_pct":
            self._require_edges(edges, edge_errors)
            scan = edges["scan"]["mtf_nyquist_half"]
            sensor = edges["sensor"]["mtf_nyquist_half"]
            value = abs(scan - sensor) / max(scan, sensor) * 100.0
            return self._edge_value(value, inputs, edges)
        if metric_id == "g2.motion_blur_px":
            self._require_edges(edges, edge_errors)
            return self._edge_value(edges["scan"]["rise_10_90_px"], inputs, edges)
        if metric_id == "g2.minimum_defect_width_px":
            return self._defect_width(inputs)
        if metric_id == "g2.resolution_asymmetry_pct":
            if inputs.scale_scan is None or inputs.scale_sensor is None:
                raise G2MeasurementError("缺少 scan/sensor 兩方向解析度 scale")
            if inputs.scale_scan <= 0 or inputs.scale_sensor <= 0:
                raise G2MeasurementError("解析度 scale 必須為正數")
            if len(inputs.scale_evidence) < 2:
                raise G2MeasurementError("解析度不對稱缺少可追溯 scale evidence")
            scale_versions = {item.method_version for item in inputs.scale_evidence}
            if len(scale_versions) != 1:
                raise G2MeasurementError("解析度 scale method_version 必須一致")
            value = (
                abs(inputs.scale_scan - inputs.scale_sensor)
                / ((inputs.scale_scan + inputs.scale_sensor) / 2.0)
                * 100.0
            )
            return _G2Value(
                value=value,
                sample_count=2,
                evidence_sources=[item.evidence_source for item in inputs.scale_evidence],
                metadata={
                    "scale_scan": inputs.scale_scan,
                    "scale_sensor": inputs.scale_sensor,
                    "method_version": next(iter(scale_versions)),
                },
            )
        if metric_id == "g2.encoder_sync_position_error_p95_px":
            return self._encoder(inputs)
        if metric_id == "g2.fov_scale_error_pct":
            return self._fov_scale(inputs)
        raise G2MeasurementError(f"未知 G2 metric：{metric_id}")

    @staticmethod
    def _require_edges(
        edges: Dict[str, Dict[str, Any]],
        edge_errors: Dict[str, str],
    ) -> None:
        missing = [key for key in ("scan", "sensor") if key not in edges]
        if missing:
            details = "; ".join(
                f"{key}: {edge_errors.get(key, '缺少證據')}" for key in missing
            )
            raise G2MeasurementError(f"slanted-edge 品質不合格：{details}")

    @staticmethod
    def _edge_value(
        value: float,
        inputs: G2MeasurementInputs,
        edges: Dict[str, Dict[str, Any]],
    ) -> _G2Value:
        sources = [item.evidence_source for item in inputs.slanted_edges]
        versions = sorted({item.method_version for item in inputs.slanted_edges})
        if len(versions) != 1:
            raise G2MeasurementError("兩方向 slanted-edge method_version 必須一致")
        return _G2Value(
            value=value,
            sample_count=2,
            evidence_sources=sources,
            roi_id=",".join(item.roi.roi_id for item in inputs.slanted_edges),
            metadata={"directions": edges, "method_version": versions[0]},
        )

    @staticmethod
    def _defect_width(inputs: G2MeasurementInputs) -> _G2Value:
        if inputs.defect_image is None or inputs.defect_mask is None:
            raise G2MeasurementError("缺少最小目標缺陷 image/mask")
        if (
            inputs.defect_image.ndim != 2
            or inputs.defect_mask.shape != inputs.defect_image.shape
        ):
            raise G2MeasurementError("缺陷 image/mask 必須是相同尺寸二維陣列")
        if inputs.defect_full_scale <= 0:
            raise G2MeasurementError("缺陷量測缺少 full_scale")
        if not inputs.defect_evidence_source or not inputs.defect_method_version:
            raise G2MeasurementError("缺陷量測缺少 evidence 或 method_version")
        mask = (inputs.defect_mask > 0).astype(np.uint8)
        count, labels = cv2.connectedComponents(mask, connectivity=8)
        if count <= 1:
            raise G2MeasurementError("缺陷 mask 無可辨識連通區")
        widths: List[float] = []
        clarity_values: List[float] = []
        image: np.ndarray = inputs.defect_image.astype(np.float64)
        gradient_x = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=3)
        gradient = np.hypot(gradient_x, gradient_y) / 4.0
        for label in range(1, count):
            component = (labels == label).astype(np.uint8)
            distance = cv2.distanceTransform(component, cv2.DIST_L2, 5)
            widths.append(float(2.0 * np.max(distance)))
            boundary = cv2.morphologyEx(
                component, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)
            ).astype(bool)
            boundary_gradient = gradient[boundary]
            if boundary_gradient.size:
                clarity_values.append(
                    float(np.percentile(boundary_gradient, 10))
                    / inputs.defect_full_scale
                    * 100.0
                )
        if not widths or not clarity_values:
            raise G2MeasurementError("缺陷輪廓無法量測")
        width = min(widths)
        clarity = min(clarity_values)
        clear = clarity >= 5.0
        return _G2Value(
            value=width,
            sample_count=int(np.count_nonzero(mask)),
            evidence_sources=[inputs.defect_evidence_source],
            metadata={
                "component_widths_px": widths,
                "boundary_gradient_p10_pct_fs_per_px": clarity,
                "contour_clear": clear,
                "contour_clear_threshold_pct_fs_per_px": 5.0,
                "method_version": inputs.defect_method_version,
            },
            forced_severity=Severity.S0 if not clear else None,
        )

    @staticmethod
    def _encoder(inputs: G2MeasurementInputs) -> _G2Value:
        values = np.asarray(inputs.encoder_positions_px, dtype=np.float64)
        if values.size < 100:
            raise G2MeasurementError(
                f"encoder 同步至少需要 100 次，實得 {values.size}"
            )
        if len(inputs.encoder_evidence_sources) != values.size:
            raise G2MeasurementError("每次 encoder 位置都必須有 evidence source")
        if not inputs.encoder_method_version:
            raise G2MeasurementError("encoder 缺少 method_version")
        if not np.all(np.isfinite(values)):
            raise G2MeasurementError("encoder positions 包含 NaN 或 Inf")
        median = float(np.median(values))
        errors = np.abs(values - median)
        return _G2Value(
            value=float(np.percentile(errors, 95)),
            sample_count=int(values.size),
            evidence_sources=list(inputs.encoder_evidence_sources),
            metadata={
                "position_median_px": median,
                "method_version": inputs.encoder_method_version,
            },
        )

    @staticmethod
    def _fov_scale(inputs: G2MeasurementInputs) -> _G2Value:
        required = {"left", "center", "right"}
        if inputs.requires_stitch_region:
            required.add("stitch")
        available = {item.region for item in inputs.scale_evidence}
        if len(available) != len(inputs.scale_evidence):
            raise G2MeasurementError("視野 scale region 不得重複")
        missing = sorted(required - available)
        if missing:
            raise G2MeasurementError(f"視野 scale 缺少區域：{', '.join(missing)}")
        versions = {item.method_version for item in inputs.scale_evidence}
        if len(versions) != 1:
            raise G2MeasurementError("各區 scale method_version 必須一致")
        errors = {
            item.region: abs(
                item.measured_units_per_pixel - item.nominal_units_per_pixel
            )
            / item.nominal_units_per_pixel
            * 100.0
            for item in inputs.scale_evidence
        }
        return _G2Value(
            value=max(errors.values()),
            sample_count=len(errors),
            evidence_sources=[item.evidence_source for item in inputs.scale_evidence],
            metadata={
                "per_region_error_pct": errors,
                "method_version": next(iter(versions)),
            },
        )

    def _missing(self, metric, inputs: G2MeasurementInputs, reason: str) -> MeasurementResult:
        return MeasurementResult(
            metric_id=metric.metric_id,
            group=MetricGroup.G2,
            severity=Severity.NOT_EVALUATED,
            unit=metric.unit,
            formula_version=self.specification.formula_version,
            image_level=inputs.image_level,
            value=None,
            sample_count=0,
            missing_reason=reason,
            metadata={"requirement_profile": metric.requirement_profile},
        )


def _measure_slanted_edge(evidence: SlantedEdgeEvidence) -> Dict[str, Any]:
    height, width = evidence.image.shape
    evidence.roi.validate_for_shape(width, height)
    crop: np.ndarray = evidence.image[
        evidence.roi.y : evidence.roi.y2,
        evidence.roi.x : evidence.roi.x2,
    ].astype(np.float64)
    if evidence.edge_orientation == "horizontal":
        crop = crop.T
    if min(crop.shape) < 16:
        raise G2MeasurementError("slanted-edge ROI 每一方向至少 16 px")
    contrast = float(np.percentile(crop, 95) - np.percentile(crop, 5))
    contrast_pct = contrast / evidence.full_scale * 100.0
    if contrast_pct < 20:
        raise G2MeasurementError("slanted-edge contrast 低於 20%FS")
    gradient = np.abs(np.diff(crop, axis=1))
    x_coordinates = np.arange(gradient.shape[1], dtype=np.float64) + 0.5
    weights = np.sum(gradient, axis=1)
    if np.any(weights <= 0):
        raise G2MeasurementError("slanted-edge 含無法定位邊緣的 row")
    edge_positions = np.sum(gradient * x_coordinates, axis=1) / weights
    rows = np.arange(crop.shape[0], dtype=np.float64)
    slope, intercept = np.polyfit(rows, edge_positions, 1)
    angle_deg = math.degrees(math.atan(abs(float(slope))))
    if not 2.0 <= angle_deg <= 15.0:
        raise G2MeasurementError(
            f"slanted-edge 角度 {angle_deg:.2f}° 不在 2～15° 品質窗"
        )
    yy, xx = np.indices(crop.shape, dtype=np.float64)
    distances = (xx - (slope * yy + intercept)) / math.sqrt(1 + slope**2)
    oversampling = 4
    bins = np.floor((distances - distances.min()) * oversampling).astype(np.int32)
    sums = np.bincount(bins.ravel(), weights=crop.ravel())
    counts = np.bincount(bins.ravel())
    valid = counts > 0
    centers = np.arange(len(sums), dtype=np.float64) / oversampling + distances.min()
    esf = np.interp(centers, centers[valid], sums[valid] / counts[valid])
    if esf[-1] < esf[0]:
        esf = esf[::-1]
    low = float(np.percentile(esf, 5))
    high = float(np.percentile(esf, 95))
    if high <= low:
        raise G2MeasurementError("slanted-edge ESF 無有效動態範圍")
    normalized = np.clip((esf - low) / (high - low), 0.0, 1.0)
    x10 = float(np.interp(0.1, normalized, centers))
    x90 = float(np.interp(0.9, normalized, centers))
    rise_width = abs(x90 - x10)
    lsf = np.diff(esf)
    lsf *= np.hamming(lsf.size)
    spectrum = np.abs(np.fft.rfft(lsf, n=max(2048, 2 ** math.ceil(math.log2(lsf.size)))))
    if spectrum[0] <= 0:
        raise G2MeasurementError("slanted-edge LSF DC 為 0")
    mtf = spectrum / spectrum[0]
    frequencies = np.fft.rfftfreq((len(spectrum) - 1) * 2, d=1 / oversampling)
    mtf_half_nyquist = float(np.interp(0.25, frequencies, mtf))
    return {
        "mtf_nyquist_half": mtf_half_nyquist,
        "rise_10_90_px": rise_width,
        "edge_angle_deg": angle_deg,
        "contrast_pct_fs": contrast_pct,
        "target_id": evidence.target_id,
        "roi_id": evidence.roi.roi_id,
        "method_version": evidence.method_version,
    }
