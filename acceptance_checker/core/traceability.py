# -*- coding: utf-8 -*-
"""v4 第 11.1 節追溯性完整度驗證。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .dataset_manifest import AcceptanceDatasetManifest, ImageEvidence
from .specification import V4Specification, load_default_v4_spec
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, Severity

_REQUIRED_METADATA_FIELDS = (
    "timestamp",
    "camera_id",
    "scan_batch_id",
    "image_sequence_id",
    "exposure_us_actual",
    "gain_actual",
    "line_rate_hz_actual",
    "light_setting_actual",
    "sample_id",
    "sample_orientation",
    "scan_speed_actual",
    "encoder_start_count",
)

_OPTIONAL_METADATA_FIELDS = (
    "temperature_c",
    "relative_humidity_pct",
    "operator",
    "warmup_minutes",
    "lighting_hours",
    "notes",
)


@dataclass
class TraceabilityReport:
    severity: Severity
    measurement: MeasurementResult
    missing_required: Dict[str, List[str]] = field(default_factory=dict)
    inconsistent_required: Dict[str, List[str]] = field(default_factory=dict)
    s0_mismatches: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TraceabilityValidator:
    """把 dataset manifest 驗證成 G5 追溯性完整度指標。"""

    def __init__(self, specification: Optional[V4Specification] = None):
        self.specification = specification or load_default_v4_spec()

    def validate(self, manifest: AcceptanceDatasetManifest) -> TraceabilityReport:
        missing: Dict[str, List[str]] = {}
        inconsistent: Dict[str, List[str]] = {}
        fatal: List[str] = []
        warnings: List[str] = []
        sequence_owners: Dict[str, str] = {}
        timestamp_owners: Dict[Tuple[str, str], str] = {}

        if not manifest.images:
            missing["<dataset>"] = ["images"]

        for image in manifest.images:
            path = image.relative_path
            absent = [
                key
                for key in _REQUIRED_METADATA_FIELDS
                if key not in image.metadata or self._missing(image.metadata[key])
            ]
            if image.image_level == ImageLevel.L1 and not image.calibration_version:
                absent.append("calibration_version")
            if not image.sha256:
                absent.append("sha256")
            if absent:
                missing[path] = sorted(set(absent))

            optional_absent = [
                key
                for key in _OPTIONAL_METADATA_FIELDS
                if key not in image.metadata or self._missing(image.metadata[key])
            ]
            if optional_absent:
                warnings.append(
                    f"{path} 選填欄位缺失：{', '.join(optional_absent)}"
                )

            self._check_timestamp(image, inconsistent)
            self._check_locked_values(manifest, image, inconsistent, fatal)
            self._check_pairing(image, sequence_owners, timestamp_owners, fatal)

        severity = (
            Severity.S0
            if fatal
            else Severity.S1
            if missing or inconsistent
            else Severity.S3
        )
        metric = self.specification.get_metric("g5.traceability_completeness")
        measurement = MeasurementResult(
            metric_id=metric.metric_id,
            group=MetricGroup.G5,
            severity=severity,
            unit=metric.unit,
            formula_version=self.specification.formula_version,
            image_level=self._dataset_level(manifest.images),
            value={
                "status": severity.value,
                "image_count": len(manifest.images),
                "missing_required_count": sum(len(items) for items in missing.values()),
                "inconsistent_required_count": sum(
                    len(items) for items in inconsistent.values()
                ),
                "s0_mismatch_count": len(fatal),
            },
            sample_count=len(manifest.images),
            evidence_sources=[item.relative_path for item in manifest.images],
            metadata={
                "session_id": manifest.session_id,
                "spec_version": manifest.spec_version,
                "manifest_hash": manifest.manifest_hash(),
                "missing_required": missing,
                "inconsistent_required": inconsistent,
                "s0_mismatches": fatal,
                "optional_warnings": warnings,
            },
        )
        return TraceabilityReport(
            severity=severity,
            measurement=measurement,
            missing_required=missing,
            inconsistent_required=inconsistent,
            s0_mismatches=fatal,
            warnings=warnings,
        )

    @staticmethod
    def _check_timestamp(
        image: ImageEvidence,
        inconsistent: Dict[str, List[str]],
    ) -> None:
        value = image.metadata.get("timestamp")
        if TraceabilityValidator._missing(value):
            return
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            inconsistent.setdefault(image.relative_path, []).append(
                "timestamp 必須是 ISO-8601"
            )
            return
        if parsed.microsecond % 1000 != 0 and parsed.microsecond != 0:
            inconsistent.setdefault(image.relative_path, []).append(
                "timestamp 精度必須可明確對應毫秒"
            )
        if "." not in str(value):
            inconsistent.setdefault(image.relative_path, []).append(
                "timestamp 必須記錄至毫秒"
            )

    @staticmethod
    def _check_locked_values(
        manifest: AcceptanceDatasetManifest,
        image: ImageEvidence,
        inconsistent: Dict[str, List[str]],
        fatal: List[str],
    ) -> None:
        metadata = image.metadata
        lock = manifest.precondition_lock
        camera_id = metadata.get("camera_id")
        if not TraceabilityValidator._missing(camera_id):
            if str(camera_id) != str(lock.camera["serial"]):
                fatal.append(
                    f"{image.relative_path} camera_id={camera_id} "
                    f"與鎖定序號 {lock.camera['serial']} 錯配"
                )
        comparisons = {
            "exposure_us_actual": lock.camera["exposure_us"],
            "gain_actual": lock.camera["gain"],
            "line_rate_hz_actual": lock.camera["line_rate_hz"],
            "light_setting_actual": lock.lighting["drive_value"],
            "sample_id": lock.sample["sample_id"],
            "sample_orientation": lock.sample["orientation"],
            "scan_speed_actual": lock.mechanics["scan_speed"],
        }
        for key, expected in comparisons.items():
            if key in metadata and not TraceabilityValidator._missing(metadata[key]):
                if not TraceabilityValidator._equivalent(metadata[key], expected):
                    inconsistent.setdefault(image.relative_path, []).append(
                        f"{key}={metadata[key]!r} 與鎖定值 {expected!r} 不一致"
                    )

    @staticmethod
    def _check_pairing(
        image: ImageEvidence,
        sequence_owners: Dict[str, str],
        timestamp_owners: Dict[Tuple[str, str], str],
        fatal: List[str],
    ) -> None:
        metadata = image.metadata
        declared_path = metadata.get("source_relative_path")
        if not TraceabilityValidator._missing(declared_path):
            if str(declared_path).replace("\\", "/") != image.relative_path:
                fatal.append(
                    f"{image.relative_path} sidecar 宣告來源 {declared_path}，影像與參數無法配對"
                )
        sequence = metadata.get("image_sequence_id")
        if not TraceabilityValidator._missing(sequence):
            sequence_key = str(sequence)
            sequence_owner = sequence_owners.setdefault(sequence_key, image.relative_path)
            if sequence_owner != image.relative_path:
                fatal.append(
                    "image_sequence_id "
                    f"{sequence_key} 同時配對 {sequence_owner} 與 {image.relative_path}"
                )
        timestamp = metadata.get("timestamp")
        camera = metadata.get("camera_id")
        if not TraceabilityValidator._missing(timestamp) and not TraceabilityValidator._missing(
            camera
        ):
            timestamp_key = (str(timestamp), str(camera))
            timestamp_owner = timestamp_owners.setdefault(
                timestamp_key, image.relative_path
            )
            if timestamp_owner != image.relative_path:
                fatal.append(
                    "timestamp/camera ID "
                    f"{timestamp_key} 同時配對 {timestamp_owner} 與 {image.relative_path}"
                )

    @staticmethod
    def _dataset_level(images: List[ImageEvidence]) -> ImageLevel:
        levels: Set[ImageLevel] = {item.image_level for item in images}
        return next(iter(levels)) if len(levels) == 1 else ImageLevel.L2

    @staticmethod
    def _missing(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    @staticmethod
    def _equivalent(left: Any, right: Any) -> bool:
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return str(left).strip() == str(right).strip()
