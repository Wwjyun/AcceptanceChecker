# -*- coding: utf-8 -*-
"""v4 G1 三種取像模式的正式原始尺度量測。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from .image import MeasurementPlaneError, RawImage
from .roi import RoiCollection, RoiDefinition, RoiError, RoiType, measure_raw_16_zones
from .specification import MetricSpecification, V4Specification, load_default_v4_spec
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, OpticalMode, Severity
from .v4_judge import S0PriorityEvent, S0PriorityEventType


class DefectPolarity(str, Enum):
    BRIGHT = "bright"
    DARK = "dark"
    BOTH = "both"
    UNSPECIFIED = "unspecified"


class MissingG1EvidenceError(ValueError):
    """某一 G1 公式缺少必要且可驗證的輸入。"""


@dataclass
class G1MeasurementInputs:
    """一輪 G1 量測的輸入與證據來源。"""

    mode: OpticalMode
    raw: RawImage
    rois: RoiCollection
    evidence_source: str
    image_level: ImageLevel = ImageLevel.L1
    primary_image_id: str = ""
    reference_raw: Optional[RawImage] = None
    blocked_raw: Optional[RawImage] = None
    dark_raw: Optional[RawImage] = None
    reference_source: str = ""
    blocked_source: str = ""
    dark_source: str = ""
    expected_defect_polarity: DefectPolarity = DefectPolarity.UNSPECIFIED

    def __post_init__(self) -> None:
        if not self.evidence_source.strip():
            raise ValueError("G1 evidence_source 不得為空")
        if not self.primary_image_id:
            self.primary_image_id = os.path.basename(self.evidence_source)


@dataclass
class G1MeasurementReport:
    measurements: List[MeasurementResult]
    warnings: List[str] = field(default_factory=list)
    priority_events: List[S0PriorityEvent] = field(default_factory=list)


@dataclass
class _ComputedMetric:
    value: float
    roi_ids: List[str]
    sample_count: int
    evidence_sources: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    forced_severity: Optional[Severity] = None


class G1Measurer:
    """依 v4 規格產生該模式完整的 G1 MeasurementResult。"""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()

    def measure(self, inputs: G1MeasurementInputs) -> G1MeasurementReport:
        metrics = [
            metric
            for metric in self.specification.metrics_for_mode(inputs.mode)
            if metric.group == MetricGroup.G1
        ]
        report = G1MeasurementReport(measurements=[])
        rois = self._applicable_rois(inputs)
        self._validate_primary_plane(inputs, rois)

        for metric in metrics:
            if inputs.image_level != ImageLevel.L1:
                report.measurements.append(
                    self._missing_result(
                        metric,
                        inputs,
                        "G1 正式驗收僅允許固定且可追溯的 L1 影像",
                    )
                )
                continue
            try:
                computed = self._compute(metric, inputs, rois)
                report.measurements.append(self._evaluated_result(metric, inputs, computed))
            except (MissingG1EvidenceError, MeasurementPlaneError, RoiError) as exc:
                report.measurements.append(self._missing_result(metric, inputs, str(exc)))

        report.warnings.extend(self._mode_plausibility_warnings(inputs, rois))
        edge_result = next(
            (
                item
                for item in report.measurements
                if item.metric_id == "g1.dark.defect_edge_low_clip_pct"
            ),
            None,
        )
        if edge_result is not None and edge_result.metadata.get("contour_interruption", False):
            report.priority_events.append(
                S0PriorityEvent(
                    event_type=S0PriorityEventType.DEFECT_SIGNAL_OBSCURED,
                    description="Golden 缺陷邊緣出現連續 ≥3 px 黑階裁切，輪廓資訊中斷",
                    evidence_sources=list(edge_result.evidence_sources),
                )
            )
        return report

    @staticmethod
    def _applicable_rois(inputs: G1MeasurementInputs) -> RoiCollection:
        return RoiCollection(
            [
                roi
                for roi in inputs.rois.rois
                if roi.image_id in ("*", inputs.primary_image_id)
            ],
            schema_version=inputs.rois.schema_version,
        )

    @staticmethod
    def _validate_primary_plane(
        inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> None:
        inputs.raw.require_full_scale()
        rois.assert_valid(inputs.raw.width, inputs.raw.height)

    def _compute(
        self,
        metric: MetricSpecification,
        inputs: G1MeasurementInputs,
        rois: RoiCollection,
    ) -> _ComputedMetric:
        formula = metric.formula
        if formula in {
            "background_mean_pct_fs",
            "spatial_std_over_mean",
            "spatial_std",
            "spatial_std_8bit_equivalent",
            "pixel_ratio_le_2pct_fs",
            "pixel_ratio_ge_86pct_fs",
            "pixel_ratio_ge_98pct_fs",
        }:
            return self._background_metric(formula, inputs, rois)
        if formula in {
            "min_region_mean_over_max_region_mean_16",
            "region_mean_range_over_mean_16",
        }:
            return self._zone_metric(formula, inputs, rois)
        if formula == "local_shadow_depth":
            return self._local_shadow_depth(inputs, rois)
        if formula == "stray_light_ratio":
            return self._stray_light(inputs, rois)
        if formula == "specular_hotspot_area_ratio":
            return self._specular_hotspot_area(inputs, rois)
        if formula == "defect_edge_low_clip_ratio":
            return self._dark_edge_low_clip(inputs, rois)
        raise MissingG1EvidenceError(f"尚未實作 G1 公式：{formula}")

    def _background_metric(
        self,
        formula: str,
        inputs: G1MeasurementInputs,
        rois: RoiCollection,
    ) -> _ComputedMetric:
        roi = self._require_one(rois, RoiType.DEFECT_FREE_BACKGROUND)
        values = self._roi_values(inputs.raw.raw_gray, roi)
        full_scale = inputs.raw.require_full_scale()
        mean = float(np.mean(values, dtype=np.float64))
        std = float(np.std(values, dtype=np.float64))
        if formula == "background_mean_pct_fs":
            value = mean / full_scale * 100.0
        elif formula == "spatial_std_over_mean":
            if mean <= 0:
                raise MissingG1EvidenceError("背景 Mean 為 0，CV 無法可靠計算")
            value = std / mean
        elif formula == "spatial_std":
            value = std
        elif formula == "spatial_std_8bit_equivalent":
            value = std / full_scale * 255.0
        elif formula == "pixel_ratio_le_2pct_fs":
            value = float(np.count_nonzero(values <= full_scale * 0.02) / values.size * 100.0)
        elif formula == "pixel_ratio_ge_86pct_fs":
            value = float(np.count_nonzero(values >= full_scale * 0.86) / values.size * 100.0)
        else:
            value = float(np.count_nonzero(values >= full_scale * 0.98) / values.size * 100.0)
        return _ComputedMetric(
            value=value,
            roi_ids=[roi.roi_id],
            sample_count=int(values.size),
            evidence_sources=[inputs.evidence_source],
        )

    def _zone_metric(
        self,
        formula: str,
        inputs: G1MeasurementInputs,
        rois: RoiCollection,
    ) -> _ComputedMetric:
        roi = self._require_one(rois, RoiType.EFFECTIVE_INSPECTION_AREA)
        zones = measure_raw_16_zones(inputs.raw, roi)
        if formula == "min_region_mean_over_max_region_mean_16":
            value = zones.uniformity_ratio
        else:
            value = zones.brightness_difference_pct
        return _ComputedMetric(
            value=value,
            roi_ids=[roi.roi_id],
            sample_count=roi.width * roi.height,
            evidence_sources=[inputs.evidence_source],
            metadata={
                "zone_means_pct_fs": list(zones.zone_means),
                "zone_boxes": [list(box) for box in zones.zone_boxes],
            },
        )

    def _local_shadow_depth(
        self, inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> _ComputedMetric:
        shadows = rois.by_type(RoiType.SHADOW)
        if not shadows:
            raise MissingG1EvidenceError("缺少 shadow ROI")
        rings = {roi.roi_id: roi for roi in rois.by_type(RoiType.LOCAL_BACKGROUND_RING)}
        depths: List[float] = []
        used_ids: List[str] = []
        sample_count = 0
        for shadow in shadows:
            ring_id = str(shadow.metadata.get("background_roi_id", ""))
            if ring_id:
                ring = rings.get(ring_id)
            elif len(rings) == 1:
                ring = next(iter(rings.values()))
            else:
                ring = None
            if ring is None:
                raise MissingG1EvidenceError(
                    f"shadow ROI {shadow.roi_id} 缺少唯一 local_background_ring"
                )
            shadow_values = self._roi_values(inputs.raw.raw_gray, shadow)
            background_values = self._roi_values(inputs.raw.raw_gray, ring)
            background_mean = float(np.mean(background_values, dtype=np.float64))
            if background_mean <= 0:
                raise MissingG1EvidenceError(
                    "local background Mean 為 0，陰影深度無法計算"
                )
            shadow_mean = float(np.mean(shadow_values, dtype=np.float64))
            depths.append(max(0.0, (background_mean - shadow_mean) / background_mean * 100.0))
            used_ids.extend([shadow.roi_id, ring.roi_id])
            sample_count += int(shadow_values.size + background_values.size)
        return _ComputedMetric(
            value=max(depths),
            roi_ids=used_ids,
            sample_count=sample_count,
            evidence_sources=[inputs.evidence_source],
            metadata={"per_shadow_depth_pct": depths},
        )

    def _stray_light(
        self, inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> _ComputedMetric:
        paired = [
            ("reference", inputs.reference_raw, inputs.reference_source),
            ("blocked", inputs.blocked_raw, inputs.blocked_source),
            ("dark", inputs.dark_raw, inputs.dark_source),
        ]
        missing = [
            name
            for name, raw, source in paired
            if raw is None or not source.strip()
        ]
        if missing:
            raise MissingG1EvidenceError(
                f"雜散光公式缺少成對證據：{', '.join(missing)}"
            )
        roi = self._require_one(rois, RoiType.DEFECT_FREE_BACKGROUND)
        resolved = [(name, raw, source) for name, raw, source in paired if raw is not None]
        reference_scale = inputs.raw.require_full_scale()
        means: Dict[str, float] = {}
        for name, raw, _source in resolved:
            if raw.width != inputs.raw.width or raw.height != inputs.raw.height:
                raise MissingG1EvidenceError(f"{name} 影像尺寸與 primary 不一致")
            if raw.require_full_scale() != reference_scale:
                raise MissingG1EvidenceError(f"{name} bit depth 與 primary 不一致")
            means[name] = float(
                np.mean(self._roi_values(raw.raw_gray, roi), dtype=np.float64)
            )
        denominator = means["reference"] - means["dark"]
        if denominator <= 0:
            raise MissingG1EvidenceError("Mean_reference 必須大於 Mean_dark")
        value = (means["blocked"] - means["dark"]) / denominator * 100.0
        return _ComputedMetric(
            value=value,
            roi_ids=[roi.roi_id],
            sample_count=roi.width * roi.height * 3,
            evidence_sources=[source for _name, _raw, source in resolved],
            metadata={"paired_means_raw": means},
        )

    def _specular_hotspot_area(
        self, inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> _ComputedMetric:
        roi = self._require_one(rois, RoiType.EFFECTIVE_INSPECTION_AREA)
        image = inputs.raw.raw_gray
        crop = self._roi_values(image, roi)
        full_scale = inputs.raw.require_full_scale()
        initial_threshold = float(np.median(crop)) + 0.30 * full_scale
        mask = (crop > initial_threshold).astype(np.uint8)
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            mask, connectivity=8
        )
        accepted_area = 0
        components: List[Dict[str, Any]] = []
        for label in range(1, count):
            local_x, local_y, width, height, _area = (int(v) for v in stats[label])
            x1 = roi.x + local_x
            y1 = roi.y + local_y
            x2 = x1 + width
            y2 = y1 + height
            outer_x1 = max(roi.x, x1 - 20)
            outer_y1 = max(roi.y, y1 - 20)
            outer_x2 = min(roi.x2, x2 + 20)
            outer_y2 = min(roi.y2, y2 + 20)
            ring = image[outer_y1:outer_y2, outer_x1:outer_x2]
            ring_mask = np.ones(ring.shape, dtype=bool)
            ring_mask[
                y1 - outer_y1 : y2 - outer_y1,
                x1 - outer_x1 : x2 - outer_x1,
            ] = False
            ring_values = ring[ring_mask]
            if ring_values.size == 0:
                continue
            local_background = float(np.median(ring_values))
            threshold = local_background + 0.30 * full_scale
            component_mask = labels[
                local_y : local_y + height,
                local_x : local_x + width,
            ] == label
            component_values = crop[
                local_y : local_y + height,
                local_x : local_x + width,
            ]
            area = int(np.count_nonzero(component_mask & (component_values > threshold)))
            if area < 50:
                continue
            accepted_area += area
            components.append(
                {
                    "box": [x1, y1, width, height],
                    "area_px": area,
                    "local_background_median": local_background,
                    "threshold_raw": threshold,
                    "ring_pad_px": 20,
                }
            )
        return _ComputedMetric(
            value=accepted_area / crop.size * 100.0,
            roi_ids=[roi.roi_id],
            sample_count=int(crop.size),
            evidence_sources=[inputs.evidence_source],
            metadata={
                "hotspot_components": components,
                "connectivity": 8,
                "minimum_area_px": 50,
                "threshold_offset_pct_fs": 30,
            },
        )

    def _dark_edge_low_clip(
        self, inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> _ComputedMetric:
        defects = rois.by_type(RoiType.GOLDEN_DEFECT)
        if not defects:
            raise MissingG1EvidenceError("缺少 Golden defect ROI")
        image = inputs.raw.raw_gray
        threshold = inputs.raw.require_full_scale() * 0.02
        rates: List[float] = []
        interruption = False
        used: List[str] = []
        sample_count = 0
        for defect in defects:
            x1 = max(0, defect.x - 5)
            y1 = max(0, defect.y - 5)
            x2 = min(inputs.raw.width, defect.x2 + 5)
            y2 = min(inputs.raw.height, defect.y2 + 5)
            outer = image[y1:y2, x1:x2]
            ring_mask = np.ones(outer.shape, dtype=bool)
            ring_mask[
                defect.y - y1 : defect.y2 - y1,
                defect.x - x1 : defect.x2 - x1,
            ] = False
            ring_values = outer[ring_mask]
            if ring_values.size == 0:
                raise MissingG1EvidenceError(
                    f"Golden defect ROI {defect.roi_id} 無 5 px 邊緣 ring"
                )
            low_mask = (outer <= threshold) & ring_mask
            rates.append(float(np.count_nonzero(low_mask) / ring_values.size * 100.0))
            interruption = interruption or self._has_run(low_mask, 3)
            used.append(defect.roi_id)
            sample_count += int(ring_values.size)
        return _ComputedMetric(
            value=max(rates),
            roi_ids=used,
            sample_count=sample_count,
            evidence_sources=[inputs.evidence_source],
            metadata={
                "per_defect_low_clip_pct": rates,
                "ring_pad_px": 5,
                "contour_interruption": interruption,
                "contiguous_run_threshold_px": 3,
            },
            forced_severity=Severity.S0 if interruption else None,
        )

    def _evaluated_result(
        self,
        metric: MetricSpecification,
        inputs: G1MeasurementInputs,
        computed: _ComputedMetric,
    ) -> MeasurementResult:
        kind = str(metric.classification["kind"])
        metadata = {
            "requirement_profile": metric.requirement_profile,
            "classification_kind": kind,
            **computed.metadata,
        }
        missing_reason = ""
        if kind == "record_only":
            severity = Severity.NOT_EVALUATED
            missing_reason = "規格指定此值僅記錄、不進行 S0～S3 分級"
            metadata["non_graded"] = True
        else:
            severity = computed.forced_severity or metric.classify(computed.value)
            if severity == Severity.NOT_EVALUATED:
                missing_reason = "規格在此數值區間未定義 S0～S3 等級"
        return MeasurementResult(
            metric_id=metric.metric_id,
            group=MetricGroup.G1,
            severity=severity,
            unit=metric.unit,
            formula_version=self.specification.formula_version,
            image_level=inputs.image_level,
            value=computed.value,
            roi_id=",".join(dict.fromkeys(computed.roi_ids)),
            sample_count=computed.sample_count,
            evidence_sources=list(dict.fromkeys(computed.evidence_sources)),
            missing_reason=missing_reason,
            metadata=metadata,
        )

    def _missing_result(
        self,
        metric: MetricSpecification,
        inputs: G1MeasurementInputs,
        reason: str,
    ) -> MeasurementResult:
        return MeasurementResult(
            metric_id=metric.metric_id,
            group=MetricGroup.G1,
            severity=Severity.NOT_EVALUATED,
            unit=metric.unit,
            formula_version=self.specification.formula_version,
            image_level=inputs.image_level,
            value=None,
            sample_count=0,
            evidence_sources=[inputs.evidence_source],
            missing_reason=reason,
            metadata={
                "requirement_profile": metric.requirement_profile,
                "classification_kind": metric.classification["kind"],
            },
        )

    def _mode_plausibility_warnings(
        self, inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> List[str]:
        warnings: List[str] = []
        backgrounds = rois.by_type(RoiType.DEFECT_FREE_BACKGROUND)
        if not backgrounds:
            return warnings
        values = self._roi_values(inputs.raw.raw_gray, backgrounds[0])
        mean_pct = (
            float(np.mean(values, dtype=np.float64))
            / inputs.raw.require_full_scale()
            * 100.0
        )
        if inputs.mode == OpticalMode.SCATTERING_DARK_FIELD and mean_pct > 25:
            warnings.append("暗場背景高於 25%FS：請檢查雜散光、反射幾何或模式命名")
        if inputs.mode == OpticalMode.SPECULAR_BRIGHT_FIELD and mean_pct <= 15:
            warnings.append("鏡面明場背景接近全黑：請確認主要鏡面反射光路是否成立")
        warnings.extend(self._polarity_warnings(inputs, rois))
        return warnings

    def _polarity_warnings(
        self, inputs: G1MeasurementInputs, rois: RoiCollection
    ) -> List[str]:
        expected = inputs.expected_defect_polarity
        if expected == DefectPolarity.UNSPECIFIED:
            return []
        defects = rois.by_type(RoiType.GOLDEN_DEFECT)
        rings = {roi.roi_id: roi for roi in rois.by_type(RoiType.LOCAL_BACKGROUND_RING)}
        warnings: List[str] = []
        tolerance = inputs.raw.require_full_scale() * 0.01
        for defect in defects:
            ring_id = str(defect.metadata.get("background_roi_id", ""))
            ring = rings.get(ring_id) if ring_id else None
            if ring is None and len(rings) == 1:
                ring = next(iter(rings.values()))
            if ring is None:
                continue
            defect_mean = float(
                np.mean(self._roi_values(inputs.raw.raw_gray, defect), dtype=np.float64)
            )
            background_mean = float(
                np.mean(self._roi_values(inputs.raw.raw_gray, ring), dtype=np.float64)
            )
            delta = defect_mean - background_mean
            if expected == DefectPolarity.BRIGHT and delta <= tolerance:
                warnings.append(f"缺陷 {defect.roi_id} 未呈預期亮極性，須檢查反射機制")
            elif expected == DefectPolarity.DARK and delta >= -tolerance:
                warnings.append(f"缺陷 {defect.roi_id} 未呈預期暗極性，須檢查反射機制")
        return warnings

    @staticmethod
    def _require_one(rois: RoiCollection, roi_type: RoiType) -> RoiDefinition:
        matching = rois.by_type(roi_type)
        if not matching:
            raise MissingG1EvidenceError(f"缺少 {roi_type.value} ROI")
        if len(matching) > 1:
            raise MissingG1EvidenceError(
                f"{roi_type.value} ROI 必須唯一，實得 {len(matching)} 個"
            )
        return matching[0]

    @staticmethod
    def _roi_values(image: np.ndarray, roi: RoiDefinition) -> np.ndarray:
        values = image[roi.y : roi.y2, roi.x : roi.x2]
        if values.size == 0:
            raise RoiError(f"ROI {roi.roi_id} 取樣結果為空")
        return values

    @staticmethod
    def _has_run(mask: np.ndarray, minimum: int) -> bool:
        for row in mask:
            if G1Measurer._one_dimensional_run(row, minimum):
                return True
        for column in mask.T:
            if G1Measurer._one_dimensional_run(column, minimum):
                return True
        return False

    @staticmethod
    def _one_dimensional_run(values: np.ndarray, minimum: int) -> bool:
        run = 0
        for value in values:
            run = run + 1 if bool(value) else 0
            if run >= minimum:
                return True
        return False
