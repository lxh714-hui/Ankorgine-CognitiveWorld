"""Offline claim/evidence audit for player insight proposals.

This is not a presentation authorization receipt. In particular, a complete
model-supplied claim list cannot prove that it covers a natural-language text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cognitive_world.presentation.contracts import PerspectiveContext, VisibleInput
from cognitive_world.presentation.visibility import VisibilityFilter


ClaimKind = Literal["state", "event", "actor", "method", "time", "cause", "hypothesis"]
ClaimMode = Literal["asserted", "presupposed", "hypothetical"]


@dataclass(frozen=True)
class EvidenceClaim:
    """A proposition and its place in the original text, not a proven fact."""

    claim_id: str
    kind: ClaimKind
    mode: ClaimMode
    subject_ref: str | None
    predicate: str
    value: object
    basis_indices: tuple[int, ...]
    text_span: tuple[int, int]


@dataclass(frozen=True)
class ClaimEvidenceDraft:
    text: str
    claims: tuple[EvidenceClaim, ...]


@dataclass(frozen=True)
class ClaimCheck:
    claim_id: str
    relation: Literal["direct", "hypothesis", "unsupported", "unknown"]
    source_fact_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ClaimEvidenceAudit:
    checks: tuple[ClaimCheck, ...]
    text_coverage: Literal["unverified"] = "unverified"

    @property
    def may_authorize_presentation(self) -> bool:
        # Surface spans and a model's own list cannot establish completeness,
        # particularly for presuppositions and pragmatic implications.
        return False


def audit_claim_evidence(
    draft: ClaimEvidenceDraft,
    visible_inputs: tuple[VisibleInput, ...],
    perspective: PerspectiveContext,
    visibility: VisibilityFilter,
    simulation_tick: int,
) -> ClaimEvidenceAudit:
    """Check explicit claims against current, owner-authorized observation facts.

    Event IDs remain locators. This does not read Event payloads as player facts.
    Unsupported semantic relationships remain unknown instead of being inferred
    from a current state or a model's asserted evidence relationship.
    """
    if not isinstance(draft, ClaimEvidenceDraft) or not isinstance(draft.text, str):
        raise TypeError("a bounded claim draft is required")
    if not draft.text.strip() or len(draft.text) > 480 or not 1 <= len(draft.claims) <= 12:
        raise ValueError("claim draft exceeds its bounds")
    if not isinstance(visible_inputs, tuple) or len(visible_inputs) > 12:
        raise ValueError("evidence exceeds its bounds")
    if type(simulation_tick) is not int or simulation_tick < 0:
        raise ValueError("simulation tick is invalid")
    for visible in visible_inputs:
        visibility.validate_input(visible, perspective)
        event = visibility.event_history.get_event(visible.source_event_id)
        if event is None or event.simulation_tick is None or event.simulation_tick > simulation_tick:
            raise PermissionError("evidence is not available at the requested simulation tick")
    checks: list[ClaimCheck] = []
    seen: set[str] = set()
    for claim in draft.claims:
        if not isinstance(claim, EvidenceClaim):
            raise TypeError("claim contract required")
        if (not isinstance(claim.claim_id, str) or not claim.claim_id or len(claim.claim_id) > 80
                or claim.claim_id in seen or claim.kind not in {"state", "event", "actor", "method", "time", "cause", "hypothesis"}
                or claim.mode not in {"asserted", "presupposed", "hypothetical"}
                or not isinstance(claim.predicate, str) or not claim.predicate or len(claim.predicate) > 160
                or claim.subject_ref is not None and (not isinstance(claim.subject_ref, str) or len(claim.subject_ref) > 160)
                or not isinstance(claim.text_span, tuple) or len(claim.text_span) != 2
                or any(type(x) is not int for x in claim.text_span)
                or not 0 <= claim.text_span[0] < claim.text_span[1] <= len(draft.text)
                or not isinstance(claim.basis_indices, tuple) or not 1 <= len(claim.basis_indices) <= 4
                or len(set(claim.basis_indices)) != len(claim.basis_indices)
                or any(type(i) is not int or i < 0 or i >= len(visible_inputs) for i in claim.basis_indices)):
            raise ValueError("claim is malformed, duplicated, or cites unavailable evidence")
        seen.add(claim.claim_id)
        cited = tuple(visible_inputs[i] for i in claim.basis_indices)
        refs = tuple(fact.source_fact_id for fact in cited)
        if claim.subject_ref is not None and not any(fact.subject_ref == claim.subject_ref for fact in cited):
            checks.append(ClaimCheck(claim.claim_id, "unsupported", refs, "subject is not grounded by cited observations"))
            continue
        if claim.mode == "hypothetical":
            checks.append(ClaimCheck(claim.claim_id, "hypothesis", refs, "possibility is not an observed fact"))
            continue
        exact = tuple(fact for fact in cited if (
            fact.subject_ref == claim.subject_ref and fact.predicate == claim.predicate
            and type(fact.value) is type(claim.value) and fact.value == claim.value
        ))
        if claim.kind == "state":
            supported = any(fact.fact_type == "environment_state" for fact in exact)
        elif claim.kind == "event":
            # A delivered utterance is an explicitly event-shaped visible fact.
            # A state observation (even one with an Event ID) is not.
            supported = any(fact.fact_type == "social_output" for fact in exact)
        else:
            supported = False
        if supported:
            checks.append(ClaimCheck(claim.claim_id, "direct", refs, "exact authorized fact"))
        elif exact:
            checks.append(ClaimCheck(claim.claim_id, "unknown", refs, "fact does not certify this claim dimension"))
        else:
            checks.append(ClaimCheck(claim.claim_id, "unsupported", refs, "cited facts do not state this proposition"))
    return ClaimEvidenceAudit(tuple(checks))
