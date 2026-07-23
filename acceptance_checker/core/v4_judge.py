# -*- coding: utf-8 -*-
"""影像品質卡控表 v4 第 4.2、13.2 節正式判定引擎。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional

from .v4_domain import AcceptanceSession, MetricGroup, OverallResult, Severity


class S0PriorityEventType(str, Enum):
    DATA_INTEGRITY_FAILURE = "data_integrity_failure"
    INSPECTION_BLIND_ZONE = "inspection_blind_zone"
    DEFECT_SIGNAL_OBSCURED = "defect_signal_obscured"
    GOLDEN_NG_STABLE_MISS = "golden_ng_stable_miss"
    MINIMUM_DEFECT_UNRECOGNIZABLE = "minimum_defect_unrecognizable"


@dataclass(frozen=True)
class S0PriorityEvent:
    event_type: S0PriorityEventType
    description: str
    evidence_sources: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("S0 priority event 必須提供 description")
        if not self.evidence_sources:
            raise ValueError("S0 priority event 必須提供 evidence_sources")


@dataclass(frozen=True)
class V4Decision:
    result: OverallResult
    rule_number: Optional[int]
    reason: str
    group_statuses: Dict[str, str]
    trigger_groups: List[str] = field(default_factory=list)
    trigger_metric_ids: List[str] = field(default_factory=list)
    missing_groups: List[str] = field(default_factory=list)
    missing_metric_ids: List[str] = field(default_factory=list)
    priority_event_types: List[str] = field(default_factory=list)


class V4AcceptanceJudge:
    """依第 13.2 節由上往下判斷，命中第一條即停止。"""

    def judge(
        self,
        session: AcceptanceSession,
        priority_events: Iterable[S0PriorityEvent] = (),
    ) -> V4Decision:
        events = list(priority_events)
        statuses = session.group_statuses()
        missing_groups = [
            group.value for group, severity in statuses.items()
            if severity == Severity.NOT_EVALUATED
        ]
        missing_metrics = [
            item.metric_id
            for item in session.measurements
            if item.severity == Severity.NOT_EVALUATED
            and not item.metadata.get("non_graded", False)
        ]

        if events:
            return self._finish(
                session,
                OverallResult.FATAL_STOP,
                1,
                "任一第 4.2 節 S0 優先項發生",
                statuses,
                missing_groups,
                missing_metrics,
                priority_event_types=[item.event_type.value for item in events],
            )

        fatal_groups = [
            group for group in (MetricGroup.G5, MetricGroup.G6)
            if statuses[group] == Severity.S0
        ]
        if fatal_groups:
            return self._finish(
                session, OverallResult.FATAL_STOP, 2, "G5 或 G6 任一項達 S0",
                statuses, missing_groups, missing_metrics, trigger_groups=fatal_groups
            )

        s0_groups = [group for group, severity in statuses.items() if severity == Severity.S0]
        if len(s0_groups) >= 2:
            return self._finish(
                session, OverallResult.FATAL_STOP, 3, "任兩個以上群組達 S0",
                statuses, missing_groups, missing_metrics, trigger_groups=s0_groups
            )

        hardware_s0 = [
            group for group in (MetricGroup.G1, MetricGroup.G2, MetricGroup.G3, MetricGroup.G4)
            if statuses[group] == Severity.S0
        ]
        if hardware_s0:
            return self._finish(
                session, OverallResult.REJECTED_RETEST, 4, "單一 G1～G4 群組達 S0",
                statuses, missing_groups, missing_metrics, trigger_groups=hardware_s0
            )

        s1_groups = [group for group, severity in statuses.items() if severity == Severity.S1]
        if s1_groups:
            return self._finish(
                session, OverallResult.REJECTED_RETEST, 5, "任一群組達 S1",
                statuses, missing_groups, missing_metrics, trigger_groups=s1_groups
            )

        if missing_groups:
            return self._finish(
                session,
                OverallResult.INSUFFICIENT_EVIDENCE,
                None,
                "仍有未評估群組，不能套用順位 6 或 7",
                statuses,
                missing_groups,
                missing_metrics,
            )

        s3_count = sum(severity == Severity.S3 for severity in statuses.values())
        if s3_count >= 4:
            return self._finish(
                session, OverallResult.ACCEPTED, 6, "全部群組 ≥S2，且至少四組達 S3",
                statuses, missing_groups, missing_metrics
            )
        return self._finish(
            session,
            OverallResult.CONDITIONALLY_ACCEPTED,
            7,
            "全部群組 ≥S2，但未達順位 6 條件",
            statuses,
            missing_groups,
            missing_metrics,
        )

    def _finish(
        self,
        session: AcceptanceSession,
        result: OverallResult,
        rule_number: Optional[int],
        reason: str,
        statuses: Dict[MetricGroup, Severity],
        missing_groups: List[str],
        missing_metrics: List[str],
        trigger_groups: Optional[List[MetricGroup]] = None,
        priority_event_types: Optional[List[str]] = None,
    ) -> V4Decision:
        groups = trigger_groups or []
        trigger_metrics = [
            item.metric_id
            for item in session.measurements
            if item.group in groups and item.severity in (Severity.S0, Severity.S1)
        ]
        session.overall_result = result
        session.decision_rule = rule_number
        return V4Decision(
            result=result,
            rule_number=rule_number,
            reason=reason,
            group_statuses={
                group.value: severity.value for group, severity in statuses.items()
            },
            trigger_groups=[group.value for group in groups],
            trigger_metric_ids=trigger_metrics,
            missing_groups=missing_groups,
            missing_metric_ids=missing_metrics,
            priority_event_types=priority_event_types or [],
        )
