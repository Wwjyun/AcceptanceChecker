# -*- coding: utf-8 -*-
"""Generate and run a complete, synthetic v4 candidate workflow.

The generated signoffs are visibly marked as demo placeholders.  They exercise
the report and waiver contracts but are not a three-party release approval.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

from acceptance_checker import (
    AcceptanceDatasetManifest,
    ApprovalLevel,
    ImageEvidence,
    ImageLevel,
    OpticalMode,
    OverallResult,
    PreconditionLock,
    SessionWorkflow,
    Severity,
    WaivedMetric,
    Waiver,
    WaiverApproval,
    evaluate_release_readiness,
    load_default_v4_spec,
    sha256_file,
)
from acceptance_checker.reporting import build_formal_report, export_formal_report
from acceptance_checker.versions import (
    DEFAULT_SPEC_VERSION,
    FORMAL_REPORT_SCHEMA_VERSION,
    PACKAGE_VERSION,
)

DEMO_SPEC = DEFAULT_SPEC_VERSION
DEMO_FORMULA = load_default_v4_spec().formula_version
DEMO_SESSION = "demo-v4-session-001"
DEMO_MACHINE = "DEMO-AOI-001"
FAILED_METRIC = "g1.diffuse.background_cv"


def _lock() -> PreconditionLock:
    return PreconditionLock(
        camera={
            "model": "Demo-LineCam",
            "serial": "DEMO-CAM-001",
            "bit_depth": 12,
            "gain": 1.0,
            "exposure_us": 100,
            "line_rate_hz": 20000,
            "binning": "1x1",
            "sensor_roi": "0,0,4096,1",
            "internal_calibration": "off",
            "auto_features": "off",
        },
        optics={
            "lens_model": "Demo-Lens",
            "aperture": "f/8",
            "working_distance_mm": 120,
            "filter": "none",
            "polarizer": "cross",
            "magnification": 0.5,
            "micrometers_per_pixel": 10,
            "focus_position": "12.3mm",
        },
        lighting={
            "model": "Demo-Light",
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
            "warmup_minutes": 30,
        },
        sample={
            "sample_id": "DEMO-GOLDEN-001",
            "batch_id": "DEMO-BATCH-001",
            "orientation": "arrow-forward",
            "surface_cleanliness": "cleaned",
            "golden_approved": True,
        },
        computation={
            "roi_version": "demo-roi-v1",
            "formula_version": DEMO_FORMULA,
            "script_version": PACKAGE_VERSION,
        },
        data={
            "raw_format": "synthetic-demo-bytes",
            "timestamp_source": "demo-clock",
            "parameter_record_source": "demo-manifest",
        },
    )


def _value_for(metric: Any, severity: Severity) -> Any:
    rule = metric.classification
    kind = rule["kind"]
    if kind == "lower_is_good":
        if severity == Severity.S1:
            return (float(rule["s2_max"]) + float(rule["s1_max"])) / 2
        return float(rule["s3_max"])
    if kind == "higher_is_good":
        if severity == Severity.S1:
            return (float(rule["s1_min"]) + float(rule["s2_min"])) / 2
        return float(rule["s3_min"])
    if kind == "target_range":
        return sum(float(value) for value in rule["s3"]) / 2
    if kind == "zero_fatal":
        return 0
    if kind == "intervals":
        interval = next(
            item for item in rule["intervals"] if item["severity"] == severity.value
        )
        return (float(interval["min"]) + float(interval["max"])) / 2
    if kind == "record_only":
        return 1.0
    return "reviewed-conforming"


def _measurement_rows(evidence: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    specification = load_default_v4_spec()
    for metric in specification.metrics_for_mode(OpticalMode.DIFFUSE_BRIGHT_FIELD):
        non_graded = metric.classification["kind"] == "record_only"
        severity = (
            Severity.NOT_EVALUATED
            if non_graded
            else Severity.S1
            if metric.metric_id == FAILED_METRIC
            else Severity.S3
        )
        rows.append(
            {
                "metric_id": metric.metric_id,
                "group": metric.group.value,
                "severity": severity.value,
                "unit": metric.unit,
                "formula_version": specification.formula_version,
                "image_level": "L0",
                "value": _value_for(
                    metric,
                    Severity.S3 if severity == Severity.NOT_EVALUATED else severity,
                ),
                "roi_id": f"demo-{metric.group.value.lower()}-roi",
                "sample_count": 30,
                "evidence_sources": [evidence],
                "missing_reason": (
                    "規格指定僅記錄、不進行分級" if non_graded else ""
                ),
                "metadata": {
                    "formula": metric.formula,
                    "non_graded": non_graded,
                    "demo_synthetic": True,
                },
            }
        )
    return rows


def _report_config(output: Path, evidence: Path, manifest: Path) -> Dict[str, Any]:
    timestamp = "2026-07-23T12:00:00+08:00"
    demo_notice = "DEMO ONLY - not a real approval"
    return {
        "report_id": "RPT-DEMO-V4-001",
        "report_schema_version": FORMAL_REPORT_SCHEMA_VERSION,
        "created_at": timestamp,
        "measurement_date": timestamp,
        "test_object": {
            "machine_id": DEMO_MACHINE,
            "production_line": "synthetic-demo-line",
            "inspection_object": "synthetic-demo-surface",
            "full_inspection_width": "4096 px",
        },
        "optical_declaration": {
            "mode": OpticalMode.DIFFUSE_BRIGHT_FIELD.value,
            "light_path_diagrams": [str(evidence.resolve())],
            "angles": {"camera_deg": 0, "light_deg": 30},
        },
        "improvements": [
            {
                "priority": 1,
                "owner": "demo-optics-owner",
                "action": "reduce synthetic background CV and repeat the Session",
                "due_date": "2026-08-15",
            }
        ],
        "artifacts": [
            {"kind": "image", "path": str(evidence.resolve())},
            {
                "kind": "parameter",
                "path": str(manifest.resolve()),
                "version": DEMO_SPEC,
            },
            {
                "kind": "script",
                "path": str(Path(__file__).resolve()),
                "version": PACKAGE_VERSION,
            },
        ],
        "signoffs": [
            {
                "party": party,
                "representative": demo_notice,
                "decision": "demo_placeholder_not_approval",
                "signed_at": timestamp,
                "dissent": demo_notice,
            }
            for party in ("imaging_system", "software", "quality")
        ],
        "output_directory": str(output.resolve()),
    }


def _waiver(session: Any, decision: Any) -> Waiver:
    failed = next(
        item for item in session.measurements if item.metric_id == FAILED_METRIC
    )
    issued = date(2026, 7, 23)
    approvals = [
        WaiverApproval(
            "DEMO ONLY - imaging placeholder",
            "imaging_system_manager",
            ApprovalLevel.JOINT_MANAGERS,
            "2026-07-23T13:00:00+08:00",
        ),
        WaiverApproval(
            "DEMO ONLY - requirements placeholder",
            "requirements_owner",
            ApprovalLevel.JOINT_MANAGERS,
            "2026-07-23T13:01:00+08:00",
        ),
    ]
    return Waiver(
        waiver_id="W-DEMO-001",
        session_id=session.manifest.session_id,
        original_result=decision.result,
        original_decision_rule=decision.rule_number,
        waived_metrics=[WaivedMetric.from_measurement(failed)],
        risk_assessment={
            "missed_detection": "synthetic demonstration risk",
            "false_detection": "synthetic demonstration risk",
            "equipment_stability": "synthetic demonstration risk",
            "traceability": "all demo files are retained with hashes",
        },
        responsible_owner="DEMO ONLY - optics placeholder",
        hardware_improvement_date=issued + timedelta(days=30),
        issued_on=issued,
        expires_on=issued + timedelta(days=60),
        approvals=approvals,
        detection_target_adjustment="no production target change; demo only",
        best_effort_acknowledgement="software delivery is best effort; demo only",
    )


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return _primitive(asdict(value))
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_primitive(item) for item in value]
    return value


def run(output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = output_dir / "demo-image.raw"
    evidence.write_bytes(b"AcceptanceChecker synthetic v4 demo evidence\n")
    sidecar = output_dir / "demo-image.raw.json"
    sidecar.write_text(
        json.dumps(
            {
                "image_level": "L0",
                "camera_id": "DEMO-CAM-001",
                "demo_synthetic": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stat = evidence.stat()
    manifest = AcceptanceDatasetManifest(
        machine_id=DEMO_MACHINE,
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        precondition_lock=_lock(),
        spec_version=DEMO_SPEC,
        session_id=DEMO_SESSION,
        images=[
            ImageEvidence(
                relative_path=evidence.name,
                sha256=sha256_file(str(evidence)),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                image_level=ImageLevel.L0,
                calibration_version="",
                sidecar_relative_path=sidecar.name,
            )
        ],
    )
    manifest_path = output_dir / "dataset_manifest.example.json"
    manifest.save_json(str(manifest_path))

    package_path = output_dir / "measurement_package.example.json"
    package_path.write_text(
        json.dumps(
            {"measurements": _measurement_rows(str(evidence.resolve()))},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    workflow = SessionWorkflow()
    workflow.load_manifest(str(manifest_path))
    evidence_check = workflow.check_evidence()
    if not evidence_check.valid:
        raise RuntimeError(evidence_check.to_dict())
    session = workflow.execute_measurement_package(str(package_path))
    decision = workflow.judge()
    if decision.result != OverallResult.REJECTED_RETEST or decision.rule_number != 5:
        raise RuntimeError("demo must exercise the section 13.2 S1 rejection path")
    session_path = output_dir / "judged_session.example.json"
    session.save_json(str(session_path))

    config = _report_config(output_dir, evidence, manifest_path)
    config_path = output_dir / "report_config.example.json"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = build_formal_report(session, decision, config)
    report_paths = export_formal_report(
        report,
        str(output_dir),
        formats=("json", "html", "pdf"),
    )
    workflow.mark_report_ready(report_paths)

    waiver = _waiver(session, decision)
    waiver_evaluation = waiver.evaluate(as_of=date(2026, 8, 1))
    waiver_path = output_dir / "waiver.example.json"
    waiver_path.write_text(
        json.dumps(
            {
                "demo_notice": "DEMO ONLY - not a real approval",
                "waiver": _primitive(waiver),
                "evaluation": _primitive(waiver_evaluation),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    readiness = evaluate_release_readiness()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_version": PACKAGE_VERSION,
        "spec_version": DEMO_SPEC,
        "report_schema_version": FORMAL_REPORT_SCHEMA_VERSION,
        "manifest_valid": True,
        "measurement_count": len(session.measurements),
        "groups": sorted(
            {item.group.value for item in session.measurements}
        ),
        "decision": decision.result.value,
        "decision_rule": decision.rule_number,
        "report_paths": report_paths,
        "waiver_status": waiver_evaluation.status.value,
        "waiver_preserves_result": (
            waiver_evaluation.formal_result == decision.result
        ),
        "official_v4_support": readiness.official_v4_support,
        "support_status": readiness.status,
        "demo_notice": "Synthetic demo outputs are not production evidence or approval.",
    }
    summary_path = output_dir / "demo_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the synthetic manifest → G1-G6 → judge → report → waiver demo"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("demo-output"),
        help="output directory (default: ./demo-output)",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
