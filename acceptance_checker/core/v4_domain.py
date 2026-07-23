# -*- coding: utf-8 -*-
"""影像品質卡控表 v4 的核心領域模型。

本模組只描述驗收資料與狀態，不依賴 Qt、OpenCV 或現行加權分數判定器。
它是 legacy 單張 quick check 與正式 v4 驗收流程之間的明確邊界。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class OpticalMode(str, Enum):
    """由光學幾何宣告的取像模式。"""

    DIFFUSE_BRIGHT_FIELD = "diffuse_bright_field"
    SPECULAR_BRIGHT_FIELD = "specular_bright_field"
    SCATTERING_DARK_FIELD = "scattering_dark_field"


class ImageLevel(str, Enum):
    """輸入影像在 v4 規範中的處理層級。"""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class Severity(str, Enum):
    """單一指標或群組的技術嚴重程度。"""

    S3 = "S3"
    S2 = "S2"
    S1 = "S1"
    S0 = "S0"
    NOT_EVALUATED = "NOT_EVALUATED"


class MetricGroup(str, Enum):
    """v4 六個正式卡控群組。"""

    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"


class OverallResult(str, Enum):
    """第 13.2 節整體結果與證據不足狀態。"""

    ACCEPTED = "accepted"
    CONDITIONALLY_ACCEPTED = "conditionally_accepted"
    REJECTED_RETEST = "rejected_retest"
    FATAL_STOP = "fatal_stop"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AcceptanceManifest:
    """一輪驗收的識別資料與前提鎖定摘要。

    P2 會把 ``precondition_lock`` 擴充成具欄位驗證的正式模型；P0.1 先以
    可序列化的 key-value 保存，避免不同機台或不同前提的結果被混在一起。
    """

    machine_id: str
    optical_mode: OpticalMode
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spec_version: str = "v4-draft"
    schema_version: str = "1.0"
    created_at: str = field(default_factory=_utc_now_iso)
    precondition_lock: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.machine_id.strip():
            raise ValueError("machine_id 不得為空")
        if not self.session_id.strip():
            raise ValueError("session_id 不得為空")
        if not self.spec_version.strip():
            raise ValueError("spec_version 不得為空")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "optical_mode": self.optical_mode.value,
            "session_id": self.session_id,
            "spec_version": self.spec_version,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "precondition_lock": dict(self.precondition_lock),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcceptanceManifest":
        return cls(
            machine_id=str(data["machine_id"]),
            optical_mode=OpticalMode(data["optical_mode"]),
            session_id=str(data["session_id"]),
            spec_version=str(data["spec_version"]),
            schema_version=str(data.get("schema_version", "1.0")),
            created_at=str(data["created_at"]),
            precondition_lock=dict(data.get("precondition_lock", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class MeasurementResult:
    """一個可追溯的 v4 指標量測與分級結果。"""

    metric_id: str
    group: MetricGroup
    severity: Severity
    unit: str
    formula_version: str
    image_level: ImageLevel
    value: Any = None
    roi_id: str = ""
    sample_count: int = 0
    evidence_sources: List[str] = field(default_factory=list)
    missing_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("metric_id 不得為空")
        if not self.formula_version.strip():
            raise ValueError("formula_version 不得為空")
        if self.sample_count < 0:
            raise ValueError("sample_count 不得小於 0")
        if self.severity == Severity.NOT_EVALUATED:
            if not self.missing_reason.strip():
                raise ValueError("NOT_EVALUATED 必須提供 missing_reason")
        elif self.value is None:
            raise ValueError("已評估的 MeasurementResult 必須提供 value")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "group": self.group.value,
            "severity": self.severity.value,
            "unit": self.unit,
            "formula_version": self.formula_version,
            "image_level": self.image_level.value,
            "value": self.value,
            "roi_id": self.roi_id,
            "sample_count": self.sample_count,
            "evidence_sources": list(self.evidence_sources),
            "missing_reason": self.missing_reason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeasurementResult":
        return cls(
            metric_id=str(data["metric_id"]),
            group=MetricGroup(data["group"]),
            severity=Severity(data["severity"]),
            unit=str(data.get("unit", "")),
            formula_version=str(data["formula_version"]),
            image_level=ImageLevel(data["image_level"]),
            value=data.get("value"),
            roi_id=str(data.get("roi_id", "")),
            sample_count=int(data.get("sample_count", 0)),
            evidence_sources=[str(item) for item in data.get("evidence_sources", [])],
            missing_reason=str(data.get("missing_reason", "")),
            metadata=dict(data.get("metadata", {})),
        )


_SEVERITY_ORDER = {
    Severity.S0: 0,
    Severity.S1: 1,
    Severity.S2: 2,
    Severity.S3: 3,
}


@dataclass
class AcceptanceSession:
    """一台機台在一組鎖定前提下的完整驗收工作階段。"""

    manifest: AcceptanceManifest
    measurements: List[MeasurementResult] = field(default_factory=list)
    overall_result: OverallResult = OverallResult.INSUFFICIENT_EVIDENCE
    decision_rule: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    def add_measurement(self, measurement: MeasurementResult) -> None:
        """加入一筆量測；群組由 measurement 自身明確指定。"""
        self.measurements.append(measurement)

    def group_status(self, group: MetricGroup) -> Severity:
        """輸出群組狀態，同時保留證據不足。

        S0/S1 即使同組另有未評估項仍須顯示，避免致命/高風險資訊被遮蔽。
        若已評估項只有 S2/S3 但仍有未評估項，群組保持 NOT_EVALUATED，
        不會被誤解為已達可通過條件。
        """
        severities = [
            item.severity
            for item in self.measurements
            if item.group == group and not item.metadata.get("non_graded", False)
        ]
        if not severities:
            return Severity.NOT_EVALUATED

        evaluated = [item for item in severities if item != Severity.NOT_EVALUATED]
        if evaluated:
            worst = min(evaluated, key=lambda item: _SEVERITY_ORDER[item])
            if worst in (Severity.S0, Severity.S1):
                return worst
        if Severity.NOT_EVALUATED in severities:
            return Severity.NOT_EVALUATED
        return min(evaluated, key=lambda item: _SEVERITY_ORDER[item])

    def group_statuses(self) -> Dict[MetricGroup, Severity]:
        return {group: self.group_status(group) for group in MetricGroup}

    def group_status_values(self) -> Dict[str, str]:
        """供 JSON/UI 使用的穩定字串 key/value。"""
        return {group.value: severity.value for group, severity in self.group_statuses().items()}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "measurements": [item.to_dict() for item in self.measurements],
            "group_statuses": self.group_status_values(),
            "overall_result": self.overall_result.value,
            "decision_rule": self.decision_rule,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcceptanceSession":
        return cls(
            manifest=AcceptanceManifest.from_dict(dict(data["manifest"])),
            measurements=[
                MeasurementResult.from_dict(dict(item)) for item in data.get("measurements", [])
            ],
            overall_result=OverallResult(
                data.get("overall_result", OverallResult.INSUFFICIENT_EVIDENCE.value)
            ),
            decision_rule=(
                int(data["decision_rule"]) if data.get("decision_rule") is not None else None
            ),
            notes=[str(item) for item in data.get("notes", [])],
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "AcceptanceSession":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("AcceptanceSession JSON 必須是物件")
        return cls.from_dict(data)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(self.to_json())
            stream.write("\n")

    @classmethod
    def load_json(cls, path: str) -> "AcceptanceSession":
        with open(path, "r", encoding="utf-8") as stream:
            return cls.from_json(stream.read())
