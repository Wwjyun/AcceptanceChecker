import json

from examples.run_v4_demo import run


def test_complete_demo_runs_manifest_through_report_and_waiver(tmp_path):
    summary = run(tmp_path / "demo")

    assert summary["manifest_valid"] is True
    assert summary["measurement_count"] == 45
    assert summary["groups"] == ["G1", "G2", "G3", "G4", "G5", "G6"]
    assert summary["decision"] == "rejected_retest"
    assert summary["decision_rule"] == 5
    assert summary["waiver_status"] == "active_not_accepted"
    assert summary["waiver_preserves_result"] is True
    assert summary["official_v4_support"] is False
    assert summary["support_status"] == "pending_three_party_review"

    output = tmp_path / "demo"
    for name in (
        "dataset_manifest.example.json",
        "measurement_package.example.json",
        "judged_session.example.json",
        "report_config.example.json",
        "RPT-DEMO-V4-001.json",
        "RPT-DEMO-V4-001.html",
        "RPT-DEMO-V4-001.pdf",
        "waiver.example.json",
        "demo_summary.json",
    ):
        assert (output / name).is_file()

    report = json.loads(
        (output / "RPT-DEMO-V4-001.json").read_text(encoding="utf-8")
    )
    assert report["specification_version"] == summary["spec_version"]
    assert report["report_schema_version"] == summary["report_schema_version"]
    assert report["sections"][4]["content"]["rule_number"] == 5
    assert report["sections"][4]["content"]["specification_status"] == "draft_unapproved"
    assert report["sections"][4]["content"]["official_v4_support"] is False
    assert (
        report["sections"][4]["content"]["support_status"]
        == "pending_three_party_review"
    )
    assert all(
        signoff["decision"] == "demo_placeholder_not_approval"
        for signoff in report["signoffs"]
    )
