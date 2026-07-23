# -*- coding: utf-8 -*-
"""v4 驗收資料集 manifest、前提鎖定與影像證據追溯。"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .v4_domain import ImageLevel, OpticalMode


class ManifestError(ValueError):
    """Manifest、sidecar 或前提鎖定內容不可信。"""


_REQUIRED_LOCK_FIELDS: Dict[str, Tuple[str, ...]] = {
    "camera": (
        "model",
        "serial",
        "bit_depth",
        "gain",
        "exposure_us",
        "line_rate_hz",
        "binning",
        "sensor_roi",
        "internal_calibration",
        "auto_features",
    ),
    "optics": (
        "lens_model",
        "aperture",
        "working_distance_mm",
        "filter",
        "polarizer",
        "magnification",
        "micrometers_per_pixel",
        "focus_position",
    ),
    "lighting": (
        "model",
        "drive_mode",
        "drive_value",
        "measured_illuminance",
        "angle_deg",
        "distance_mm",
        "polarization",
        "aging_hours",
    ),
    "mechanics": (
        "scan_speed",
        "encoder_resolution",
        "trigger_mode",
        "vibration_state",
        "fixture_state",
    ),
    "environment": (
        "ambient_light_shielded",
        "temperature_c",
        "relative_humidity_pct",
        "warmup_minutes",
    ),
    "sample": (
        "sample_id",
        "batch_id",
        "orientation",
        "surface_cleanliness",
        "golden_approved",
    ),
    "computation": (
        "roi_version",
        "formula_version",
        "script_version",
    ),
    "data": (
        "raw_format",
        "timestamp_source",
        "parameter_record_source",
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical_json(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass
class PreconditionLock:
    """第 2 節八類鎖定參數；所有欄位都參與 session 指紋。"""

    camera: Dict[str, Any]
    optics: Dict[str, Any]
    lighting: Dict[str, Any]
    mechanics: Dict[str, Any]
    environment: Dict[str, Any]
    sample: Dict[str, Any]
    computation: Dict[str, Any]
    data: Dict[str, Any]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.schema_version != "1.0":
            raise ManifestError(
                f"不支援的 PreconditionLock schema_version：{self.schema_version}"
            )
        for category, required in _REQUIRED_LOCK_FIELDS.items():
            values = getattr(self, category)
            if not isinstance(values, dict):
                raise ManifestError(f"precondition.{category} 必須是物件")
            missing = [key for key in required if key not in values or _is_missing(values[key])]
            if missing:
                raise ManifestError(
                    f"precondition.{category} 缺少欄位：{', '.join(missing)}"
                )
        warmup = self.warmup_minutes
        if warmup < 0:
            raise ManifestError("warmup_minutes 不得小於 0")
        bit_depth = int(self.camera["bit_depth"])
        if bit_depth not in (8, 10, 12, 14, 16):
            raise ManifestError("camera.bit_depth 僅支援 8、10、12、14、16")

    @property
    def warmup_minutes(self) -> float:
        try:
            return float(self.environment["warmup_minutes"])
        except (TypeError, ValueError) as exc:
            raise ManifestError("environment.warmup_minutes 必須是數值") from exc

    @property
    def measurements_valid(self) -> bool:
        """規範要求暖機至少 30 分鐘，未達時整輪數據無效。"""
        return self.warmup_minutes >= 30.0

    @property
    def invalid_reason(self) -> str:
        if self.measurements_valid:
            return ""
        return f"暖機僅 {self.warmup_minutes:g} 分鐘，低於規範要求的 30 分鐘"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "camera": dict(self.camera),
            "optics": dict(self.optics),
            "lighting": dict(self.lighting),
            "mechanics": dict(self.mechanics),
            "environment": dict(self.environment),
            "sample": dict(self.sample),
            "computation": dict(self.computation),
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreconditionLock":
        try:
            return cls(
                camera=dict(data["camera"]),
                optics=dict(data["optics"]),
                lighting=dict(data["lighting"]),
                mechanics=dict(data["mechanics"]),
                environment=dict(data["environment"]),
                sample=dict(data["sample"]),
                computation=dict(data["computation"]),
                data=dict(data["data"]),
                schema_version=str(data.get("schema_version", "1.0")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"PreconditionLock 格式錯誤：{exc}") from exc

    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def changed_fields(self, other: "PreconditionLock") -> List[str]:
        left = self.to_dict()
        right = other.to_dict()
        changes: List[str] = []
        for category in _REQUIRED_LOCK_FIELDS:
            keys = sorted(set(left[category]) | set(right[category]))
            for key in keys:
                if left[category].get(key) != right[category].get(key):
                    changes.append(f"{category}.{key}")
        return changes


@dataclass
class ImageEvidence:
    """一張來源影像的不可猜測追溯資訊。"""

    relative_path: str
    sha256: str
    size_bytes: int
    mtime_ns: int
    image_level: ImageLevel
    calibration_version: str
    sidecar_relative_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        path = Path(self.relative_path)
        if path.is_absolute() or ".." in path.parts or not self.relative_path.strip():
            raise ManifestError("relative_path 必須是資料集內的安全相對路徑")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ManifestError("sha256 必須是 64 位小寫十六進位")
        if self.size_bytes < 0 or self.mtime_ns < 0:
            raise ManifestError("檔案大小與 mtime_ns 不得為負")
        if self.image_level == ImageLevel.L1 and not self.calibration_version.strip():
            raise ManifestError("L1 影像必須記錄 calibration_version")
        if not self.sidecar_relative_path.strip():
            raise ManifestError("正式影像證據必須記錄 sidecar_relative_path")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "image_level": self.image_level.value,
            "calibration_version": self.calibration_version,
            "sidecar_relative_path": self.sidecar_relative_path,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageEvidence":
        return cls(
            relative_path=str(data["relative_path"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
            mtime_ns=int(data["mtime_ns"]),
            image_level=ImageLevel(data["image_level"]),
            calibration_version=str(data.get("calibration_version", "")),
            sidecar_relative_path=str(data["sidecar_relative_path"]),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AcceptanceDatasetManifest:
    """一組不得跨前提混算的正式驗收資料集。"""

    machine_id: str
    optical_mode: OpticalMode
    precondition_lock: PreconditionLock
    images: List[ImageEvidence] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spec_version: str = "v4-draft"
    schema_version: str = "1.0"
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        if not self.machine_id.strip() or not self.session_id.strip():
            raise ManifestError("machine_id 與 session_id 不得為空")
        if self.schema_version != "1.0":
            raise ManifestError(f"不支援的 dataset schema_version：{self.schema_version}")
        paths = [image.relative_path for image in self.images]
        if len(paths) != len(set(paths)):
            raise ManifestError("同一 dataset manifest 不得包含重複 relative_path")

    @property
    def measurements_valid(self) -> bool:
        return self.precondition_lock.measurements_valid

    @property
    def invalid_reason(self) -> str:
        return self.precondition_lock.invalid_reason

    def add_image(self, image: ImageEvidence) -> None:
        if any(item.relative_path == image.relative_path for item in self.images):
            raise ManifestError(f"影像路徑重複：{image.relative_path}")
        self.images.append(image)

    def to_dict(self, *, include_manifest_hash: bool = True) -> Dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "machine_id": self.machine_id,
            "optical_mode": self.optical_mode.value,
            "spec_version": self.spec_version,
            "created_at": self.created_at,
            "measurements_valid": self.measurements_valid,
            "invalid_reason": self.invalid_reason,
            "precondition_lock": self.precondition_lock.to_dict(),
            "images": [image.to_dict() for image in self.images],
        }
        if include_manifest_hash:
            data["manifest_hash"] = self.manifest_hash()
        return data

    def manifest_hash(self) -> str:
        payload = self.to_dict(include_manifest_hash=False)
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(self.to_json())
            stream.write("\n")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcceptanceDatasetManifest":
        expected_hash = str(data.get("manifest_hash", ""))
        manifest = cls(
            machine_id=str(data["machine_id"]),
            optical_mode=OpticalMode(data["optical_mode"]),
            precondition_lock=PreconditionLock.from_dict(dict(data["precondition_lock"])),
            images=[ImageEvidence.from_dict(dict(item)) for item in data.get("images", [])],
            session_id=str(data["session_id"]),
            spec_version=str(data["spec_version"]),
            schema_version=str(data.get("schema_version", "1.0")),
            created_at=str(data["created_at"]),
        )
        if expected_hash and expected_hash != manifest.manifest_hash():
            raise ManifestError("dataset manifest_hash 驗證失敗，內容可能已被修改")
        return manifest

    @classmethod
    def load_json(cls, path: str) -> "AcceptanceDatasetManifest":
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ManifestError("dataset manifest JSON 必須是物件")
        return cls.from_dict(data)


@dataclass(frozen=True)
class SessionInput:
    """依前提指紋切分 session 時的一筆輸入。"""

    precondition_lock: PreconditionLock
    image: ImageEvidence


@dataclass
class SessionPartition:
    session_id: str
    precondition_lock: PreconditionLock
    images: List[ImageEvidence]
    changed_fields_from_previous: List[str] = field(default_factory=list)


def partition_sessions(records: Sequence[SessionInput]) -> List[SessionPartition]:
    """依輸入順序切分；任一鎖定值改變即建立新 session。"""
    partitions: List[SessionPartition] = []
    for record in records:
        if (
            not partitions
            or partitions[-1].precondition_lock.fingerprint()
            != record.precondition_lock.fingerprint()
        ):
            changes = (
                partitions[-1].precondition_lock.changed_fields(record.precondition_lock)
                if partitions
                else []
            )
            partitions.append(
                SessionPartition(
                    session_id=str(uuid.uuid4()),
                    precondition_lock=record.precondition_lock,
                    images=[record.image],
                    changed_fields_from_previous=changes,
                )
            )
        else:
            partitions[-1].images.append(record.image)
    return partitions


def sha256_file(path: str, *, chunk_size: int = 1024 * 1024) -> str:
    if chunk_size <= 0:
        raise ValueError("chunk_size 必須為正數")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_candidates(image_path: str) -> List[str]:
    """回傳固定檔名規則；不從影像內容猜測 metadata。"""
    image = Path(image_path)
    return [
        str(image.with_name(image.name + ".json")),
        str(image.with_suffix(".json")),
        str(image.with_name(image.name + ".csv")),
        str(image.with_suffix(".csv")),
    ]


def load_image_sidecar(image_path: str) -> Tuple[Dict[str, Any], str]:
    candidates = (
        path for path in sidecar_candidates(image_path) if os.path.isfile(path)
    )
    matches = list(dict.fromkeys(candidates))
    if not matches:
        raise ManifestError(f"找不到影像 sidecar：{image_path}")
    if len(matches) > 1:
        raise ManifestError(f"影像 sidecar 不唯一：{', '.join(matches)}")
    path = matches[0]
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ManifestError("sidecar JSON 必須是物件")
        return dict(data), path
    return _load_sidecar_csv(path), path


def _load_sidecar_csv(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows:
        raise ManifestError("sidecar CSV 不得為空")
    if rows[0] == ["key", "value"]:
        result: Dict[str, Any] = {}
        for row_number, row in enumerate(rows[1:], start=2):
            if len(row) != 2 or not row[0].strip():
                raise ManifestError(f"sidecar CSV 第 {row_number} 列必須是 key,value")
            if row[0] in result:
                raise ManifestError(f"sidecar CSV key 重複：{row[0]}")
            result[row[0]] = row[1]
        return result
    if len(rows) != 2 or len(rows[0]) != len(rows[1]):
        raise ManifestError("sidecar CSV 必須是單列寬表，或 key,value 長表")
    if len(set(rows[0])) != len(rows[0]) or any(not key.strip() for key in rows[0]):
        raise ManifestError("sidecar CSV 表頭不得空白或重複")
    return dict(zip(rows[0], rows[1]))


def build_image_evidence(image_path: str, dataset_root: str) -> ImageEvidence:
    """由檔案系統可證實資訊與唯一 sidecar 建立影像證據。"""
    root = Path(dataset_root).resolve()
    image = Path(image_path).resolve()
    try:
        relative = image.relative_to(root)
    except ValueError as exc:
        raise ManifestError("影像必須位於 dataset_root 內") from exc
    metadata, sidecar_path = load_image_sidecar(str(image))
    try:
        image_level = ImageLevel(str(metadata["image_level"]))
    except (KeyError, ValueError) as exc:
        raise ManifestError("sidecar 必須明確提供有效 image_level") from exc
    calibration_version = str(metadata.get("calibration_version", ""))
    if image_level == ImageLevel.L1 and not calibration_version.strip():
        raise ManifestError("L1 sidecar 必須提供 calibration_version")
    stat = image.stat()
    try:
        sidecar_relative = Path(sidecar_path).resolve().relative_to(root)
    except ValueError as exc:
        raise ManifestError("sidecar 必須位於 dataset_root 內") from exc
    return ImageEvidence(
        relative_path=relative.as_posix(),
        sha256=sha256_file(str(image)),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        image_level=image_level,
        calibration_version=calibration_version,
        sidecar_relative_path=sidecar_relative.as_posix(),
        metadata=metadata,
    )


def build_dataset_manifest(
    *,
    dataset_root: str,
    machine_id: str,
    optical_mode: OpticalMode,
    precondition_lock: PreconditionLock,
    image_paths: Iterable[str],
    spec_version: str = "v4-draft",
) -> AcceptanceDatasetManifest:
    manifest = AcceptanceDatasetManifest(
        machine_id=machine_id,
        optical_mode=optical_mode,
        precondition_lock=precondition_lock,
        spec_version=spec_version,
    )
    for path in image_paths:
        manifest.add_image(build_image_evidence(path, dataset_root))
    return manifest
