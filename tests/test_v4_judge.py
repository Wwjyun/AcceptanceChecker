# -*- coding: utf-8 -*-
"""v4 第 13.2 節依序判定 decision-table 測試。"""

from __future__ import annotations

import pytest

from acceptance_checker import (
    AcceptanceManifest,
    AcceptanceSession,
    ImageLevel,
    MeasurementResult,
    MetricGroup,
    OpticalMode,
    OverallResult,
    S0PriorityEvent,
    S0PriorityEventType,
    Severity,
    V4AcceptanceJudge,
)


def _session(statuses):
    session = AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="AOI-01",
            optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        )
    )
    for group, severity in statuses.items():
        session.add_measurement(
            MeasurementResult(
                metric_id=f"{group.value.lower()}.test",
                group=group,
                severity=severity,
                unit="ratio",
                formula_version="test",
                image_level=ImageLevel.L1,
                value=None if severity == Severity.NOT_EVALUATED else 1.0,
                missing_reason="缺少證據" if severity == Severity.NOT_EVALUATED else "",
                evidence_sources=["fixture.json"],
            )
        )
    return session


def _all(severity=Severity.S3):
    return {group: severity for group in MetricGroup}


@pytest.mark.parametrize(
    "statuses, events, expected_result, expected_rule",
    [
        (
            _all(),
            [
                S0PriorityEvent(
                    S0PriorityEventType.INSPECTION_BLIND_ZONE,
                    "接縫形成 1 px 盲區",
                    ["scan-log.json"],
                )
            ],
            OverallResult.FATAL_STOP,
            1,
        ),
        (
            {**_all(), MetricGroup.G5: Severity.S0},
            [],
            OverallResult.FATAL_STOP,
            2,
        ),
        (
            {**_all(), MetricGroup.G1: Severity.S0, MetricGroup.G2: Severity.S0},
            [],
            OverallResult.FATAL_STOP,
            3,
        ),
        (
            {**_all(), MetricGroup.G3: Severity.S0},
            [],
            OverallResult.REJECTED_RETEST,
            4,
        ),
        (
            {**_all(), MetricGroup.G4: Severity.S1},
            [],
            OverallResult.REJECTED_RETEST,
            5,
        ),
        (
            {
                MetricGroup.G1: Severity.S3,
                MetricGroup.G2: Severity.S3,
                MetricGroup.G3: Severity.S3,
                MetricGroup.G4: Severity.S3,
                MetricGroup.G5: Severity.S2,
                MetricGroup.G6: Severity.S2,
            },
            [],
            OverallResult.ACCEPTED,
            6,
        ),
        (
            {
                MetricGroup.G1: Severity.S3,
                MetricGroup.G2: Severity.S3,
                MetricGroup.G3: Severity.S3,
                MetricGroup.G4: Severity.S2,
                MetricGroup.G5: Severity.S2,
                MetricGroup.G6: Severity.S2,
            },
            [],
            OverallResult.CONDITIONALLY_ACCEPTED,
            7,
        ),
    ],
)
def test_decision_table(statuses, events, expected_result, expected_rule):
    session = _session(statuses)

    decision = V4AcceptanceJudge().judge(session, events)

    assert decision.result == expected_result
    assert decision.rule_number == expected_rule
    assert session.overall_result == expected_result
    assert session.decision_rule == expected_rule


def test_first_matching_rule_wins_when_multiple_conditions_apply():
    session = _session(
        {
            **_all(),
            MetricGroup.G1: Severity.S0,
            MetricGroup.G5: Severity.S0,
        }
    )

    decision = V4AcceptanceJudge().judge(session)

    assert decision.rule_number == 2
    assert decision.trigger_groups == ["G5"]
    assert decision.trigger_metric_ids == ["g5.test"]


def test_missing_group_cannot_be_accepted():
    statuses = _all()
    del statuses[MetricGroup.G6]
    session = _session(statuses)

    decision = V4AcceptanceJudge().judge(session)

    assert decision.result == OverallResult.INSUFFICIENT_EVIDENCE
    assert decision.rule_number is None
    assert decision.missing_groups == ["G6"]


def test_not_evaluated_metric_is_reported_as_evidence_gap():
    session = _session({**_all(), MetricGroup.G2: Severity.NOT_EVALUATED})

    decision = V4AcceptanceJudge().judge(session)

    assert decision.result == OverallResult.INSUFFICIENT_EVIDENCE
    assert decision.missing_metric_ids == ["g2.test"]


def test_s0_priority_event_requires_evidence():
    with pytest.raises(ValueError, match="evidence_sources"):
        S0PriorityEvent(
            S0PriorityEventType.GOLDEN_NG_STABLE_MISS,
            "Golden NG 穩定漏檢",
            [],
        )
