"""Action-only interpretation and a narrow, extensible causal rule slice."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Protocol
from urllib.error import URLError
from cognitive_world.resolution.provider_budget import claim_provider_call, provider_call_scope
from copy import deepcopy
from uuid import uuid4

from cognitive_world.core.door import DoorState
from cognitive_world.core.action_result import ActionResultKind
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.passage import PassageState
from cognitive_world.core.world_state import WorldState, WorldStateSlotRead
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.attempt import Attempt
from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine
from cognitive_world.runtime.clock import SimulationTime
from cognitive_world.safety.governance import SafetyInput, SafetyDisposition, UniversalSafetyGovernance
from cognitive_world.resolution.interaction_context import (
    CausalWorldContext,
    InteractionStateAggregator,
)


_AUTHORITY_FIELDS = frozenset({
    "success", "confirmed", "outcome", "result", "world_changes",
    "npc_reactions", "permissions", "owner_id", "observed_facts",
    "event", "events", "event_ids", "authorization", "visible_scopes",
    "prompt", "debug", "diagnostics", "private_cognition", "observations",
    "npc_reaction", "reaction", "world_fact", "world_facts", "world_state",
    "effect", "effects", "resolved", "event_id", "actor_id", "agent_id",
    "observation", "identity", "audience", "visible",
})


def _attempt_value(value: object) -> bool:
    """Validate bounded JSON-like attempt data without recursive traversal."""
    pending: list[tuple[object, int, bool]] = [(value, 0, False)]
    active_containers: set[int] = set()
    visited_nodes = 0
    while pending:
        current, depth, leaving = pending.pop()
        if leaving:
            active_containers.remove(id(current))
            continue
        visited_nodes += 1
        if visited_nodes > 512 or depth > 6:
            return False
        if current is None or isinstance(current, (bool, int)):
            continue
        if isinstance(current, str):
            if len(current) > 1024:
                return False
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                return False
            continue
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in active_containers or len(current) > 32:
                return False
            active_containers.add(identity)
            pending.append((current, depth, True))
            for key, item in current.items():
                if not isinstance(key, str) or len(key) > 1024 or key.casefold() in _AUTHORITY_FIELDS:
                    return False
                pending.append((item, depth + 1, False))
            continue
        if isinstance(current, (tuple, list)):
            identity = id(current)
            if identity in active_containers or len(current) > 16:
                return False
            active_containers.add(identity)
            pending.append((current, depth, True))
            pending.extend((item, depth + 1, False) for item in current)
            continue
        return False
    return True


def _bounded_shape(value: object, *, depth: int = 0) -> bool:
    # Kept as a compatibility helper; shape, depth, cycles and node count are
    # enforced together by the bounded iterative validator above.
    return depth == 0 and _attempt_value(value)


def _validated_proposal_parts(
    proposal: ActionProposal, actor_id: str | None = None
) -> tuple[dict[str, object], list[str], dict[str, object], list[str]]:
    if not isinstance(proposal, ActionProposal):
        raise TypeError("proposal must be an ActionProposal")
    if any(
        not isinstance(value, str) or not value or len(value) > 1024
        for value in (proposal.proposal_id, proposal.agent_id, proposal.action_type)
    ):
        raise ValueError("proposal identity and action description must be bounded non-empty text")
    if actor_id is not None and proposal.agent_id != actor_id:
        raise PermissionError("proposal actor does not match the trusted actor")
    target_refs = proposal.target_refs
    params = proposal.parameters
    metadata = proposal.metadata
    reasoning_refs = proposal.reasoning_refs
    if not isinstance(target_refs, list) or len(target_refs) > 16 or any(
        not isinstance(target, str) or not target or len(target) > 1024
        for target in target_refs
    ):
        raise ValueError("proposal targets exceed the trusted interpretation bound")
    if not isinstance(params, dict) or not isinstance(metadata, dict):
        raise TypeError("proposal parameters and metadata must be mappings")
    if not isinstance(reasoning_refs, list) or len(reasoning_refs) > 16 or any(
        not isinstance(source_ref, str) or not source_ref or len(source_ref) > 1024
        for source_ref in reasoning_refs
    ):
        raise ValueError("proposal reasoning references exceed the trusted bound")
    forbidden = {
        key for key in params
        if isinstance(key, str) and len(key) <= 1024 and key.casefold() in _AUTHORITY_FIELDS
    }
    if forbidden:
        raise PermissionError(f"proposal contains result or authority fields: {sorted(forbidden)}")
    forbidden_metadata = {
        key for key in metadata
        if isinstance(key, str) and len(key) <= 1024 and key.casefold() in _AUTHORITY_FIELDS
    }
    if forbidden_metadata:
        raise PermissionError(f"proposal metadata contains authority fields: {sorted(forbidden_metadata)}")
    if not _attempt_value(params) or not _attempt_value(metadata):
        raise TypeError("proposal parameters must contain only bounded data values")
    return params, target_refs, metadata, reasoning_refs


class ActionInterpreter:
    """Convert a proposal into an Attempt without treating claimed outcomes as facts."""

    def __init__(self, provider: ActionInterpretationProvider | None = None, *, maximum_output_chars: int = 8000) -> None:
        if isinstance(maximum_output_chars, bool) or not 1 <= maximum_output_chars <= 8000:
            raise ValueError("maximum_output_chars is outside the trusted bound")
        self.provider = provider
        self.maximum_output_chars = maximum_output_chars

    def proposal_fingerprint(self, proposal: ActionProposal, *, actor_id: str | None = None) -> str:
        """Validate and fingerprint all proposal content used by a step plan."""
        params, target_refs, metadata, reasoning_refs = _validated_proposal_parts(proposal, actor_id)
        snapshot = {
            "proposal_id": proposal.proposal_id,
            "agent_id": proposal.agent_id,
            "action_type": proposal.action_type,
            "target_refs": target_refs,
            "parameters": params,
            "reasoning_refs": reasoning_refs,
            "metadata": metadata,
        }
        try:
            encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("proposal content is not canonically serializable") from exc
        if len(encoded) > 12_000:
            raise ValueError("proposal content exceeds the trusted input bound")
        return sha256(encoded).hexdigest()

    def interpret(
        self, proposal: ActionProposal, *, actor_id: str | None = None,
        attempt_id: str | None = None,
    ) -> Attempt:
        params, target_refs, metadata, _ = _validated_proposal_parts(proposal, actor_id)
        if self.provider is not None:
            interpret = getattr(self.provider, "interpret_attempt", None)
            if not callable(interpret):
                raise TypeError("interpreter provider must implement interpret_attempt")
            try:
                with provider_call_scope():
                    raw = (
                        interpret(proposal, max_output_chars=self.maximum_output_chars)
                        if claim_provider_call()
                        else None
                    )
            except (URLError, TimeoutError, OSError):
                # Explicit safe no-model degradation: preserve the submitted
                # Attempt fields and continue through the same Resolution checks.
                raw = None
            if raw is not None:
                from cognitive_world.resolution.providers import validate_interpretation_payload

                extracted = validate_interpretation_payload(raw)
                for step in extracted.get("steps", ()):
                    if isinstance(step, Mapping) and step.get("target") is not None and step["target"] not in target_refs:
                        raise PermissionError("model step target is outside the supplied reference set")
                allowed_update = deepcopy(params)
                allowed_update.update({key: value for key, value in extracted.items() if key != "target_refs"})
                params = allowed_update
                model_targets = extracted.get("target_refs")
                if model_targets is not None:
                    # Parsing is not grounding. A model may narrow an already
                    # supplied reference set, but cannot mint a new target.
                    if any(target not in target_refs for target in model_targets):
                        raise PermissionError("model target is outside the supplied reference set")
                    target_refs = model_targets
                if not _attempt_value(params) or not _bounded_shape(params):
                    raise ValueError("interpreted Attempt exceeds the trusted structural bound")
        steps = params.get("steps", ())
        if isinstance(steps, (tuple, list)) and len(steps) > 5:
            raise ValueError("attempt plan exceeds the trusted per-attempt step budget")
        allowed = deepcopy(params)
        # The Attempt's existing action_proposal_id is the authoritative source
        # reference. Expected outcome prose remains only a proposal parameter.
        return Attempt(
            attempt_id=attempt_id or f"attempt:{uuid4().hex}",
            agent_id=proposal.agent_id,
            action_proposal_id=proposal.proposal_id,
            action_type=proposal.action_type,
            target_refs=target_refs,
            parameters=allowed,
            metadata=metadata,
        )


class AssessmentStatus(str, Enum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    PARTIALLY_FEASIBLE = "partially_feasible"
    INSUFFICIENT_INFORMATION = "insufficient_information"


def _effect_value_snapshot(value: object) -> object:
    """Canonicalize the small immutable values used by installed effects."""
    if type(value) in (DoorState, PassageState):
        return {
            name: getattr(value, name)
            for name in value.__dataclass_fields__
        }
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str) and len(value) <= 1024:
        return value
    raise TypeError("physical effect payload contains an unsupported mutable or untyped value")


def physical_effect_fingerprint(payload: Mapping[str, object]) -> str:
    """Stable digest for the effect payload carried by an issued proposal."""
    if not isinstance(payload, Mapping) or len(payload) > 16:
        raise ValueError("physical effect payload exceeds the supported bound")
    normalized = {
        key: _effect_value_snapshot(value)
        for key, value in payload.items()
        if isinstance(key, str)
    }
    if len(normalized) != len(payload):
        raise TypeError("physical effect payload keys must be text")
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, init=False)
class PhysicalEffectProposal:
    """Uncommitted, immutable state-change proposal bound to one interaction view.

    This record does not authorize a change. The causal policy proposes it;
    MethodBasedResolutionEngine checks its binding and provenance; the existing
    EventFactory/EventProcessor handlers remain the only commit path.
    """

    attempt_id: str
    attempt_fingerprint: str
    target_ref: str
    simulation_tick: int
    source_refs: tuple[str, ...]
    verified_conditions: tuple[str, ...]
    unknown_conditions: tuple[str, ...]
    proposed_participants: tuple["EffectParticipant", ...]
    state_slot_reads: tuple[WorldStateSlotRead, ...]
    _effect_payload: Mapping[str, object]

    def __deepcopy__(self, memo: dict[int, object]) -> "PhysicalEffectProposal":
        memo[id(self)] = self
        return self

    def __init__(
        self,
        *,
        attempt_id: str,
        attempt_fingerprint: str,
        target_ref: str,
        simulation_tick: int,
        source_refs: tuple[str, ...],
        effect_payload: Mapping[str, object],
        verified_conditions: tuple[str, ...],
        unknown_conditions: tuple[str, ...] = (),
        proposed_participants: tuple["EffectParticipant", ...] = (),
        state_slot_reads: tuple[WorldStateSlotRead, ...] = (),
    ) -> None:
        if (
            not all(isinstance(value, str) and value and len(value) <= 1024 for value in (attempt_id, target_ref))
            or not isinstance(attempt_fingerprint, str)
            or len(attempt_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in attempt_fingerprint)
        ):
            raise ValueError("physical effect proposal requires Attempt and target bindings")
        if isinstance(simulation_tick, bool) or not isinstance(simulation_tick, int) or simulation_tick < 0:
            raise ValueError("physical effect proposal requires a trusted non-negative tick")
        for name, values in (("source_refs", source_refs), ("verified_conditions", verified_conditions), ("unknown_conditions", unknown_conditions)):
            if (
                not isinstance(values, tuple)
                or len(values) > 32
                or any(not isinstance(value, str) or not value or len(value) > 512 for value in values)
            ):
                raise TypeError(f"{name} must be an immutable tuple of non-empty text")
        if not source_refs or not verified_conditions:
            raise ValueError("physical effect proposal requires state sources and verified conditions")
        if not isinstance(proposed_participants, tuple) or len(proposed_participants) > 12 or any(
            not isinstance(item, EffectParticipant) for item in proposed_participants
        ):
            raise ValueError("proposed participants must be a bounded immutable tuple")
        if (not isinstance(state_slot_reads, tuple) or len(state_slot_reads) > 32
                or any(not isinstance(item, WorldStateSlotRead) for item in state_slot_reads)):
            raise ValueError("state slot reads must be a bounded immutable tuple")
        if any(item.value_fingerprint is None or item.origin_kind == "unverified"
               for item in state_slot_reads):
            raise PermissionError("physical proposal cannot carry unverifiable slot reads")
        snapshot = deepcopy(dict(effect_payload)) if isinstance(effect_payload, Mapping) else None
        if snapshot is None or not 1 <= len(snapshot) <= 16:
            raise ValueError("physical effect payload is empty or exceeds its bound")
        # Payload values are limited to immutable typed snapshots and scalars;
        # arbitrary nested model output cannot cross this boundary.
        for key, value in snapshot.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise TypeError("physical effect payload keys must be bounded text")
            _effect_value_snapshot(value)
        physical_effect_fingerprint(snapshot)
        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "attempt_fingerprint", attempt_fingerprint)
        object.__setattr__(self, "target_ref", target_ref)
        object.__setattr__(self, "simulation_tick", simulation_tick)
        object.__setattr__(self, "source_refs", source_refs)
        object.__setattr__(self, "verified_conditions", verified_conditions)
        object.__setattr__(self, "unknown_conditions", unknown_conditions)
        object.__setattr__(self, "proposed_participants", proposed_participants)
        object.__setattr__(self, "state_slot_reads", state_slot_reads)
        object.__setattr__(self, "_effect_payload", MappingProxyType(snapshot))

    @classmethod
    def from_context(
        cls,
        attempt: Attempt,
        context: CausalWorldContext,
        effect_payload: Mapping[str, object],
        *,
        verified_conditions: tuple[str, ...],
        unknown_conditions: tuple[str, ...] = (),
    ) -> "PhysicalEffectProposal":
        if (
            not isinstance(attempt, Attempt)
            or context.attempt_id != attempt.attempt_id
            or context.attempt_fingerprint != attempt.content_fingerprint()
            or context.target_ref != attempt.target
            or context.simulation_tick is None
        ):
            raise PermissionError("effect proposal requires a current Attempt-bound physical context")
        return cls(
            attempt_id=attempt.attempt_id,
            attempt_fingerprint=attempt.content_fingerprint(),
            target_ref=attempt.target or "",
            simulation_tick=context.simulation_tick,
            source_refs=context.source_refs,
            effect_payload=effect_payload,
            verified_conditions=verified_conditions,
            unknown_conditions=unknown_conditions,
            state_slot_reads=context.slot_reads,
        )

    @property
    def effect_payload(self) -> dict[str, object]:
        return deepcopy(dict(self._effect_payload))

    @property
    def effect_fingerprint(self) -> str:
        return physical_effect_fingerprint(self._effect_payload)

    def is_bound_to(self, attempt: Attempt, context: "CausalWorldContext") -> bool:
        return (
            isinstance(attempt, Attempt)
            and self.attempt_id == attempt.attempt_id
            and self.attempt_fingerprint == attempt.content_fingerprint()
            and self.target_ref == attempt.target == context.target_ref
            and self.simulation_tick == context.simulation_tick
            and self.source_refs == context.source_refs
            and self.state_slot_reads == context.slot_reads
            and context.attempt_id == attempt.attempt_id
            and context.attempt_fingerprint == self.attempt_fingerprint
        )

    def provenance_record(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_fingerprint": self.attempt_fingerprint,
            "target_ref": self.target_ref,
            "simulation_tick": self.simulation_tick,
            "source_refs": self.source_refs,
            "verified_conditions": self.verified_conditions,
            "unknown_conditions": self.unknown_conditions,
            "effect_fingerprint": self.effect_fingerprint,
            "proposed_participants": tuple({
                "reference": item.reference, "relation": item.relation,
                "status": "model_proposed_unverified",
            } for item in self.proposed_participants),
            "state_slot_reads": tuple(item.to_record() for item in self.state_slot_reads),
        }


@dataclass(frozen=True)
class CausalAssessment:
    status: AssessmentStatus
    explanation: str
    world_effects: tuple[dict[str, object], ...] = ()
    missing_evidence: tuple[str, ...] = ()
    effect_proposals: tuple[PhysicalEffectProposal, ...] = ()
    failure_conditions: tuple[str, ...] = ()
    failure_source_refs: tuple[str, ...] = ()
    failure_state_slot_reads: tuple[WorldStateSlotRead, ...] = ()
    result_kind: ActionResultKind | None = None


class CausalAssessmentPolicy(Protocol):
    def assess(self, attempt: Attempt, context: "CausalWorldContext") -> CausalAssessment:
        """Assess only against an immutable owner/action-scoped world snapshot."""


class ActionInterpretationProvider(Protocol):
    def interpret_attempt(self, proposal: ActionProposal, *, max_output_chars: int) -> str:
        """Return an untrusted bounded JSON attempt extraction."""


class CausalReasoningProvider(Protocol):
    """Optional advisory source; it cannot issue effects or authorize outcomes."""

    def suggest_missing_evidence(self, attempt: Attempt, context: CausalWorldContext) -> "CausalReasoningAdvice":
        """Return bounded advisory text, never facts or authorization."""


@dataclass(frozen=True)
class CausalReasoningAdvice:
    mechanisms: tuple[str, ...] = ()
    required_conditions: tuple[str, ...] = ()
    possible_effects: tuple[str, ...] = ()
    unknown_conditions: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectParticipant:
    """A proposed causal role, not proof that this entity changed state."""

    reference: str
    relation: str

    def __post_init__(self) -> None:
        InteractionReference.parse(self.reference)
        if not isinstance(self.relation, str) or not self.relation.strip() or len(self.relation) > 80:
            raise ValueError("participant relation must be bounded text")


@dataclass(frozen=True)
class SuggestedPhysicalChange:
    """Untrusted possible change; unsupported effects stay unresolved."""

    effect_type: str
    affected_refs: tuple[str, ...]
    required_conditions: tuple[str, ...] = ()
    unknown_conditions: tuple[str, ...] = ()
    participants: tuple[EffectParticipant, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.effect_type, str) or not self.effect_type.strip() or len(self.effect_type) > 160:
            raise ValueError("suggested effect type must be bounded text")
        if not isinstance(self.affected_refs, tuple) or not 1 <= len(self.affected_refs) <= 8:
            raise ValueError("suggested effect needs bounded affected references")
        for reference in self.affected_refs:
            InteractionReference.parse(reference)
        for values in (self.required_conditions, self.unknown_conditions):
            if not isinstance(values, tuple) or len(values) > 8 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 160 for item in values
            ):
                raise ValueError("suggested conditions must be bounded text")
        if not isinstance(self.participants, tuple) or len(self.participants) > 12 or any(
            not isinstance(item, EffectParticipant) for item in self.participants
        ):
            raise ValueError("effect participants must be a bounded immutable tuple")


@dataclass(frozen=True)
class PhysicalEffectSuggestion:
    """Locally bound model suggestion; it cannot authorize a WorldUpdate."""

    attempt_id: str
    attempt_fingerprint: str
    actor_id: str
    initiator_id: str | None
    target_ref: str | None
    simulation_tick: int
    source_refs: tuple[str, ...]
    participants: tuple[EffectParticipant, ...]
    changes: tuple[SuggestedPhysicalChange, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.participants, tuple) or len(self.participants) > 12 or any(
            not isinstance(item, EffectParticipant) for item in self.participants
        ):
            raise ValueError("suggested participants exceed bound")
        if not isinstance(self.changes, tuple) or not 1 <= len(self.changes) <= 4 or any(
            not isinstance(item, SuggestedPhysicalChange) for item in self.changes
        ):
            raise ValueError("suggested changes exceed bound")

    def is_bound_to(self, attempt: Attempt, context: CausalWorldContext) -> bool:
        return (
            self.attempt_id == attempt.attempt_id
            and self.attempt_fingerprint == attempt.content_fingerprint() == context.attempt_fingerprint
            and self.actor_id == attempt.agent_id == context.actor_id
            and self.initiator_id == attempt.initiator_id
            and self.target_ref == attempt.target == context.target_ref
            and self.simulation_tick == context.simulation_tick
            and self.source_refs == context.source_refs
        )


class PhysicalEffectSuggestionProvider(Protocol):
    def suggest_effects(self, attempt: Attempt, context: CausalWorldContext) -> PhysicalEffectSuggestion:
        """Return only model-proposed relations and possible effects."""


@dataclass(frozen=True)
class PhysicalEffectTranslation:
    """A scoped conversion result, never an effect or world-write authority."""

    assessment: CausalAssessment | None
    missing_contracts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupportedPhysicalEffectTranslator:
    """Convert open semantic suggestions only through installed state rules.

    A suggested label is not a WorldUpdate schema. The domain policy must
    independently produce a bound PhysicalEffectProposal from current state.
    """

    def translate(
        self, suggestion: PhysicalEffectSuggestion, attempt: Attempt,
        context: CausalWorldContext, policy: CausalAssessmentPolicy,
    ) -> PhysicalEffectTranslation:
        if not suggestion.is_bound_to(attempt, context):
            return PhysicalEffectTranslation(None, ("attempt_or_state_binding_invalid",))
        allowed_refs = {
            *context.grounded_refs,
            *(f"object:{item}" for item in context.held_tool_ids),
        }
        if any(item.reference not in allowed_refs for item in suggestion.participants) or any(
            item.reference not in allowed_refs
            for change in suggestion.changes for item in change.participants
        ) or any(
            reference not in allowed_refs
            for change in suggestion.changes for reference in change.affected_refs
        ):
            return PhysicalEffectTranslation(None, ("participant_reference_not_grounded",))
        if len(suggestion.changes) != 1:
            return PhysicalEffectTranslation(None, ("multi_effect_transition_not_installed",))
        change = suggestion.changes[0]
        if change.unknown_conditions:
            return PhysicalEffectTranslation(None, ("required_condition_unverified",))
        if change.affected_refs != (attempt.target,):
            return PhysicalEffectTranslation(None, ("affected_state_transition_not_installed",))
        participants = change.participants or suggestion.participants
        if any(item.reference not in {f"agent:{attempt.agent_id}", attempt.target}
               for item in participants):
            return PhysicalEffectTranslation(None, ("participant_relation_not_verified",))
        assess = getattr(policy, "assess_suggested_effect", None)
        if not callable(assess):
            return PhysicalEffectTranslation(None, ("state_transition_policy_not_installed",))
        assessment = assess(attempt, context, change.effect_type)
        if assessment.status is AssessmentStatus.INSUFFICIENT_INFORMATION:
            return PhysicalEffectTranslation(
                None, assessment.missing_evidence or (f"state_transition_unsupported:{change.effect_type}",),
            )
        if assessment.status is AssessmentStatus.FEASIBLE and assessment.effect_proposals:
            enriched = tuple(
                PhysicalEffectProposal(
                    attempt_id=item.attempt_id,
                    attempt_fingerprint=item.attempt_fingerprint,
                    target_ref=item.target_ref,
                    simulation_tick=item.simulation_tick,
                    source_refs=item.source_refs,
                    effect_payload=item.effect_payload,
                    verified_conditions=item.verified_conditions,
                    unknown_conditions=item.unknown_conditions,
                    proposed_participants=participants,
                    state_slot_reads=item.state_slot_reads,
                )
                for item in assessment.effect_proposals
            )
            assessment = CausalAssessment(
                assessment.status, assessment.explanation, assessment.world_effects,
                assessment.missing_evidence, enriched,
            )
        return PhysicalEffectTranslation(assessment)


def _contains_operation(text: str) -> bool:
    # This narrow door rule requires an attempted operation, not a state
    # description such as "the door is already open". Uncovered phrasing
    # remains unresolved for a semantic interpreter or future causal policy.
    lowered = text.casefold()
    return bool(
        re.search(r"\b(push|pull|force|apply force)\b", lowered)
        or re.search(r"\bopen\s+(?:the|a|this|that|my|your)?\s*(?:door|gate|it)\b", lowered)
    )
def _contains_negation(text: str) -> bool:
    """Treat ambiguous negated descriptions as uncovered, never as permission."""
    normalized = text.casefold()
    return bool(
        re.search(r"\b(not|never|don't|dont|cannot|can't)\b", normalized)

    )


@dataclass(frozen=True)
class DoorCausalAssessmentPolicy:
    """Resolve only evidence-backed direct door operation; other methods defer."""

    @staticmethod
    def supported_attempt_methods() -> tuple[str, ...]:
        """Return canonical method phrases already accepted by this typed rule."""
        return ("push the door", "pull the door", "force the door", "open the door")

    def assess(
        self, attempt: Attempt, context: CausalWorldContext,
        *, semantic_effect_type: str | None = None,
    ) -> CausalAssessment:
        target = attempt.target
        if target is None:
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "no target", missing_evidence=("target",))
        try:
            address = InteractionReference.parse(target)
        except ValueError:
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "invalid target reference", missing_evidence=("target",))
        raw = context.target
        if address.namespace != "object" or not isinstance(raw, DoorState) or raw.door_id != address.identifier:
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "door state is unknown", missing_evidence=(f"door:{target}",))
        location = context.actor_location
        if context.actor_id != attempt.agent_id or context.physical_capabilities is None or location is None:
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "actor capability or position is unknown", missing_evidence=("actor_entity", "actor_location"))
        reach = context.interaction_reach
        if (reach is None or not reach.configured) and location != raw.interaction_location_id:
            return CausalAssessment(AssessmentStatus.INFEASIBLE, "actor is not at the door interaction location")
        params = attempt.parameters
        method = params.get("method")
        steps = params.get("steps", ())
        # A plan is never treated as a batch of completed actions. This
        # resolution pass assesses only its currently executable first step.
        method_text = method if isinstance(method, str) else ""
        if isinstance(steps, (tuple, list)) and steps:
            if not isinstance(steps[0], str):
                return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "first plan step is malformed", missing_evidence=("first_step",))
            method_text = steps[0]
        if semantic_effect_type is not None and semantic_effect_type != "door_state_changed":
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "suggested effect has no installed door rule", missing_evidence=(f"state_transition_unsupported:{semantic_effect_type}",))
        if semantic_effect_type is None and (not _contains_operation(method_text) or _contains_negation(method_text)):
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "method is not covered by an installed causal rule", missing_evidence=("method_rule",))
        reach = context.interaction_reach
        if reach is not None and reach.configured:
            if reach.status == "unknown":
                return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION,
                    "interaction geometry is unknown", missing_evidence=("interaction_geometry",))
            if reach.status == "out_of_reach":
                return CausalAssessment(AssessmentStatus.INFEASIBLE, "actor is out of reach",
                    failure_conditions=("interaction_out_of_reach",),
                    failure_source_refs=context.source_refs,
                    failure_state_slot_reads=tuple(r for r in context.slot_reads if r.slot in reach.slots))
        if raw.is_open:
            return CausalAssessment(
                AssessmentStatus.INFEASIBLE, "door is already open",
                result_kind=ActionResultKind.GOAL_ALREADY_SATISFIED,
            )
        tools = params.get("tools", ())
        tool_ids = tuple(tools) if isinstance(tools, (tuple, list)) else ()
        has_key = bool(raw.key_id and raw.key_id in tool_ids and raw.key_id in context.held_tool_ids)
        key_method = bool(re.search(r"\b(key|unlock|use)\b", method_text.casefold()))
        physical = context.physical_capabilities
        hand_operation = raw.hand_operable and physical is not None and "manual_manipulation" in physical
        if raw.is_locked and (not has_key or not key_method):
            return CausalAssessment(
                AssessmentStatus.INFEASIBLE,
                "the confirmed lock prevents this method",
                failure_conditions=("door_locked", "attempt_method_does_not_unlock"),
                failure_source_refs=context.source_refs,
                failure_state_slot_reads=tuple(
                    item for item in context.slot_reads
                    if (item.slot.collection == "environment"
                        and item.slot.record_id == raw.door_id
                        and item.slot.path == ("is_locked",))
                ),
            )
        if not hand_operation:
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "manual capability or door operability is unknown", missing_evidence=("manual_manipulation", "hand_operable"))
        changed = DoorState(raw.door_id, raw.interaction_location_id, True, False, raw.hand_operable, raw.key_id)
        effect = {
            "effect_type": "door_state_changed",
            "door_id": raw.door_id,
            "expected": raw,
            "state": changed,
            "actor_id": attempt.agent_id,
            "actor_location": context.actor_location,
            "key_id": raw.key_id if raw.is_locked and has_key else None,
        }
        proposal = PhysicalEffectProposal.from_context(
            attempt, context, effect,
            verified_conditions=(
                "target_state_matches",
                "interaction_within_reach" if reach is not None and reach.configured else "actor_at_interaction_location",
                "method_supported",
                "manual_manipulation_available",
                *(("required_tool_owned",) if raw.is_locked and has_key else ()),
            ),
        )
        return CausalAssessment(
            AssessmentStatus.FEASIBLE,
            "current state and method support opening",
            effect_proposals=(proposal,),
        )


@dataclass(frozen=True)
class PassageCausalAssessmentPolicy:
    """Resolve movement only across an explicitly known traversable passage."""

    @staticmethod
    def supported_attempt_methods() -> tuple[str, ...]:
        """Return canonical method phrases already accepted by this typed rule."""
        return ("walk through the passage", "move through the passage", "traverse the passage")

    def assess(
        self, attempt: Attempt, context: CausalWorldContext,
        *, semantic_effect_type: str | None = None,
    ) -> CausalAssessment:
        passage = context.target
        if not isinstance(passage, PassageState):
            return CausalAssessment(
                AssessmentStatus.INSUFFICIENT_INFORMATION,
                "passage state is unknown",
                missing_evidence=(f"passage:{attempt.target or 'unknown'}",),
            )
        if context.actor_id != attempt.agent_id or context.actor_location is None:
            return CausalAssessment(
                AssessmentStatus.INSUFFICIENT_INFORMATION,
                "actor identity or position is unknown",
                missing_evidence=("actor_location",),
            )
        params = attempt.parameters
        method = params.get("method")
        steps = params.get("steps", ())
        if isinstance(steps, (tuple, list)) and steps:
            method = steps[0]
        if semantic_effect_type is not None and semantic_effect_type != "actor_location_changed":
            return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "suggested effect has no installed passage rule", missing_evidence=(f"state_transition_unsupported:{semantic_effect_type}",))
        if semantic_effect_type is None and (not isinstance(method, str) or not re.search(
            r"\b(walk|move|travel|go|traverse|pass through)\b", method.casefold()
        )):
            return CausalAssessment(
                AssessmentStatus.INSUFFICIENT_INFORMATION,
                "no installed passage mechanism matches this method",
                missing_evidence=("method_mechanism",),
            )
        if context.actor_location != passage.source_location_id:
            return CausalAssessment(
                AssessmentStatus.INFEASIBLE,
                "actor is not at the passage source",
            )
        if context.physical_capabilities is None:
            return CausalAssessment(
                AssessmentStatus.INSUFFICIENT_INFORMATION,
                "locomotion capability is unknown",
                missing_evidence=("locomotion_capability",),
            )
        if not any(cap in context.physical_capabilities for cap in ("locomotion", "movement")):
            return CausalAssessment(AssessmentStatus.INFEASIBLE, "actor has no confirmed locomotion capability")
        if not passage.traversable:
            return CausalAssessment(AssessmentStatus.INFEASIBLE, "the confirmed passage is not traversable")
        effect = {
            "effect_type": "actor_location_changed",
            "passage_id": passage.passage_id,
            "expected": passage,
            "actor_id": attempt.agent_id,
            "expected_location": passage.source_location_id,
            "destination_location": passage.destination_location_id,
        }
        proposal = PhysicalEffectProposal.from_context(
            attempt, context, effect,
            verified_conditions=(
                "target_passage_matches",
                "actor_at_source",
                "locomotion_available",
                "passage_traversable",
                "method_supported",
            ),
        )
        return CausalAssessment(
            AssessmentStatus.FEASIBLE,
            "confirmed route and locomotion capability support traversal",
            effect_proposals=(proposal,),
        )


@dataclass(frozen=True)
class CompositeCausalAssessmentPolicy:
    """Dispatch the shared resolution pipeline to typed domain adapters."""

    door_policy: CausalAssessmentPolicy = DoorCausalAssessmentPolicy()
    passage_policy: CausalAssessmentPolicy = PassageCausalAssessmentPolicy()

    def supported_attempt_methods(self, mechanism_kind: str) -> tuple[str, ...]:
        """Expose only method expressions accepted by the installed typed adapter."""
        if mechanism_kind == "door":
            provider = getattr(self.door_policy, "supported_attempt_methods", None)
        elif mechanism_kind == "passage":
            provider = getattr(self.passage_policy, "supported_attempt_methods", None)
        else:
            return ()
        values = provider() if callable(provider) else ()
        return tuple(value for value in values if isinstance(value, str) and value)

    def assess(self, attempt: Attempt, context: CausalWorldContext) -> CausalAssessment:
        if isinstance(context.target, DoorState):
            return self.door_policy.assess(attempt, context)
        if isinstance(context.target, PassageState):
            return self.passage_policy.assess(attempt, context)
        return CausalAssessment(
            AssessmentStatus.INSUFFICIENT_INFORMATION,
            "target state has no installed causal domain adapter",
            missing_evidence=("typed_target_state",),
        )

    def assess_suggested_effect(
        self, attempt: Attempt, context: CausalWorldContext, effect_type: str,
    ) -> CausalAssessment:
        """Recheck a semantic suggestion using an installed typed causal rule."""
        if isinstance(context.target, DoorState):
            return self.door_policy.assess(attempt, context, semantic_effect_type=effect_type)
        if isinstance(context.target, PassageState):
            return self.passage_policy.assess(attempt, context, semantic_effect_type=effect_type)
        return CausalAssessment(AssessmentStatus.INSUFFICIENT_INFORMATION, "no installed rule for suggested effect", missing_evidence=("typed_target_state_unavailable",))


@dataclass
class MethodBasedResolutionEngine(ResolutionEngine):
    """One ResolutionEngine dispatching to the currently installed typed domains."""

    world_state: WorldState | None = None
    event_history: object | None = None
    assessment_policy: CausalAssessmentPolicy = CompositeCausalAssessmentPolicy()
    simulation_time: SimulationTime | None = None
    reasoning_provider: CausalReasoningProvider | None = None
    effect_suggestion_provider: PhysicalEffectSuggestionProvider | None = None
    safety_governance: UniversalSafetyGovernance = field(default_factory=UniversalSafetyGovernance)
    effect_translator: SupportedPhysicalEffectTranslator = field(default_factory=SupportedPhysicalEffectTranslator)
    _interaction_state_aggregator: InteractionStateAggregator = field(
        default_factory=InteractionStateAggregator, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise TypeError("MethodBasedResolutionEngine requires UniversalSafetyGovernance")
        if self.effect_suggestion_provider is not None and not callable(
            getattr(self.effect_suggestion_provider, "suggest_effects", None)
        ):
            raise TypeError("effect_suggestion_provider must provide suggest_effects")
        if not isinstance(self.effect_translator, SupportedPhysicalEffectTranslator):
            raise TypeError("effect_translator must preserve the installed state transition boundary")

    def bind_safety_governance(self, governance: UniversalSafetyGovernance) -> None:
        if not isinstance(governance, UniversalSafetyGovernance):
            raise TypeError("governance must be UniversalSafetyGovernance")
        self.safety_governance = governance

    def supported_attempt_methods(self, mechanism_kind: str) -> tuple[str, ...]:
        """Ask the installed causal adapters for their accepted input expressions."""
        provider = getattr(self.assessment_policy, "supported_attempt_methods", None)
        return tuple(provider(mechanism_kind)) if callable(provider) else ()

    def _adjudicate(self, attempt: Attempt) -> ResolutionDecision | None:
        if (
            self.world_state is None
            or not isinstance(self.simulation_time, SimulationTime)
            or not self.simulation_time.is_clock_issued()
        ):
            return None
        try:
            context = self._interaction_state_aggregator.aggregate(
                attempt, self.world_state, self.simulation_time,
                event_history=self.event_history,
            ).physical
        except (TypeError, ValueError, PermissionError):
            return None
        assessment = self.assessment_policy.assess(attempt, context)
        if assessment.status is AssessmentStatus.INSUFFICIENT_INFORMATION and self.effect_suggestion_provider is not None:
            try:
                with provider_call_scope():
                    if not claim_provider_call():
                        return None
                    suggestion = self.effect_suggestion_provider.suggest_effects(attempt, context)
                if not isinstance(suggestion, PhysicalEffectSuggestion) or not suggestion.is_bound_to(attempt, context):
                    return None
                safety = self.safety_governance.assess(SafetyInput(
                    actor_id=attempt.agent_id,
                    source="causal_model_advice",
                    intent=attempt.action_type,
                    method=" ".join(
                        [item.relation for item in suggestion.participants]
                        + [participant.relation for change in suggestion.changes for participant in change.participants]
                        + [item.effect_type for item in suggestion.changes]
                        + [condition for item in suggestion.changes
                           for condition in (*item.required_conditions, *item.unknown_conditions)]
                    )[:4_000],
                    context="untrusted physical effect suggestion; never world authority",
                ))
                if safety.disposition in {SafetyDisposition.REFUSE, SafetyDisposition.CLARIFY}:
                    return None
                # The translator maps open suggestions only to installed state
                # semantics. Its gap result is diagnostic, not authorization.
                translation = self.effect_translator.translate(
                    suggestion, attempt, context, self.assessment_policy,
                )
                if translation.assessment is None:
                    return None
                assessment = translation.assessment
            except (TypeError, ValueError, PermissionError, OSError, TimeoutError, KeyError):
                return None
        # Legacy raw mappings and model-supplied result-shaped values are not
        # effect authority. Only the installed policy's bounded proposal record
        # may proceed, and it must match this exact Attempt, target, tick and
        # aggregate source set.
        if assessment.world_effects:
            return None
        if not isinstance(assessment.effect_proposals, tuple) or any(
            not isinstance(proposal, PhysicalEffectProposal)
            or not proposal.is_bound_to(attempt, context)
            or proposal.unknown_conditions
            or not self._effect_matches_bound_state(proposal, attempt, context)
            for proposal in assessment.effect_proposals
        ):
            return None
        if len(assessment.effect_proposals) > 1:
            return None
        if assessment.status is AssessmentStatus.INSUFFICIENT_INFORMATION:
            if self.reasoning_provider is not None:
                # The advice is deliberately discarded after schema/type
                # validation. It cannot supply an effect or change status.
                try:
                    with provider_call_scope():
                        if not claim_provider_call():
                            return None
                        advice = self.reasoning_provider.suggest_missing_evidence(attempt, context)
                except Exception:
                    return None
                if not isinstance(advice, CausalReasoningAdvice):
                    return None
                advice_text = " ".join(
                    text
                    for group in (advice.mechanisms, advice.required_conditions, advice.possible_effects, advice.unknown_conditions, advice.side_effects)
                    for text in group
                )
                advice_result = self.safety_governance.assess(SafetyInput(
                    actor_id=attempt.agent_id,
                    source="causal_model_advice",
                    intent=attempt.action_type,
                    method=advice_text[:4_000],
                    context="untrusted causal suggestion; never world authority",
                ))
                if advice_result.disposition in {SafetyDisposition.REFUSE, SafetyDisposition.CLARIFY}:
                    return None
            return None
        if assessment.status is AssessmentStatus.PARTIALLY_FEASIBLE:
            return ResolutionDecision(
                False,
                "partial: " + assessment.explanation,
                world_effects=tuple(proposal.effect_payload for proposal in assessment.effect_proposals),
                metadata={
                    "timestamp": str(self.simulation_time.tick),
                    "simulation_tick": self.simulation_time.tick,
                    "physical_effect_provenance": [
                        proposal.provenance_record() for proposal in assessment.effect_proposals
                    ],
                },
            )
        if assessment.status is not AssessmentStatus.FEASIBLE:
            failure_metadata = {}
            if assessment.failure_conditions and assessment.failure_state_slot_reads:
                failure_metadata["confirmed_failure_conditions"] = {
                    "conditions": assessment.failure_conditions,
                    "source_refs": assessment.failure_source_refs,
                    "state_slot_reads": tuple(
                        item.to_record() for item in assessment.failure_state_slot_reads
                    ),
                }
            return ResolutionDecision(
                False, assessment.explanation,
                metadata={
                    "timestamp": str(self.simulation_time.tick),
                    "simulation_tick": self.simulation_time.tick,
                    **failure_metadata,
                },
                result_kind=(assessment.result_kind or ActionResultKind.ACTION_FAILED),
            )
        if not assessment.effect_proposals:
            # Feasibility without a verified effect is not a world change.
            return None
        tick = self.simulation_time.tick
        metadata = {
            "timestamp": str(tick),
            "simulation_tick": tick,
            "physical_effect_provenance": [
                proposal.provenance_record() for proposal in assessment.effect_proposals
            ],
        }
        return ResolutionDecision(
            True, assessment.explanation, metadata=metadata,
            world_effects=tuple(proposal.effect_payload for proposal in assessment.effect_proposals),
            result_kind=ActionResultKind.STATE_CHANGED,
        )

    @staticmethod
    def _effect_matches_bound_state(
        proposal: PhysicalEffectProposal, attempt: Attempt, context: CausalWorldContext
    ) -> bool:
        payload = proposal.effect_payload
        try:
            address = InteractionReference.parse(proposal.target_ref)
        except ValueError:
            return False
        if address.namespace != "object" or payload.get("actor_id") != attempt.agent_id:
            return False
        expected = payload.get("expected")
        if expected is None or expected != context.target:
            return False
        target_id = getattr(context.target, "door_id", None) or getattr(context.target, "passage_id", None)
        payload_id = payload.get("door_id", payload.get("passage_id"))
        if address.identifier != target_id or payload_id != target_id:
            return False
        # A proposal may cite only the actual scoped reads of this aggregate.
        required_sources = {
            f"world_state:entities:{attempt.agent_id}",
            f"world_state:locations:{attempt.agent_id}",
            f"world_state:environment:{address.identifier}",
        }
        if not required_sources.issubset(proposal.source_refs):
            return False
        if proposal.state_slot_reads != context.slot_reads:
            return False
        if isinstance(context.target, DoorState):
            state = payload.get("state")
            required = {
                "effect_type", "door_id", "expected", "state", "actor_id",
                "actor_location", "key_id",
            }
            if (
                set(payload) != required
                or payload.get("effect_type") != "door_state_changed"
                or type(state) is not DoorState
                or not state.is_open
                or state.is_locked
                or (state.door_id, state.interaction_location_id, state.hand_operable, state.key_id)
                != (context.target.door_id, context.target.interaction_location_id,
                    context.target.hand_operable, context.target.key_id)
                or context.target.is_open
                or payload.get("actor_location") != context.actor_location
                or (context.interaction_reach.status != "reachable" if context.interaction_reach is not None
                    and context.interaction_reach.configured else context.actor_location != context.target.interaction_location_id)
                or "manual_manipulation" not in (context.physical_capabilities or ())
            ):
                return False
            required_key = context.target.key_id if context.target.is_locked else None
            if payload.get("key_id") != required_key:
                return False
            if required_key is not None:
                claimed_tools = attempt.parameters.get("tools", ())
                if (
                    required_key not in context.held_tool_ids
                    or not isinstance(claimed_tools, (tuple, list))
                    or required_key not in claimed_tools
                ):
                    return False
            return True
        if isinstance(context.target, PassageState):
            required = {
                "effect_type", "passage_id", "expected", "actor_id",
                "expected_location", "destination_location",
            }
            return (
                set(payload) == required
                and payload.get("effect_type") == "actor_location_changed"
                and context.actor_location == context.target.source_location_id
                and context.target.traversable
                and any(cap in (context.physical_capabilities or ()) for cap in ("locomotion", "movement"))
                and payload.get("expected_location") == context.target.source_location_id
                and payload.get("destination_location") == context.target.destination_location_id
            )
        return False
