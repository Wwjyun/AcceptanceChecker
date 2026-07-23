from acceptance_checker import (
    AcceptanceManifest,
    AcceptanceSession,
    ImageLevel,
    MeasurementResult,
    MetricGroup,
    OpticalMode,
    ResponsibilityAnalyzer,
    ReviewParty,
    Severity,
    ThreePartyPosition,
)


def measurement(metric_id, group, severity):
    return MeasurementResult(
        metric_id=metric_id,
        group=group,
        severity=severity,
        unit="x",
        formula_version="1",
        image_level=ImageLevel.L1,
        value=1,
    )


def session_with(items):
    return AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="m", optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD
        ),
        measurements=items,
    )


def test_hardware_s1_prohibits_l2_and_precedes_g6_software_work():
    report = ResponsibilityAnalyzer().analyze(
        session_with(
            [
                measurement("g1.diffuse.background_cv", MetricGroup.G1, Severity.S1),
                measurement("g6.golden_ng_detection", MetricGroup.G6, Severity.S1),
            ]
        )
    )

    assert report.l2_remediation_prohibited
    assert "L2" in report.l2_warning
    assert report.actions[0].primary_units == ("optics", "lighting")
    assert report.actions[1].primary_units == ("corresponding_hardware_units",)


def test_s2_relation_is_presumed_pending_and_not_automatic_assignment():
    report = ResponsibilityAnalyzer().analyze(
        session_with(
            [
                measurement("g1.diffuse.background_cv", MetricGroup.G1, Severity.S2),
                measurement("g6.defect_cnr", MetricGroup.G6, Severity.S1),
            ]
        )
    )

    assert report.s2_correlations[0].related_g6_metric_ids == ("g6.defect_cnr",)
    assert report.s2_correlations[0].status.startswith("presumed")
    assert report.final_assignment_status == "pending_three_party_confirmation"
    assert report.actions[-1].primary_units == ("pending_three_party_confirmation",)


def test_disagreeing_three_party_positions_require_experiment():
    positions = [
        ThreePartyPosition(party, party.value, position, "2026-07-23")
        for party, position in zip(
            ReviewParty, ("hardware_related", "not_related", "hardware_related")
        )
    ]
    report = ResponsibilityAnalyzer().analyze(
        session_with(
            [
                measurement("g2.motion_blur_px", MetricGroup.G2, Severity.S2),
                measurement("g6.golden_ng_detection", MetricGroup.G6, Severity.S1),
            ]
        ),
        three_party_positions=positions,
    )

    assert report.final_assignment_status == "disputed_experiment_required"
