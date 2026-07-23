# -*- coding: utf-8 -*-
"""Formal v4 G6 measurements from approved Golden and detector evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .g1_measurement import DefectPolarity
from .golden_catalog import (
    DetectorDecision,
    DetectorResultSet,
    FullWidthRegion,
    GoldenCatalog,
    GoldenCatalogError,
    GoldenDisposition,
    GoldenSample,
)
from .specification import V4Specification, load_default_v4_spec
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, Severity
from .v4_judge import S0PriorityEvent, S0PriorityEventType


class G6MeasurementError(ValueError):
    """Raised when approved Golden evidence cannot support a G6 metric."""


@dataclass
class G6MeasurementInputs:
    catalog: GoldenCatalog
    detector_results: DetectorResultSet
    images: Dict[str, np.ndarray] = field(default_factory=dict)
    minimum_defect_recognizable: Optional[bool] = None
    recognizability_evidence_source: str = ""

    def __post_init__(self) -> None:
        if (
            self.minimum_defect_recognizable is not None
            and not self.recognizability_evidence_source
        ):
            raise G6MeasurementError(
                "minimum-defect recognizability decision requires an evidence source"
            )


@dataclass
class G6MeasurementReport:
    measurements: List[MeasurementResult]
    priority_events: List[S0PriorityEvent] = field(default_factory=list)


@dataclass
class _G6Value:
    value: Any
    severity: Optional[Severity]
    sample_count: int
    evidence_sources: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class G6Measurer:
    """Produce all eight G6 metrics and explicit S0 priority events."""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()

    def measure(self, inputs: G6MeasurementInputs) -> G6MeasurementReport:
        results: List[MeasurementResult] = []
        for metric in self.specification.metrics:
            if metric.group != MetricGroup.G6:
                continue
            try:
                computed = self._compute(metric.metric_id, inputs)
                severity = computed.severity or metric.classify(float(computed.value))
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G6,
                        severity=severity,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=ImageLevel.L1,
                        value=computed.value,
                        sample_count=computed.sample_count,
                        evidence_sources=list(dict.fromkeys(computed.evidence_sources)),
                        metadata={
                            "requirement_profile": metric.requirement_profile,
                            "golden_catalog": inputs.catalog.reference,
                            **computed.metadata,
                        },
                    )
                )
            except (G6MeasurementError, GoldenCatalogError) as exc:
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G6,
                        severity=Severity.NOT_EVALUATED,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=ImageLevel.L1,
                        value=None,
                        sample_count=0,
                        missing_reason=str(exc),
                        metadata={
                            "requirement_profile": metric.requirement_profile,
                            "golden_catalog": inputs.catalog.reference,
                        },
                    )
                )
        return G6MeasurementReport(
            measurements=results,
            priority_events=self._priority_events(inputs),
        )

    def _compute(self, metric_id: str, inputs: G6MeasurementInputs) -> _G6Value:
        if metric_id == "g6.defect_cnr":
            return self._cnr(inputs, delta_only=False)
        if metric_id == "g6.defect_delta_gray":
            return self._cnr(inputs, delta_only=True)
        if metric_id == "g6.golden_ng_detection":
            return self._ng_detection(inputs)
        if metric_id == "g6.golden_ng_samples_per_type":
            return self._samples_per_type(inputs)
        if metric_id == "g6.defect_type_coverage_pct":
            return self._type_coverage(inputs)
        if metric_id == "g6.golden_pass_false_positive_pct":
            return self._false_positive(inputs)
        if metric_id == "g6.false_positive_upper_95_pct":
            return self._false_positive_upper(inputs)
        if metric_id == "g6.full_width_detection_consistency_pct":
            return self._full_width(inputs)
        raise G6MeasurementError(f"unknown G6 metric: {metric_id}")

    @staticmethod
    def _validate_results(inputs: G6MeasurementInputs) -> Dict[str, DetectorDecision]:
        inputs.detector_results.validate_against(inputs.catalog)
        return {item.sample_id: item for item in inputs.detector_results.decisions}

    @staticmethod
    def _sources(inputs: G6MeasurementInputs, *, images: Sequence[str] = ()) -> List[str]:
        return [
            inputs.catalog.approval_record_source,
            inputs.detector_results.imported_from,
            *images,
        ]

    def _cnr(self, inputs: G6MeasurementInputs, *, delta_only: bool) -> _G6Value:
        samples = [
            sample
            for sample in inputs.catalog.samples
            if sample.disposition == GoldenDisposition.NG
        ]
        if not samples:
            raise G6MeasurementError("approved Golden catalog contains no NG samples")
        rows: List[Dict[str, Any]] = []
        per_polarity: Dict[str, List[float]] = {
            DefectPolarity.BRIGHT.value: [],
            DefectPolarity.DARK.value: [],
        }
        image_sources: List[str] = []
        for sample in samples:
            image = inputs.images.get(sample.sample_id)
            if image is None:
                raise G6MeasurementError(
                    f"formal CNR image is missing for Golden sample {sample.sample_id}"
                )
            cnr, delta_gray, background_std = _sample_cnr(sample, image)
            assert sample.defect_roi is not None
            assert sample.background_ring is not None
            rows.append(
                {
                    "sample_id": sample.sample_id,
                    "polarity": sample.defect_polarity.value,
                    "cnr": cnr,
                    "delta_gray": delta_gray,
                    "background_std": background_std,
                    "defect_roi_id": sample.defect_roi.roi_id,
                    "background_ring_id": sample.background_ring.roi_id,
                }
            )
            per_polarity[sample.defect_polarity.value].append(cnr)
            image_sources.append(sample.image_source)
        missing_polarities = [
            polarity for polarity, values in per_polarity.items() if not values
        ]
        if missing_polarities:
            raise G6MeasurementError(
                "formal CNR requires both bright and dark Golden defects; missing "
                + ", ".join(missing_polarities)
            )
        polarity_worst = {
            polarity: min(values) for polarity, values in per_polarity.items()
        }
        metadata = {
            "per_sample": rows,
            "worst_by_polarity": polarity_worst,
            "aggregation": "minimum_of_bright_and_dark_polarity_worst",
            "approved_golden_only": True,
        }
        if delta_only:
            return _G6Value(
                value={
                    "bright_worst_absolute_delta_gray": min(
                        abs(row["delta_gray"])
                        for row in rows
                        if row["polarity"] == DefectPolarity.BRIGHT.value
                    ),
                    "dark_worst_absolute_delta_gray": min(
                        abs(row["delta_gray"])
                        for row in rows
                        if row["polarity"] == DefectPolarity.DARK.value
                    ),
                },
                severity=Severity.S3,
                sample_count=len(rows),
                evidence_sources=[
                    inputs.catalog.approval_record_source,
                    *image_sources,
                ],
                metadata={**metadata, "non_graded": True},
            )
        return _G6Value(
            value=min(polarity_worst.values()),
            severity=None,
            sample_count=len(rows),
            evidence_sources=[
                inputs.catalog.approval_record_source,
                *image_sources,
            ],
            metadata=metadata,
        )

    def _ng_detection(self, inputs: G6MeasurementInputs) -> _G6Value:
        decisions = self._validate_results(inputs)
        ng_samples = [
            sample
            for sample in inputs.catalog.samples
            if sample.disposition == GoldenDisposition.NG
        ]
        if not ng_samples:
            raise G6MeasurementError("approved Golden catalog contains no NG samples")
        ng_decisions = [decisions[sample.sample_id] for sample in ng_samples]
        detected = sum(item.detected for item in ng_decisions)
        misses = [item.sample_id for item in ng_decisions if not item.detected]
        retries = [
            item.sample_id
            for item in ng_decisions
            if item.detected and item.capture_attempts > 1
        ]
        worst_margin = min(item.margin_pct for item in ng_decisions)
        if misses:
            severity = Severity.S0
        elif retries or worst_margin < 10:
            severity = Severity.S1
        elif worst_margin < 30:
            severity = Severity.S2
        else:
            severity = Severity.S3
        numerator = detected
        denominator = len(ng_decisions)
        return _G6Value(
            value={
                "detected": numerator,
                "total": denominator,
                "rate_pct": numerator / denominator * 100.0,
                "worst_margin_pct": worst_margin,
                "retry_count": len(retries),
            },
            severity=severity,
            sample_count=denominator,
            evidence_sources=self._sources(inputs),
            metadata={
                "ratio": _ratio_metadata(numerator, denominator),
                "stable_miss_sample_ids": misses,
                "retry_pass_sample_ids": retries,
                "detector_id": inputs.detector_results.detector_id,
                "detector_version": inputs.detector_results.detector_version,
                "decision_rule_version": inputs.detector_results.decision_rule_version,
            },
        )

    def _samples_per_type(self, inputs: G6MeasurementInputs) -> _G6Value:
        counts = {
            defect_type: sum(
                sample.disposition == GoldenDisposition.NG
                and sample.defect_type == defect_type
                for sample in inputs.catalog.samples
            )
            for defect_type in inputs.catalog.required_defect_types
        }
        minimum = min(counts.values())
        return _G6Value(
            value=minimum,
            severity=None,
            sample_count=sum(counts.values()),
            evidence_sources=[inputs.catalog.approval_record_source],
            metadata={"counts_by_required_type": counts, "aggregation": "minimum"},
        )

    def _type_coverage(self, inputs: G6MeasurementInputs) -> _G6Value:
        required = list(inputs.catalog.required_defect_types)
        covered = sorted(
            {
                sample.defect_type
                for sample in inputs.catalog.samples
                if sample.disposition == GoldenDisposition.NG
                and sample.defect_type in required
            }
        )
        numerator = len(covered)
        denominator = len(required)
        value = numerator / denominator * 100.0
        return _G6Value(
            value=value,
            severity=None,
            sample_count=denominator,
            evidence_sources=[inputs.catalog.approval_record_source],
            metadata={
                "ratio": _ratio_metadata(numerator, denominator),
                "covered_types": covered,
                "missing_types": sorted(set(required) - set(covered)),
            },
        )

    def _pass_counts(
        self, inputs: G6MeasurementInputs
    ) -> Tuple[int, int, List[str]]:
        decisions = self._validate_results(inputs)
        pass_samples = [
            sample
            for sample in inputs.catalog.samples
            if sample.disposition == GoldenDisposition.PASS
        ]
        if not pass_samples:
            raise G6MeasurementError("approved Golden catalog contains no PASS samples")
        false_ids = [
            sample.sample_id
            for sample in pass_samples
            if decisions[sample.sample_id].detected
        ]
        return len(false_ids), len(pass_samples), false_ids

    def _false_positive(self, inputs: G6MeasurementInputs) -> _G6Value:
        numerator, denominator, false_ids = self._pass_counts(inputs)
        value = numerator / denominator * 100.0
        metric = self.specification.get_metric("g6.golden_pass_false_positive_pct")
        severity = metric.classify(value)
        insufficient = denominator < 200
        if insufficient and severity in {Severity.S3, Severity.S2}:
            severity = Severity.S1
        return _G6Value(
            value=value,
            severity=severity,
            sample_count=denominator,
            evidence_sources=self._sources(inputs),
            metadata={
                "ratio": _ratio_metadata(numerator, denominator),
                "false_positive_sample_ids": false_ids,
                "minimum_pass_samples": 200,
                "sample_size_restricted_grade": insufficient,
            },
        )

    def _false_positive_upper(self, inputs: G6MeasurementInputs) -> _G6Value:
        numerator, denominator, false_ids = self._pass_counts(inputs)
        upper = clopper_pearson_upper(numerator, denominator, confidence=0.95)
        return _G6Value(
            value=upper * 100.0,
            severity=None,
            sample_count=denominator,
            evidence_sources=self._sources(inputs),
            metadata={
                "ratio": {
                    **_ratio_metadata(numerator, denominator),
                    "clopper_pearson_one_sided_95": [0.0, upper],
                },
                "false_positive_sample_ids": false_ids,
            },
        )

    def _full_width(self, inputs: G6MeasurementInputs) -> _G6Value:
        decisions = self._validate_results(inputs)
        required_regions = list(FullWidthRegion)
        counts: Dict[str, Tuple[int, int]] = {}
        missed_by_region: Dict[str, List[str]] = {}
        for region in required_regions:
            samples = [
                sample
                for sample in inputs.catalog.samples
                if sample.disposition == GoldenDisposition.NG
                and sample.full_width_region == region
            ]
            if not samples:
                raise G6MeasurementError(
                    f"full-width detection has no approved NG sample in {region.value}"
                )
            detected = sum(decisions[sample.sample_id].detected for sample in samples)
            counts[region.value] = (detected, len(samples))
            missed_by_region[region.value] = [
                sample.sample_id
                for sample in samples
                if not decisions[sample.sample_id].detected
            ]
        rates = {
            region: numerator / denominator * 100.0
            for region, (numerator, denominator) in counts.items()
        }
        value = max(rates.values()) - min(rates.values())
        any_miss = any(missed_by_region.values())
        return _G6Value(
            value=value,
            severity=Severity.S0 if any_miss else None,
            sample_count=sum(denominator for _, denominator in counts.values()),
            evidence_sources=self._sources(inputs),
            metadata={
                "rates_pct_by_region": rates,
                "ratios_by_region": {
                    region: _ratio_metadata(numerator, denominator)
                    for region, (numerator, denominator) in counts.items()
                },
                "missed_sample_ids_by_region": missed_by_region,
            },
        )

    def _priority_events(self, inputs: G6MeasurementInputs) -> List[S0PriorityEvent]:
        events: List[S0PriorityEvent] = []
        try:
            decisions = self._validate_results(inputs)
        except GoldenCatalogError:
            return events
        ng_samples = [
            sample
            for sample in inputs.catalog.samples
            if sample.disposition == GoldenDisposition.NG
        ]
        stable_misses = [
            sample.sample_id
            for sample in ng_samples
            if not decisions[sample.sample_id].detected
        ]
        if stable_misses:
            events.append(
                S0PriorityEvent(
                    event_type=S0PriorityEventType.GOLDEN_NG_STABLE_MISS,
                    description=(
                        "approved Golden NG stable miss: " + ", ".join(stable_misses)
                    ),
                    evidence_sources=self._sources(inputs),
                )
            )
        narrow = [
            sample.sample_id
            for sample in ng_samples
            if sample.effective_width_px is not None
            and sample.effective_width_px < 2.0
        ]
        if narrow:
            events.append(
                S0PriorityEvent(
                    event_type=S0PriorityEventType.MINIMUM_DEFECT_UNRECOGNIZABLE,
                    description=(
                        "approved Golden effective defect width <2 px: "
                        + ", ".join(narrow)
                    ),
                    evidence_sources=[
                        inputs.catalog.approval_record_source,
                        *(
                            sample.image_source
                            for sample in ng_samples
                            if sample.sample_id in narrow
                        ),
                    ],
                )
            )
        if inputs.minimum_defect_recognizable is False:
            if not inputs.recognizability_evidence_source:
                return events
            events.append(
                S0PriorityEvent(
                    event_type=S0PriorityEventType.MINIMUM_DEFECT_UNRECOGNIZABLE,
                    description="minimum approved defect is not visually recognizable",
                    evidence_sources=[inputs.recognizability_evidence_source],
                )
            )
        return events


def _sample_cnr(sample: GoldenSample, image: np.ndarray) -> Tuple[float, float, float]:
    if image.ndim != 2 or image.size == 0 or not np.all(np.isfinite(image)):
        raise G6MeasurementError(f"Golden image {sample.sample_id} must be a finite 2D array")
    defect_roi = sample.defect_roi
    background_ring = sample.background_ring
    assert defect_roi is not None and background_ring is not None
    height, width = image.shape
    defect_roi.validate_for_shape(width, height)
    background_ring.validate_for_shape(width, height)
    defect: np.ndarray = image[
        defect_roi.y : defect_roi.y2,
        defect_roi.x : defect_roi.x2,
    ].astype(np.float64)
    ring: np.ndarray = image[
        background_ring.y : background_ring.y2,
        background_ring.x : background_ring.x2,
    ].astype(np.float64)
    mask = np.ones(ring.shape, dtype=bool)
    y1 = defect_roi.y - background_ring.y
    x1 = defect_roi.x - background_ring.x
    mask[y1 : y1 + defect_roi.height, x1 : x1 + defect_roi.width] = False
    background = ring[mask]
    if background.size < 20:
        raise G6MeasurementError(
            f"Golden sample {sample.sample_id} background ring has fewer than 20 pixels"
        )
    defect_mean = float(np.mean(defect))
    background_mean = float(np.mean(background))
    background_std = float(np.std(background, ddof=1))
    if background_std <= 0:
        raise G6MeasurementError(
            f"Golden sample {sample.sample_id} background standard deviation is zero"
        )
    delta = defect_mean - background_mean
    if sample.defect_polarity == DefectPolarity.BRIGHT and delta <= 0:
        raise G6MeasurementError(
            f"Golden sample {sample.sample_id} bright polarity disagrees with ROI signal"
        )
    if sample.defect_polarity == DefectPolarity.DARK and delta >= 0:
        raise G6MeasurementError(
            f"Golden sample {sample.sample_id} dark polarity disagrees with ROI signal"
        )
    return abs(delta) / background_std, delta, background_std


def _ratio_metadata(numerator: int, denominator: int) -> Dict[str, Any]:
    lower, upper = wilson_interval(numerator, denominator, confidence=0.95)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator,
        "confidence_interval_95": [lower, upper],
        "interval_method": "Wilson score",
    }


def wilson_interval(
    successes: int, total: int, *, confidence: float = 0.95
) -> Tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise G6MeasurementError("ratio requires 0 <= numerator <= denominator and denominator > 0")
    if confidence != 0.95:
        raise G6MeasurementError("only the audited 95% Wilson interval is supported")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - half), min(1.0, center + half)


def clopper_pearson_upper(
    successes: int, total: int, *, confidence: float = 0.95
) -> float:
    """Exact one-sided binomial upper confidence bound."""
    if total <= 0 or not 0 <= successes <= total:
        raise G6MeasurementError("Clopper-Pearson requires a valid binomial ratio")
    if not 0 < confidence < 1:
        raise G6MeasurementError("confidence must be between zero and one")
    if successes == total:
        return 1.0
    alpha = 1.0 - confidence
    if successes == 0:
        return 1.0 - alpha ** (1.0 / total)
    low = successes / total
    high = 1.0
    for _ in range(80):
        midpoint = (low + high) / 2.0
        cdf = _binomial_cdf(successes, total, midpoint)
        if cdf > alpha:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    if probability <= 0:
        return 1.0
    if probability >= 1:
        return 0.0 if k < n else 1.0
    log_p = math.log(probability)
    log_q = math.log1p(-probability)
    logs = [
        math.lgamma(n + 1)
        - math.lgamma(index + 1)
        - math.lgamma(n - index + 1)
        + index * log_p
        + (n - index) * log_q
        for index in range(k + 1)
    ]
    maximum = max(logs)
    return math.exp(maximum) * sum(math.exp(value - maximum) for value in logs)
