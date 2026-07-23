import hashlib
import json
from pathlib import Path

from tests.test_g6_measurement import make_inputs


def _canonical_sha256(data) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_deidentified_golden_regression_manifest_matches_deterministic_dataset():
    path = Path(__file__).parent / "data" / "golden_regression_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    inputs = make_inputs()
    results = inputs.detector_results
    result_data = {
        "catalog_id": results.catalog_id,
        "catalog_version": results.catalog_version,
        "detector_id": results.detector_id,
        "detector_version": results.detector_version,
        "decision_rule_version": results.decision_rule_version,
        "imported_from": results.imported_from,
        "decisions": [item.to_dict() for item in results.decisions],
    }

    assert manifest["classification"] == "synthetic_deidentified_test_fixture"
    assert manifest["production_use_allowed"] is False
    assert manifest["sample_counts"] == {"NG": 30, "PASS": 200}
    assert _canonical_sha256(inputs.catalog.to_dict()) == manifest["storage"][
        "catalog_sha256"
    ]
    assert _canonical_sha256(result_data) == manifest["storage"][
        "detector_results_sha256"
    ]
    assert all(
        source.startswith("external://")
        for key, source in manifest["storage"].items()
        if not key.endswith("_sha256")
    )
