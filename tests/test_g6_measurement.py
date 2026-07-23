# -*- coding: utf-8 -*-
"""Approved-Golden formulas, statistics, grading, and S0-event tests."""

from __future__ import annotations

import numpy as np
import pytest

from acceptance_checker import (
    DefectPolarity,
    DetectorDecision,
    DetectorResultSet,
    FullWidthRegion,
    G6MeasurementError,
    G6MeasurementInputs,
    G6Measurer,
    GoldenCatalog,
    GoldenDisposition,
    GoldenSample,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
    S0PriorityEventType,
    Severity,
    clopper_pearson_upper,
)


def roi(sample_id, roi_id, roi_type, x, y, width, height):
    return RoiDefinition(
        roi_id=roi_id,
        roi_type=roi_type,
        x=x,
        y=y,
        width=width,
        height=height,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="quality",
        version="roi-1",
        image_id=sample_id,
    )


def ng_sample(index, *, width=2.5):
    sample_id = f"ng-{index:03d}"
    polarity = DefectPolarity.BRIGHT if index % 2 == 0 else DefectPolarity.DARK
    regions = list(FullWidthRegion)
    return GoldenSample(
        sample_id=sample_id,
        disposition=GoldenDisposition.NG,
        image_source=f"{sample_id}.tif",
        sha256=f"{index + 1:064x}",
        batch_id="ng-batch",
        orientation="forward",
        full_width_region=regions[index % len(regions)],
        defect_type="scratch",
        defect_size_um=20.0,
        defect_size_px=3.0,
        effective_width_px=width,
        defect_direction="scan",
        defect_polarity=polarity,
        defect_position=f"x=8,y=8,index={index}",
        defect_roi=roi(
            sample_id, f"{sample_id}-defect", RoiType.GOLDEN_DEFECT, 8, 8, 2, 2
        ),
        background_ring=roi(
            sample_id,
            f"{sample_id}-ring",
            RoiType.LOCAL_BACKGROUND_RING,
            5,
            5,
            10,
            10,
        ),
    )


def pass_sample(index):
    sample_id = f"pass-{index:03d}"
    return GoldenSample(
        sample_id=sample_id,
        disposition=GoldenDisposition.PASS,
        image_source=f"{sample_id}.tif",
        sha256=f"{1000 + index:064x}",
        batch_id="pass-batch",
        orientation="forward",
        full_width_region=FullWidthRegion.CENTER,
    )


def make_image(sample):
    y, x = np.indices((20, 20))
    image = (99.0 + ((x + y) % 2) * 2.0).astype(np.float64)
    value = 110.0 if sample.defect_polarity == DefectPolarity.BRIGHT else 90.0
    image[8:10, 8:10] = value
    return image


def make_inputs(*, ng_count=30, pass_count=200, narrow_index=None):
    ng_samples = [
        ng_sample(index, width=1.5 if index == narrow_index else 2.5)
        for index in range(ng_count)
    ]
    pass_samples = [pass_sample(index) for index in range(pass_count)]
    catalog = GoldenCatalog(
        catalog_id="line-a",
        version="2.0",
        approved=True,
        approved_by="quality",
        approved_at="2026-07-23T10:00:00+08:00",
        approval_record_source="approval.pdf",
        required_defect_types=["scratch"],
        samples=[*ng_samples, *pass_samples],
    )
    decisions = [
        *[
            DetectorDecision(sample.sample_id, 1.4, 1.0, True)
            for sample in ng_samples
        ],
        *[
            DetectorDecision(sample.sample_id, 0.0, 1.0, False)
            for sample in pass_samples
        ],
    ]
    results = DetectorResultSet(
        catalog_id="line-a",
        catalog_version="2.0",
        detector_id="production-detector",
        detector_version="5.2",
        decision_rule_version="recipe-7",
        imported_from="detector-results.csv",
        decisions=decisions,
    )
    return G6MeasurementInputs(
        catalog=catalog,
        detector_results=results,
        images={sample.sample_id: make_image(sample) for sample in ng_samples},
    )


def by_id(report):
    return {item.metric_id: item for item in report.measurements}


def replace_decision(inputs, sample_id, **changes):
    decisions = []
    for item in inputs.detector_results.decisions:
        if item.sample_id == sample_id:
            decisions.append(
                DetectorDecision(
                    sample_id=item.sample_id,
                    score=changes.get("score", item.score),
                    threshold=changes.get("threshold", item.threshold),
                    detected=changes.get("detected", item.detected),
                    capture_attempts=changes.get(
                        "capture_attempts", item.capture_attempts
                    ),
                )
            )
        else:
            decisions.append(item)
    inputs.detector_results = DetectorResultSet(
        catalog_id=inputs.detector_results.catalog_id,
        catalog_version=inputs.detector_results.catalog_version,
        detector_id=inputs.detector_results.detector_id,
        detector_version=inputs.detector_results.detector_version,
        decision_rule_version=inputs.detector_results.decision_rule_version,
        imported_from=inputs.detector_results.imported_from,
        decisions=decisions,
    )


