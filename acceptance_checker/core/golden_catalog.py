# -*- coding: utf-8 -*-
"""Versioned, approved Golden sample catalogs and detector-result imports."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .g1_measurement import DefectPolarity
from .roi import RoiDefinition, RoiType


class GoldenCatalogError(ValueError):
    """Raised when Golden evidence is incomplete, inconsistent, or mutable."""


class GoldenDisposition(str, Enum):
    PASS = "PASS"
    NG = "NG"


class FullWidthRegion(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    STITCH = "stitch"


def _parse_iso8601(value: str, field_name: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoldenCatalogError(f"{field_name} must be ISO-8601") from exc


@dataclass(frozen=True)
class GoldenSample:
    sample_id: str
    disposition: GoldenDisposition
    image_source: str
    sha256: str
    batch_id: str
    orientation: str
    full_width_region: FullWidthRegion
    defect_type: str = ""
    defect_size_um: Optional[float] = None
    defect_size_px: Optional[float] = None
    effective_width_px: Optional[float] = None
    defect_direction: str = ""
    defect_polarity: DefectPolarity = DefectPolarity.UNSPECIFIED
    defect_position: str = ""
    defect_roi: Optional[RoiDefinition] = None
    background_ring: Optional[RoiDefinition] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = (
            self.sample_id,
            self.image_source,
            self.batch_id,
            self.orientation,
        )
        if any(not value.strip() for value in required):
            raise GoldenCatalogError("Golden sample identity fields cannot be empty")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise GoldenCatalogError("Golden sample sha256 must be 64 lowercase hex digits")
        if self.disposition == GoldenDisposition.NG:
            self._validate_ng()
        else:
            defect_fields = (
                self.defect_type,
                self.defect_size_um,
                self.defect_size_px,
                self.effective_width_px,
                self.defect_direction,
                self.defect_position,
                self.defect_roi,
                self.background_ring,
            )
            if any(value not in ("", None) for value in defect_fields):
                raise GoldenCatalogError("PASS samples cannot carry NG defect labels")
            if self.defect_polarity != DefectPolarity.UNSPECIFIED:
                raise GoldenCatalogError("PASS samples cannot carry a defect polarity")

    def _validate_ng(self) -> None:
        if not self.defect_type or not self.defect_direction or not self.defect_position:
            raise GoldenCatalogError(
                "NG samples require defect type, direction, and position"
            )
        if self.defect_polarity not in {DefectPolarity.BRIGHT, DefectPolarity.DARK}:
            raise GoldenCatalogError("NG defect polarity must be bright or dark")
        numeric = (self.defect_size_um, self.defect_size_px, self.effective_width_px)
        if any(value is None or value <= 0 for value in numeric):
            raise GoldenCatalogError(
                "NG samples require positive physical size, pixel size, and effective width"
            )
        if self.defect_roi is None or self.background_ring is None:
            raise GoldenCatalogError("NG samples require defect ROI and background ring")
        if self.defect_roi.roi_type != RoiType.GOLDEN_DEFECT:
            raise GoldenCatalogError("defect_roi must be golden_defect")
        if self.background_ring.roi_type != RoiType.LOCAL_BACKGROUND_RING:
            raise GoldenCatalogError("background_ring must be local_background_ring")
        if (
            self.defect_roi.image_id != self.sample_id
            or self.background_ring.image_id != self.sample_id
        ):
            raise GoldenCatalogError("Golden ROI image_id must match sample_id")
        if not self.background_ring.overlaps(self.defect_roi):
            raise GoldenCatalogError("background ring must geometrically contain the defect ROI")
        if not (
            self.background_ring.x <= self.defect_roi.x
            and self.background_ring.y <= self.defect_roi.y
            and self.background_ring.x2 >= self.defect_roi.x2
            and self.background_ring.y2 >= self.defect_roi.y2
        ):
            raise GoldenCatalogError("background ring must fully contain the defect ROI")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "disposition": self.disposition.value,
            "image_source": self.image_source,
            "sha256": self.sha256,
            "batch_id": self.batch_id,
            "orientation": self.orientation,
            "full_width_region": self.full_width_region.value,
            "defect_type": self.defect_type,
            "defect_size_um": self.defect_size_um,
            "defect_size_px": self.defect_size_px,
            "effective_width_px": self.effective_width_px,
            "defect_direction": self.defect_direction,
            "defect_polarity": self.defect_polarity.value,
            "defect_position": self.defect_position,
            "defect_roi": self.defect_roi.to_dict() if self.defect_roi else None,
            "background_ring": (
                self.background_ring.to_dict() if self.background_ring else None
            ),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenSample":
        try:
            return cls(
                sample_id=str(data["sample_id"]),
                disposition=GoldenDisposition(str(data["disposition"])),
                image_source=str(data["image_source"]),
                sha256=str(data["sha256"]),
                batch_id=str(data["batch_id"]),
                orientation=str(data["orientation"]),
                full_width_region=FullWidthRegion(str(data["full_width_region"])),
                defect_type=str(data.get("defect_type", "")),
                defect_size_um=_optional_float(data.get("defect_size_um")),
                defect_size_px=_optional_float(data.get("defect_size_px")),
                effective_width_px=_optional_float(data.get("effective_width_px")),
                defect_direction=str(data.get("defect_direction", "")),
                defect_polarity=DefectPolarity(
                    str(data.get("defect_polarity", DefectPolarity.UNSPECIFIED.value))
                ),
                defect_position=str(data.get("defect_position", "")),
                defect_roi=(
                    RoiDefinition.from_dict(dict(data["defect_roi"]))
                    if data.get("defect_roi")
                    else None
                ),
                background_ring=(
                    RoiDefinition.from_dict(dict(data["background_ring"]))
                    if data.get("background_ring")
                    else None
                ),
                metadata=dict(data.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GoldenCatalogError(f"invalid Golden sample: {exc}") from exc


@dataclass(frozen=True)
class GoldenCatalog:
    catalog_id: str
    version: str
    approved: bool
    approved_by: str
    approved_at: str
    approval_record_source: str
    required_defect_types: Sequence[str]
    samples: Sequence[GoldenSample]
    schema_version: str = "1.0"
    supersedes_version: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise GoldenCatalogError("unsupported Golden catalog schema version")
        if not self.catalog_id or not self.version:
            raise GoldenCatalogError("Golden catalog id and version are required")
        if not self.approved:
            raise GoldenCatalogError("formal G6 evidence requires an approved Golden catalog")
        if not self.approved_by or not self.approved_at or not self.approval_record_source:
            raise GoldenCatalogError("approved catalog requires approver, time, and record")
        _parse_iso8601(self.approved_at, "approved_at")
        if not self.samples:
            raise GoldenCatalogError("Golden catalog cannot be empty")
        ids = [sample.sample_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise GoldenCatalogError("Golden sample ids must be unique")
        required = [item.strip() for item in self.required_defect_types]
        if not required or any(not item for item in required):
            raise GoldenCatalogError("required defect type list cannot be empty")
        if len(required) != len(set(required)):
            raise GoldenCatalogError("required defect types must be unique")
        catalog_types = {
            sample.defect_type
            for sample in self.samples
            if sample.disposition == GoldenDisposition.NG
        }
        unknown = sorted(catalog_types - set(required))
        if unknown:
            raise GoldenCatalogError(
                f"catalog contains unregistered defect types: {', '.join(unknown)}"
            )

    @property
    def reference(self) -> str:
        return f"{self.catalog_id}@{self.version}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "catalog_id": self.catalog_id,
            "version": self.version,
            "supersedes_version": self.supersedes_version,
            "approved": self.approved,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "approval_record_source": self.approval_record_source,
            "required_defect_types": list(self.required_defect_types),
            "samples": [sample.to_dict() for sample in self.samples],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenCatalog":
        try:
            return cls(
                catalog_id=str(data["catalog_id"]),
                version=str(data["version"]),
                supersedes_version=str(data.get("supersedes_version", "")),
                approved=bool(data["approved"]),
                approved_by=str(data["approved_by"]),
                approved_at=str(data["approved_at"]),
                approval_record_source=str(data["approval_record_source"]),
                required_defect_types=[
                    str(item) for item in data["required_defect_types"]
                ],
                samples=[
                    GoldenSample.from_dict(dict(item)) for item in data["samples"]
                ],
                schema_version=str(data.get("schema_version", "1.0")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GoldenCatalogError(f"invalid Golden catalog: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> "GoldenCatalog":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GoldenCatalogError(f"invalid Golden catalog JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise GoldenCatalogError("Golden catalog JSON must be an object")
        return cls.from_dict(data)


class GoldenCatalogRepository:
    """Append-only filesystem store keyed by catalog id and version."""

    def __init__(self, root: str):
        self.root = Path(root)

    def path_for(self, catalog_id: str, version: str) -> Path:
        if (
            not catalog_id
            or not version
            or Path(catalog_id).name != catalog_id
            or Path(version).name != version
        ):
            raise GoldenCatalogError("catalog id and version must be safe path segments")
        return self.root / catalog_id / f"{version}.json"

    def save_new(self, catalog: GoldenCatalog) -> Path:
        path = self.path_for(catalog.catalog_id, catalog.version)
        if path.exists():
            raise GoldenCatalogError(
                f"Golden catalog version is immutable and already exists: {catalog.reference}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(catalog.to_json() + "\n", encoding="utf-8")
        return path

    def load(self, catalog_id: str, version: str) -> GoldenCatalog:
        path = self.path_for(catalog_id, version)
        if not path.is_file():
            raise GoldenCatalogError(f"Golden catalog version not found: {catalog_id}@{version}")
        return GoldenCatalog.from_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class DetectorDecision:
    sample_id: str
    score: float
    threshold: float
    detected: bool
    capture_attempts: int = 1

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise GoldenCatalogError("detector decision sample_id is required")
        if self.capture_attempts < 1:
            raise GoldenCatalogError("capture_attempts must be >= 1")

    @property
    def margin_pct(self) -> float:
        denominator = max(abs(self.threshold), 1e-12)
        return (self.score - self.threshold) / denominator * 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "score": self.score,
            "threshold": self.threshold,
            "detected": self.detected,
            "capture_attempts": self.capture_attempts,
            "margin_pct": self.margin_pct,
        }


@dataclass(frozen=True)
class DetectorResultSet:
    catalog_id: str
    catalog_version: str
    detector_id: str
    detector_version: str
    decision_rule_version: str
    imported_from: str
    decisions: Sequence[DetectorDecision]

    def __post_init__(self) -> None:
        identity = (
            self.catalog_id,
            self.catalog_version,
            self.detector_id,
            self.detector_version,
            self.decision_rule_version,
            self.imported_from,
        )
        if any(not item.strip() for item in identity):
            raise GoldenCatalogError("detector result provenance fields cannot be empty")
        if not self.decisions:
            raise GoldenCatalogError("detector result set cannot be empty")
        ids = [item.sample_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise GoldenCatalogError("detector result sample ids must be unique")

    def validate_against(self, catalog: GoldenCatalog) -> None:
        if (self.catalog_id, self.catalog_version) != (
            catalog.catalog_id,
            catalog.version,
        ):
            raise GoldenCatalogError("detector results reference a different Golden version")
        catalog_ids = {sample.sample_id for sample in catalog.samples}
        result_ids = {item.sample_id for item in self.decisions}
        missing = sorted(catalog_ids - result_ids)
        unknown = sorted(result_ids - catalog_ids)
        if missing or unknown:
            raise GoldenCatalogError(
                f"detector result coverage mismatch; missing={missing}, unknown={unknown}"
            )

    @classmethod
    def load_csv(
        cls,
        path: str,
        *,
        catalog_id: str,
        catalog_version: str,
        detector_id: str,
        detector_version: str,
        decision_rule_version: str,
    ) -> "DetectorResultSet":
        decisions: List[DetectorDecision] = []
        with open(path, "r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {
                "sample_id",
                "score",
                "threshold",
                "detected",
                "capture_attempts",
            }
            missing_fields = sorted(required - set(reader.fieldnames or []))
            if missing_fields:
                raise GoldenCatalogError(
                    f"detector CSV missing fields: {', '.join(missing_fields)}"
                )
            for row_number, row in enumerate(reader, start=2):
                try:
                    decisions.append(
                        DetectorDecision(
                            sample_id=str(row["sample_id"]),
                            score=float(row["score"]),
                            threshold=float(row["threshold"]),
                            detected=_parse_bool(str(row["detected"])),
                            capture_attempts=int(row["capture_attempts"]),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise GoldenCatalogError(
                        f"invalid detector CSV row {row_number}: {exc}"
                    ) from exc
        return cls(
            catalog_id=catalog_id,
            catalog_version=catalog_version,
            detector_id=detector_id,
            detector_version=detector_version,
            decision_rule_version=decision_rule_version,
            imported_from=str(path),
            decisions=decisions,
        )


def _optional_float(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "detected", "ng"}:
        return True
    if normalized in {"0", "false", "no", "not_detected", "pass"}:
        return False
    raise GoldenCatalogError(f"invalid detector boolean: {value}")
