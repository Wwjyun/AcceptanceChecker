# -*- coding: utf-8 -*-
"""v4 dataset manifest、前提鎖定、sidecar 與 hash 測試。"""

from __future__ import annotations

import csv
import json

import pytest

from acceptance_checker import (
    AcceptanceDatasetManifest,
    AcceptanceManifest,
    ImageEvidence,
    ImageLevel,
    ManifestError,
    OpticalMode,
    PreconditionLock,
    SessionInput,
    build_dataset_manifest,
    build_image_evidence,
    load_image_sidecar,
    partition_sessions,
    sha256_file,
)


def valid_lock(*, warmup: float = 30, gain: float = 1.0) -> PreconditionLock:
    return PreconditionLock(
        camera={
            "model": "LineCam-X",
            "serial": "CAM-001",
            "bit_depth": 12,
            "gain": gain,
            "exposure_us": 100,
            "line_rate_hz": 20000,
            "binning": "1x1",
            "sensor_roi": "0,0,4096,1",
            "internal_calibration": "off",
            "auto_features": "off",
        },
        optics={
            "lens_model": "Lens-01",
            "aperture": "f/8",
            "working_distance_mm": 120,
            "filter": "none",
            "polarizer": "cross",
            "magnification": 0.5,
            "micrometers_per_pixel": 10,
            "focus_position": "12.3mm",
        },
        lighting={
            "model": "Light-01",
            "drive_mode": "constant_current",
            "drive_value": "1.2A",
            "measured_illuminance": "15000lx",
            "angle_deg": 30,
            "distance_mm": 80,
            "polarization": "horizontal",
            "aging_hours": 120,
        },
        mechanics={
            "scan_speed": "200mm/s",
            "encoder_resolution": "1um",
            "trigger_mode": "encoder",
            "vibration_state": "production",
            "fixture_state": "locked",
        },
        environment={
            "ambient_light_shielded": True,
            "temperature_c": 24.5,
            "relative_humidity_pct": 55,
            "warmup_minutes": warmup,
        },
        sample={
            "sample_id": "GS-001",
            "batch_id": "B-001",
            "orientation": "arrow-forward",
            "surface_cleanliness": "cleaned",
            "golden_approved": True,
        },
        computation={
            "roi_version": "roi-v1",
            "formula_version": "v4-formula-1",
            "script_version": "0.1.0",
        },
        data={
            "raw_format": "tiff-uint16",
            "timestamp_source": "camera_ptp",
            "parameter_record_source": "acquisition_log",
        },
    )


def evidence(path: str, seed: str = "0") -> ImageEvidence:
    return ImageEvidence(
        relative_path=path,
        sha256=seed * 64,
        size_bytes=10,
        mtime_ns=20,
        image_level=ImageLevel.L1,
        calibration_version="cal-v1",
        sidecar_relative_path=path + ".json",
    )


def test_precondition_lock_validates_all_categories_and_warmup():
    lock = valid_lock(warmup=29.5)

    assert lock.measurements_valid is False
    assert "低於" in lock.invalid_reason
    assert len(lock.fingerprint()) == 64

    data = lock.to_dict()
    del data["camera"]["serial"]
    with pytest.raises(ManifestError, match="camera.*serial"):
        PreconditionLock.from_dict(data)


def test_any_lock_change_starts_a_new_session():
    first = valid_lock(gain=1.0)
    same = PreconditionLock.from_dict(first.to_dict())
    changed = valid_lock(gain=1.1)

    partitions = partition_sessions(
        [
            SessionInput(first, evidence("a.tif", "a")),
            SessionInput(same, evidence("b.tif", "b")),
            SessionInput(changed, evidence("c.tif", "c")),
        ]
    )

    assert len(partitions) == 2
    assert [len(item.images) for item in partitions] == [2, 1]
    assert partitions[1].changed_fields_from_previous == ["camera.gain"]
    assert partitions[0].session_id != partitions[1].session_id


