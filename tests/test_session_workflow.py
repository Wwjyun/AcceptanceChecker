import json
from pathlib import Path

import pytest

from acceptance_checker import (
    AcceptanceDatasetManifest,
    ImageEvidence,
    ImageLevel,
    MetricGroup,
    OpticalMode,
    SessionWorkflow,
    Severity,
    WorkflowError,
    WorkflowStep,
    sha256_file,
)
from tests.test_traceability import lock


def build_workflow_files(tmp_path: Path, *, severity: Severity = Severity.S3):
    image = tmp_path / "image.raw"
    image.write_bytes(b"formal-raw-evidence")
    sidecar = tmp_path / "image.json"
    sidecar.write_text('{"image_level":"L0"}', encoding="utf-8")
    stat = image.stat()
    manifest = AcceptanceDatasetManifest(
        machine_id="AOI-SESSION-1",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        precondition_lock=lock(),
        spec_version="v4-discussion-2026-07-23",
        session_id="session-workflow-1",
        images=[
            ImageEvidence(
                relative_path=image.name,
                sha256=sha256_file(str(image)),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                image_level=ImageLevel.L0,
                calibration_version="",
                sidecar_relative_path=sidecar.name,
            )
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.save_json(str(manifest_path))
    measurements = []
    for group in MetricGroup:
        measurements.append(
            {
                "metric_id": f"{group.value.lower()}.workflow.synthetic",
                "group": group.value,
                "severity": severity.value,
                "unit": "ratio",
                "formula_version": "v4-formula-1",
                "image_level": "L0",
                "value": 1.0,
                "roi_id": f"{group.value}-roi",
                "sample_count": 30,
                "evidence_sources": [str(image)],
                "metadata": {"formula": "synthetic_fixture"},
            }
        )
    package_path = tmp_path / "measurements.json"
    package_path.write_text(
        json.dumps({"measurements": measurements}, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path, package_path, image


def test_workflow_enforces_order_and_reaches_report_ready(tmp_path):
    manifest_path, package_path, _image = build_workflow_files(tmp_path)
    workflow = SessionWorkflow()

    with pytest.raises(WorkflowError, match="先執行證據檢查"):
        workflow.execute_measurement_package(str(package_path))
    workflow.load_manifest(str(manifest_path))
    assert workflow.step == WorkflowStep.MANIFEST_LOADED
    assert workflow.check_evidence().valid
    assert workflow.step == WorkflowStep.EVIDENCE_CHECKED

    session = workflow.execute_measurement_package(str(package_path))
    assert len(session.measurements) == 6
    decision = workflow.judge()
    assert decision.result.value == "accepted"
    assert decision.rule_number == 6
    workflow.mark_report_ready([str(tmp_path / "report.json")])
    assert workflow.step == WorkflowStep.REPORT_READY


def test_workflow_refuses_measurement_when_evidence_hash_changed(tmp_path):
    manifest_path, package_path, image = build_workflow_files(tmp_path)
    workflow = SessionWorkflow()
    workflow.load_manifest(str(manifest_path))
    image.write_bytes(b"tampered")

    check = workflow.check_evidence()
    assert not check.valid
    assert any("SHA-256" in item.reason for item in check.issues)
    with pytest.raises(WorkflowError, match="證據檢查未通過"):
        workflow.execute_measurement_package(str(package_path))


def test_priority_events_persist_through_session_json(tmp_path):
    manifest_path, package_path, _image = build_workflow_files(tmp_path)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["priority_events"] = [
        {
            "event_type": "inspection_blind_zone",
            "description": "接縫形成 1 px 不可檢區",
            "evidence_sources": ["stitch-log.json"],
        }
    ]
    package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

    workflow = SessionWorkflow()
    workflow.load_manifest(str(manifest_path))
    assert workflow.check_evidence().valid
    session = workflow.execute_measurement_package(str(package_path))
    restored = SessionWorkflow.from_session(type(session).from_json(session.to_json()))
    decision = restored.judge()
    assert decision.result.value == "fatal_stop"
    assert decision.rule_number == 1
    assert decision.priority_event_types == ["inspection_blind_zone"]
