import json

from acceptance_checker.cli.batch import main
from tests.test_session_workflow import build_workflow_files


def test_composable_cli_and_no_gate_only_changes_exit_code(tmp_path, capsys):
    manifest, package, _image = build_workflow_files(tmp_path)
    validation = tmp_path / "validation.json"
    session = tmp_path / "session.json"
    judged_gate = tmp_path / "judged-gate.json"
    judged_no_gate = tmp_path / "judged-no-gate.json"

    assert main(["validate-manifest", str(manifest), "--output", str(validation)]) == 0
    assert main(
        [
            "measure",
            str(manifest),
            str(package),
            "--output",
            str(session),
        ]
    ) == 0

    payload = json.loads(package.read_text(encoding="utf-8"))
    payload["measurements"][0]["severity"] = "S1"
    package.write_text(json.dumps(payload), encoding="utf-8")
    assert main(
        [
            "measure",
            str(manifest),
            str(package),
            "--output",
            str(session),
        ]
    ) == 0

    assert main(["judge", str(session), "--output", str(judged_gate)]) == 1
    assert (
        main(
            [
                "judge",
                str(session),
                "--output",
                str(judged_no_gate),
                "--no-gate",
            ]
        )
        == 0
    )
    assert judged_gate.read_bytes() == judged_no_gate.read_bytes()
    assert json.loads(judged_gate.read_text(encoding="utf-8"))[
        "overall_result"
    ] == "rejected_retest"
    capsys.readouterr()


def test_report_command_writes_template_and_formal_json_html(tmp_path):
    manifest, package, image = build_workflow_files(tmp_path)
    session = tmp_path / "session.json"
    config_template = tmp_path / "report-config-template.json"
    assert main(
        ["measure", str(manifest), str(package), "--output", str(session)]
    ) == 0
    assert main(
        [
            "report",
            str(session),
            "--write-config-template",
            str(config_template),
        ]
    ) == 0

    parameter = tmp_path / "parameter.json"
    script = tmp_path / "measure.py"
    parameter.write_text("{}", encoding="utf-8")
    script.write_text("print('measure')\n", encoding="utf-8")
    config = json.loads(config_template.read_text(encoding="utf-8"))
    config["test_object"].update(
        {
            "production_line": "Line-1",
            "inspection_object": "metal",
            "full_inspection_width": "1200 mm",
        }
    )
    config["optical_declaration"].update(
        {"light_path_diagrams": [str(image)], "angles": {"camera_deg": 0}}
    )
    config["improvements"] = [
        {
            "priority": 1,
            "owner": "Imaging",
            "action": "retain approved settings",
            "due_date": "2026-08-01",
        }
    ]
    config["artifacts"] = [
        {"kind": "image", "path": str(image)},
        {"kind": "parameter", "path": str(parameter)},
        {"kind": "script", "path": str(script)},
    ]
    for item in config["signoffs"]:
        item["representative"] = f"{item['party']}-owner"
        item["decision"] = "reviewed"
    config_path = tmp_path / "report-config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    output_dir = tmp_path / "report"
    assert main(
        [
            "report",
            str(session),
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--format",
            "json",
            "--format",
            "html",
        ]
    ) == 0
    report_json = next(output_dir.glob("*.json"))
    report_html = next(output_dir.glob("*.html"))
    report_data = json.loads(report_json.read_text(encoding="utf-8"))
    assert report_data["sections"][4]["content"]["result"] == "accepted"
    assert "內部工程管制線" in report_html.read_text(encoding="utf-8")


def test_top_level_help_marks_legacy_as_non_formal(capsys):
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "v4 Session 候選流程" in output
    assert "不是完整 v4 驗收" in output