def test_json_and_csv_sidecars_follow_fixed_filename_rules(tmp_path):
    image = tmp_path / "frame.tif"
    image.write_bytes(b"raw-image")
    json_sidecar = tmp_path / "frame.tif.json"
    json_sidecar.write_text(
        json.dumps({"image_level": "L1", "calibration_version": "cal-v1"}),
        encoding="utf-8",
    )

    metadata, source = load_image_sidecar(str(image))
    assert metadata["image_level"] == "L1"
    assert source == str(json_sidecar)

    json_sidecar.unlink()
    csv_sidecar = tmp_path / "frame.csv"
    with csv_sidecar.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["image_level", "calibration_version"])
        writer.writerow(["L0", ""])
    metadata, source = load_image_sidecar(str(image))
    assert metadata["image_level"] == "L0"
    assert source == str(csv_sidecar)

    (tmp_path / "frame.tif.csv").write_text(
        "key,value\nimage_level,L0\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError, match="不唯一"):
        load_image_sidecar(str(image))


def test_build_image_evidence_uses_sha_relative_path_mtime_and_sidecar(tmp_path):
    image = tmp_path / "影像.tif"
    image.write_bytes(b"abc123")
    sidecar = tmp_path / "影像.tif.json"
    sidecar.write_text(
        json.dumps(
            {
                "image_level": "L1",
                "calibration_version": "flat-field-20260723",
                "camera_id": "CAM-001",
            }
        ),
        encoding="utf-8",
    )

    result = build_image_evidence(str(image), str(tmp_path))

    assert result.relative_path == "影像.tif"
    assert result.sha256 == sha256_file(str(image))
    assert result.sha256 == (
        "6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090"
    )
    assert result.size_bytes == 6
    assert result.mtime_ns > 0
    assert result.image_level == ImageLevel.L1
    assert result.calibration_version == "flat-field-20260723"
    assert result.sidecar_relative_path == "影像.tif.json"


def test_image_level_and_l1_calibration_are_never_guessed(tmp_path):
    image = tmp_path / "frame.tif"
    image.write_bytes(b"x")
    (tmp_path / "frame.tif.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ManifestError, match="image_level"):
        build_image_evidence(str(image), str(tmp_path))

    (tmp_path / "frame.tif.json").write_text(
        json.dumps({"image_level": "L1"}), encoding="utf-8"
    )
    with pytest.raises(ManifestError, match="calibration_version"):
        build_image_evidence(str(image), str(tmp_path))


def test_dataset_manifest_hash_round_trip_and_tamper_detection(tmp_path):
    image = tmp_path / "frame.tif"
    image.write_bytes(b"dataset")
    (tmp_path / "frame.tif.json").write_text(
        json.dumps({"image_level": "L0"}), encoding="utf-8"
    )
    manifest = build_dataset_manifest(
        dataset_root=str(tmp_path),
        machine_id="AOI-01",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        precondition_lock=valid_lock(warmup=20),
        image_paths=[str(image)],
    )
    path = tmp_path / "acceptance-manifest.json"
    manifest.save_json(str(path))

    restored = AcceptanceDatasetManifest.load_json(str(path))
    assert restored.to_dict() == manifest.to_dict()
    assert restored.measurements_valid is False

    data = json.loads(path.read_text(encoding="utf-8"))
    data["machine_id"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestError, match="hash"):
        AcceptanceDatasetManifest.load_json(str(path))


def test_acceptance_session_manifest_round_trips_formal_lock():
    manifest = AcceptanceManifest(
        machine_id="AOI-01",
        optical_mode=OpticalMode.SPECULAR_BRIGHT_FIELD,
        precondition_lock=valid_lock(),
    )

    restored = AcceptanceManifest.from_dict(manifest.to_dict())

    assert isinstance(restored.precondition_lock, PreconditionLock)
    assert restored.precondition_lock.fingerprint() == valid_lock().fingerprint()
