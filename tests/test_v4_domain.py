# -*- coding: utf-8 -*-
"""v4 領域模型、序列化、群組狀態與 legacy 邊界測試。"""

from __future__ import annotations

import os

import pytest

from acceptance_checker import (
    AcceptanceManifest,
    AcceptanceSession,
    ImageLevel,
    LegacyMetricsAdapter,
    MeasurementResult,
    MetricGroup,
    Metrics,
    OpticalMode,
    OverallResult,
    Severity,
    legacy_metrics_to_measurements,
)


def _measurement(
    metric_id: str,
    group: MetricGroup,
    severity: Severity,
    value=1.0,
    missing_reason: str = "",
) -> MeasurementResult:
    return MeasurementResult(
        metric_id=metric_id,
        group=group,
        severity=severity,
        unit="ratio",
        formula_version="test-v1",
        image_level=ImageLevel.L1,
        value=value,
        roi_id="background",
        sample_count=30,
        evidence_sources=["images/frame-001.tif"],
        missing_reason=missing_reason,
    )


def test_session_json_round_trip_is_lossless():
    manifest = AcceptanceManifest(
        machine_id="AOI-01",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        session_id="session-fixed",
        spec_version="v4-draft",
        created_at="2026-07-23T12:00:00+00:00",
        precondition_lock={"camera_serial": "CAM-001", "gain": 2.5},
        metadata={"line": "L1"},
    )
    session = AcceptanceSession(
        manifest=manifest,
        measurements=[_measurement("g1.uniformity", MetricGroup.G1, Severity.S2, 0.88)],
        overall_result=OverallResult.CONDITIONALLY_ACCEPTED,
        decision_rule=7,
        notes=["等待趨勢監控"],
    )

    restored = AcceptanceSession.from_json(session.to_json())

    assert restored == session
    assert restored.to_dict() == session.to_dict()


def test_unicode_file_round_trip(tmp_path):
    session = AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="機台一號",
            optical_mode=OpticalMode.SCATTERING_DARK_FIELD,
        )
    )
    path = os.path.join(tmp_path, "驗收工作階段.json")

    session.save_json(path)

    assert AcceptanceSession.load_json(path) == session


def test_empty_groups_are_not_evaluated():
    session = AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="AOI-01",
            optical_mode=OpticalMode.SPECULAR_BRIGHT_FIELD,
        )
    )

    assert session.group_statuses() == {
        group: Severity.NOT_EVALUATED for group in MetricGroup
    }
    assert session.overall_result == OverallResult.INSUFFICIENT_EVIDENCE


def test_group_status_keeps_missing_evidence_without_hiding_s0_or_s1():
    session = AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="AOI-01",
            optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        )
    )
    session.add_measurement(_measurement("g1.mean", MetricGroup.G1, Severity.S3, 55.0))
    session.add_measurement(
        _measurement(
            "g1.stray_light",
            MetricGroup.G1,
            Severity.NOT_EVALUATED,
            value=None,
            missing_reason="缺少 blocked 與 dark 影像",
        )
    )
    assert session.group_status(MetricGroup.G1) == Severity.NOT_EVALUATED

    session.add_measurement(_measurement("g1.blind_zone", MetricGroup.G1, Severity.S0, 1))
    assert session.group_status(MetricGroup.G1) == Severity.S0

    session.add_measurement(
        _measurement(
            "g2.mtf",
            MetricGroup.G2,
            Severity.NOT_EVALUATED,
            value=None,
            missing_reason="缺少 slanted-edge 標靶",
        )
    )
    session.add_measurement(_measurement("g2.blur", MetricGroup.G2, Severity.S1, 1.8))
    assert session.group_status(MetricGroup.G2) == Severity.S1


def test_measurement_validation_rejects_ambiguous_state():
    with pytest.raises(ValueError, match="missing_reason"):
        _measurement("g1.mean", MetricGroup.G1, Severity.NOT_EVALUATED, value=None)

    with pytest.raises(ValueError, match="必須提供 value"):
        _measurement("g1.mean", MetricGroup.G1, Severity.S3, value=None)

    with pytest.raises(ValueError, match="sample_count"):
        MeasurementResult(
            metric_id="g1.mean",
            group=MetricGroup.G1,
            severity=Severity.S3,
            unit="percent_fs",
            formula_version="v1",
            image_level=ImageLevel.L1,
            value=50.0,
            sample_count=-1,
        )


def test_legacy_adapter_never_claims_v4_evaluation():
    metrics = Metrics(
        file_name="sample.tif",
        file_path="data/sample.tif",
        norm_method="16bit-percentile(1-99)",
        mean_gray=120.0,
        uniformity_ratio=0.9,
        signal_to_noise_ratio=42.0,
        auto_defect_cnr_est=8.0,
    )

    adapted = legacy_metrics_to_measurements(metrics)

    assert adapted == LegacyMetricsAdapter().adapt(metrics)
    assert len(adapted) == 9
    assert {item.severity for item in adapted} == {Severity.NOT_EVALUATED}
    assert {item.image_level for item in adapted} == {ImageLevel.L2}
    assert all(item.missing_reason for item in adapted)
    assert any(item.metric_id == "legacy.single_image_spatial_snr_proxy" for item in adapted)
    assert all(item.evidence_sources == ["data/sample.tif"] for item in adapted)


def test_session_json_rejects_non_object():
    with pytest.raises(ValueError, match="必須是物件"):
        AcceptanceSession.from_json("[1, 2, 3]")
