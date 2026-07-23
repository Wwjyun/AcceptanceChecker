# -*- coding: utf-8 -*-
"""時域 SNR、G4、R&R 與明確樣本下限測試。"""

from __future__ import annotations

import numpy as np
import pytest

from acceptance_checker import (
    ImageLevel,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
    RRObservation,
    Severity,
    TemperatureRecord,
    TemporalAcceptanceMeasurer,
    TemporalMeasurementInputs,
    TemporalSeries,
)
from acceptance_checker.reporting import DriftReporter


def background_roi() -> RoiDefinition:
    return RoiDefinition(
        roi_id="background",
        roi_type=RoiType.DEFECT_FREE_BACKGROUND,
        x=0,
        y=0,
        width=8,
        height=6,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="tester",
        version="1",
        image_id="*",
    )


def synthetic_series(count: int = 31, *, cover_8h: bool = True) -> TemporalSeries:
    rng = np.random.default_rng(7)
    base = rng.normal(100, 2, (count, 6, 8))
    if cover_8h:
        timestamps = np.linspace(0, 8 * 3600, count)
    else:
        timestamps = np.linspace(0, 20 * 60, count)
    return TemporalSeries(
        frames=base,
        timestamps_seconds=timestamps.tolist(),
        evidence_sources=[f"frame-{index:03}.tif" for index in range(count)],
    )


def rr_observations() -> list[RRObservation]:
    values = []
    cycle = 0
    for operator_index, operator in enumerate(("A", "B")):
        for part_index, part in enumerate(("P1", "P2", "P3")):
            for repeat in range(2):
                cycle += 1
                values.append(
                    RRObservation(
                        operator_id=operator,
                        part_id=part,
                        cycle_id=f"C{cycle:02}",
                        value=100 + part_index * 10 + operator_index * 0.2 + repeat * 0.1,
                    )
                )
    return values


def temperature_records(days: float = 7.0) -> list[TemperatureRecord]:
    count = int(days * 4) + 1
    return [
        TemperatureRecord(
            timestamp_seconds=index * 6 * 3600,
            temperature_c=20 + index / max(count - 1, 1) * 10,
            mean_signal=100 + index / max(count - 1, 1) * 2,
        )
        for index in range(count)
    ]


def complete_inputs() -> TemporalMeasurementInputs:
    rr = rr_observations()
    temperatures = temperature_records()
    return TemporalMeasurementInputs(
        series=synthetic_series(),
        roi=background_roi(),
        rr_observations=rr,
        rr_evidence_sources=[f"rr-{index}.csv" for index in range(len(rr))],
        restart_means=[100, 101, 99.5, 100.2, 99.8],
        restart_evidence_sources=[f"restart-{index}.tif" for index in range(5)],
        temperature_records=temperatures,
        temperature_evidence_sources=[
            f"temperature-{index}.csv" for index in range(len(temperatures))
        ],
    )


def by_id(report, metric_id: str):
    return next(item for item in report.measurements if item.metric_id == metric_id)


def test_temporal_snr_uses_same_pixel_across_at_least_30_frames():
    report = TemporalAcceptanceMeasurer().measure(complete_inputs())
    result = by_id(report, "g3.temporal_snr")

    stack = complete_inputs().series.frames.astype(np.float64)
    expected_sigma = float(np.mean(np.std(stack, axis=0, ddof=0)))
    expected_snr = float(np.mean(stack) / expected_sigma)
    assert result.value == pytest.approx(expected_snr)
    assert report.temporal_sigma_mean == pytest.approx(expected_sigma)
    assert result.sample_count == 31 * 6 * 8
    assert result.metadata["frame_count"] == 31


def test_complete_temporal_design_evaluates_all_seven_metrics():
    report = TemporalAcceptanceMeasurer().measure(complete_inputs())

    assert len(report.measurements) == 7
    assert all(item.severity != Severity.NOT_EVALUATED for item in report.measurements)
    assert by_id(report, "g4.gray_drift_30min_pct").metadata["actual_elapsed_seconds"] >= 1800
    assert by_id(report, "g4.gray_drift_8h_pct").metadata["actual_elapsed_seconds"] >= 28800
    rr = by_id(report, "g4.reproducibility_rr_pct")
    assert rr.metadata["method"] == "balanced_crossed_random_effects_anova"
    assert rr.metadata["cycle_count"] >= 10


def test_fewer_than_30_frames_are_explicitly_not_evaluated():
    inputs = complete_inputs()
    inputs.series = synthetic_series(count=29)
    report = TemporalAcceptanceMeasurer().measure(inputs)

    for metric_id in (
        "g3.temporal_snr",
        "g4.repeatability_cv_pct",
        "g4.gray_drift_30min_pct",
        "g4.gray_drift_8h_pct",
    ):
        result = by_id(report, metric_id)
        assert result.severity == Severity.NOT_EVALUATED
        assert "30 張" in result.missing_reason


def test_short_time_coverage_does_not_invent_drift_results():
    inputs = complete_inputs()
    inputs.series = synthetic_series(31, cover_8h=False)
    report = TemporalAcceptanceMeasurer().measure(inputs)

    assert by_id(report, "g4.gray_drift_30min_pct").severity == Severity.NOT_EVALUATED
    assert by_id(report, "g4.gray_drift_8h_pct").severity == Severity.NOT_EVALUATED


def test_restart_and_rr_minimum_designs_are_enforced():
    inputs = complete_inputs()
    inputs.restart_means = [100, 101, 99, 100]
    inputs.restart_evidence_sources = ["a", "b", "c", "d"]
    inputs.rr_observations = inputs.rr_observations[:8]
    inputs.rr_evidence_sources = inputs.rr_evidence_sources[:8]
    report = TemporalAcceptanceMeasurer().measure(inputs)

    restart = by_id(report, "g4.restart_reproducibility_pct")
    rr = by_id(report, "g4.reproducibility_rr_pct")
    assert restart.severity == Severity.NOT_EVALUATED
    assert "5 次" in restart.missing_reason
    assert rr.severity == Severity.NOT_EVALUATED
    assert "10 個" in rr.missing_reason


def test_temperature_evidence_under_seven_days_caps_grade_at_s1():
    inputs = complete_inputs()
    records = temperature_records(days=6.0)
    inputs.temperature_records = records
    inputs.temperature_evidence_sources = [f"t-{index}" for index in range(len(records))]
    report = TemporalAcceptanceMeasurer().measure(inputs)

    result = by_id(report, "g4.temperature_tolerance_drift_pct")
    assert result.value < 3
    assert result.severity == Severity.S1
    assert result.metadata["continuous_7d_evidence"] is False
    assert any("7 日" in warning for warning in report.warnings)


def test_l2_sequence_never_claims_formal_temporal_measurement():
    inputs = complete_inputs()
    inputs.image_level = ImageLevel.L2
    report = TemporalAcceptanceMeasurer().measure(inputs)

    assert {item.severity for item in report.measurements} == {Severity.NOT_EVALUATED}
    assert all("L1" in item.missing_reason for item in report.measurements)


def test_legacy_drift_reporter_uses_relative_drift_not_histogram_thresholds():
    from acceptance_checker import Metrics, Thresholds

    baseline = Metrics(mean_gray=100)
    changed = Metrics(mean_gray=104)
    thresholds = Thresholds(hist_spread_warn=1000, hist_spread_fail=2000)

    report = DriftReporter(thresholds).analyze([baseline, changed])

    assert report.mean_gray_spread == 4
    assert report.mean_gray_drift_pct == pytest.approx(4)
    assert report.drift_status == "WARNING"
