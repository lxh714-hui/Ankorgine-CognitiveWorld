"""Validation boundary for proposed cognition-state changes."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from weakref import ref

from cognitive_world.cognition.belief_update import BeliefUpdateProposal
from cognitive_world.cognition.goal_update import GoalUpdateProposal
from cognitive_world.cognition.proposal_origin import original_proposal_permit


_VALIDATION_SEAL = object()
_issued_results: dict[int, tuple[Any, Any, Any, Any]] = {}
_issued_lock = RLock()


def _issue_result(result: "ValidationResult", proposal: Any) -> "ValidationResult":
    key = id(result)

    def discard(weak_result: Any) -> None:
        with _issued_lock:
            current = _issued_results.get(key)
            if current is not None and current[0] is weak_result:
                _issued_results.pop(key, None)

    with _issued_lock:
        _issued_results[key] = (
            ref(result, discard), ref(proposal), deepcopy(proposal),
            original_proposal_permit(proposal),
        )
    return result


@dataclass(frozen=True)
class ValidationResult:
    """Describe whether a cognition update proposal passes validation."""

    accepted: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    _proposal_snapshot: Any = field(default=None, repr=False, compare=False)
    _seal: object | None = field(default=None, repr=False, compare=False)
    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", deepcopy(self.metadata))
        object.__setattr__(self, "_proposal_snapshot", deepcopy(self._proposal_snapshot))

    def authorizes(self, proposal: Any) -> bool:
        """Return whether this validator-issued result matches this proposal."""
        try:
            with _issued_lock:
                issued = _issued_results.get(id(self))
            return (
                issued is not None and issued[0]() is self
                and self.accepted
                and self._seal is _VALIDATION_SEAL
                and issued[1]() is proposal
                and issued[2] == proposal
                and issued[3] is original_proposal_permit(proposal)
            )
        except PermissionError:
            return False


@dataclass
class CognitiveUpdateValidator:
    """Validate proposal source and Agent ownership without applying changes."""

    def validate(self, proposal: Any, context: Any) -> ValidationResult:
        """Return a validation result for a supported cognition proposal."""
        from cognitive_world.cognition.self_model_evolution import SelfModelUpdateProposal

        is_self_model = isinstance(proposal, SelfModelUpdateProposal)
        if not isinstance(proposal, (BeliefUpdateProposal, GoalUpdateProposal)) and not is_self_model:
            return ValidationResult(False, "unsupported proposal type")

        source_refs = proposal.source_refs
        if (
            not isinstance(source_refs, (list, tuple))
            or not source_refs
            or any(
                not isinstance(source_ref, str) or not source_ref
                for source_ref in source_refs
            )
        ):
            return ValidationResult(False, "proposal must contain source_refs")

        if isinstance(context, Mapping):
            agent_id = context.get("agent_id")
        else:
            agent_id = getattr(context, "agent_id", None)
        if proposal.owner_id != agent_id:
            return ValidationResult(
                False, "proposal owner does not match context agent"
            )

        if is_self_model:
            if (
                not isinstance(proposal.claim, str)
                or not proposal.claim.strip()
                or len(proposal.claim) > 512
                or not isinstance(proposal.previous_self_beliefs, tuple)
                or not proposal.source_event_ids
            ):
                return ValidationResult(False, "SelfModel proposal is malformed")

        if isinstance(context, Mapping) and "authorized_source_refs" in context:
            authorized_sources = context.get("authorized_source_refs")
            if (
                not isinstance(authorized_sources, (tuple, list, set, frozenset))
                or any(not isinstance(item, str) or not item for item in authorized_sources)
                or not set(source_refs).issubset(set(authorized_sources))
            ):
                return ValidationResult(
                    False, "proposal cites evidence outside the authorized sources"
                )
        if is_self_model and isinstance(context, Mapping):
            authorized_events = context.get("authorized_event_ids", ())
            if (
                not isinstance(authorized_events, (tuple, list, set, frozenset))
                or not set(proposal.source_event_ids).issubset(set(authorized_events))
            ):
                return ValidationResult(False, "SelfModel proposal cites an unauthorized source Event")
            source_event_pairs = context.get("authorized_source_event_pairs", {})
            if not isinstance(source_event_pairs, Mapping) or any(
                source_event_pairs.get(observation_id) != event_id
                for observation_id, event_id in zip(proposal.source_refs, proposal.source_event_ids)
            ) or len(proposal.source_refs) != len(proposal.source_event_ids):
                return ValidationResult(False, "SelfModel source Observation/Event binding is invalid")

        return _issue_result(ValidationResult(
            accepted=True,
            reason="proposal source and owner validated",
            metadata={
                "proposal_type": type(proposal).__name__,
                "source_ref_count": len(source_refs),
            },
            _proposal_snapshot=proposal,
            _seal=_VALIDATION_SEAL,
        ), proposal)
