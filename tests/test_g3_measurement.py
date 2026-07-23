# -*- coding: utf-8 -*-
"""G3 DSNU、PRNU、FPN、Golden STD 與壞點測試。"""

from __future__ import annotations

import numpy as np

from acceptance_checker import (
    G3MeasurementInputs,
    G3Measurer,
    ImageLevel,
    MeasurementResult,
    MetricGroup,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
    SensorFrameSeries,
    Severity,
)


def roi(roi_id: str, roi_type: RoiType, x=0, y=0, width=16, height=16):
    return RoiDefinition(
        roi_id=roi_id,
        roi_type=roi_type,
        x=x,
        y=y,
        width=width,
        height=height,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="tester",
        version="1",
        image_id="*",
    )


def series(condition: str, count: int) -> SensorFrameSeries:
    rng = np.random.default_rng(42 if condition == "dark" else 43)
    yy, xx = np.indices((16, 16))
    if condition == "dark":
        fixed = 30 + (yy % 4) * 0.5
        frames = fixed + rng.normal(0, 0.5, (count, 16, 16))
    else:
        fixed = 2000 + (xx % 4) * 5 + (yy % 3) * 2
        frames = fixed + rng.normal(0, 2, (count, 16, 16))
    return SensorFrameSeries(
        frames=frames.astype(np.float64),
        condition=condition,
        full_scale=4095,
        evidence_sources=[f"{condition}-{index:03}.tif" for index in range(count)],
        method_version="emva-style-v1",
    )


def temporal_snr() -> MeasurementResult:
    return MeasurementResult(
        metric_id="g3.temporal_snr",
        group=MetricGroup.G3,
        severity=Severity.S3,
        unit="ratio",
        formula_version="v4-formula-1",
        image_level=ImageLevel.L1,
        value=50.0,
        roi_id="sensor",
        sample_count=30 * 16 * 16,
        evidence_sources=[f"temporal-{index}.tif" for index in range(30)],
    )


def complete_inputs() -> G3MeasurementInputs:
    rng = np.random.default_rng(9)
    current = rng.normal(100, 5.5, (16, 16))
    return G3MeasurementInputs(
        temporal_snr=temporal_snr(),
        dark_series=series("dark", 100),
        uniform_series=series("uniform", 100),
        sensor_roi=roi("sensor", RoiType.DEFECT_FREE_BACKGROUND),
        current_l1_image=current,
        current_l1_evidence="current-l1.tif",
        golden_spatial_std=5.0,
        golden_evidence="approved-golden.json",
        golden_approved=True,
        baseline_bad_pixels={(1, 1)},
        current_bad_pixels={(1, 1)},
        effective_roi=roi("effective", RoiType.EFFECTIVE_INSPECTION_AREA),
        golden_defect_rois=[
            roi("golden-defect", RoiType.GOLDEN_DEFECT, 6, 6, 4, 4)
        ],
        bad_pixel_evidence_sources=["bad-pixel-map.json"],
        bad_pixel_method_version="emva-defect-pixel-v1",
    )


def by_id(report, metric_id: str):
    return next(item for item in report.measurements if item.metric_id == metric_id)


def test_complete_g3_design_evaluates_all_six_metrics():
    report = G3Measurer().measure(complete_inputs())

    assert len(report.measurements) == 6
    assert all(item.severity != Severity.NOT_EVALUATED for item in report.measurements)
    dsnu = by_id(report, "g3.dsnu_pct_fs")
    prnu = by_id(report, "g3.prnu_pct")
    fpn = by_id(report, "g3.vertical_fpn_pct_fs")
    assert dsnu.metadata["frame_count"] == 100
    assert prnu.metadata["temporal_variance_contribution"] > 0
    assert prnu.metadata["corrected_spatial_variance"] <= prnu.metadata["spatial_variance"]
    assert fpn.metadata["frame_count"] == 100
    assert fpn.metadata["calculation"].startswith("std(column_means")
    assert by_id(report, "g3.new_bad_hot_pixels").severity == Severity.S3


def test_dsnu_prnu_need_30_and_fpn_bad_pixels_need_100_frames():
    inputs = complete_inputs()
    inputs.dark_series = series("dark", 29)
    inputs.uniform_series = series("uniform", 99)
    report = G3Measurer().measure(inputs)

    assert by_id(report, "g3.dsnu_pct_fs").severity == Severity.NOT_EVALUATED
    assert by_id(report, "g3.prnu_pct").severity == Severity.NOT_EVALUATED
    assert by_id(report, "g3.vertical_fpn_pct_fs").severity == Severity.NOT_EVALUATED
    assert by_id(report, "g3.new_bad_hot_pixels").severity == Severity.NOT_EVALUATED


def test_bad_pixel_location_and_fixed_mask_drive_categorical_grade():
    outside = complete_inputs()
    outside.current_bad_pixels.add((20, 20))
    # Expand sensor frame/ROI contract for a point outside effective ROI.
    outside.uniform_series = SensorFrameSeries(
        frames=np.pad(outside.uniform_series.frames, ((0, 0), (0, 8), (0, 8))),
        condition="uniform",
        full_scale=4095,
        evidence_sources=outside.uniform_series.evidence_sources,
        method_version="emva-style-v1",
    )
    outside.effective_roi = roi(
        "effective", RoiType.EFFECTIVE_INSPECTION_AREA, width=16, height=16
    )
    result = by_id(G3Measurer().measure(outside), "g3.new_bad_hot_pixels")
    assert result.severity == Severity.S2

    masked = complete_inputs()
    masked.current_bad_pixels.add((3, 3))
    masked.fixed_mask_pixels.add((3, 3))
    result = by_id(G3Measurer().measure(masked), "g3.new_bad_hot_pixels")
    assert result.severity == Severity.S1
    assert result.metadata["fixed_mask_coordinates"] == [[3, 3]]

    golden = complete_inputs()
    golden.current_bad_pixels.add((7, 7))
    golden.fixed_mask_pixels.add((7, 7))
    result = by_id(G3Measurer().measure(golden), "g3.new_bad_hot_pixels")
    assert result.severity == Severity.S0
    assert result.metadata["inside_golden_coordinates"] == [[7, 7]]


def test_unmasked_bad_pixel_inside_effective_area_is_not_guessed():
    inputs = complete_inputs()
    inputs.current_bad_pixels.add((3, 3))

    result = by_id(G3Measurer().measure(inputs), "g3.new_bad_hot_pixels")

    assert result.severity == Severity.NOT_EVALUATED
    assert "固定遮罩" in result.missing_reason


def test_golden_std_requires_written_approval_and_evidence():
    inputs = complete_inputs()
    inputs.golden_approved = False

    result = by_id(
        G3Measurer().measure(inputs),
        "g3.spatial_std_increase_vs_golden_pct",
    )

    assert result.severity == Severity.NOT_EVALUATED
    assert "書面核准" in result.missing_reason
