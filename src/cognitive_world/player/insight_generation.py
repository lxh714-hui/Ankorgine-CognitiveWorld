"""Offline generation protocol probes; never issue Presentation permission.

The protocols separate claims proposed before wording from wording itself.
Exact assembly can prove that no *new bytes* were introduced during the final
render, but cannot prove that a source fragment has no implicit premise.
"""

from __future__ import annotations

from dataclasses import dataclass

from cognitive_world.player.claim_evidence import (
    ClaimEvidenceAudit, ClaimEvidenceDraft, EvidenceClaim, audit_claim_evidence,
)
from cognitive_world.presentation.contracts import PerspectiveContext, VisibleInput
from cognitive_world.presentation.visibility import VisibilityFilter


@dataclass(frozen=True)
class ClaimFirstProposal:
    """Claims are proposed before an unconstrained final wording."""

    final_text: str
    claims: tuple[EvidenceClaim, ...]


@dataclass(frozen=True)
class SemanticContentUnit:
    """One independently auditable source fragment and its proposed claims."""

    unit_id: str
    surface: str
    claims: tuple[EvidenceClaim, ...]


@dataclass(frozen=True)
class ConstrainedInsightProposal:
    units: tuple[SemanticContentUnit, ...]
    selected_unit_ids: tuple[str, ...]
    final_text: str


@dataclass(frozen=True)
class GenerationProtocolAudit:
    claim_audits: tuple[ClaimEvidenceAudit, ...]
    surface_relation: str
    text_coverage: str = "unverified"

    @property
    def may_authorize_presentation(self) -> bool:
        return False


def inspect_free_text_extraction(
    draft: ClaimEvidenceDraft,
    visible: tuple[VisibleInput, ...], perspective: PerspectiveContext,
    visibility: VisibilityFilter, tick: int,
) -> GenerationProtocolAudit:
    """A: extraction after free text. Missing extracted premises stay unknown."""
    audit = audit_claim_evidence(draft, visible, perspective, visibility, tick)
    return GenerationProtocolAudit((audit,), "free_text_unbounded")


def inspect_claim_first(
    proposal: ClaimFirstProposal,
    visible: tuple[VisibleInput, ...], perspective: PerspectiveContext,
    visibility: VisibilityFilter, tick: int,
) -> GenerationProtocolAudit:
    """B: correct proposed claims do not constrain subsequent free wording."""
    if not isinstance(proposal, ClaimFirstProposal):
        raise TypeError("claim-first proposal required")
    audit = audit_claim_evidence(
        ClaimEvidenceDraft(proposal.final_text, proposal.claims),
        visible, perspective, visibility, tick,
    )
    return GenerationProtocolAudit((audit,), "final_wording_unbounded")


def inspect_constrained_units(
    proposal: ConstrainedInsightProposal,
    visible: tuple[VisibleInput, ...], perspective: PerspectiveContext,
    visibility: VisibilityFilter, tick: int,
) -> GenerationProtocolAudit:
    """C: final wording must exactly assemble selected, separately audited units.

    The joiner is a single space, not an open-ended model-created connector.
    This proves only final-surface provenance, never semantic completeness.
    """
    if not isinstance(proposal, ConstrainedInsightProposal):
        raise TypeError("constrained insight proposal required")
    if (not isinstance(proposal.units, tuple) or not 1 <= len(proposal.units) <= 3
            or not isinstance(proposal.selected_unit_ids, tuple)
            or not 1 <= len(proposal.selected_unit_ids) <= len(proposal.units)
            or any(not isinstance(unit, SemanticContentUnit) for unit in proposal.units)):
        raise ValueError("invalid semantic content units")
    by_id: dict[str, SemanticContentUnit] = {}
    for unit in proposal.units:
        if (not isinstance(unit.unit_id, str) or not unit.unit_id or len(unit.unit_id) > 80
                or unit.unit_id in by_id or not isinstance(unit.surface, str)
                or not unit.surface.strip() or len(unit.surface) > 480
                or not isinstance(unit.claims, tuple) or not unit.claims):
            raise ValueError("invalid or duplicate semantic content unit")
        by_id[unit.unit_id] = unit
    if (any(not isinstance(unit_id, str) for unit_id in proposal.selected_unit_ids)
            or len(set(proposal.selected_unit_ids)) != len(proposal.selected_unit_ids)
            or any(unit_id not in by_id for unit_id in proposal.selected_unit_ids)):
        raise ValueError("selected content unit is unavailable or repeated")
    expected = " ".join(by_id[unit_id].surface for unit_id in proposal.selected_unit_ids)
    if (not isinstance(proposal.final_text, str) or len(expected) > 480
            or proposal.final_text != expected):
        raise ValueError("final text adds or changes content outside selected units")
    # Validate every submitted unit, including an unselected one, so a mixed
    # batch cannot hide invalid claims for a later selection.
    audits = tuple(
        audit_claim_evidence(ClaimEvidenceDraft(unit.surface, unit.claims),
                             visible, perspective, visibility, tick)
        for unit in proposal.units
    )
    return GenerationProtocolAudit(audits, "exact_unit_assembly")
