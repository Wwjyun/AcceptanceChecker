# -*- coding: utf-8 -*-
"""Formal v4 session workflow shared by the GUI and composable CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .dataset_manifest import AcceptanceDatasetManifest, sha256_file
from .specification import load_default_v4_spec
from .v4_domain import (
    AcceptanceManifest,
    AcceptanceSession,
    MeasurementResult,
    OpticalMode,
)
from .v4_judge import (
    S0PriorityEvent,
    S0PriorityEventType,
    V4AcceptanceJudge,
    V4Decision,
)


class WorkflowError(ValueError):
    """Raised when a formal workflow step is invalid or out of order."""


class WorkflowStep(str, Enum):
    EMPTY = "empty"
    MANIFEST_LOADED = "manifest_loaded"
    EVIDENCE_CHECKED = "evidence_checked"
    MEASURED = "measured"
    JUDGED = "judged"
    REPORT_READY = "report_ready"


@dataclass(frozen=True)
class EvidenceIssue:
    item_id: str
    reason: str
    source: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "item_id": self.item_id,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class EvidenceCheck:
    valid: bool
    issues: Sequence[EvidenceIssue]
    checked_sources: Sequence[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [item.to_dict() for item in self.issues],
            "checked_sources": list(self.checked_sources),
        }


@dataclass
class SessionWorkflow:
    """Ordered v4 workflow without any GUI dependency.

    The ``measure`` step consumes the machine-readable outputs of the G1-G6
    measurers.  It never upgrades missing evidence or legacy quick-check values
    into a formal grade.
    """

    dataset_manifest: Optional[AcceptanceDatasetManifest] = None
    dataset_root: Optional[Path] = None
    session: Optional[AcceptanceSession] = None
    evidence_check: Optional[EvidenceCheck] = None
    priority_events: List[S0PriorityEvent] = field(default_factory=list)
    decision: Optional[V4Decision] = None
    report_paths: List[str] = field(default_factory=list)
    step: WorkflowStep = WorkflowStep.EMPTY

    def load_manifest(self, path: str) -> AcceptanceDatasetManifest:
        source = Path(path).resolve()
        dataset = AcceptanceDatasetManifest.load_json(str(source))
        self.dataset_manifest = dataset
        self.dataset_root = source.parent
        self.session = AcceptanceSession(
            manifest=AcceptanceManifest(
                machine_id=dataset.machine_id,
                optical_mode=dataset.optical_mode,
                session_id=dataset.session_id,
                spec_version=dataset.spec_version,
                schema_version=dataset.schema_version,
                created_at=dataset.created_at,
                precondition_lock=dataset.precondition_lock,
                metadata={
                    "dataset_manifest": str(source),
                    "dataset_image_count": len(dataset.images),
                },
                manifest_hash=dataset.manifest_hash(),
            )
        )
        self.evidence_check = None
        self.priority_events = []
        self.decision = None
        self.report_paths = []
        self.step = WorkflowStep.MANIFEST_LOADED
        return dataset

    def select_mode(self, mode: OpticalMode) -> None:
        session = self._require_session()
        if self.step not in {WorkflowStep.MANIFEST_LOADED, WorkflowStep.EVIDENCE_CHECKED}:
            raise WorkflowError("量測開始後不得變更取像模式")
        session.manifest.optical_mode = mode
        if self.dataset_manifest is not None:
            self.dataset_manifest.optical_mode = mode

    def check_evidence(self) -> EvidenceCheck:
        dataset = self._require_dataset()
        root = self._require_root()
        issues: List[EvidenceIssue] = []
        checked: List[str] = []

        if not dataset.measurements_valid:
            issues.append(
                EvidenceIssue(
                    "precondition.warmup_minutes",
                    dataset.invalid_reason,
                    "precondition_lock.environment.warmup_minutes",
                )
            )
        if not dataset.images:
            issues.append(EvidenceIssue("images", "manifest 沒有任何影像證據"))

        for image in dataset.images:
            image_path = (root / image.relative_path).resolve()
            sidecar_path = (root / image.sidecar_relative_path).resolve()
            for item_id, source in (
                (image.relative_path, image_path),
                (image.sidecar_relative_path, sidecar_path),
            ):
                checked.append(str(source))
                if not source.is_file():
                    issues.append(EvidenceIssue(item_id, "證據檔不存在", str(source)))
            if image_path.is_file():
                stat = image_path.stat()
                if stat.st_size != image.size_bytes:
                    issues.append(
                        EvidenceIssue(
                            image.relative_path,
                            "檔案大小與 manifest 不一致",
                            str(image_path),
                        )
                    )
                if sha256_file(str(image_path)) != image.sha256:
                    issues.append(
                        EvidenceIssue(
                            image.relative_path,
                            "SHA-256 與 manifest 不一致",
                            str(image_path),
                        )
                    )

        result = EvidenceCheck(not issues, tuple(issues), tuple(checked))
        self.evidence_check = result
        session = self._require_session()
        session.manifest.metadata["evidence_check"] = result.to_dict()
        self.step = WorkflowStep.EVIDENCE_CHECKED
        return result

    def execute_measurement_package(self, path: str) -> AcceptanceSession:
        if self.evidence_check is None:
            raise WorkflowError("請先執行證據檢查")
        if not self.evidence_check.valid:
            raise WorkflowError("證據檢查未通過；不得執行正式量測")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise WorkflowError("量測套件 JSON 必須是物件")
        raw_measurements = payload.get("measurements")
        if not isinstance(raw_measurements, list) or not raw_measurements:
            raise WorkflowError("量測套件必須包含非空 measurements 陣列")

        session = self._require_session()
        package_hash = sha256_file(path)
        measurements = [
            MeasurementResult.from_dict(dict(item)) for item in raw_measurements
        ]
        actual_ids = [item.metric_id for item in measurements]
        duplicates = sorted(
            {metric_id for metric_id in actual_ids if actual_ids.count(metric_id) > 1}
        )
        expected_ids = {
            item.metric_id
            for item in load_default_v4_spec().metrics_for_mode(
                session.manifest.optical_mode
            )
        }
        missing = sorted(expected_ids - set(actual_ids))
        unknown = sorted(set(actual_ids) - expected_ids)
        if duplicates or missing or unknown:
            raise WorkflowError(
                "正式量測套件必須讓每個適用 metric 恰好出現一次；"
                f"duplicates={duplicates}, missing={missing}, unknown={unknown}"
            )
        session.measurements = measurements
        self.priority_events = [
            _priority_event_from_dict(dict(item))
            for item in payload.get("priority_events", [])
        ]
        session.manifest.metadata.update(
            {
                "measurement_package": str(Path(path).resolve()),
                "measurement_package_sha256": package_hash,
                "priority_events": [
                    _priority_event_to_dict(item) for item in self.priority_events
                ],
            }
        )
        self.decision = None
        self.report_paths = []
        self.step = WorkflowStep.MEASURED
        return session

    def judge(self) -> V4Decision:
        session = self._require_session()
        if not session.measurements:
            raise WorkflowError("尚未執行正式量測")
        self.priority_events = _events_from_session(session, self.priority_events)
        self.decision = V4AcceptanceJudge().judge(session, self.priority_events)
        session.manifest.metadata["decision"] = {
            "result": self.decision.result.value,
            "rule_number": self.decision.rule_number,
            "reason": self.decision.reason,
        }
        self.step = WorkflowStep.JUDGED
        return self.decision

    def mark_report_ready(self, paths: Sequence[str]) -> None:
        if self.decision is None:
            raise WorkflowError("請先完成正式判定")
        if not paths:
            raise WorkflowError("正式報告至少需要一個輸出檔")
        self.report_paths = [str(Path(path).resolve()) for path in paths]
        self.step = WorkflowStep.REPORT_READY

    @classmethod
    def from_session(cls, session: AcceptanceSession) -> "SessionWorkflow":
        events = _events_from_session(session)
        workflow = cls(
            session=session,
            priority_events=events,
            step=WorkflowStep.MEASURED if session.measurements else WorkflowStep.MANIFEST_LOADED,
        )
        evidence = session.manifest.metadata.get("evidence_check")
        if isinstance(evidence, dict):
            workflow.evidence_check = EvidenceCheck(
                bool(evidence.get("valid", False)),
                tuple(
                    EvidenceIssue(
                        str(item.get("item_id", "")),
                        str(item.get("reason", "")),
                        str(item.get("source", "")),
                    )
                    for item in evidence.get("issues", [])
                ),
                tuple(str(item) for item in evidence.get("checked_sources", [])),
            )
        return workflow

    def _require_session(self) -> AcceptanceSession:
        if self.session is None:
            raise WorkflowError("請先建立或載入 manifest")
        return self.session

    def _require_dataset(self) -> AcceptanceDatasetManifest:
        if self.dataset_manifest is None:
            raise WorkflowError("證據檢查需要 dataset manifest")
        return self.dataset_manifest

    def _require_root(self) -> Path:
        if self.dataset_root is None:
            raise WorkflowError("缺少 dataset root")
        return self.dataset_root


def _priority_event_to_dict(event: S0PriorityEvent) -> Dict[str, Any]:
    return {
        "event_type": event.event_type.value,
        "description": event.description,
        "evidence_sources": list(event.evidence_sources),
    }


def _priority_event_from_dict(data: Dict[str, Any]) -> S0PriorityEvent:
    return S0PriorityEvent(
        event_type=S0PriorityEventType(data["event_type"]),
        description=str(data["description"]),
        evidence_sources=[str(item) for item in data.get("evidence_sources", [])],
    )


def _events_from_session(
    session: AcceptanceSession,
    fallback: Sequence[S0PriorityEvent] = (),
) -> List[S0PriorityEvent]:
    raw = session.manifest.metadata.get("priority_events")
    if isinstance(raw, list):
        return [_priority_event_from_dict(dict(item)) for item in raw]
    return list(fallback)
