# -*- coding: utf-8 -*-
"""v4 版本化規格的完整性、traceability 與邊界測試。"""

from __future__ import annotations

import copy
import json
import math
from importlib import resources

import pytest

from acceptance_checker import (
    MetricGroup,
    OpticalMode,
    Severity,
    SpecificationError,
    V4Specification,
    load_default_v4_spec,
    load_v4_spec,
)


def _raw_spec():
    with resources.files("acceptance_checker.specs").joinpath("v4_draft.json").open(
        "r", encoding="utf-8"
    ) as stream:
        return json.load(stream)


def test_default_spec_has_all_63_excel_rows():
    spec = load_default_v4_spec()

    assert len(spec.metrics) == 63
    assert {group: sum(item.group == group for item in spec.metrics) for group in MetricGroup} == {
        MetricGroup.G1: 28,
        MetricGroup.G2: 7,
        MetricGroup.G3: 6,
        MetricGroup.G4: 6,
        MetricGroup.G5: 8,
        MetricGroup.G6: 8,
    }
    assert len(spec.metrics_for_mode(OpticalMode.DIFFUSE_BRIGHT_FIELD)) == 45
    assert len(spec.metrics_for_mode(OpticalMode.SPECULAR_BRIGHT_FIELD)) == 44
    assert len(spec.metrics_for_mode(OpticalMode.SCATTERING_DARK_FIELD)) == 44
    assert spec.status == "draft_unapproved"
    assert spec.effective_date is None
    assert len(spec.source_documents) == 2


def test_every_metric_has_traceability_fields():
    spec = load_default_v4_spec()

    for metric in spec.metrics:
        assert metric.metric_id
        assert metric.name
        assert metric.unit
        assert metric.formula
        assert metric.requirement_profile in spec.requirement_profiles
        assert set(metric.display_bands) == {"S3", "S2", "S1", "S0"}


def test_all_simple_numeric_boundaries_are_deterministic():
    spec = load_default_v4_spec()

    for metric in spec.metrics:
        rule = metric.classification
        kind = rule["kind"]
        if kind == "lower_is_good":
            s3, s2, s1 = (float(rule[key]) for key in ("s3_max", "s2_max", "s1_max"))
            assert metric.classify(s3) == Severity.S3
            assert metric.classify(math.nextafter(s3, math.inf)) == Severity.S2
            assert metric.classify(s2) == Severity.S2
            assert metric.classify(math.nextafter(s2, math.inf)) == Severity.S1
            assert metric.classify(s1) == Severity.S1
            assert metric.classify(math.nextafter(s1, math.inf)) == Severity.S0
        elif kind == "higher_is_good":
            s1, s2, s3 = (float(rule[key]) for key in ("s1_min", "s2_min", "s3_min"))
            assert metric.classify(s3) == Severity.S3
            assert metric.classify(math.nextafter(s3, -math.inf)) == Severity.S2
            assert metric.classify(s2) == Severity.S2
            assert metric.classify(math.nextafter(s2, -math.inf)) == Severity.S1
            assert metric.classify(s1) == Severity.S1
            assert metric.classify(math.nextafter(s1, -math.inf)) == Severity.S0
        elif kind == "target_range":
            s3_low, s3_high = (float(item) for item in rule["s3"])
            s2_low, s2_high = (float(item) for item in rule["s2"])
            s1_low, s1_high = (float(item) for item in rule["s1"])
            assert metric.classify(s3_low) == Severity.S3
            assert metric.classify(s3_high) == Severity.S3
            assert metric.classify(s2_low) == Severity.S2
            assert metric.classify(s2_high) == Severity.S2
            assert metric.classify(s1_low) == Severity.S1
            assert metric.classify(s1_high) == Severity.S1
            assert metric.classify(math.nextafter(s1_low, -math.inf)) == Severity.S0
            assert metric.classify(math.nextafter(s1_high, math.inf)) == Severity.S0
        elif kind == "zero_fatal":
            assert metric.classify(0) == Severity.S3
            assert metric.classify(1) == Severity.S0


def test_dark_field_source_gap_is_explicit_not_evaluated():
    metric = load_default_v4_spec().get_metric("g1.dark.background_mean_pct_fs")

    assert metric.classify(1.99) == Severity.S0
    assert metric.classify(2.0) == Severity.NOT_EVALUATED
    assert metric.classify(2.5) == Severity.NOT_EVALUATED
    assert metric.classify(3.0) == Severity.S3
    assert metric.classify(12.0) == Severity.S3
    assert metric.classify(12.01) == Severity.S2
    assert metric.classify(25.0) == Severity.S1
    assert metric.classify(25.01) == Severity.S0


def test_qualitative_rule_refuses_single_numeric_guess():
    metric = load_default_v4_spec().get_metric("g5.traceability_completeness")

    with pytest.raises(SpecificationError, match="不能只用單一數值"):
        metric.classify(100)


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda data: data.update(schema_version="9.9"), "schema_version"),
        (lambda data: data["metrics"].pop(), "63 項"),
        (
            lambda data: data["metrics"][1].update(id=data["metrics"][0]["id"]),
            "不得重複",
        ),
        (
            lambda data: data["metrics"][0].update(requirement_profile="missing"),
            "不存在",
        ),
    ],
)
def test_incomplete_or_unsupported_specs_are_rejected(mutator, message):
    data = copy.deepcopy(_raw_spec())
    mutator(data)

    with pytest.raises(SpecificationError, match=message):
        V4Specification.from_dict(data)


def test_unicode_external_spec_round_trip(tmp_path):
    path = tmp_path / "影像品質_v4.json"
    path.write_text(json.dumps(_raw_spec(), ensure_ascii=False), encoding="utf-8")

    loaded = load_v4_spec(str(path))

    assert loaded.spec_version == "v4-discussion-2026-07-23"
    assert loaded.get_metric("g6.defect_cnr").group == MetricGroup.G6
