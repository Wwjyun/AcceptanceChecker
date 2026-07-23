# -*- coding: utf-8 -*-
"""v4 多影像時域雜訊、穩定性、再現性與 G4 量測。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .roi import RoiDefinition, RoiError
from .specification import MetricSpecification, V4Specification, load_default_v4_spec
from .v4_domain import ImageLevel, MeasurementResult, Severity


class TemporalAnalysisError(ValueError):
    """時域資料形狀、樣本數或實驗設計不符合規範。"""


@dataclass
class TemporalSeries:
    """同一前提、同一像素座標的 L1 影像序列。"""

    frames: np.ndarray
    timestamps_seconds: Sequence[float]
    evidence_sources: Sequence[str]

    def __post_init__(self) -> None:
        if self.frames.ndim != 3:
            raise TemporalAnalysisError("frames 必須是 (N, H, W) 灰階序列")
        count = int(self.frames.shape[0])
        if count == 0:
            raise TemporalAnalysisError("frames 不得為空")
        if len(self.timestamps_seconds) != count:
            raise TemporalAnalysisError("timestamps_seconds 數量必須與 frames 相同")
        if len(self.evidence_sources) != count or any(
            not source.strip() for source in self.evidence_sources
        ):
            raise TemporalAnalysisError("每張 frame 都必須有 evidence source")
        timestamps = [float(item) for item in self.timestamps_seconds]
        if any(not math.isfinite(item) for item in timestamps):
            raise TemporalAnalysisError("timestamp 必須是有限數值")
        if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
            raise TemporalAnalysisError("timestamp 必須嚴格遞增")
        if not np.all(np.isfinite(self.frames)):
            raise TemporalAnalysisError("frames 包含 NaN 或 Inf")

    @property
    def count(self) -> int:
        return int(self.frames.shape[0])

    @property
    def height(self) -> int:
        return int(self.frames.shape[1])

    @property
    def width(self) -> int:
        return int(self.frames.shape[2])

    def roi_stack(self, roi: RoiDefinition) -> np.ndarray:
        roi.validate_for_shape(self.width, self.height)
        stack = self.frames[:, roi.y : roi.y2, roi.x : roi.x2]
        if stack.size == 0:
            raise RoiError(f"ROI {roi.roi_id} 時域取樣結果為空")
        return stack.astype(np.float64)


@dataclass(frozen=True)
class RRObservation:
    operator_id: str
    part_id: str
    cycle_id: str
    value: float

    def __post_init__(self) -> None:
        if not self.operator_id or not self.part_id or not self.cycle_id:
            raise TemporalAnalysisError("R&R operator、part、cycle ID 不得為空")
        if not math.isfinite(self.value):
            raise TemporalAnalysisError("R&R value 必須是有限數值")


@dataclass(frozen=True)
class TemperatureRecord:
    timestamp_seconds: float
    temperature_c: float
    mean_signal: float

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value)
            for value in (self.timestamp_seconds, self.temperature_c, self.mean_signal)
        ):
            raise TemporalAnalysisError("溫度紀錄必須是有限數值")


@dataclass
class TemporalMeasurementInputs:
    series: TemporalSeries
    roi: RoiDefinition
    image_level: ImageLevel = ImageLevel.L1
    warm_reference_index: int = 0
    rr_observations: Sequence[RRObservation] = field(default_factory=list)
    restart_means: Sequence[float] = field(default_factory=list)
    temperature_records: Sequence[TemperatureRecord] = field(default_factory=list)
    rr_evidence_sources: Sequence[str] = field(default_factory=list)
    restart_evidence_sources: Sequence[str] = field(default_factory=list)
    temperature_evidence_sources: Sequence[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0 <= self.warm_reference_index < self.series.count:
            raise TemporalAnalysisError("warm_reference_index 超出序列範圍")


@dataclass
class TemporalMeasurementReport:
    measurements: List[MeasurementResult]
    temporal_sigma_mean: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class _TemporalValue:
    value: float
    sample_count: int
    evidence_sources: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    severity_cap: Optional[Severity] = None


class TemporalAcceptanceMeasurer:
    """產生 G3 時域 SNR 與完整六項 G4 MeasurementResult。"""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()

    def measure(self, inputs: TemporalMeasurementInputs) -> TemporalMeasurementReport:
        metric_ids = [
            "g3.temporal_snr",
            "g4.repeatability_cv_pct",
            "g4.reproducibility_rr_pct",
            "g4.gray_drift_30min_pct",
            "g4.gray_drift_8h_pct",
            "g4.temperature_tolerance_drift_pct",
            "g4.restart_reproducibility_pct",
        ]
        report = TemporalMeasurementReport(measurements=[])
        if inputs.image_level != ImageLevel.L1:
            report.measurements = [
                self._missing(
                    self.specification.get_metric(metric_id),
                    inputs,
                    "時域與 G4 正式量測必須使用固定 L1 影像",
                )
                for metric_id in metric_ids
            ]
            return report

        sigma: Optional[float] = None
        for metric_id in metric_ids:
            metric = self.specification.get_metric(metric_id)
            try:
                result = self._compute(metric, inputs)
                if metric_id == "g3.temporal_snr":
                    sigma = float(result.metadata["temporal_sigma_mean"])
                measurement = self._evaluated(metric, inputs, result)
                report.measurements.append(measurement)
                if result.severity_cap == Severity.S1:
                    report.warnings.append(
                        "環境溫度紀錄不足連續 7 日，依規範本項最高不得判 S3/S2"
                    )
            except (TemporalAnalysisError, RoiError) as exc:
                report.measurements.append(self._missing(metric, inputs, str(exc)))
        report.temporal_sigma_mean = sigma
        return report

    def _compute(
        self,
        metric: MetricSpecification,
        inputs: TemporalMeasurementInputs,
    ) -> _TemporalValue:
        if metric.formula == "mean_over_temporal_sigma":
            return self._temporal_snr(inputs)
        if metric.formula == "repeatability_cv":
            return self._repeatability(inputs)
        if metric.formula == "anova_rr_over_total":
            return self._rr(inputs)
        if metric.metric_id == "g4.gray_drift_30min_pct":
            return self._drift(inputs, 30 * 60)
        if metric.metric_id == "g4.gray_drift_8h_pct":
            return self._drift(inputs, 8 * 60 * 60)
        if metric.formula == "temperature_window_drift":
            return self._temperature(inputs)
        if metric.formula == "cold_restart_reproducibility":
            return self._restart(inputs)
        raise TemporalAnalysisError(f"尚未實作時域公式：{metric.formula}")

    @staticmethod
    def _require_30(inputs: TemporalMeasurementInputs) -> np.ndarray:
        if inputs.series.count < 30:
            raise TemporalAnalysisError(
                f"時域量測至少需要 30 張，實得 {inputs.series.count}"
            )
        return inputs.series.roi_stack(inputs.roi)

    def _temporal_snr(self, inputs: TemporalMeasurementInputs) -> _TemporalValue:
        stack = self._require_30(inputs)
        per_pixel_sigma = np.std(stack, axis=0, ddof=0)
        temporal_sigma = float(np.mean(per_pixel_sigma, dtype=np.float64))
        signal = float(np.mean(stack, dtype=np.float64))
        if signal <= 0:
            raise TemporalAnalysisError("ROI Mean 必須大於 0 才能計算時域 SNR")
        if temporal_sigma <= 0:
            value = 1.0e12
            zero_sigma = True
        else:
            value = signal / temporal_sigma
            zero_sigma = False
        return _TemporalValue(
            value=value,
            sample_count=int(stack.size),
            evidence_sources=list(inputs.series.evidence_sources),
            metadata={
                "temporal_sigma_mean": temporal_sigma,
                "signal_mean": signal,
                "frame_count": inputs.series.count,
                "zero_sigma_reported_as_lower_bound": zero_sigma,
            },
        )

    def _repeatability(self, inputs: TemporalMeasurementInputs) -> _TemporalValue:
        stack = self._require_30(inputs)
        frame_means = np.mean(stack, axis=(1, 2), dtype=np.float64)
        mean_value = float(np.mean(frame_means))
        if mean_value <= 0:
            raise TemporalAnalysisError("frame Mean 必須大於 0 才能計算重複性 CV")
        value = float(np.std(frame_means, ddof=0) / mean_value * 100.0)
        return _TemporalValue(
            value=value,
            sample_count=inputs.series.count,
            evidence_sources=list(inputs.series.evidence_sources),
            metadata={"frame_means": frame_means.tolist()},
        )

    def _drift(
        self,
        inputs: TemporalMeasurementInputs,
        elapsed_seconds: float,
    ) -> _TemporalValue:
        stack = self._require_30(inputs)
        timestamps = [float(item) for item in inputs.series.timestamps_seconds]
        reference_index = inputs.warm_reference_index
        target_time = timestamps[reference_index] + elapsed_seconds
        target_index = next(
            (index for index, value in enumerate(timestamps) if value >= target_time),
            None,
        )
        label = "30 分鐘" if elapsed_seconds == 1800 else "8 小時"
        if target_index is None:
            raise TemporalAnalysisError(f"序列未涵蓋暖機基準後 {label}")
        reference_mean = float(np.mean(stack[reference_index], dtype=np.float64))
        target_mean = float(np.mean(stack[target_index], dtype=np.float64))
        if reference_mean <= 0:
            raise TemporalAnalysisError("暖機完成基準 Mean 必須大於 0")
        value = abs(target_mean - reference_mean) / reference_mean * 100.0
        return _TemporalValue(
            value=value,
            sample_count=2,
            evidence_sources=[
                inputs.series.evidence_sources[reference_index],
                inputs.series.evidence_sources[target_index],
            ],
            metadata={
                "reference_index": reference_index,
                "target_index": target_index,
                "reference_mean": reference_mean,
                "target_mean": target_mean,
                "actual_elapsed_seconds": (
                    timestamps[target_index] - timestamps[reference_index]
                ),
            },
        )

    def _restart(self, inputs: TemporalMeasurementInputs) -> _TemporalValue:
        values = np.asarray(inputs.restart_means, dtype=np.float64)
        if values.size < 5:
            raise TemporalAnalysisError(
                f"重新開機再現性至少需要 5 次冷啟動，實得 {values.size}"
            )
        if len(inputs.restart_evidence_sources) != values.size:
            raise TemporalAnalysisError("每次冷啟動都必須有 evidence source")
        if not np.all(np.isfinite(values)):
            raise TemporalAnalysisError("restart_means 包含 NaN 或 Inf")
        mean_value = float(np.mean(values))
        if mean_value <= 0:
            raise TemporalAnalysisError("冷啟動 Mean 必須大於 0")
        value = float(np.max(np.abs(values - mean_value)) / mean_value * 100.0)
        return _TemporalValue(
            value=value,
            sample_count=int(values.size),
            evidence_sources=list(inputs.restart_evidence_sources),
            metadata={
                "restart_means": values.tolist(),
                "calculation": "max_abs_deviation_from_restart_mean_pct",
            },
        )

    def _temperature(self, inputs: TemporalMeasurementInputs) -> _TemporalValue:
        records = sorted(inputs.temperature_records, key=lambda item: item.timestamp_seconds)
        if len(records) < 2:
            raise TemporalAnalysisError("環境溫度耐受至少需要兩筆溫度與灰階紀錄")
        if len(inputs.temperature_evidence_sources) != len(records):
            raise TemporalAnalysisError("每筆溫度紀錄都必須有 evidence source")
        timestamps = [item.timestamp_seconds for item in records]
        if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
            raise TemporalAnalysisError("溫度紀錄 timestamp 必須嚴格遞增")
        reference = records[0].mean_signal
        if reference <= 0:
            raise TemporalAnalysisError("溫度實驗基準 Mean 必須大於 0")
        drifts = [
            abs(item.mean_signal - reference) / reference * 100.0 for item in records
        ]
        duration = timestamps[-1] - timestamps[0]
        gaps = [right - left for left, right in zip(timestamps, timestamps[1:])]
        continuous_7d = duration >= 7 * 24 * 60 * 60 and max(gaps, default=0) <= 6 * 60 * 60
        return _TemporalValue(
            value=max(drifts),
            sample_count=len(records),
            evidence_sources=list(inputs.temperature_evidence_sources),
            metadata={
                "duration_days": duration / (24 * 60 * 60),
                "max_gap_hours": max(gaps, default=0) / 3600,
                "temperature_min_c": min(item.temperature_c for item in records),
                "temperature_max_c": max(item.temperature_c for item in records),
                "continuous_7d_evidence": continuous_7d,
            },
            severity_cap=None if continuous_7d else Severity.S1,
        )

    def _rr(self, inputs: TemporalMeasurementInputs) -> _TemporalValue:
        observations = list(inputs.rr_observations)
        cycle_count = len({item.cycle_id for item in observations})
        if cycle_count < 10:
            raise TemporalAnalysisError(
                f"R&R 至少需要 10 個重新上下料/定位循環，實得 {cycle_count}"
            )
        if len(inputs.rr_evidence_sources) != len(observations):
            raise TemporalAnalysisError("每筆 R&R observation 都必須有 evidence source")
        result = _balanced_crossed_anova(observations)
        return _TemporalValue(
            value=result["rr_pct"],
            sample_count=len(observations),
            evidence_sources=list(inputs.rr_evidence_sources),
            metadata=result,
        )

    def _evaluated(
        self,
        metric: MetricSpecification,
        inputs: TemporalMeasurementInputs,
        result: _TemporalValue,
    ) -> MeasurementResult:
        severity = metric.classify(result.value)
        if result.severity_cap == Severity.S1 and severity in (Severity.S3, Severity.S2):
            severity = Severity.S1
        return MeasurementResult(
            metric_id=metric.metric_id,
            group=metric.group,
            severity=severity,
            unit=metric.unit,
            formula_version=self.specification.formula_version,
            image_level=inputs.image_level,
            value=result.value,
            roi_id=inputs.roi.roi_id,
            sample_count=result.sample_count,
            evidence_sources=list(dict.fromkeys(result.evidence_sources)),
            metadata={
                "requirement_profile": metric.requirement_profile,
                **result.metadata,
            },
        )

    def _missing(
        self,
        metric: MetricSpecification,
        inputs: TemporalMeasurementInputs,
        reason: str,
    ) -> MeasurementResult:
        return MeasurementResult(
            metric_id=metric.metric_id,
            group=metric.group,
            severity=Severity.NOT_EVALUATED,
            unit=metric.unit,
            formula_version=self.specification.formula_version,
            image_level=inputs.image_level,
            value=None,
            roi_id=inputs.roi.roi_id,
            sample_count=0,
            evidence_sources=list(inputs.series.evidence_sources),
            missing_reason=reason,
            metadata={"requirement_profile": metric.requirement_profile},
        )


def _balanced_crossed_anova(observations: Sequence[RRObservation]) -> Dict[str, Any]:
    operators = sorted({item.operator_id for item in observations})
    parts = sorted({item.part_id for item in observations})
    if len(operators) < 2 or len(parts) < 2:
        raise TemporalAnalysisError("R&R ANOVA 至少需要 2 位操作者與 2 個 part")
    cells: Dict[Tuple[str, str], List[float]] = {
        (operator, part): [] for operator in operators for part in parts
    }
    for item in observations:
        cells[(item.operator_id, item.part_id)].append(float(item.value))
    counts = {len(values) for values in cells.values()}
    if len(counts) != 1 or not counts or next(iter(counts)) < 2:
        raise TemporalAnalysisError("R&R ANOVA 必須是每個 operator×part 至少重複 2 次的平衡設計")
    repeats = next(iter(counts))
    operator_count = len(operators)
    part_count = len(parts)
    all_values = np.asarray([item.value for item in observations], dtype=np.float64)
    grand = float(np.mean(all_values))
    operator_means = {
        operator: float(
            np.mean(
                [
                    value
                    for (cell_operator, _part), values in cells.items()
                    if cell_operator == operator
                    for value in values
                ]
            )
        )
        for operator in operators
    }
    part_means = {
        part: float(
            np.mean(
                [
                    value
                    for (_operator, cell_part), values in cells.items()
                    if cell_part == part
                    for value in values
                ]
            )
        )
        for part in parts
    }
    cell_means = {key: float(np.mean(values)) for key, values in cells.items()}
    ss_operator = part_count * repeats * sum(
        (operator_means[item] - grand) ** 2 for item in operators
    )
    ss_part = operator_count * repeats * sum(
        (part_means[item] - grand) ** 2 for item in parts
    )
    ss_interaction = repeats * sum(
        (
            cell_means[(operator, part)]
            - operator_means[operator]
            - part_means[part]
            + grand
        )
        ** 2
        for operator in operators
        for part in parts
    )
    ss_repeat = sum(
        (value - cell_means[key]) ** 2
        for key, values in cells.items()
        for value in values
    )
    df_operator = operator_count - 1
    df_part = part_count - 1
    df_interaction = df_operator * df_part
    df_repeat = operator_count * part_count * (repeats - 1)
    ms_operator = ss_operator / df_operator
    ms_part = ss_part / df_part
    ms_interaction = ss_interaction / df_interaction
    ms_repeat = ss_repeat / df_repeat
    variance_repeat = max(ms_repeat, 0.0)
    variance_interaction = max((ms_interaction - ms_repeat) / repeats, 0.0)
    variance_operator = max(
        (ms_operator - ms_interaction) / (part_count * repeats), 0.0
    )
    variance_part = max(
        (ms_part - ms_interaction) / (operator_count * repeats), 0.0
    )
    variance_rr = variance_repeat + variance_interaction + variance_operator
    variance_total = variance_rr + variance_part
    if variance_total <= 0:
        raise TemporalAnalysisError("R&R ANOVA 總變異為 0，比例無法定義")
    return {
        "rr_pct": math.sqrt(variance_rr / variance_total) * 100.0,
        "operator_count": operator_count,
        "part_count": part_count,
        "repeats_per_cell": repeats,
        "cycle_count": len({item.cycle_id for item in observations}),
        "variance_repeat": variance_repeat,
        "variance_interaction": variance_interaction,
        "variance_operator": variance_operator,
        "variance_part": variance_part,
        "variance_total": variance_total,
        "method": "balanced_crossed_random_effects_anova",
    }
