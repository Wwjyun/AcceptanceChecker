# -*- coding: utf-8 -*-
"""第 11.1 節追溯性分級與輸出欄位測試。"""

from __future__ import annotations

import csv

from acceptance_checker import (
    AcceptanceDatasetManifest,
    AcceptanceManifest,
    AcceptanceSession,
    ImageEvidence,
    ImageLevel,
    Metrics,
    OpticalMode,
    PreconditionLock,
    Severity,
    TraceabilityValidator,
)
from acceptance_checker.reporting import CsvExporter, HistoryLogger


def lock() -> PreconditionLock:
    return PreconditionLock(
        camera={
            "model": "Cam",
            "serial": "CAM-1",
            "bit_depth": 12,
            "gain": 2,
            "exposure_us": 100,
            "line_rate_hz": 20000,
            "binning": "1x1",
            "sensor_roi": "full",
            "internal_calibration": "off",
            "auto_features": "off",
        },
        optics={
            "lens_model": "Lens",
            "aperture": "f/8",
            "working_distance_mm": 100,
            "filter": "none",
            "polarizer": "none",
            "magnification": 1,
            "micrometers_per_pixel": 10,
            "focus_position": "fixed",
        },
        lighting={
            "model": "Light",
            "drive_mode": "current",
            "drive_value": "1A",
            "measured_illuminance": "1000lx",
            "angle_deg": 30,
            "distance_mm": 50,
            "polarization": "none",
            "aging_hours": 10,
        },
        mechanics={
            "scan_speed": "200mm/s",
            "encoder_resolution": "1um",
            "trigger_mode": "encoder",
            "vibration_state": "normal",
            "fixture_state": "locked",
        },
        environment={
            "ambient_light_shielded": True,
            "temperature_c": 25,
            "relative_humidity_pct": 50,
            "warmup_minutes": 30,
        },
        sample={
            "sample_id": "S-1",
            "batch_id": "B-1",
            "orientation": "forward",
            "surface_cleanliness": "clean",
            "golden_approved": True,
        },
        computation={
            "roi_version": "1",
            "formula_version": "1",
            "script_version": "1",
        },
        data={
            "raw_format": "tiff",
            "timestamp_source": "ptp",
            "parameter_record_source": "sidecar",
        },
    )


def metadata(sequence: str = "1", timestamp: str = "2026-07-23T12:00:00.123+08:00"):
    return {
        "timestamp": timestamp,
        "camera_id": "CAM-1",
        "scan_batch_id": "BATCH-1",
        "image_sequence_id": sequence,
        "exposure_us_actual": 100,
        "gain_actual": 2,
        "line_rate_hz_actual": 20000,
        "light_setting_actual": "1A",
        "sample_id": "S-1",
        "sample_orientation": "forward",
        "scan_speed_actual": "200mm/s",
        "encoder_start_count": 1000,
        "image_level": "L1",
        "calibration_version": "cal-1",
    }


def image(path: str, sequence: str = "1", timestamp: str = "2026-07-23T12:00:00.123+08:00"):
    return ImageEvidence(
        relative_path=path,
        sha256="a" * 64,
        size_bytes=100,
        mtime_ns=1,
        image_level=ImageLevel.L1,
        calibration_version="cal-1",
        sidecar_relative_path=path + ".json",
        metadata=metadata(sequence, timestamp),
    )


def manifest(images=None) -> AcceptanceDatasetManifest:
    return AcceptanceDatasetManifest(
        machine_id="AOI-1",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        precondition_lock=lock(),
        images=list(images or [image("a.tif")]),
        session_id="session-1",
        spec_version="v4-draft",
        created_at="2026-07-23T00:00:00+00:00",
    )


def test_complete_required_fields_are_s3_even_when_optional_fields_are_missing():
    report = TraceabilityValidator().validate(manifest())

    assert report.severity == Severity.S3
    assert report.warnings
    assert report.missing_required == {}
    assert report.measurement.metadata["session_id"] == "session-1"
    assert len(report.measurement.metadata["manifest_hash"]) == 64


def test_missing_or_inconsistent_required_field_is_s1():
    missing_image = image("a.tif")
    del missing_image.metadata["encoder_start_count"]
    mismatch_image = image("b.tif", "2", "2026-07-23T12:00:01.123+08:00")
    mismatch_image.metadata["gain_actual"] = 3

    report = TraceabilityValidator().validate(manifest([missing_image, mismatch_image]))

    assert report.severity == Severity.S1
    assert "encoder_start_count" in report.missing_required["a.tif"]
    assert any("gain_actual" in item for item in report.inconsistent_required["b.tif"])


def test_camera_pairing_or_timestamp_sequence_collision_is_s0():
    wrong_camera = image("a.tif")
    wrong_camera.metadata["camera_id"] = "CAM-X"
    collision = image("b.tif")
    collision.metadata["camera_id"] = "CAM-X"

    report = TraceabilityValidator().validate(manifest([wrong_camera, collision]))

    assert report.severity == Severity.S0
    assert any("camera_id" in item for item in report.s0_mismatches)
    assert any("image_sequence_id" in item for item in report.s0_mismatches)
    assert any("timestamp/camera ID" in item for item in report.s0_mismatches)


def test_declared_sidecar_source_mismatch_is_s0():
    item = image("a.tif")
    item.metadata["source_relative_path"] = "other.tif"

    report = TraceabilityValidator().validate(manifest([item]))

    assert report.severity == Severity.S0
    assert any("無法配對" in message for message in report.s0_mismatches)


def test_csv_history_and_session_json_keep_trace_keys(tmp_path):
    metrics = Metrics(
        file_name="a.tif",
        session_id="session-1",
        spec_version="v4-draft",
        manifest_hash="f" * 64,
    )
    csv_path = tmp_path / "report.csv"
    history_path = tmp_path / "history.csv"
    CsvExporter().export(metrics, str(csv_path))
    HistoryLogger().append(metrics, str(history_path))

    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        csv_row = next(csv.DictReader(stream))
    with history_path.open(encoding="utf-8-sig", newline="") as stream:
        history_row = next(csv.DictReader(stream))
    for row in (csv_row, history_row):
        assert row["session_id"] == "session-1"
        assert row["spec_version"] == "v4-draft"
        assert row["manifest_hash"] == "f" * 64

    session = AcceptanceSession(
        manifest=AcceptanceManifest(
            machine_id="AOI-1",
            optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
            session_id="session-1",
            spec_version="v4-draft",
            manifest_hash="f" * 64,
        )
    )
    restored = AcceptanceSession.from_json(session.to_json())
    assert restored.manifest.session_id == "session-1"
    assert restored.manifest.spec_version == "v4-draft"
    assert restored.manifest.manifest_hash == "f" * 64
