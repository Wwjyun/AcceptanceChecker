# -*- coding: utf-8 -*-
"""Formal v4 G5 acquisition-integrity and multi-camera stitching measurements."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .dataset_manifest import AcceptanceDatasetManifest
from .specification import V4Specification, load_default_v4_spec
from .traceability import TraceabilityValidator
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, Severity


class G5MeasurementError(ValueError):
    """Raised when the evidence cannot support a formal G5 measurement."""


@dataclass(frozen=True)
class ImageContract:
    width: int
    height: int
    bit_depth: int
    evidence_source: str
    contract_version: str

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise G5MeasurementError("expected image dimensions must be positive")
        if self.bit_depth not in {8, 10, 12, 14, 16}:
            raise G5MeasurementError("expected bit depth must be 8, 10, 12, 14, or 16")
        if not self.evidence_source or not self.contract_version:
            raise G5MeasurementError("image contract requires source and version")


@dataclass(frozen=True)
class ImageObservation:
    source: str
    width: int
    height: int
    bit_depth: int
    scan_sequence_id: str

    def __post_init__(self) -> None:
        if not self.source or not self.scan_sequence_id:
            raise G5MeasurementError("image observation requires source and sequence id")
        if self.width <= 0 or self.height <= 0 or self.bit_depth <= 0:
            raise G5MeasurementError("observed image contract values must be positive")


@dataclass(frozen=True)
class AcquisitionIntegrityEvidence:
    """Expected and observed identifiers from a log or encoder/timestamp evidence."""

    basis: str
    evidence_source: str
    method_version: str
    expected_line_ids: Sequence[int] = field(default_factory=tuple)
    observed_line_ids: Sequence[int] = field(default_factory=tuple)
    expected_frame_ids: Sequence[int] = field(default_factory=tuple)
    observed_frame_ids: Sequence[int] = field(default_factory=tuple)
    interruption_events: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.basis not in {"acquisition_log", "encoder_timestamp"}:
            raise G5MeasurementError(
                "integrity basis must be acquisition_log or encoder_timestamp"
            )
        if not self.evidence_source or not self.method_version:
            raise G5MeasurementError("integrity evidence requires source and method version")
        identifiers = (
            *self.expected_line_ids,
            *self.observed_line_ids,
            *self.expected_frame_ids,
            *self.observed_frame_ids,
        )
        if any(not isinstance(item, int) or item < 0 for item in identifiers):
            raise G5MeasurementError("line and frame identifiers must be non-negative integers")
        if any(not str(item).strip() for item in self.interruption_events):
            raise G5MeasurementError("interruption event identifiers cannot be empty")


@dataclass(frozen=True)
class StitchEvidence:
    required: bool
    evidence_sources: Sequence[str]
    method_version: str
    left_band: Optional[np.ndarray] = None
    right_band: Optional[np.ndarray] = None
    position_residuals_px: Sequence[float] = field(default_factory=tuple)
    blind_zone_widths_px: Sequence[float] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.evidence_sources or not self.method_version:
            raise G5MeasurementError("stitch evidence requires sources and method version")
        if self.required:
            if self.left_band is None or self.right_band is None:
                raise G5MeasurementError("required stitching needs two seam bands")
            if self.left_band.ndim != 2 or self.right_band.ndim != 2:
                raise G5MeasurementError("stitch seam bands must be two-dimensional")
            if self.left_band.shape != self.right_band.shape or self.left_band.size == 0:
                raise G5MeasurementError("stitch seam bands must have the same non-empty shape")
            if not np.all(np.isfinite(self.left_band)) or not np.all(
                np.isfinite(self.right_band)
            ):
                raise G5MeasurementError("stitch seam bands contain NaN or Inf")
            if len(self.position_residuals_px) < 3:
                raise G5MeasurementError(
                    "stitch position error requires at least three matched features"
                )
            if not self.blind_zone_widths_px:
                raise G5MeasurementError("stitch blind-zone coverage evidence is required")
        numeric = (*self.position_residuals_px, *self.blind_zone_widths_px)
        if any(not np.isfinite(item) or item < 0 for item in numeric):
            raise G5MeasurementError("stitch residuals and blind widths must be finite and >= 0")


@dataclass(frozen=True)
class InterCameraGrayEvidence:
    camera_rois: Dict[str, np.ndarray]
    evidence_sources: Sequence[str]
    method_version: str

    def __post_init__(self) -> None:
        if not self.camera_rois:
            raise G5MeasurementError("at least one camera ROI is required")
        if not self.evidence_sources or not self.method_version:
            raise G5MeasurementError(
                "inter-camera evidence requires sources and method version"
            )
        shapes = set()
        for camera_id, roi in self.camera_rois.items():
            if not camera_id or roi.ndim != 2 or roi.size == 0:
                raise G5MeasurementError("camera ROIs require ids and non-empty 2D arrays")
            if not np.all(np.isfinite(roi)):
                raise G5MeasurementError("camera ROI contains NaN or Inf")
            shapes.add(roi.shape)
        if len(shapes) != 1:
            raise G5MeasurementError("camera ROIs must use equivalent coordinates and shape")


@dataclass
class G5MeasurementInputs:
    image_contract: Optional[ImageContract] = None
    image_observations: Sequence[ImageObservation] = field(default_factory=list)
    acquisition_integrity: Optional[AcquisitionIntegrityEvidence] = None
    stitch: Optional[StitchEvidence] = None
    inter_camera: Optional[InterCameraGrayEvidence] = None
    manifest: Optional[AcceptanceDatasetManifest] = None


@dataclass
class G5MeasurementReport:
    measurements: List[MeasurementResult]


@dataclass
class _G5Value:
    value: Any
    severity: Optional[Severity]
    sample_count: int
    evidence_sources: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class G5Measurer:
    """Produce every formal G5 metric without inferring zero from absent logs."""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()
        self.traceability = TraceabilityValidator(self.specification)

    def measure(self, inputs: G5MeasurementInputs) -> G5MeasurementReport:
        results: List[MeasurementResult] = []
        for metric in self.specification.metrics:
            if metric.group != MetricGroup.G5:
                continue
            try:
                computed = self._compute(metric.metric_id, inputs)
                severity = computed.severity or metric.classify(float(computed.value))
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G5,
                        severity=severity,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=ImageLevel.L1,
                        value=computed.value,
                        sample_count=computed.sample_count,
                        evidence_sources=list(dict.fromkeys(computed.evidence_sources)),
                        metadata={
                            "requirement_profile": metric.requirement_profile,
                            **computed.metadata,
                        },
                    )
                )
            except G5MeasurementError as exc:
                results.append(
                    MeasurementResult(
                        metric_id=metric.metric_id,
                        group=MetricGroup.G5,
                        severity=Severity.NOT_EVALUATED,
                        unit=metric.unit,
                        formula_version=self.specification.formula_version,
                        image_level=ImageLevel.L1,
                        value=None,
                        sample_count=0,
                        missing_reason=str(exc),
                        metadata={"requirement_profile": metric.requirement_profile},
                    )
                )
        return G5MeasurementReport(measurements=results)

    def _compute(self, metric_id: str, inputs: G5MeasurementInputs) -> _G5Value:
        if metric_id == "g5.missing_duplicate_lines":
            return self._line_integrity(inputs)
        if metric_id == "g5.image_shape_bit_depth_match":
            return self._image_contract(inputs)
        if metric_id == "g5.dropped_frames_interruptions":
            return self._frame_integrity(inputs)
        if metric_id == "g5.stitch_brightness_difference_pct":
            return self._stitch_brightness(inputs)
        if metric_id == "g5.stitch_position_error_px":
            return self._stitch_position(inputs)
        if metric_id == "g5.stitch_blind_width_px":
            return self._stitch_blind_width(inputs)
        if metric_id == "g5.inter_camera_gray_difference_pct":
            return self._inter_camera(inputs)
        if metric_id == "g5.traceability_completeness":
            return self._traceability(inputs)
        raise G5MeasurementError(f"unknown G5 metric: {metric_id}")

    @staticmethod
    def _require_integrity(inputs: G5MeasurementInputs) -> AcquisitionIntegrityEvidence:
        evidence = inputs.acquisition_integrity
        if evidence is None:
            raise G5MeasurementError(
                "acquisition log or encoder/timestamp evidence is required; "
                "absence cannot prove zero integrity events"
            )
        return evidence

    @staticmethod
    def _anomalies(
        expected: Sequence[int], observed: Sequence[int], label: str
    ) -> Dict[str, List[int]]:
        if not expected or not observed:
            raise G5MeasurementError(f"{label} expected and observed identifiers are required")
        expected_counts = Counter(expected)
        observed_counts = Counter(observed)
        missing: List[int] = []
        duplicate: List[int] = []
        unexpected: List[int] = []
        for identifier, count in expected_counts.items():
            missing.extend([identifier] * max(count - observed_counts[identifier], 0))
        for identifier, count in observed_counts.items():
            duplicate.extend([identifier] * max(count - expected_counts[identifier], 0))
            if identifier not in expected_counts:
                unexpected.extend([identifier] * count)
        return {
            "missing": sorted(missing),
            "duplicate_or_unexpected": sorted(duplicate),
            "unexpected": sorted(unexpected),
        }

    def _line_integrity(self, inputs: G5MeasurementInputs) -> _G5Value:
        evidence = self._require_integrity(inputs)
        anomalies = self._anomalies(
            evidence.expected_line_ids, evidence.observed_line_ids, "line"
        )
        count = len(anomalies["missing"]) + len(anomalies["duplicate_or_unexpected"])
        return _G5Value(
            value=count,
            severity=None,
            sample_count=len(evidence.observed_line_ids),
            evidence_sources=[evidence.evidence_source],
            metadata={
                "basis": evidence.basis,
                "method_version": evidence.method_version,
                **anomalies,
            },
        )

    @staticmethod
    def _image_contract(inputs: G5MeasurementInputs) -> _G5Value:
        contract = inputs.image_contract
        if contract is None or not inputs.image_observations:
            raise G5MeasurementError("image contract and observed image headers are required")
        mismatches: List[Dict[str, Any]] = []
        sequence_owners: Dict[str, str] = {}
        for item in inputs.image_observations:
            actual = (item.width, item.height, item.bit_depth)
            expected = (contract.width, contract.height, contract.bit_depth)
            if actual != expected:
                mismatches.append(
                    {
                        "source": item.source,
                        "expected": list(expected),
                        "actual": list(actual),
                    }
                )
            previous = sequence_owners.setdefault(item.scan_sequence_id, item.source)
            if previous != item.source:
                mismatches.append(
                    {
                        "source": item.source,
                        "duplicate_scan_sequence_id": item.scan_sequence_id,
                        "previous_source": previous,
                    }
                )
        severity = Severity.S3 if not mismatches else Severity.S0
        return _G5Value(
            value=not mismatches,
            severity=severity,
            sample_count=len(inputs.image_observations),
            evidence_sources=[
                contract.evidence_source,
                *(item.source for item in inputs.image_observations),
            ],
            metadata={
                "contract_version": contract.contract_version,
                "expected": [contract.width, contract.height, contract.bit_depth],
                "mismatches": mismatches,
            },
        )

    def _frame_integrity(self, inputs: G5MeasurementInputs) -> _G5Value:
        evidence = self._require_integrity(inputs)
        anomalies = self._anomalies(
            evidence.expected_frame_ids, evidence.observed_frame_ids, "frame"
        )
        count = (
            len(anomalies["missing"])
            + len(anomalies["duplicate_or_unexpected"])
            + len(evidence.interruption_events)
        )
        return _G5Value(
            value=count,
            severity=None,
            sample_count=len(evidence.observed_frame_ids),
            evidence_sources=[evidence.evidence_source],
            metadata={
                "basis": evidence.basis,
                "method_version": evidence.method_version,
                "interruption_events": list(evidence.interruption_events),
                **anomalies,
            },
        )

    @staticmethod
    def _require_stitch(inputs: G5MeasurementInputs) -> StitchEvidence:
        if inputs.stitch is None:
            raise G5MeasurementError(
                "stitching evidence or an explicit versioned single-camera declaration "
                "is required"
            )
        return inputs.stitch

    def _stitch_brightness(self, inputs: G5MeasurementInputs) -> _G5Value:
        stitch = self._require_stitch(inputs)
        if not stitch.required:
            return self._not_applicable_stitch(stitch)
        assert stitch.left_band is not None and stitch.right_band is not None
        left_mean = float(np.mean(stitch.left_band.astype(np.float64)))
        right_mean = float(np.mean(stitch.right_band.astype(np.float64)))
        denominator = (abs(left_mean) + abs(right_mean)) / 2.0
        if denominator <= 0:
            raise G5MeasurementError("stitch brightness denominator is zero")
        value = abs(left_mean - right_mean) / denominator * 100.0
        severity = Severity.S0 if max(stitch.blind_zone_widths_px) >= 1.0 else None
        return _G5Value(
            value=value,
            severity=severity,
            sample_count=int(stitch.left_band.size + stitch.right_band.size),
            evidence_sources=list(stitch.evidence_sources),
            metadata={
                "method_version": stitch.method_version,
                "left_mean": left_mean,
                "right_mean": right_mean,
                "blind_zone_forced_s0": severity == Severity.S0,
            },
        )

    def _stitch_position(self, inputs: G5MeasurementInputs) -> _G5Value:
        stitch = self._require_stitch(inputs)
        if not stitch.required:
            return self._not_applicable_stitch(stitch)
        value = float(max(stitch.position_residuals_px))
        return _G5Value(
            value=value,
            severity=None,
            sample_count=len(stitch.position_residuals_px),
            evidence_sources=list(stitch.evidence_sources),
            metadata={
                "method_version": stitch.method_version,
                "position_residuals_px": list(stitch.position_residuals_px),
                "aggregation": "maximum_absolute_residual",
            },
        )

    def _stitch_blind_width(self, inputs: G5MeasurementInputs) -> _G5Value:
        stitch = self._require_stitch(inputs)
        if not stitch.required:
            return self._not_applicable_stitch(stitch)
        value = float(max(stitch.blind_zone_widths_px))
        return _G5Value(
            value=value,
            severity=None,
            sample_count=len(stitch.blind_zone_widths_px),
            evidence_sources=list(stitch.evidence_sources),
            metadata={
                "method_version": stitch.method_version,
                "blind_zone_widths_px": list(stitch.blind_zone_widths_px),
                "aggregation": "maximum_uncovered_width",
            },
        )

    @staticmethod
    def _not_applicable_stitch(stitch: StitchEvidence) -> _G5Value:
        return _G5Value(
            value=0.0,
            severity=Severity.S3,
            sample_count=1,
            evidence_sources=list(stitch.evidence_sources),
            metadata={
                "method_version": stitch.method_version,
                "not_applicable": True,
                "architecture": "single_camera_no_stitch",
            },
        )

    @staticmethod
    def _inter_camera(inputs: G5MeasurementInputs) -> _G5Value:
        evidence = inputs.inter_camera
        if evidence is None:
            raise G5MeasurementError(
                "equivalent camera ROIs or an explicit single-camera ROI record are required"
            )
        camera_means = {
            camera_id: float(np.mean(roi.astype(np.float64)))
            for camera_id, roi in evidence.camera_rois.items()
        }
        if len(camera_means) == 1:
            value = 0.0
        else:
            means = list(camera_means.values())
            denominator = (max(means) + min(means)) / 2.0
            if denominator <= 0:
                raise G5MeasurementError("inter-camera gray denominator is zero")
            value = (max(means) - min(means)) / denominator * 100.0
        return _G5Value(
            value=value,
            severity=None,
            sample_count=sum(roi.size for roi in evidence.camera_rois.values()),
            evidence_sources=list(evidence.evidence_sources),
            metadata={
                "method_version": evidence.method_version,
                "camera_means": camera_means,
                "roi_shape": list(next(iter(evidence.camera_rois.values())).shape),
                "single_camera": len(camera_means) == 1,
            },
        )

    def _traceability(self, inputs: G5MeasurementInputs) -> _G5Value:
        if inputs.manifest is None:
            raise G5MeasurementError("dataset manifest is required for traceability")
        report = self.traceability.validate(inputs.manifest)
        measurement = report.measurement
        return _G5Value(
            value=measurement.value,
            severity=measurement.severity,
            sample_count=measurement.sample_count,
            evidence_sources=list(measurement.evidence_sources),
            metadata=dict(measurement.metadata),
        )
