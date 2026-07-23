# -*- coding: utf-8 -*-
"""Composable formal-v4 CLI commands."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List, Optional

from ..core import (
    AcceptanceSession,
    SessionWorkflow,
    WorkflowError,
)
from ..reporting import (
    build_formal_report,
    export_formal_report,
    load_report_config,
    report_config_template,
)

logger = logging.getLogger("acceptance_checker.cli.v4")

COMMANDS = {"validate-manifest", "measure", "judge", "report"}
_GATE_FAILURES = {
    "fatal_stop",
    "rejected_retest",
    "insufficient_evidence",
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-manifest":
            return _validate_manifest(args)
        if args.command == "measure":
            return _measure(args)
        if args.command == "judge":
            return _judge(args)
        if args.command == "report":
            return _report(args)
    except (OSError, ValueError, KeyError, WorkflowError) as exc:
        logger.error("%s", exc)
        return 2
    parser.error("missing command")
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acceptance-checker-cli",
        description="AcceptanceChecker 正式 v4 Session 工作流",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate-manifest",
        help="驗證 dataset manifest、前提鎖定、檔案與 SHA-256 證據",
    )
    validate.add_argument("manifest")
    validate.add_argument("--output", help="將證據檢查結果寫成 JSON")

    measure = subparsers.add_parser(
        "measure",
        help="驗證證據並執行／匯入 G1-G6 量測套件，輸出 Session JSON",
    )
    measure.add_argument("manifest")
    measure.add_argument("measurement_package")
    measure.add_argument("--output", required=True, help="Session JSON 輸出路徑")

    judge = subparsers.add_parser(
        "judge",
        help="依 v4 第 13.2 節判定 Session",
    )
    judge.add_argument("session")
    judge.add_argument("--output", required=True, help="已判定 Session JSON")
    judge.add_argument(
        "--no-gate",
        action="store_true",
        help="只把外部程序 exit code 改為 0；不更動正式結果或輸出內容",
    )

    report = subparsers.add_parser(
        "report",
        help="從已量測 Session 與三方審閱設定產生正式 JSON/HTML/PDF 報告",
    )
    report.add_argument("session")
    report.add_argument("--config", help="正式報告設定 JSON")
    report.add_argument("--write-config-template", help="寫出待填的報告設定範本")
    report.add_argument("--output-dir", help="正式報告輸出資料夾")
    report.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=["json", "html", "pdf"],
        help="可重複指定；預設輸出 json、html、pdf",
    )
    report.add_argument(
        "--no-gate",
        action="store_true",
        help="只把外部程序 exit code 改為 0；報告內正式結果保持不變",
    )
    return parser


def _validate_manifest(args: argparse.Namespace) -> int:
    workflow = SessionWorkflow()
    dataset = workflow.load_manifest(args.manifest)
    result = workflow.check_evidence()
    payload = {
        "manifest_valid": True,
        "manifest_hash": dataset.manifest_hash(),
        "session_id": dataset.session_id,
        "machine_id": dataset.machine_id,
        "optical_mode": dataset.optical_mode.value,
        "evidence_check": result.to_dict(),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.output:
        _write_text(args.output, text + "\n")
    return 0 if result.valid else 1


def _measure(args: argparse.Namespace) -> int:
    workflow = SessionWorkflow()
    workflow.load_manifest(args.manifest)
    evidence = workflow.check_evidence()
    if not evidence.valid:
        print(json.dumps(evidence.to_dict(), ensure_ascii=False, indent=2))
        return 1
    session = workflow.execute_measurement_package(args.measurement_package)
    session.save_json(args.output)
    print(
        json.dumps(
            {
                "session": str(Path(args.output).resolve()),
                "measurement_count": len(session.measurements),
                "priority_event_count": len(workflow.priority_events),
                "formal_v4": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _judge(args: argparse.Namespace) -> int:
    session = AcceptanceSession.load_json(args.session)
    workflow = SessionWorkflow.from_session(session)
    decision = workflow.judge()
    session.save_json(args.output)
    payload = _decision_payload(decision)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return _gate_exit(decision.result.value, args.no_gate)


def _report(args: argparse.Namespace) -> int:
    session = AcceptanceSession.load_json(args.session)
    workflow = SessionWorkflow.from_session(session)
    decision = workflow.judge()

    if args.write_config_template:
        template = report_config_template(session)
        _write_text(
            args.write_config_template,
            json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        )
        print(f"已寫出正式報告設定範本：{Path(args.write_config_template).resolve()}")
        if not args.config:
            return 0

    if not args.config or not args.output_dir:
        raise WorkflowError(
            "產生正式報告需要 --config 與 --output-dir；"
            "可先用 --write-config-template 建立範本"
        )
    report = build_formal_report(session, decision, load_report_config(args.config))
    paths = export_formal_report(
        report,
        args.output_dir,
        formats=args.formats or ("json", "html", "pdf"),
    )
    workflow.mark_report_ready(paths)
    print(
        json.dumps(
            {
                "decision": _decision_payload(decision),
                "report_paths": paths,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return _gate_exit(decision.result.value, args.no_gate)


def _decision_payload(decision) -> dict:
    return {
        "result": decision.result.value,
        "rule_number": decision.rule_number,
        "reason": decision.reason,
        "group_statuses": decision.group_statuses,
        "trigger_groups": decision.trigger_groups,
        "trigger_metric_ids": decision.trigger_metric_ids,
        "missing_groups": decision.missing_groups,
        "missing_metric_ids": decision.missing_metric_ids,
        "priority_event_types": decision.priority_event_types,
    }


def _gate_exit(result: str, no_gate: bool) -> int:
    if no_gate:
        return 0
    return 1 if result in _GATE_FAILURES else 0


def _write_text(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def top_level_help() -> str:
    return """AcceptanceChecker

正式 v4 Session 子命令：
  validate-manifest  驗證 manifest、前提鎖定與證據檔
  measure            執行／匯入 G1-G6 量測套件
  judge              依第 13.2 節產生正式判定
  report             產生 JSON／HTML／PDF 正式報告

快速工程檢查（不是完整 v4 驗收）：
  quick-check IMAGE... [legacy options]
  為相容舊版，也可直接傳入 IMAGE...。

使用 COMMAND --help 查看各命令參數。
"""
