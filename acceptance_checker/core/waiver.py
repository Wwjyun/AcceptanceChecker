# -*- coding: utf-8 -*-
"""v4 section 15 written-waiver lifecycle and 30-day tracking."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import Enum, IntEnum
from typing import Any, Dict, Optional, Sequence

from .v4_domain import MeasurementResult, MetricGroup, OverallResult, Severity


class WaiverError(ValueError):
    """Raised when a waiver violates section 15 controls."""


class ApprovalLevel(IntEnum):
    JOINT_MANAGERS = 1
    SENIOR_MANAGER = 2
    DIRECTOR = 3
    EXECUTIVE = 4


class WaiverStatus(str, Enum):
    ACTIVE_NOT_ACCEPTED = "active_not_accepted"
    EXPIRED_ORIGINAL_RESULT_RESTORED = "expired_original_result_restored"
    INVALIDATED_BY_NEW_S0 = "invalidated_by_new_s0"
    CLOSED_AFTER_REVALIDATION = "closed_after_revalidation"


@dataclass(frozen=True)
class WaivedMetric:
    metric_id: str
    group: MetricGroup
    severity: Severity
    value: Any
    unit: str

    def __post_init__(self) -> None:
        if not self.metric_id or self.severity == Severity.NOT_EVALUATED:
            raise WaiverError("metric snapshot must contain an evaluated severity")

    @classmethod
    def from_measurement(cls, item: MeasurementResult) -> "WaivedMetric":
        return cls(item.metric_id, item.group, item.severity, item.value, item.unit)


@dataclass(frozen=True)
class WaiverApproval:
    approver: str
    role: str
    level: ApprovalLevel
    signed_at: str

    def __post_init__(self) -> None:
        if not all((self.approver, self.role, self.signed_at)):
            raise WaiverError("waiver approval fields cannot be empty")
        _parse_datetime(self.signed_at, "signed_at")


@dataclass(frozen=True)
class WaiverTrackingReport:
    reported_on: date
    hardware_progress_pct: float
    remaining_work: str
    missed_detections: int
    false_detections: int
    latest_measurements: Sequence[WaivedMetric]
    new_s1_metric_ids: Sequence[str] = field(default_factory=tuple)
    new_s0_metric_ids: Sequence[str] = field(default_factory=tuple)
    evidence_sources: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 0 <= self.hardware_progress_pct <= 100:
            raise WaiverError("hardware progress must be 0..100 percent")
        if not self.remaining_work or not self.evidence_sources:
            raise WaiverError("tracking report requires remaining work and evidence")
        if self.missed_detections < 0 or self.false_detections < 0:
            raise WaiverError("tracking defect counts cannot be negative")
        if not self.latest_measurements:
            raise WaiverError("tracking report requires current metric measurements")


@dataclass(frozen=True)
class WaiverEvaluation:
    status: WaiverStatus
    effective: bool
    formal_result: OverallResult
    original_result: OverallResult
    extension_eligible: bool
    next_tracking_due: date
    reasons: Sequence[str]


@dataclass(frozen=True)
class Waiver:
    waiver_id: str
    session_id: str
    original_result: OverallResult
    original_decision_rule: int
    waived_metrics: Sequence[WaivedMetric]
    risk_assessment: Dict[str, str]
    responsible_owner: str
    hardware_improvement_date: date
    issued_on: date
    expires_on: date
    approvals: Sequence[WaiverApproval]
    detection_target_adjustment: str
    best_effort_acknowledgement: str
    extension_count: int = 0
    parent_waiver_id: str = ""
    alternative_solution: str = ""
    tracking_reports: Sequence[WaiverTrackingReport] = field(default_factory=tuple)
    closed_revalidation_result: Optional[OverallResult] = None
    remediation_order: Sequence[str] = (
        "optical_geometry",
        "lighting",
        "mechanics_and_scan",
        "camera_hardware",
        "L1_calibration",
        "software_algorithm",
    )

    def __post_init__(self) -> None:
        if not self.waiver_id or not self.session_id or not self.responsible_owner:
            raise WaiverError("waiver identity and responsible owner are required")
        if self.original_result not in {
            OverallResult.REJECTED_RETEST,
            OverallResult.FATAL_STOP,
        }:
            raise WaiverError("waiver requires an original rejected or fatal result")
        if self.original_decision_rule < 1 or not self.waived_metrics:
            raise WaiverError("waiver requires original decision and failed metrics")
        if any(
            item.severity not in {Severity.S0, Severity.S1}
            for item in self.waived_metrics
        ):
            raise WaiverError("original waived metrics must be S0 or S1")
        if self.extension_count not in {0, 1, 2}:
            raise WaiverError("the same metric may be extended at most twice")
        if self.extension_count and not self.parent_waiver_id:
            raise WaiverError("an extension must reference its parent waiver")
        if self.extension_count == 2 and not self.alternative_solution.strip():
            raise WaiverError("the third submission requires an alternative solution")
        if self.expires_on <= self.issued_on:
            raise WaiverError("waiver expiration must be after issue date")
        if self.expires_on - self.issued_on > timedelta(days=90):
            raise WaiverError("waiver validity cannot exceed 90 days")
        if not self.issued_on <= self.hardware_improvement_date <= self.expires_on:
            raise WaiverError("hardware improvement date must fall within waiver validity")
        required_risks = {
            "missed_detection",
            "false_detection",
            "equipment_stability",
            "traceability",
        }
        if required_risks - set(self.risk_assessment) or any(
            not self.risk_assessment[key].strip() for key in required_risks
        ):
            raise WaiverError("waiver requires all four formal risk assessments")
        if not self.detection_target_adjustment or not self.best_effort_acknowledgement:
            raise WaiverError("target adjustment and software best-effort terms are required")
        if "best effort" not in self.best_effort_acknowledgement.lower():
            raise WaiverError("software delivery must explicitly state best effort")
        self._validate_approvals()
        report_dates = [item.reported_on for item in self.tracking_reports]
        if report_dates != sorted(report_dates) or len(report_dates) != len(set(report_dates)):
            raise WaiverError("tracking reports must be uniquely chronological")
        if any(
            not self.issued_on < item.reported_on <= self.expires_on
            for item in self.tracking_reports
        ):
            raise WaiverError("tracking report date must fall within waiver validity")

    @property
    def baseline_s0_metric_ids(self) -> set:
        return {
            item.metric_id
            for item in self.waived_metrics
            if item.severity == Severity.S0
        }

    @property
    def required_approval_level(self) -> ApprovalLevel:
        base = (
            ApprovalLevel.SENIOR_MANAGER
            if any(
                item.severity == Severity.S0
                and item.group in {MetricGroup.G5, MetricGroup.G6}
                for item in self.waived_metrics
            )
            else ApprovalLevel.JOINT_MANAGERS
        )
        return ApprovalLevel(min(int(base) + self.extension_count, int(ApprovalLevel.EXECUTIVE)))

    def _validate_approvals(self) -> None:
        roles = {item.role for item in self.approvals}
        required_roles = {"imaging_system_manager", "requirements_owner"}
        if not required_roles <= roles:
            raise WaiverError("imaging-system and requirements managers must jointly approve")
        required = (
            ApprovalLevel.SENIOR_MANAGER
            if any(
                item.severity == Severity.S0
                and item.group in {MetricGroup.G5, MetricGroup.G6}
                for item in self.waived_metrics
            )
            else ApprovalLevel.JOINT_MANAGERS
        )
        required = ApprovalLevel(
            min(int(required) + self.extension_count, int(ApprovalLevel.EXECUTIVE))
        )
        maximum_level = max(
            (item.level for item in self.approvals),
            default=ApprovalLevel.JOINT_MANAGERS,
        )
        if maximum_level < required:
            raise WaiverError(f"waiver requires approval level {required.name}")

    def evaluate(
        self,
        *,
        as_of: date,
        current_measurements: Sequence[MeasurementResult] = (),
    ) -> WaiverEvaluation:
        if self.closed_revalidation_result is not None:
            return WaiverEvaluation(
                WaiverStatus.CLOSED_AFTER_REVALIDATION,
                False,
                self.closed_revalidation_result,
                self.original_result,
                False,
                self._next_tracking_due(),
                ("formal revalidation closed this waiver",),
            )
        current_new_s0 = {
            item.metric_id
            for item in current_measurements
            if item.severity == Severity.S0
        } - self.baseline_s0_metric_ids
        tracked_new_s0 = {
            metric_id
            for report in self.tracking_reports
            for metric_id in report.new_s0_metric_ids
        } - self.baseline_s0_metric_ids
        new_s0 = sorted(current_new_s0 | tracked_new_s0)
        if new_s0:
            return WaiverEvaluation(
                WaiverStatus.INVALIDATED_BY_NEW_S0,
                False,
                self.original_result,
                self.original_result,
                False,
                self._next_tracking_due(),
                ("new S0 immediately invalidated waiver: " + ", ".join(new_s0),),
            )
        if as_of > self.expires_on:
            return WaiverEvaluation(
                WaiverStatus.EXPIRED_ORIGINAL_RESULT_RESTORED,
                False,
                self.original_result,
                self.original_result,
                False,
                self._next_tracking_due(),
                ("waiver expired; original result restored and related work must stop",),
            )
        next_due = self._next_tracking_due()
        overdue = as_of > next_due and next_due <= self.expires_on
        return WaiverEvaluation(
            WaiverStatus.ACTIVE_NOT_ACCEPTED,
            True,
            self.original_result,
            self.original_result,
            not overdue and self.extension_count < 2,
            next_due,
            (
                "active waiver never changes the formal acceptance result",
                *(
                    ("30-day tracking is overdue; extension eligibility is lost",)
                    if overdue
                    else ()
                ),
            ),
        )

    def _next_tracking_due(self) -> date:
        anchor = (
            self.tracking_reports[-1].reported_on
            if self.tracking_reports
            else self.issued_on
        )
        return anchor + timedelta(days=30)

    def extend(
        self,
        *,
        waiver_id: str,
        issued_on: date,
        expires_on: date,
        hardware_improvement_date: date,
        approvals: Sequence[WaiverApproval],
        alternative_solution: str = "",
    ) -> "Waiver":
        if self.extension_count >= 2:
            raise WaiverError("the same metric may be extended at most twice")
        prior = self.evaluate(as_of=self.expires_on)
        if not prior.extension_eligible:
            raise WaiverError("waiver is not eligible for extension")
        return replace(
            self,
            waiver_id=waiver_id,
            parent_waiver_id=self.waiver_id,
            issued_on=issued_on,
            expires_on=expires_on,
            hardware_improvement_date=hardware_improvement_date,
            approvals=tuple(approvals),
            extension_count=self.extension_count + 1,
            alternative_solution=alternative_solution,
            tracking_reports=(),
        )

    def add_tracking_report(self, report: WaiverTrackingReport) -> "Waiver":
        return replace(self, tracking_reports=(*self.tracking_reports, report))


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WaiverError(f"{field_name} must be ISO-8601") from exc
