# -*- coding: utf-8 -*-
"""Formula, evidence, and S0-path tests for formal v4 G5 measurements."""

from __future__ import annotations

import numpy as np
import pytest

from acceptance_checker import (
    AcquisitionIntegrityEvidence,
    G5MeasurementError,
    G5MeasurementInputs,
    G5Measurer,
    ImageContract,
    ImageObservation,
    InterCameraGrayEvidence,
    Severity,
    StitchEvidence,
)
from tests.test_traceability import manifest


def by_id(report):
    return {item.metric_id: item for item in report.measurements}


def good_integrity():
    return AcquisitionIntegrityEvidence(
        basis="acquisition_log",
        evidence_source="acquisition.csv",
        method_version="integrity-1",
        expected_line_ids=range(6),
        observed_line_ids=range(6),
        expected_frame_ids=range(3),
        observed_frame_ids=range(3),
    )


def good_inputs():
    return G5MeasurementInputs(
        image_contract=ImageContract(8, 6, 12, "contract.json", "contract-1"),
        image_observations=[
            ImageObservation("frame-0.raw", 8, 6, 12, "scan-0"),
            ImageObservation("frame-1.raw", 8, 6, 12, "scan-1"),
        ],
        acquisition_integrity=good_integrity(),
        stitch=StitchEvidence(
            required=True,
            evidence_sources=["seam-target.raw", "stitch-log.json"],
            method_version="stitch-1",
            left_band=np.full((4, 3), 100.0),
            right_band=np.full((4, 3), 104.0),
            position_residuals_px=[0.5, 1.0, 1.5],
            blind_zone_widths_px=[0.0, 0.0, 0.0],
        ),
        inter_camera=InterCameraGrayEvidence(
            camera_rois={
                "CAM-1": np.full((4, 4), 100.0),
                "CAM-2": np.full((4, 4), 102.0),
            },
            evidence_sources=["camera-equivalent-rois.json"],
            method_version="gray-1",
        ),
        manifest=manifest(),
    )


def test_complete_g5_design_evaluates_all_eight_metrics():
    metrics = by_id(G5Measurer().measure(good_inputs()))

    assert len(metrics) == 8
    assert metrics["g5.missing_duplicate_lines"].severity == Severity.S3
    assert metrics["g5.image_shape_bit_depth_match"].severity == Severity.S3
    assert metrics["g5.dropped_frames_interruptions"].severity == Severity.S3
    assert metrics["g5.stitch_brightness_difference_pct"].value == pytest.approx(
        4 / 102 * 100
    )
    assert metrics["g5.stitch_brightness_difference_pct"].severity == Severity.S2
    assert metrics["g5.stitch_position_error_px"].value == 1.5
    assert metrics["g5.stitch_position_error_px"].severity == Severity.S2
    assert metrics["g5.stitch_blind_width_px"].severity == Severity.S3
    assert metrics["g5.inter_camera_gray_difference_pct"].value == pytest.approx(
        2 / 101 * 100
    )
    assert metrics["g5.traceability_completeness"].severity == Severity.S3


def test_line_frame_and_interruption_evidence_identifies_each_s0_event():
    inputs = good_inputs()
    inputs.acquisition_integrity = AcquisitionIntegrityEvidence(
        basis="encoder_timestamp",
        evidence_source="encoder.csv",
        method_version="integrity-1",
        expected_line_ids=[0, 1, 2, 3],
        observed_line_ids=[0, 1, 1, 3],
        expected_frame_ids=[0, 1, 2],
        observed_frame_ids=[0, 2, 2],
        interruption_events=["scan-2:trigger-timeout"],
    )

    metrics = by_id(G5Measurer().measure(inputs))

    line = metrics["g5.missing_duplicate_lines"]
    frame = metrics["g5.dropped_frames_interruptions"]
    assert line.severity == Severity.S0
    assert line.value == 2
    assert line.metadata["missing"] == [2]
    assert line.metadata["duplicate_or_unexpected"] == [1]
    assert frame.severity == Severity.S0
    assert frame.value == 3
    assert frame.metadata["missing"] == [1]
    assert frame.metadata["duplicate_or_unexpected"] == [2]
    assert frame.metadata["interruption_events"] == ["scan-2:trigger-timeout"]


