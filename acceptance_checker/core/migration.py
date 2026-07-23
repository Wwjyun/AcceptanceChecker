# -*- coding: utf-8 -*-
"""Explicit legacy-to-v4 engineering-reference migration helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import MISSING, dataclass, fields
from pathlib import Path
from typing import Any, Dict, List

from .config import Thresholds
from .legacy_adapter import LegacyMetricsAdapter
from .metrics import Metrics
from .v4_domain import AcceptanceManifest, AcceptanceSession, OpticalMode

LEGACY_REFERENCE_NOTICE = (
    "此轉換內容僅供工程參考；舊資料缺少 v4 的模式化 ROI、原始證據、"
    "樣本設計或 Golden 核准資料，不得補造或宣稱為正式 S0～S3 驗收結果。"
)


@dataclass(frozen=True)
class LegacyMigrationBundle:
    source_type: str
    source_path: str
    records: List[Dict[str, Any]]
    schema_version: str = "legacy-migration-1.0"
    engineering_reference_only: bool = True
    formal_v4_grade_allowed: bool = False
    notice: str = LEGACY_REFERENCE_NOTICE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "engineering_reference_only": self.engineering_reference_only,
            "formal_v4_grade_allowed": self.formal_v4_grade_allowed,
            "notice": self.notice,
            "records": self.records,
        }

    def save_json(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


def migrate_legacy_threshold_profile(path: str) -> LegacyMigrationBundle:
    thresholds = Thresholds.load_json(path)
    return LegacyMigrationBundle(
        source_type="legacy_threshold_profile",
        source_path=str(Path(path).resolve()),
        records=[
            {
                "profile_type": "legacy_weighted_score_thresholds",
                "thresholds": thresholds.to_dict(),
                "v4_specification_mapping": None,
                "migration_status": "engineering_reference_only",
            }
        ],
    )


def migrate_legacy_csv(
    path: str,
    *,
    machine_id: str,
    optical_mode: OpticalMode,
) -> LegacyMigrationBundle:
    if not machine_id.strip():
        raise ValueError("legacy CSV migration requires machine_id")
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("legacy CSV is missing a header")
        source_type = _detect_csv_type(reader.fieldnames)
        rows = list(reader)
    if not rows:
        raise ValueError("legacy CSV has no data rows")

    sessions = [
        _legacy_row_to_session(
            row,
            machine_id=machine_id,
            optical_mode=optical_mode,
            source_path=str(Path(path).resolve()),
            source_type=source_type,
            row_number=index,
        ).to_dict()
        for index, row in enumerate(rows, start=2)
    ]
    return LegacyMigrationBundle(
        source_type=source_type,
        source_path=str(Path(path).resolve()),
        records=sessions,
    )


def _detect_csv_type(fieldnames: List[str]) -> str:
    names = set(fieldnames)
    if {"file_name", "width_px", "quality_score", "overall_status"} <= names:
        return "legacy_metrics_csv"
    if {"timestamp", "file_name", "quality_score", "overall_status"} <= names:
        return "legacy_history_log"
    raise ValueError(
        "CSV header is neither a legacy Metrics export nor a legacy history log"
    )


def _legacy_row_to_session(
    row: Dict[str, str],
    *,
    machine_id: str,
    optical_mode: OpticalMode,
    source_path: str,
    source_type: str,
    row_number: int,
) -> AcceptanceSession:
    metrics = _metrics_from_row(row)
    manifest = AcceptanceManifest(
        machine_id=machine_id,
        optical_mode=optical_mode,
        session_id=metrics.session_id or f"legacy-row-{row_number}",
        spec_version="legacy-engineering-reference-1",
        metadata={
            "migration": {
                "source_type": source_type,
                "source_path": source_path,
                "source_row": row_number,
                "engineering_reference_only": True,
                "formal_v4_grade_allowed": False,
                "notice": LEGACY_REFERENCE_NOTICE,
            },
            "legacy_timestamp": row.get("timestamp", ""),
            "legacy_spec_version": metrics.spec_version,
            "legacy_overall_status": metrics.overall_status,
            "legacy_risk_level": metrics.risk_level,
            "legacy_quality_score": metrics.quality_score,
        },
        manifest_hash=metrics.manifest_hash,
    )
    return AcceptanceSession(
        manifest=manifest,
        measurements=LegacyMetricsAdapter().adapt(metrics),
        notes=[LEGACY_REFERENCE_NOTICE],
    )


def _metrics_from_row(row: Dict[str, str]) -> Metrics:
    values: Dict[str, Any] = {}
    for item in fields(Metrics):
        if item.name not in row or row[item.name] in (None, ""):
            continue
        raw = row[item.name]
        default = item.default if item.default is not MISSING else None
        try:
            if isinstance(default, bool):
                values[item.name] = str(raw).strip().lower() in {"1", "true", "yes"}
            elif isinstance(default, int):
                values[item.name] = int(float(raw))
            elif isinstance(default, float):
                values[item.name] = float(raw)
            else:
                values[item.name] = str(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"legacy CSV field {item.name!r} has invalid value {raw!r}"
            ) from exc
    return Metrics(**values)
