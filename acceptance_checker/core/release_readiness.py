# -*- coding: utf-8 -*-
"""Release gate that prevents an unapproved draft from claiming formal v4 support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from .responsibility import ReviewParty
from .specification import V4Specification, load_default_v4_spec


class ReleaseReadinessError(ValueError):
    """Raised when a three-party release review record is incomplete."""


@dataclass(frozen=True)
class ReleaseReviewSignoff:
    party: ReviewParty
    representative: str
    decision: str
    signed_at: str

    def __post_init__(self) -> None:
        if not self.representative or self.decision != "approved" or not self.signed_at:
            raise ReleaseReadinessError(
                "release signoff requires an identified representative and approved decision"
            )
        try:
            datetime.fromisoformat(self.signed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReleaseReadinessError(
                "release signoff time must be ISO-8601"
            ) from exc


@dataclass(frozen=True)
class ThreePartyReleaseReview:
    review_id: str
    spec_version: str
    formula_reviewed: bool
    evidence_requirements_reviewed: bool
    report_content_reviewed: bool
    signoffs: Sequence[ReleaseReviewSignoff]
    evidence_source: str

    def __post_init__(self) -> None:
        if not self.review_id or not self.spec_version or not self.evidence_source:
            raise ReleaseReadinessError(
                "release review requires identity, spec version, and written evidence"
            )
        if not all(
            (
                self.formula_reviewed,
                self.evidence_requirements_reviewed,
                self.report_content_reviewed,
            )
        ):
            raise ReleaseReadinessError(
                "formula, evidence requirements, and report content must all be reviewed"
            )
        parties = [item.party for item in self.signoffs]
        if len(parties) != len(set(parties)) or set(parties) != set(ReviewParty):
            raise ReleaseReadinessError(
                "exactly one imaging, software, and quality release signoff is required"
            )


@dataclass(frozen=True)
class ReleaseReadiness:
    official_v4_support: bool
    status: str
    reasons: Sequence[str]


def evaluate_release_readiness(
    specification: Optional[V4Specification] = None,
    review: Optional[ThreePartyReleaseReview] = None,
) -> ReleaseReadiness:
    """Return an auditable support status without manufacturing human approval."""
    spec = specification or load_default_v4_spec()
    reasons = []
    if spec.status != "approved" or not spec.effective_date:
        reasons.append(
            f"specification {spec.spec_version} is {spec.status} and has no approved effective date"
        )
    if review is None:
        reasons.append("three-party release review record is absent")
    elif review.spec_version != spec.spec_version:
        reasons.append(
            f"release review targets {review.spec_version}, not {spec.spec_version}"
        )
    if reasons:
        return ReleaseReadiness(
            False,
            "pending_three_party_review",
            tuple(reasons),
        )
    return ReleaseReadiness(True, "official_v4_supported", ())
