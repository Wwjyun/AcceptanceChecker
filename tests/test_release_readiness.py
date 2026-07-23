import json
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

import pytest

from acceptance_checker import (
    DEFAULT_SPEC_VERSION,
    FORMAL_REPORT_SCHEMA_VERSION,
    FORMAL_V4_SUPPORT_STATUS,
    PACKAGE_VERSION,
    ReleaseReadinessError,
    ReleaseReviewSignoff,
    ReviewParty,
    ThreePartyReleaseReview,
    evaluate_release_readiness,
    load_default_v4_spec,
)


def _signoffs():
    return [
        ReleaseReviewSignoff(
            party,
            f"{party.value} owner",
            "approved",
            "2026-07-23T12:00:00+08:00",
        )
        for party in ReviewParty
    ]


def _review():
    return ThreePartyReleaseReview(
        review_id="RR-v4-001",
        spec_version=DEFAULT_SPEC_VERSION,
        formula_reviewed=True,
        evidence_requirements_reviewed=True,
        report_content_reviewed=True,
        signoffs=_signoffs(),
        evidence_source="three-party-review-record.pdf",
    )


def test_versions_are_independent_public_contracts():
    spec = load_default_v4_spec()
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "acceptance_checker"
            / "schemas"
            / "formal_report_v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert PACKAGE_VERSION == "0.1.0"
    assert version("acceptance-checker") == PACKAGE_VERSION
    assert spec.spec_version == DEFAULT_SPEC_VERSION
    assert FORMAL_REPORT_SCHEMA_VERSION == "1.0"
    assert (
        schema["properties"]["report_schema_version"]["const"]
        == FORMAL_REPORT_SCHEMA_VERSION
    )
    assert len({PACKAGE_VERSION, DEFAULT_SPEC_VERSION, FORMAL_REPORT_SCHEMA_VERSION}) == 3


def test_draft_spec_cannot_claim_official_support_even_with_review_record():
    readiness = evaluate_release_readiness(load_default_v4_spec(), _review())

    assert not readiness.official_v4_support
    assert readiness.status == FORMAL_V4_SUPPORT_STATUS
    assert "draft_unapproved" in readiness.reasons[0]


def test_approved_spec_and_matching_three_party_review_unlock_support():
    spec = replace(
        load_default_v4_spec(),
        status="approved",
        effective_date="2026-08-01",
    )

    readiness = evaluate_release_readiness(spec, _review())

    assert readiness.official_v4_support
    assert readiness.status == "official_v4_supported"


def test_release_review_requires_exactly_three_distinct_parties():
    with pytest.raises(ReleaseReadinessError, match="exactly one"):
        ThreePartyReleaseReview(
            review_id="RR-v4-bad",
            spec_version=DEFAULT_SPEC_VERSION,
            formula_reviewed=True,
            evidence_requirements_reviewed=True,
            report_content_reviewed=True,
            signoffs=[_signoffs()[0], _signoffs()[0], _signoffs()[1]],
            evidence_source="review.pdf",
        )
