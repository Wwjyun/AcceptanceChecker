# -*- coding: utf-8 -*-
"""Build a formal report from a finalized session and a reviewed JSON config."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from acceptance_checker.core.dataset_manifest import PreconditionLock
from acceptance_checker.core.responsibility import ResponsibilityAnalyzer, ReviewParty
from acceptance_checker.core.v4_domain import AcceptanceSession
from acceptance_checker.core.v4_judge import V4Decision

from .formal_report import (
    FormalAcceptanceReport,
    FormalReportError,
    ImprovementAction,
    OpticalDeclaration,
    ReportArtifact,
    ReportSignoff,
    TestObject,
)


def load_report_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise FormalReportError("report config JSON must be an object")
    return config


def build_formal_report(
    session: AcceptanceSession,
    decision: V4Decision,
    config: Dict[str, Any],
) -> FormalAcceptanceReport:
    lock = session.manifest.precondition_lock
    if isinstance(lock, dict):
        lock = PreconditionLock.from_dict(lock)
    if not isinstance(lock, PreconditionLock):
        raise FormalReportError("formal report requires a validated PreconditionLock")

    try:
        test_object_data = dict(config["test_object"])
        optical_data = dict(config["optical_declaration"])
        improvements_data = list(config["improvements"])
        artifacts_data = list(config["artifacts"])
        signoffs_data = list(config["signoffs"])
    except (KeyError, TypeError) as exc:
        raise FormalReportError(f"report config is incomplete: {exc}") from exc

    return FormalAcceptanceReport(
        report_id=str(config.get("report_id", f"RPT-{session.manifest.session_id}")),
        report_schema_version=str(config.get("report_schema_version", "1.0")),
        created_at=str(config.get("created_at", _utc_now_iso())),
        measurement_date=str(config.get("measurement_date", _utc_now_iso())),
        test_object=TestObject(
            machine_id=str(test_object_data["machine_id"]),
            production_line=str(test_object_data["production_line"]),
            inspection_object=str(test_object_data["inspection_object"]),
            full_inspection_width=str(test_object_data["full_inspection_width"]),
        ),
        optical_declaration=OpticalDeclaration(
            mode=str(optical_data["mode"]),
            light_path_diagrams=[
                str(item) for item in optical_data["light_path_diagrams"]
            ],
            angles=dict(optical_data["angles"]),
        ),
        precondition_lock=lock,
        session=session,
        decision=decision,
        responsibility=ResponsibilityAnalyzer().analyze(session),
        improvements=[
            ImprovementAction(
                priority=int(item["priority"]),
                owner=str(item["owner"]),
                action=str(item["action"]),
                due_date=str(item["due_date"]),
            )
            for item in improvements_data
        ],
        artifacts=_artifacts(artifacts_data),
        signoffs=[
            ReportSignoff(
                party=ReviewParty(item["party"]),
                representative=str(item["representative"]),
                decision=str(item["decision"]),
                signed_at=str(item["signed_at"]),
                dissent=str(item.get("dissent", "")),
            )
            for item in signoffs_data
        ],
    )


def export_formal_report(
    report: FormalAcceptanceReport,
    output_dir: str,
    *,
    formats: Sequence[str] = ("json", "html", "pdf"),
) -> List[str]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths: List[str] = []
    for output_format in formats:
        normalized = output_format.lower()
        path = directory / f"{report.report_id}.{normalized}"
        if normalized == "json":
            report.save_json(str(path))
        elif normalized == "html":
            report.save_html(str(path))
        elif normalized == "pdf":
            report.save_pdf(str(path))
        else:
            raise FormalReportError(f"unsupported report format: {output_format}")
        paths.append(str(path.resolve()))
    return paths


def report_config_template(session: AcceptanceSession) -> Dict[str, Any]:
    mode = session.manifest.optical_mode.value
    return {
        "report_id": f"RPT-{session.manifest.session_id}",
        "report_schema_version": "1.0",
        "created_at": _utc_now_iso(),
        "measurement_date": _utc_now_iso(),
        "test_object": {
            "machine_id": session.manifest.machine_id,
            "production_line": "待填",
            "inspection_object": "待填",
            "full_inspection_width": "待填",
        },
        "optical_declaration": {
            "mode": mode,
            "light_path_diagrams": ["待填"],
            "angles": {"camera_deg": "待填", "light_deg": "待填"},
        },
        "improvements": [
            {
                "priority": 1,
                "owner": "待填",
                "action": "待填",
                "due_date": "待填 YYYY-MM-DD",
            }
        ],
        "artifacts": [
            {"kind": "image", "path": "待填", "sha256": "待填"},
            {"kind": "parameter", "path": "待填", "sha256": "待填"},
            {"kind": "script", "path": "待填", "sha256": "待填"},
        ],
        "signoffs": [
            {
                "party": party.value,
                "representative": "待填",
                "decision": "待填",
                "signed_at": _utc_now_iso(),
                "dissent": "",
            }
            for party in ReviewParty
        ],
    }


def _artifacts(rows: Sequence[Dict[str, Any]]) -> List[ReportArtifact]:
    artifacts: List[ReportArtifact] = []
    for item in rows:
        path = str(item["path"])
        sha256 = str(item.get("sha256", ""))
        if not sha256 and Path(path).is_file():
            artifacts.append(
                ReportArtifact.from_file(
                    str(item["kind"]),
                    path,
                    version=str(item.get("version", "")),
                )
            )
        else:
            artifacts.append(
                ReportArtifact(
                    kind=str(item["kind"]),
                    path=path,
                    sha256=sha256,
                    version=str(item.get("version", "")),
                )
            )
    return artifacts


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