def test_complete_g6_design_evaluates_all_metrics_and_ratio_provenance():
    report = G6Measurer().measure(make_inputs())
    metrics = by_id(report)

    assert len(metrics) == 8
    assert report.priority_events == []
    assert metrics["g6.defect_cnr"].severity == Severity.S3
    assert set(metrics["g6.defect_cnr"].metadata["worst_by_polarity"]) == {
        "bright",
        "dark",
    }
    assert metrics["g6.defect_delta_gray"].metadata["non_graded"]
    assert metrics["g6.golden_ng_detection"].severity == Severity.S3
    assert metrics["g6.golden_ng_samples_per_type"].value == 30
    assert metrics["g6.defect_type_coverage_pct"].value == 100.0
    assert metrics["g6.golden_pass_false_positive_pct"].value == 0.0
    assert metrics["g6.golden_pass_false_positive_pct"].severity == Severity.S3
    assert metrics["g6.false_positive_upper_95_pct"].value == pytest.approx(
        (1 - 0.05 ** (1 / 200)) * 100
    )
    assert metrics["g6.full_width_detection_consistency_pct"].value == 0.0
    for metric_id in (
        "g6.golden_ng_detection",
        "g6.defect_type_coverage_pct",
        "g6.golden_pass_false_positive_pct",
        "g6.false_positive_upper_95_pct",
    ):
        ratio = metrics[metric_id].metadata["ratio"]
        assert ratio["numerator"] >= 0
        assert ratio["denominator"] > 0
        assert len(ratio["confidence_interval_95"]) == 2
        assert metrics[metric_id].metadata["golden_catalog"] == "line-a@2.0"


def test_pass_sample_count_below_200_cannot_receive_s3_or_s2():
    metric = by_id(G6Measurer().measure(make_inputs(pass_count=20)))[
        "g6.golden_pass_false_positive_pct"
    ]

    assert metric.value == 0.0
    assert metric.severity == Severity.S1
    assert metric.metadata["sample_size_restricted_grade"]


def test_retry_pass_is_s1_and_stable_miss_is_s0_priority_event():
    retry_inputs = make_inputs()
    replace_decision(retry_inputs, "ng-000", capture_attempts=2)
    retry_report = G6Measurer().measure(retry_inputs)
    assert by_id(retry_report)["g6.golden_ng_detection"].severity == Severity.S1

    miss_inputs = make_inputs()
    replace_decision(miss_inputs, "ng-001", detected=False, score=0.2)
    miss_report = G6Measurer().measure(miss_inputs)
    assert by_id(miss_report)["g6.golden_ng_detection"].severity == Severity.S0
    assert (
        by_id(miss_report)["g6.full_width_detection_consistency_pct"].severity
        == Severity.S0
    )
    assert any(
        event.event_type == S0PriorityEventType.GOLDEN_NG_STABLE_MISS
        for event in miss_report.priority_events
    )


def test_narrow_or_unrecognizable_minimum_defect_creates_s0_priority_event():
    narrow = G6Measurer().measure(make_inputs(narrow_index=0))
    assert any(
        event.event_type == S0PriorityEventType.MINIMUM_DEFECT_UNRECOGNIZABLE
        for event in narrow.priority_events
    )

    inputs = make_inputs()
    inputs.minimum_defect_recognizable = False
    inputs.recognizability_evidence_source = "three-party-review.pdf"
    report = G6Measurer().measure(inputs)
    assert any(
        event.evidence_sources == ["three-party-review.pdf"]
        for event in report.priority_events
    )


def test_formal_cnr_requires_images_and_both_polarities():
    missing = make_inputs()
    missing.images.pop("ng-000")
    metrics = by_id(G6Measurer().measure(missing))
    assert metrics["g6.defect_cnr"].severity == Severity.NOT_EVALUATED
    assert metrics["g6.defect_delta_gray"].severity == Severity.NOT_EVALUATED

    one_polarity = make_inputs()
    one_polarity.catalog = GoldenCatalog(
        **{
            **one_polarity.catalog.__dict__,
            "samples": [
                sample
                for sample in one_polarity.catalog.samples
                if sample.disposition == GoldenDisposition.PASS
                or sample.defect_polarity == DefectPolarity.BRIGHT
            ],
        }
    )
    one_polarity.detector_results = DetectorResultSet(
        **{
            **one_polarity.detector_results.__dict__,
            "decisions": [
                item
                for item in one_polarity.detector_results.decisions
                if item.sample_id
                in {sample.sample_id for sample in one_polarity.catalog.samples}
            ],
        }
    )
    metric = by_id(G6Measurer().measure(one_polarity))["g6.defect_cnr"]
    assert metric.severity == Severity.NOT_EVALUATED
    assert "both bright and dark" in metric.missing_reason


def test_exact_clopper_pearson_boundaries_and_input_validation():
    assert clopper_pearson_upper(0, 200) == pytest.approx(
        1 - 0.05 ** (1 / 200)
    )
    assert clopper_pearson_upper(200, 200) == 1.0
    with pytest.raises(G6MeasurementError):
        clopper_pearson_upper(2, 1)
