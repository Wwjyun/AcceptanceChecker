# -*- coding: utf-8 -*-
"""Approved Golden catalog, immutable version, and detector import tests."""

from __future__ import annotations

import csv

import pytest

from acceptance_checker import (
    DefectPolarity,
    DetectorDecision,
    DetectorResultSet,
    FullWidthRegion,
    GoldenCatalog,
    GoldenCatalogError,
    GoldenCatalogRepository,
    GoldenDisposition,
    GoldenSample,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
)


def roi(sample_id, roi_id, roi_type, x, y, width, height):
    return RoiDefinition(
        roi_id=roi_id,
        roi_type=roi_type,
        x=x,
        y=y,
        width=width,
        height=height,
        creation_method=RoiCreationMethod.GUI_MANUAL,
        operator="quality",
        version="roi-1",
        image_id=sample_id,
    )


def ng_sample(sample_id="ng-1", defect_type="scratch"):
    return GoldenSample(
        sample_id=sample_id,
        disposition=GoldenDisposition.NG,
        image_source=f"{sample_id}.tif",
        sha256="a" * 64,
        batch_id="batch-1",
        orientation="forward",
        full_width_region=FullWidthRegion.CENTER,
        defect_type=defect_type,
        defect_size_um=20.0,
        defect_size_px=3.0,
        effective_width_px=2.5,
        defect_direction="scan",
        defect_polarity=DefectPolarity.DARK,
        defect_position="x=50,y=40",
        defect_roi=roi(
            sample_id, f"{sample_id}-defect", RoiType.GOLDEN_DEFECT, 50, 40, 3, 4
        ),
        background_ring=roi(
            sample_id,
            f"{sample_id}-ring",
            RoiType.LOCAL_BACKGROUND_RING,
            45,
            35,
            13,
            14,
        ),
    )


def pass_sample(sample_id="pass-1"):
    return GoldenSample(
        sample_id=sample_id,
        disposition=GoldenDisposition.PASS,
        image_source=f"{sample_id}.tif",
        sha256="b" * 64,
        batch_id="batch-1",
        orientation="forward",
        full_width_region=FullWidthRegion.LEFT,
    )


def catalog(version="1.0"):
    return GoldenCatalog(
        catalog_id="line-a",
        version=version,
        approved=True,
        approved_by="quality-lead",
        approved_at="2026-07-23T10:00:00+08:00",
        approval_record_source="approval-42.pdf",
        required_defect_types=["scratch"],
        samples=[ng_sample(), pass_sample()],
    )


def test_catalog_round_trip_preserves_labels_rois_and_approval():
    restored = GoldenCatalog.from_json(catalog().to_json())

    assert restored.reference == "line-a@1.0"
    assert restored.samples[0].defect_roi.roi_type == RoiType.GOLDEN_DEFECT
    assert (
        restored.samples[0].background_ring.roi_type
        == RoiType.LOCAL_BACKGROUND_RING
    )
    assert restored.samples[0].effective_width_px == 2.5
    assert restored.approval_record_source == "approval-42.pdf"


def test_pass_sample_rejects_defect_labels_and_ng_requires_both_rois():
    with pytest.raises(GoldenCatalogError, match="PASS"):
        GoldenSample(
            sample_id="pass",
            disposition=GoldenDisposition.PASS,
            image_source="pass.tif",
            sha256="a" * 64,
            batch_id="b",
            orientation="forward",
            full_width_region=FullWidthRegion.CENTER,
            defect_type="scratch",
        )

    sample = ng_sample()
    with pytest.raises(GoldenCatalogError, match="background ring"):
        GoldenSample(
            **{
                **sample.__dict__,
                "background_ring": None,
            }
        )


def test_repository_never_overwrites_an_existing_golden_version(tmp_path):
    repository = GoldenCatalogRepository(str(tmp_path))
    path = repository.save_new(catalog())

    assert repository.load("line-a", "1.0").reference == "line-a@1.0"
    with pytest.raises(GoldenCatalogError, match="immutable"):
        repository.save_new(catalog())
    assert path.read_text(encoding="utf-8") == catalog().to_json() + "\n"

    newer = GoldenCatalog(
        **{
            **catalog("2.0").__dict__,
            "supersedes_version": "1.0",
        }
    )
    assert repository.save_new(newer).name == "2.0.json"
    assert repository.load("line-a", "1.0").version == "1.0"


def test_detector_csv_import_has_real_detector_provenance_and_version(tmp_path):
    csv_path = tmp_path / "detector.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "sample_id",
                "score",
                "threshold",
                "detected",
                "capture_attempts",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": "ng-1",
                "score": 1.4,
                "threshold": 1.0,
                "detected": "true",
                "capture_attempts": 1,
            }
        )
        writer.writerow(
            {
                "sample_id": "pass-1",
                "score": 0.2,
                "threshold": 1.0,
                "detected": "false",
                "capture_attempts": 1,
            }
        )

    results = DetectorResultSet.load_csv(
        str(csv_path),
        catalog_id="line-a",
        catalog_version="1.0",
        detector_id="production-detector",
        detector_version="5.2.0",
        decision_rule_version="recipe-7",
    )
    results.validate_against(catalog())

    assert results.decisions[0].margin_pct == pytest.approx(40.0)
    assert results.imported_from == str(csv_path)


def test_detector_results_must_cover_exact_catalog_version_and_samples():
    results = DetectorResultSet(
        catalog_id="line-a",
        catalog_version="old",
        detector_id="production",
        detector_version="1",
        decision_rule_version="1",
        imported_from="detector.csv",
        decisions=[
            DetectorDecision("ng-1", 1.0, 0.5, True),
            DetectorDecision("pass-1", 0.0, 0.5, False),
        ],
    )

    with pytest.raises(GoldenCatalogError, match="different Golden"):
        results.validate_against(catalog())