def test_absent_acquisition_evidence_never_claims_zero_events():
    inputs = good_inputs()
    inputs.acquisition_integrity = None

    metrics = by_id(G5Measurer().measure(inputs))

    for metric_id in (
        "g5.missing_duplicate_lines",
        "g5.dropped_frames_interruptions",
    ):
        assert metrics[metric_id].severity == Severity.NOT_EVALUATED
        assert "cannot prove zero" in metrics[metric_id].missing_reason


def test_empty_inputs_make_every_g5_metric_not_evaluated():
    metrics = G5Measurer().measure(G5MeasurementInputs()).measurements

    assert len(metrics) == 8
    assert all(item.severity == Severity.NOT_EVALUATED for item in metrics)
    assert all(item.missing_reason for item in metrics)


def test_image_contract_mismatch_and_duplicate_sequence_are_s0_with_sources():
    inputs = good_inputs()
    inputs.image_observations = [
        ImageObservation("a.raw", 8, 6, 12, "scan-0"),
        ImageObservation("b.raw", 9, 6, 8, "scan-0"),
    ]

    metric = by_id(G5Measurer().measure(inputs))[
        "g5.image_shape_bit_depth_match"
    ]

    assert metric.severity == Severity.S0
    assert metric.value is False
    assert len(metric.metadata["mismatches"]) == 2
    assert {"a.raw", "b.raw"} <= set(metric.evidence_sources)


def test_blind_zone_is_s0_and_forces_brightness_s0_regardless_of_threshold():
    inputs = good_inputs()
    inputs.stitch = StitchEvidence(
        required=True,
        evidence_sources=["seam.raw"],
        method_version="stitch-1",
        left_band=np.full((4, 3), 100.0),
        right_band=np.full((4, 3), 100.0),
        position_residuals_px=[0.0, 0.0, 0.0],
        blind_zone_widths_px=[0.0, 1.0],
    )

    metrics = by_id(G5Measurer().measure(inputs))

    assert metrics["g5.stitch_blind_width_px"].severity == Severity.S0
    assert metrics["g5.stitch_brightness_difference_pct"].value == 0.0
    assert metrics["g5.stitch_brightness_difference_pct"].severity == Severity.S0
    assert metrics["g5.stitch_brightness_difference_pct"].metadata[
        "blind_zone_forced_s0"
    ]


def test_explicit_single_camera_architecture_evaluates_non_applicable_stitching():
    inputs = good_inputs()
    inputs.stitch = StitchEvidence(
        required=False,
        evidence_sources=["architecture.json"],
        method_version="architecture-1",
    )
    inputs.inter_camera = InterCameraGrayEvidence(
        camera_rois={"CAM-1": np.full((4, 4), 100.0)},
        evidence_sources=["camera-roi.json"],
        method_version="gray-1",
    )

    metrics = by_id(G5Measurer().measure(inputs))

    for metric_id in (
        "g5.stitch_brightness_difference_pct",
        "g5.stitch_position_error_px",
        "g5.stitch_blind_width_px",
        "g5.inter_camera_gray_difference_pct",
    ):
        assert metrics[metric_id].severity == Severity.S3


def test_stitch_evidence_requires_feature_and_coverage_quality():
    with pytest.raises(G5MeasurementError, match="three matched"):
        StitchEvidence(
            required=True,
            evidence_sources=["seam.raw"],
            method_version="stitch-1",
            left_band=np.ones((2, 2)),
            right_band=np.ones((2, 2)),
            position_residuals_px=[0.1, 0.2],
            blind_zone_widths_px=[0.0],
        )
