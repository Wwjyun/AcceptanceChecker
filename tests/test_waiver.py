from dataclasses import replace
from datetime import date, timedelta

import pytest

from acceptance_checker import (
    ApprovalLevel,
    ImageLevel,
    MeasurementResult,
    MetricGroup,
    OverallResult,
    Severity,
    WaivedMetric,
    Waiver,
    WaiverApproval,
    WaiverError,
    WaiverStatus,
    WaiverTrackingReport,
)

ISSUED = date(2026, 1, 1)


def approvals(level=ApprovalLevel.JOINT_MANAGERS):
    return [
        WaiverApproval(
            "Imaging Manager",
            "imaging_system_manager",
            ApprovalLevel.JOINT_MANAGERS,
            "2026-01-01T09:00:00+08:00",
        ),
        WaiverApproval(
            "Requirements Owner",
            "requirements_owner",
            level,
            "2026-01-01T09:01:00+08:00",
        ),
    ]


def metric(metric_id="g1.diffuse.background_cv", severity=Severity.S1):
    return WaivedMetric(metric_id, MetricGroup.G1, severity, 0.2, "ratio")


def waiver(**changes):
    data = {
        "waiver_id": "W-1",
        "session_id": "S-1",
        "original_result": OverallResult.REJECTED_RETEST,
        "original_decision_rule": 5,
        "waived_metrics": [metric()],
        "risk_assessment": {
            "missed_detection": "reduced margin",
            "false_detection": "monitor false calls",
            "equipment_stability": "drift risk",
            "traceability": "retain all records",
        },
        "responsible_owner": "Optics Team",
        "hardware_improvement_date": ISSUED + timedelta(days=60),
        "issued_on": ISSUED,
        "expires_on": ISSUED + timedelta(days=89),
        "approvals": approvals(),
        "detection_target_adjustment": "targets unchanged; risk accepted temporarily",
        "best_effort_acknowledgement": "software delivery is best effort only",
    }
    data.update(changes)
    return Waiver(**data)


def tracking(day, *, new_s0=()):
    return WaiverTrackingReport(
        reported_on=ISSUED + timedelta(days=day),
        hardware_progress_pct=day,
        remaining_work="replace illumination and repeat G1/G6",
        missed_detections=0,
        false_detections=1,
        latest_measurements=[metric(severity=Severity.S2)],
        new_s1_metric_ids=["g4.gray_drift_30min_pct"],
        new_s0_metric_ids=list(new_s0),
        evidence_sources=[f"tracking-{day}.pdf"],
    )


def current_s0(metric_id):
    return MeasurementResult(
        metric_id=metric_id,
        group=MetricGroup.G5,
        severity=Severity.S0,
        unit="count",
        formula_version="1",
        image_level=ImageLevel.L1,
        value=1,
    )


def test_active_waiver_never_changes_original_formal_result():
    evaluation = waiver().evaluate(as_of=ISSUED + timedelta(days=10))

    assert evaluation.status == WaiverStatus.ACTIVE_NOT_ACCEPTED
    assert evaluation.effective
    assert evaluation.formal_result == OverallResult.REJECTED_RETEST
    assert "never changes" in evaluation.reasons[0]


def test_validity_cannot_exceed_90_days_and_expiry_restores_original_result():
    with pytest.raises(WaiverError, match="90"):
        waiver(expires_on=ISSUED + timedelta(days=91))

    evaluation = waiver().evaluate(as_of=ISSUED + timedelta(days=90))
    assert evaluation.status == WaiverStatus.EXPIRED_ORIGINAL_RESULT_RESTORED
    assert not evaluation.effective
    assert evaluation.formal_result == OverallResult.REJECTED_RETEST


def test_new_s0_immediately_invalidates_active_waiver():
    evaluation = waiver().evaluate(
        as_of=ISSUED + timedelta(days=10),
        current_measurements=[current_s0("g5.missing_duplicate_lines")],
    )

    assert evaluation.status == WaiverStatus.INVALIDATED_BY_NEW_S0
    assert not evaluation.effective
    assert not evaluation.extension_eligible


def test_30_day_tracking_controls_extension_eligibility():
    overdue = waiver().evaluate(as_of=ISSUED + timedelta(days=31))
    assert overdue.effective
    assert not overdue.extension_eligible
    assert "overdue" in overdue.reasons[-1]

    tracked = waiver().add_tracking_report(tracking(30)).add_tracking_report(
        tracking(60)
    )
    evaluation = tracked.evaluate(as_of=ISSUED + timedelta(days=80))
    assert evaluation.extension_eligible
    assert evaluation.next_tracking_due == ISSUED + timedelta(days=90)


def test_extensions_raise_approval_and_second_requires_alternative_solution():
    base = waiver().add_tracking_report(tracking(30)).add_tracking_report(tracking(60))
    first = base.extend(
        waiver_id="W-2",
        issued_on=ISSUED + timedelta(days=90),
        expires_on=ISSUED + timedelta(days=170),
        hardware_improvement_date=ISSUED + timedelta(days=150),
        approvals=approvals(ApprovalLevel.SENIOR_MANAGER),
    )
    assert first.extension_count == 1
    assert first.required_approval_level == ApprovalLevel.SENIOR_MANAGER

    first = replace(
        first,
        tracking_reports=(
            replace(tracking(30), reported_on=ISSUED + timedelta(days=120)),
            replace(tracking(60), reported_on=ISSUED + timedelta(days=150)),
        ),
    )
    with pytest.raises(WaiverError, match="alternative"):
        first.extend(
            waiver_id="W-3",
            issued_on=ISSUED + timedelta(days=171),
            expires_on=ISSUED + timedelta(days=250),
            hardware_improvement_date=ISSUED + timedelta(days=240),
            approvals=approvals(ApprovalLevel.DIRECTOR),
        )
    second = first.extend(
        waiver_id="W-3",
        issued_on=ISSUED + timedelta(days=171),
        expires_on=ISSUED + timedelta(days=250),
        hardware_improvement_date=ISSUED + timedelta(days=240),
        approvals=approvals(ApprovalLevel.DIRECTOR),
        alternative_solution="replace camera or narrow the approved inspection scope",
    )
    assert second.extension_count == 2
    with pytest.raises(WaiverError, match="at most twice"):
        second.extend(
            waiver_id="W-4",
            issued_on=ISSUED + timedelta(days=251),
            expires_on=ISSUED + timedelta(days=300),
            hardware_improvement_date=ISSUED + timedelta(days=290),
            approvals=approvals(ApprovalLevel.EXECUTIVE),
        )


def test_g5_or_g6_s0_requires_extra_approval_level():
    fatal = metric("g5.missing_duplicate_lines", Severity.S0)
    fatal = replace(fatal, group=MetricGroup.G5)
    with pytest.raises(WaiverError, match="SENIOR_MANAGER"):
        waiver(
            original_result=OverallResult.FATAL_STOP,
            original_decision_rule=2,
            waived_metrics=[fatal],
        )
