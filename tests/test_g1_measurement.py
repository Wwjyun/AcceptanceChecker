# -*- coding: utf-8 -*-
"""v4 G1 三模式量測、缺證與 S0 特例測試。"""

from __future__ import annotations

import numpy as np
import pytest

from acceptance_checker import (
    AcceptanceManifest,
    AcceptanceSession,
    DefectPolarity,
    G1MeasurementInputs,
    G1Measurer,
    ImageLevel,
    MetricGroup,
    OpticalMode,
    RawImage,
    RoiCollection,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
    Severity,
)


def roi(
    roi_id: str,
    roi_type: RoiType,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    metadata=None,
) -> RoiDefinition:
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
        metadata=dict(metadata or {}),
    )


def base_rois(*, include_defect: bool = False) -> RoiCollection:
    result = [
        roi("background", RoiType.DEFECT_FREE_BACKGROUND, 0, 0, 32, 8),
        roi("effective", RoiType.EFFECTIVE_INSPECTION_AREA, 0, 8, 32, 8),
        roi(
            "shadow",
            RoiType.SHADOW,
            0,
            16,
            4,
            4,
            metadata={"background_roi_id": "shadow-ring"},
        ),
        roi("shadow-ring", RoiType.LOCAL_BACKGROUND_RING, 4, 16, 4, 4),
    ]
    if include_defect:
        result.append(
            roi(
                "golden-1",
                RoiType.GOLDEN_DEFECT,
                12,
                20,
                4,
                4,
                metadata={"background_roi_id": "shadow-ring"},
            )
        )
    return RoiCollection(result)


def raw_with_regions() -> RawImage:
    image = np.full((32, 40), 100, dtype=np.uint8)
    image[0:8, 0:32] = 128
    image[8:16, 0:32] = 100
    image[16:20, 0:4] = 80
    image[16:20, 4:8] = 100
    return RawImage.from_array(image)


def paired_raw(value: int) -> RawImage:
    return RawImage.from_array(np.full((32, 40), value, dtype=np.uint8))


def inputs_for(
    mode: OpticalMode,
    *,
    raw: RawImage | None = None,
    rois: RoiCollection | None = None,
    paired: bool = True,
    image_level: ImageLevel = ImageLevel.L1,
    polarity: DefectPolarity = DefectPolarity.UNSPECIFIED,
) -> G1MeasurementInputs:
    kwargs = {}
    if paired:
        kwargs = {
            "reference_raw": paired_raw(128),
            "blocked_raw": paired_raw(10),
            "dark_raw": paired_raw(0),
            "reference_source": "reference.tif",
            "blocked_source": "blocked.tif",
            "dark_source": "dark.tif",
        }
    return G1MeasurementInputs(
        mode=mode,
        raw=raw or raw_with_regions(),
        rois=rois or base_rois(),
        evidence_source="primary.tif",
        image_level=image_level,
        expected_defect_polarity=polarity,
        **kwargs,
    )


def by_id(report, metric_id: str):
    return next(item for item in report.measurements if item.metric_id == metric_id)


def test_diffuse_mode_computes_all_ten_metrics_from_raw_scale():
    report = G1Measurer().measure(inputs_for(OpticalMode.DIFFUSE_BRIGHT_FIELD))

    assert len(report.measurements) == 10
    mean = by_id(report, "g1.diffuse.background_mean_pct_fs")
    cv = by_id(report, "g1.diffuse.background_cv")
    std = by_id(report, "g1.diffuse.background_spatial_std")
    zones = by_id(report, "g1.diffuse.uniformity_u")
    shadow = by_id(report, "g1.diffuse.local_shadow_depth_pct")
    stray = by_id(report, "g1.diffuse.stray_light_pct")

    assert mean.value == pytest.approx(128 / 255 * 100)
    assert mean.severity == Severity.S3
    assert cv.value == 0
    assert zones.value == pytest.approx(1.0)
    assert len(zones.metadata["zone_means_pct_fs"]) == 16
    assert shadow.value == pytest.approx(20.0)
    assert stray.value == pytest.approx(10 / 128 * 100)
    assert std.value == 0
    assert std.severity == Severity.NOT_EVALUATED
    assert std.metadata["non_graded"] is True

    session = AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="AOI-1",
            optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        ),
        measurements=report.measurements,
    )
    assert session.group_status(MetricGroup.G1) != Severity.NOT_EVALUATED


def test_missing_paired_stray_light_evidence_never_claims_pass():
    report = G1Measurer().measure(
        inputs_for(OpticalMode.DIFFUSE_BRIGHT_FIELD, paired=False)
    )

    stray = by_id(report, "g1.diffuse.stray_light_pct")
    assert stray.severity == Severity.NOT_EVALUATED
    assert stray.value is None
    assert "reference" in stray.missing_reason
    assert "blocked" in stray.missing_reason
    assert "dark" in stray.missing_reason


