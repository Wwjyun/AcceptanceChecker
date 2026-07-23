import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from acceptance_checker.reporting import load_formal_report_schema_v1
from tests.test_formal_report import build_report


def test_formal_report_v1_validates_against_packaged_json_schema(tmp_path):
    data = build_report(tmp_path).to_dict()
    validator = Draft202012Validator(
        load_formal_report_schema_v1(),
        format_checker=FormatChecker(),
    )

    assert list(validator.iter_errors(data)) == []


def test_formal_report_contract_snapshot_is_stable(tmp_path):
    data = build_report(tmp_path).to_dict()
    actual = {
        "top_level_keys": sorted(data),
        "section_titles": [item["title"] for item in data["sections"]],
        "measurement_keys": sorted(data["sections"][3]["content"][0]),
        "signoff_keys": sorted(data["signoffs"][0]),
    }
    snapshot_path = (
        Path(__file__).parent / "snapshots" / "formal_report_v1_contract.json"
    )
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert actual == expected
