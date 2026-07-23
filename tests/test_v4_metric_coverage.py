# -*- coding: utf-8 -*-
"""Cross-group synthetic coverage for all 63 formal v4 metrics."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from acceptance_checker import (
    G1Measurer,
    G2Measurer,
    G3Measurer,
    G5Measurer,
    G6Measurer,
    ImageLevel,
    OpticalMode,
    RawImage,
    Severity,
    TemporalAcceptanceMeasurer,
    load_default_v4_spec,
)
from tests.test_g1_measurement import (
    base_rois,
    inputs_for,
)
from tests.test_g2_measurement import complete_inputs as g2_inputs
from tests.test_g3_measurement import complete_inputs as g3_inputs
from tests.test_g5_measurement import good_inputs as g5_inputs
from tests.test_g6_measurement import make_inputs as g6_inputs
from tests.test_temporal_analysis import complete_inputs as temporal_inputs


def test_synthetic_scenario_manifest_covers_required_p6_cases():
    path = Path(__file__).parent / "data" / "synthetic_scenarios.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))

    assert fixture["seed"] == 20260723
    assert set(fixture["optical_modes"]) == {mode.value for mode in OpticalMode}
    assert fixture["bit_depths"] == [8, 10, 12, 14, 16]
    assert set(fixture["scenarios"]) == {
        "mode_and_bit_depth_scaling",
        "temporal_noise",
        "gray_drift_30min_and_8h",
        "specular_hotspot",
        "local_shadow",
        "stitch_blind_zone",
        "missing_and_duplicate_line",
        "dropped_frame_and_interruption",
        "golden_stable_miss",
    }


def test_complete_synthetic_design_emits_every_one_of_the_63_spec_metrics():
    reports = [
        G1Measurer().measure(inputs_for(mode)) for mode in OpticalMode
    ]
    reports.extend(
        [
            G2Measurer().measure(g2_inputs()),
            TemporalAcceptanceMeasurer().measure(temporal_inputs()),
            G3Measurer().measure(g3_inputs()),
            G5Measurer().measure(g5_inputs()),
            G6Measurer().measure(g6_inputs()),
        ]
    )
    emitted = {
        item.metric_id
        for report in reports
        for item in report.measurements
    }
    expected = {item.metric_id for item in load_default_v4_spec().metrics}

    assert emitted == expected
    assert len(emitted) == 63


@pytest.mark.parametrize("bit_depth", [8, 10, 12, 14, 16])
@pytest.mark.parametrize("mode", list(OpticalMode))
def test_g1_physical_gray_ratio_is_stable_across_modes_and_bit_depths(
    bit_depth, mode
):
    full_scale = (1 << bit_depth) - 1
    dtype = np.uint8 if bit_depth == 8 else np.uint16
    image = np.full((32, 40), round(full_scale * 0.5), dtype=dtype)
    raw = RawImage.from_array(image, bit_depth=bit_depth)
    report = G1Measurer().measure(
        inputs_for(mode, raw=raw, rois=base_rois(include_defect=True))
    )
    metric_id = {
        OpticalMode.DIFFUSE_BRIGHT_FIELD: "g1.diffuse.background_mean_pct_fs",
        OpticalMode.SPECULAR_BRIGHT_FIELD: "g1.specular.background_mean_pct_fs",
        OpticalMode.SCATTERING_DARK_FIELD: "g1.dark.background_mean_pct_fs",
    }[mode]
    result = next(item for item in report.measurements if item.metric_id == metric_id)

    expected_pct = round(full_scale * 0.5) / full_scale * 100.0
    assert result.value == pytest.approx(expected_pct)
    assert result.metadata["bit_depth"] == bit_depth
    assert result.metadata["full_scale"] == full_scale


def test_every_group_has_an_explicit_missing_evidence_regression_path():
    missing_reports = [
        *[
            G1Measurer().measure(
                inputs_for(mode, image_level=ImageLevel.L2)
            )
            for mode in OpticalMode
        ],
        G2Measurer().measure(_with_image_level(g2_inputs(), ImageLevel.L2)),
        TemporalAcceptanceMeasurer().measure(
            _with_image_level(temporal_inputs(), ImageLevel.L2)
        ),
        G3Measurer().measure(type(g3_inputs())()),
        G5Measurer().measure(type(g5_inputs())()),
    ]
    missing_ids = {
        item.metric_id
        for report in missing_reports
        for item in report.measurements
        if item.severity == Severity.NOT_EVALUATED and item.missing_reason
    }
    expected_non_g6 = {
        item.metric_id
        for item in load_default_v4_spec().metrics
        if item.group.value != "G6"
    }

    assert missing_ids == expected_non_g6
    # G6 evidence is gated one layer earlier: unapproved Golden catalogs are rejected
    # by the GoldenCatalog constructor, while individual missing image/result paths are
    # covered in test_g6_measurement.py.


def _with_image_level(inputs, image_level):
    inputs.image_level = image_level
    return inputs
