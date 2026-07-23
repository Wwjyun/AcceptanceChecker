# -*- coding: utf-8 -*-
"""G2 slanted-edge、缺陷寬度、尺度與 encoder 測試。"""

from __future__ import annotations

import cv2
import numpy as np

from acceptance_checker import (
    G2MeasurementInputs,
    G2Measurer,
    ImageLevel,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
    ScaleEvidence,
    Severity,
    SlantedEdgeEvidence,
)


def roi(roi_id: str, width: int = 96, height: int = 96) -> RoiDefinition:
    return RoiDefinition(
        roi_id=roi_id,
        roi_type=RoiType.EFFECTIVE_INSPECTION_AREA,
        x=0,
        y=0,
        width=width,
        height=height,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="tester",
        version="1",
        image_id="*",
    )


def edge_image(*, slope: float = 0.1, blur_sigma: float = 0.65) -> np.ndarray:
    yy, xx = np.indices((96, 96), dtype=np.float64)
    signed = xx - (43 + slope * yy)
    image = np.where(signed >= 0, 220.0, 20.0)
    return cv2.GaussianBlur(image, (0, 0), blur_sigma).astype(np.uint8)


def edge(direction: str, orientation: str = "vertical", slope: float = 0.1):
    image = edge_image(slope=slope)
    if orientation == "horizontal":
        image = image.T
    return SlantedEdgeEvidence(
        image=image,
        roi=roi(f"{direction}-edge"),
        measured_direction=direction,
        edge_orientation=orientation,
        full_scale=255,
        evidence_source=f"{direction}-edge.tif",
        method_version="sfr-4x-v1",
        target_id="ISO12233-edge-1",
    )


def scales():
    return [
        ScaleEvidence(region, measured, 10.0, f"{region}.csv", "scale-v1")
        for region, measured in (
            ("left", 10.05),
            ("center", 10.0),
            ("right", 9.95),
            ("stitch", 10.08),
        )
    ]


def complete_inputs() -> G2MeasurementInputs:
    defect_image = np.full((40, 40), 20, dtype=np.uint8)
    defect_mask = np.zeros((40, 40), dtype=np.uint8)
    defect_mask[10:16, 8:30] = 1
    defect_image[defect_mask > 0] = 220
    positions = 100 + np.sin(np.linspace(0, 8 * np.pi, 100)) * 0.2
    return G2MeasurementInputs(
        slanted_edges=[edge("scan"), edge("sensor", "horizontal")],
        defect_image=defect_image,
        defect_mask=defect_mask,
        defect_full_scale=255,
        defect_evidence_source="minimum-defect.tif",
        defect_method_version="mask-width-v1",
        scale_scan=10.0,
        scale_sensor=10.1,
        scale_evidence=scales(),
        encoder_positions_px=positions.tolist(),
        encoder_evidence_sources=[f"scan-{index:03}.json" for index in range(100)],
        encoder_method_version="encoder-p95-v1",
        requires_stitch_region=True,
    )


def by_id(report, metric_id: str):
    return next(item for item in report.measurements if item.metric_id == metric_id)


def test_complete_g2_design_evaluates_all_seven_metrics():
    report = G2Measurer().measure(complete_inputs())

    assert len(report.measurements) == 7
    assert all(item.severity != Severity.NOT_EVALUATED for item in report.measurements)
    mtf = by_id(report, "g2.mtf_nyquist_half")
    assert 0 < mtf.value <= 1.1
    assert set(mtf.metadata["directions"]) == {"scan", "sensor"}
    assert mtf.metadata["method_version"] == "sfr-4x-v1"
    width = by_id(report, "g2.minimum_defect_width_px")
    assert width.value >= 4
    assert width.metadata["contour_clear"] is True
    fov = by_id(report, "g2.fov_scale_error_pct")
    assert fov.metadata["per_region_error_pct"]["stitch"] > 0
    encoder = by_id(report, "g2.encoder_sync_position_error_p95_px")
    assert encoder.sample_count == 100
    assert encoder.value < 0.5


def test_encoder_under_100_and_missing_stitch_are_not_evaluated():
    inputs = complete_inputs()
    inputs.encoder_positions_px = inputs.encoder_positions_px[:99]
    inputs.encoder_evidence_sources = inputs.encoder_evidence_sources[:99]
    inputs.scale_evidence = inputs.scale_evidence[:3]
    report = G2Measurer().measure(inputs)

    encoder = by_id(report, "g2.encoder_sync_position_error_p95_px")
    fov = by_id(report, "g2.fov_scale_error_pct")
    assert encoder.severity == Severity.NOT_EVALUATED
    assert "100 次" in encoder.missing_reason
    assert fov.severity == Severity.NOT_EVALUATED
    assert "stitch" in fov.missing_reason


def test_bad_slanted_edge_angle_blocks_all_edge_derived_metrics():
    inputs = complete_inputs()
    inputs.slanted_edges = [edge("scan", slope=0.01), edge("sensor", slope=0.01)]
    report = G2Measurer().measure(inputs)

    for metric_id in (
        "g2.mtf_nyquist_half",
        "g2.mtf_direction_asymmetry_pct",
        "g2.motion_blur_px",
    ):
        result = by_id(report, metric_id)
        assert result.severity == Severity.NOT_EVALUATED
        assert "slanted-edge" in result.missing_reason


def test_unrecognizable_defect_contour_forces_s0():
    inputs = complete_inputs()
    inputs.defect_image = np.full((40, 40), 100, dtype=np.uint8)
    report = G2Measurer().measure(inputs)

    width = by_id(report, "g2.minimum_defect_width_px")
    assert width.value >= 4
    assert width.metadata["contour_clear"] is False
    assert width.severity == Severity.S0


def test_l2_input_never_claims_formal_g2_results():
    inputs = complete_inputs()
    inputs.image_level = ImageLevel.L2
    report = G2Measurer().measure(inputs)

    assert {item.severity for item in report.measurements} == {Severity.NOT_EVALUATED}
    assert all("L1" in item.missing_reason for item in report.measurements)
