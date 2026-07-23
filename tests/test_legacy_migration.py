import json

import numpy as np
import pytest

from acceptance_checker import (
    AcceptancePipeline,
    Metrics,
    OpticalMode,
    Severity,
    Thresholds,
    migrate_legacy_csv,
    migrate_legacy_threshold_profile,
)
from acceptance_checker.cli.batch import main
from acceptance_checker.core.image import imwrite_unicode
from acceptance_checker.reporting import CsvExporter, HistoryLogger


def legacy_metrics() -> Metrics:
    return Metrics(
        file_name="legacy.png",
        file_path="archive/legacy.png",
        width_px=640,
        height_px=480,
        dtype="uint8",
        bit_depth=8,
        full_scale=255,
        norm_method="uint8-copy",
        mean_gray=120.0,
        uniformity_ratio=0.8,
        signal_to_noise_ratio=18.0,
        auto_defect_cnr_est=3.2,
        quality_score=72.0,
        risk_level="量產觀察項",
        overall_status="WARNING",
        review_note="legacy review",
    )


def test_legacy_threshold_profile_is_preserved_without_v4_mapping(tmp_path):
    source = tmp_path / "thresholds.json"
    output = tmp_path / "migrated.json"
    Thresholds(mean_gray_fail=22).save_json(str(source))

    bundle = migrate_legacy_threshold_profile(str(source))
    bundle.save_json(str(output))
    data = json.loads(output.read_text(encoding="utf-8"))

    assert data["source_type"] == "legacy_threshold_profile"
    assert data["engineering_reference_only"] is True
    assert data["formal_v4_grade_allowed"] is False
    assert data["records"][0]["thresholds"]["mean_gray_fail"] == 22
    assert data["records"][0]["v4_specification_mapping"] is None


@pytest.mark.parametrize("kind", ["metrics", "history"])
def test_legacy_csv_and_history_convert_to_not_evaluated_sessions(tmp_path, kind):
    source = tmp_path / f"{kind}.csv"
    metrics = legacy_metrics()
    if kind == "metrics":
        CsvExporter().export(metrics, str(source))
        expected_type = "legacy_metrics_csv"
    else:
        HistoryLogger().append(metrics, str(source))
        expected_type = "legacy_history_log"

    bundle = migrate_legacy_csv(
        str(source),
        machine_id="AOI-MIGRATED",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
    )
    session = bundle.records[0]

    assert bundle.source_type == expected_type
    assert session["overall_result"] == "insufficient_evidence"
    assert session["manifest"]["metadata"]["migration"][
        "engineering_reference_only"
    ]
    assert session["manifest"]["metadata"]["migration"][
        "formal_v4_grade_allowed"
    ] is False
    assert all(
        item["severity"] == Severity.NOT_EVALUATED.value
        for item in session["measurements"]
    )
    assert all(item["image_level"] == "L2" for item in session["measurements"])
    assert all(item["missing_reason"] for item in session["measurements"])


def test_migration_cli_requires_declared_machine_and_mode(tmp_path):
    source = tmp_path / "legacy.csv"
    output = tmp_path / "migration.json"
    CsvExporter().export(legacy_metrics(), str(source))

    assert (
        main(
            [
                "migrate-legacy",
                "csv",
                str(source),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "migrate-legacy",
                "csv",
                str(source),
                "--output",
                str(output),
                "--machine-id",
                "AOI-1",
                "--mode",
                "diffuse_bright_field",
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))[
        "formal_v4_grade_allowed"
    ] is False


def test_legacy_pipeline_warns_for_one_compatibility_cycle(tmp_path):
    image_path = tmp_path / "legacy.png"
    assert imwrite_unicode(
        str(image_path),
        np.full((64, 64), 128, dtype=np.uint8),
    )

    with pytest.warns(DeprecationWarning, match="legacy quick engineering check"):
        result = AcceptancePipeline().run(str(image_path))

    assert result.metrics.file_name == "legacy.png"