def test_specular_hotspot_uses_30pct_fs_8_connectivity_and_50px_minimum():
    image = np.full((48, 48), 100, dtype=np.uint8)
    image[8:40, 8:40] = 100
    image[16:26, 16:26] = 255
    rois = RoiCollection(
        [
            roi("background", RoiType.DEFECT_FREE_BACKGROUND, 8, 8, 32, 8),
            roi("effective", RoiType.EFFECTIVE_INSPECTION_AREA, 8, 8, 32, 32),
            roi(
                "shadow",
                RoiType.SHADOW,
                0,
                0,
                4,
                4,
                metadata={"background_roi_id": "ring"},
            ),
            roi("ring", RoiType.LOCAL_BACKGROUND_RING, 4, 0, 4, 4),
        ]
    )
    report = G1Measurer().measure(
        inputs_for(
            OpticalMode.SPECULAR_BRIGHT_FIELD,
            raw=RawImage.from_array(image),
            rois=rois,
        )
    )

    hotspot = by_id(report, "g1.specular.hotspot_area_pct")
    assert hotspot.value == pytest.approx(100 / (32 * 32) * 100)
    assert hotspot.severity == Severity.S0
    assert hotspot.metadata["connectivity"] == 8
    assert hotspot.metadata["minimum_area_px"] == 50
    assert hotspot.metadata["hotspot_components"][0]["ring_pad_px"] == 20


def test_dark_edge_contiguous_low_clip_forces_s0_priority_event():
    image = np.full((40, 40), 20, dtype=np.uint8)
    image[10:14, 10:14] = 100
    image[5:10, 5:19] = 0
    rois = RoiCollection(
        [
            roi("background", RoiType.DEFECT_FREE_BACKGROUND, 20, 0, 16, 8),
            roi("effective", RoiType.EFFECTIVE_INSPECTION_AREA, 20, 8, 16, 8),
            roi("golden", RoiType.GOLDEN_DEFECT, 10, 10, 4, 4),
        ]
    )
    report = G1Measurer().measure(
        inputs_for(
            OpticalMode.SCATTERING_DARK_FIELD,
            raw=RawImage.from_array(image),
            rois=rois,
        )
    )

    edge = by_id(report, "g1.dark.defect_edge_low_clip_pct")
    assert edge.severity == Severity.S0
    assert edge.metadata["contour_interruption"] is True
    assert edge.metadata["ring_pad_px"] == 5
    assert len(report.priority_events) == 1
    assert report.priority_events[0].event_type.value == "defect_signal_obscured"


def test_dark_background_undefined_two_to_three_percent_is_not_evaluated():
    image = np.full((32, 40), 6, dtype=np.uint8)
    rois = RoiCollection(
        [
            roi("background", RoiType.DEFECT_FREE_BACKGROUND, 0, 0, 16, 8),
            roi("effective", RoiType.EFFECTIVE_INSPECTION_AREA, 0, 8, 16, 8),
            roi("golden", RoiType.GOLDEN_DEFECT, 20, 20, 4, 4),
        ]
    )
    report = G1Measurer().measure(
        inputs_for(
            OpticalMode.SCATTERING_DARK_FIELD,
            raw=RawImage.from_array(image),
            rois=rois,
        )
    )

    mean = by_id(report, "g1.dark.background_mean_pct_fs")
    assert 2 < mean.value < 3
    assert mean.severity == Severity.NOT_EVALUATED
    assert "未定義" in mean.missing_reason


def test_mode_and_polarity_plausibility_are_warnings_not_reclassification():
    image = np.full((32, 40), 100, dtype=np.uint8)
    image[0:8, 0:32] = 80
    image[20:24, 12:16] = 50
    rois = base_rois(include_defect=True)
    report = G1Measurer().measure(
        inputs_for(
            OpticalMode.SCATTERING_DARK_FIELD,
            raw=RawImage.from_array(image),
            rois=rois,
            polarity=DefectPolarity.BRIGHT,
        )
    )

    assert any("高於 25%FS" in warning for warning in report.warnings)
    assert any("未呈預期亮極性" in warning for warning in report.warnings)


def test_l2_input_makes_every_g1_metric_not_evaluated():
    report = G1Measurer().measure(
        inputs_for(
            OpticalMode.SPECULAR_BRIGHT_FIELD,
            image_level=ImageLevel.L2,
        )
    )

    assert len(report.measurements) == 9
    assert {item.severity for item in report.measurements} == {Severity.NOT_EVALUATED}
    assert all("L1" in item.missing_reason for item in report.measurements)
