# -*- coding: utf-8 -*-
"""v4 section 14 responsibility routing and non-binding S2 correlations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Sequence

from .v4_domain import AcceptanceSession, MetricGroup, Severity


class ResponsibilityError(ValueError):
    """Raised when responsibility-review evidence is incomplete."""


class ReviewParty(str, Enum):
    IMAGING = "imaging_system"
    SOFTWARE = "software"
    QUALITY = "quality"


_GROUP_OWNERS: Dict[MetricGroup, Sequence[str]] = {
    MetricGroup.G1: ("optics", "lighting"),
    MetricGroup.G2: ("optics", "mechanics", "control"),
    MetricGroup.G3: ("camera", "equipment_vendor"),
    MetricGroup.G4: ("lighting", "mechanics", "facilities"),
    MetricGroup.G5: ("camera", "control", "mechanics"),
    MetricGroup.G6: ("software",),
}

_COUNTERMEASURES: Dict[MetricGroup, str] = {
    MetricGroup.G1: "geometry, illumination, polarization, aperture, exposure/scan matching",
    MetricGroup.G2: "lens, focus, working distance, vibration, line rate, encoder/speed matching",
    MetricGroup.G3: "camera selection, TDI, calibration, power, temperature, sensor defects",
    MetricGroup.G4: "warm-up, aging, thermal/power control, fixture and repositioning",
    MetricGroup.G5: "trigger, encoder, buffering, bandwidth, stitching and field coverage",
    MetricGroup.G6: "algorithm, features, model and decision parameters",
}

_S2_RELATIONS = (
    (
        ("background_cv", "background_spatial_std"),
        "background variation directly reduces defect CNR through its denominator",
        ("g6.defect_cnr",),
    ),
    (
        ("uniformity_u", "region_brightness_difference"),
        "field nonuniformity can directly reduce full-width detection consistency",
        ("g6.full_width_detection_consistency_pct",),
    ),
    (
        ("mtf_", "minimum_defect_width", "motion_blur"),
        "resolution or blur can directly reduce minimum-defect recognizability",
        ("g6.defect_cnr", "g6.golden_ng_detection"),
    ),
    (
        ("overexposure", "low_clip", "highlight", "defect_edge_low_clip"),
        "clipping or highlight occupancy can truncate the defect signal",
        ("g6.defect_cnr", "g6.golden_ng_detection"),
    ),
    (
        ("repeatability", "reproducibility", "drift", "restart"),
        "instability can directly reduce Golden margin and cause intermittent misses",
        ("g6.golden_ng_detection",),
    ),
    (
        ("stitch_", "inter_camera_gray"),
        "stitch or camera mismatch can directly reduce regional detection rate",
        ("g6.full_width_detection_consistency_pct",),
    ),
)


@dataclass(frozen=True)
class TechnicalObjection:
    objection_id: str
    party: ReviewParty
    statement: str
    submitted_at: str
    evidence_sources: Sequence[str]

    def __post_init__(self) -> None:
        if not self.objection_id or not self.statement or not self.submitted_at:
            raise ResponsibilityError("technical objection identity and statement are required")
        if not self.evidence_sources:
            raise ResponsibilityError("technical objection requires written evidence")


@dataclass(frozen=True)
class DiagnosticAttachment:
    attachment_id: str
    experiment_type: str
    source: str
    sha256: str
    conclusion: str

    def __post_init__(self) -> None:
        if not all(
            (self.attachment_id, self.experiment_type, self.source, self.conclusion)
        ):
            raise ResponsibilityError("diagnostic attachment fields cannot be empty")
        if len(self.sha256) != 64:
            raise ResponsibilityError("diagnostic attachment requires SHA-256")


@dataclass(frozen=True)
class ThreePartyPosition:
    party: ReviewParty
    representative: str
    position: str
    signed_at: str

    def __post_init__(self) -> None:
        if not all((self.representative, self.position, self.signed_at)):
            raise ResponsibilityError("three-party position fields cannot be empty")


@dataclass(frozen=True)
class CorrelationAssessment:
    source_metric_id: str
    source_group: MetricGroup
    related_g6_metric_ids: Sequence[str]
    mechanism: str
    status: str = "presumed_pending_three_party_confirmation"
    burden_of_evidence: str = "party_claiming_no_direct_relation"


@dataclass(frozen=True)
class ResponsibilityAction:
    priority: int
    group: MetricGroup
    severity: Severity
    primary_units: Sequence[str]
    countermeasure: str
    role_status: str


@dataclass
class ResponsibilityReport:
    actions: List[ResponsibilityAction]
    s2_correlations: List[CorrelationAssessment]
    l2_remediation_prohibited: bool
    l2_warning: str
    final_assignment_status: str
    objections: Sequence[TechnicalObjection] = field(default_factory=list)
    three_party_positions: Sequence[ThreePartyPosition] = field(default_factory=list)
    diagnostic_attachments: Sequence[DiagnosticAttachment] = field(default_factory=list)


class ResponsibilityAnalyzer:
    """Create prioritized owners without replacing evidence or three-party review."""

    def analyze(
        self,
        session: AcceptanceSession,
        *,
        objections: Sequence[TechnicalObjection] = (),
        three_party_positions: Sequence[ThreePartyPosition] = (),
        diagnostic_attachments: Sequence[DiagnosticAttachment] = (),
    ) -> ResponsibilityReport:
        statuses = session.group_statuses()
        hardware_failure = any(
            statuses[group] in {Severity.S0, Severity.S1}
            for group in (
                MetricGroup.G1,
                MetricGroup.G2,
                MetricGroup.G3,
                MetricGroup.G4,
                MetricGroup.G5,
            )
        )
        actions: List[ResponsibilityAction] = []
        for group in MetricGroup:
            severity = statuses[group]
            if severity not in {Severity.S0, Severity.S1}:
                continue
            if group == MetricGroup.G6 and hardware_failure:
                actions.append(
                    ResponsibilityAction(
                        priority=80,
                        group=group,
                        severity=severity,
                        primary_units=("corresponding_hardware_units",),
                        countermeasure="repair G1-G5 capability, then repeat formal G6",
                        role_status="software_measurement_only_no_quality_target",
                    )
                )
            else:
                actions.append(
                    ResponsibilityAction(
                        priority=_priority(severity, group),
                        group=group,
                        severity=severity,
                        primary_units=_GROUP_OWNERS[group],
                        countermeasure=_COUNTERMEASURES[group],
                        role_status=(
                            "software_primary"
                            if group == MetricGroup.G6
                            else "software_measurement_and_analysis_only"
                        ),
                    )
                )
        correlations = self._correlations(session)
        g6_failed = statuses[MetricGroup.G6] in {Severity.S0, Severity.S1}
        if g6_failed and correlations:
            actions.append(
                ResponsibilityAction(
                    priority=60,
                    group=MetricGroup.G6,
                    severity=statuses[MetricGroup.G6],
                    primary_units=("pending_three_party_confirmation",),
                    countermeasure="complete causal evidence before final ownership assignment",
                    role_status="presumed_relation_not_final_assignment",
                )
            )
        actions.sort(key=lambda item: (item.priority, item.group.value))
        l2_warning = (
            "G1-G5 contains S1/S0: L2 denoise, sharpen, CLAHE, gamma, local recipe, "
            "or AI repair cannot be used as an acceptance countermeasure."
            if hardware_failure
            else ""
        )
        positions = {item.party for item in three_party_positions}
        if g6_failed and correlations:
            final_status = (
                "three_party_confirmed"
                if positions == set(ReviewParty)
                else "pending_three_party_confirmation"
            )
            if positions == set(ReviewParty):
                unique_positions = {item.position for item in three_party_positions}
                if len(unique_positions) > 1 and not diagnostic_attachments:
                    final_status = "disputed_experiment_required"
        else:
            final_status = "rule_based_assignment"
        return ResponsibilityReport(
            actions=actions,
            s2_correlations=correlations,
            l2_remediation_prohibited=hardware_failure,
            l2_warning=l2_warning,
            final_assignment_status=final_status,
            objections=list(objections),
            three_party_positions=list(three_party_positions),
            diagnostic_attachments=list(diagnostic_attachments),
        )

    @staticmethod
    def _correlations(session: AcceptanceSession) -> List[CorrelationAssessment]:
        assessments: List[CorrelationAssessment] = []
        for measurement in session.measurements:
            if (
                measurement.group == MetricGroup.G6
                or measurement.severity != Severity.S2
                or measurement.metadata.get("non_graded", False)
            ):
                continue
            for fragments, mechanism, related in _S2_RELATIONS:
                if any(fragment in measurement.metric_id for fragment in fragments):
                    assessments.append(
                        CorrelationAssessment(
                            source_metric_id=measurement.metric_id,
                            source_group=measurement.group,
                            related_g6_metric_ids=related,
                            mechanism=mechanism,
                        )
                    )
                    break
        return assessments


def _priority(severity: Severity, group: MetricGroup) -> int:
    severity_rank = 0 if severity == Severity.S0 else 20
    group_rank = {
        MetricGroup.G5: 0,
        MetricGroup.G6: 1,
        MetricGroup.G1: 2,
        MetricGroup.G2: 3,
        MetricGroup.G3: 4,
        MetricGroup.G4: 5,
    }[group]
    return severity_rank + group_rank
