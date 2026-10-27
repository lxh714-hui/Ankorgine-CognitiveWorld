"""Bounded, cognition-grounded policies for open-ended Agent decisions.

This module has no Store, WorldState, EventHistory, or Presentation dependency.
Its deterministic rules are a useful no-model fallback, not a claim of general
intelligence. Optional language-model output is parsed as untrusted candidate
data before it can reach the existing ActionProposal contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any, Protocol

from cognitive_world.core.provider_transport import post_provider_json, validate_provider_endpoint


MAX_CANDIDATES = 6
MAX_PLAN_STEPS = 5
MAX_TEXT_CHARS = 480
MAX_CONTEXT_ITEMS = 24
MAX_MODEL_INPUT_CHARS = 48_000


@dataclass(frozen=True)
class CandidateExtension:
    """Versioned canonical bytes carried through candidate selection unchanged."""

    schema_id: str
    schema_version: int
    payload: bytes
    sha256_hex: str

    def __post_init__(self) -> None:
        if (not isinstance(self.schema_id, str) or not self.schema_id
                or type(self.schema_version) is not int or self.schema_version < 1
                or not isinstance(self.payload, bytes)
                or self.sha256_hex != sha256(self.payload).hexdigest()):
            raise ValueError("candidate extension envelope is invalid")
MAX_MODEL_OUTPUT_CHARS = 16_000
MAX_MODEL_CALLS_PER_TURN = 1
MAX_DECISION_REVIEWS = 1


def _text(value: Any, *, maximum: int = MAX_TEXT_CHARS, required: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError("decision text fields must be strings")
    result = " ".join(value.split())
    if required and not result:
        raise ValueError("decision text fields must not be empty")
    if len(result) > maximum:
        raise ValueError("decision text field exceeds its size bound")
    return result


def _plain_value(value: Any) -> str:
    if value is None or isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, tuple) and all(
        item is None or isinstance(item, (str, int, float, bool)) for item in value
    ):
        return ", ".join(str(item) for item in value)
    return "[unavailable structured value]"


def _text_atoms(value: Any, *, depth: int = 0) -> tuple[str, ...]:
    if depth > 4:
        return ()
    if isinstance(value, str):
        return (_text(value),) if value.strip() else ()
    if isinstance(value, Mapping) or hasattr(value, "items"):
        try:
            return tuple(
                text
                for key, item in value.items()
                for text in (*_text_atoms(key, depth=depth + 1), *_text_atoms(item, depth=depth + 1))
            )
        except (TypeError, AttributeError):
            return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(text for item in value for text in _text_atoms(item, depth=depth + 1))
    return ()


@dataclass(frozen=True)
class SituationFact:
    """Fact available through this Agent's verified Percept, not omniscience."""

    percept_id: str
    source_event_id: str
    fact_type: str
    predicate: str
    value: str
    fact_id: str | None = None
    subject_ref: str | None = None


@dataclass(frozen=True)
class SituationBelief:
    """Owner-local subjective belief; confidence is not objective truth."""

    belief_id: str
    claim: str
    confidence: float
    source_refs: tuple[str, ...]
    contextual_binding: Any = None
    structured_judgment: bool = False


@dataclass(frozen=True)
class SituationMemory:
    """Owner-local retrieved recollection with provenance retained."""

    memory_id: str
    recollection: str
    source_event_id: str


@dataclass(frozen=True)
class SituationGoal:
    goal_id: str
    description: str
    priority: float
    motivation_score: float
    blocked: bool
    source_refs: tuple[str, ...] = ()
    status: str = "active"


@dataclass(frozen=True)
class SchedulerEvidenceRef:
    """Typed reference to owner-local evidence used by a scheduler finding."""

    reference_type: str
    reference_id: str

    def __post_init__(self) -> None:
        if self.reference_type not in {
            "percept", "event", "goal", "goal_revision", "candidate", "world_slot"
        }:
            raise ValueError("unsupported scheduler reference type")
        if not isinstance(self.reference_id, str) or not self.reference_id:
            raise ValueError("scheduler evidence reference must be non-empty")


@dataclass(frozen=True)
class ConflictOpportunityCandidate:
    """Unconfirmed owner-scoped tension/opportunity hypothesis."""

    finding_id: str
    owner_id: str
    kind: str
    goal_ids: tuple[str, ...]
    target_refs: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    source_refs: tuple[SchedulerEvidenceRef, ...]
    importance: float
    relevance: float
    uncertainties: tuple[str, ...]
    first_seen_tick: int
    last_seen_tick: int
    sightings: int
    revision: int
    lifecycle: str

    def __post_init__(self) -> None:
        for name in ("finding_id", "owner_id", "kind"):
            _text(getattr(self, name), required=True)
        for name in ("goal_ids", "target_refs", "candidate_ids", "uncertainties"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item for item in values):
                raise TypeError(f"{name} must contain non-empty strings")
        if not isinstance(self.source_refs, tuple) or any(
            not isinstance(item, SchedulerEvidenceRef) for item in self.source_refs
        ):
            raise TypeError("source_refs must contain typed scheduler references")
        for name in ("importance", "relevance"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be finite and in [0,1]")
        if (
            isinstance(self.first_seen_tick, bool)
            or not isinstance(self.first_seen_tick, int)
            or isinstance(self.last_seen_tick, bool)
            or not isinstance(self.last_seen_tick, int)
            or self.first_seen_tick < 0
            or self.last_seen_tick < self.first_seen_tick
            or self.sightings < 1
            or self.revision < 1
            or self.lifecycle not in {"active", "dormant"}
        ):
            raise ValueError("scheduler lifecycle metadata is invalid")


@dataclass(frozen=True)
class ObservedAffordance:
    """A narrow action possibility derived only from this owner's Percepts.

    The record describes evidence-backed affordances for installed causal
    domains. It is neither a world capability grant nor an action enum.
    """

    domain: str
    target_ref: str
    location_id: str
    method_hint: str
    required_capabilities: tuple[str, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class SituationAssessment:
    """Bounded subjective view prepared only from one frozen DecisionContext."""

    owner_id: str
    observed_facts: tuple[SituationFact, ...]
    working_memory: tuple[str, ...]
    memories: tuple[SituationMemory, ...]
    beliefs: tuple[SituationBelief, ...]
    capabilities: tuple[tuple[str, bool | None], ...]
    limitations: tuple[str, ...]
    personality_preferences: tuple[str, ...]
    personality_values: tuple[str, ...]
    personality_traits: tuple[str, ...]
    goals: tuple[SituationGoal, ...]
    emotion_levels: tuple[tuple[str, float], ...]
    motivation_scores: tuple[tuple[str, float], ...]
    goal_conflicts: tuple[tuple[str, str], ...]
    attention_bias: tuple[tuple[str, float], ...]
    risk_bias: float
    impulse_bias: float
    impulse_ceiling: float
    review_bias: float
    metacognitive_cues: tuple[str, ...]
    metacognitive_queries: tuple[str, ...]
    uncertainties: tuple[str, ...]
    affordances: tuple[ObservedAffordance, ...] = ()
    scheduler_findings: tuple[ConflictOpportunityCandidate, ...] = ()

    @property
    def authorized_target_refs(self) -> tuple[str, ...]:
        """References explicitly present in this owner's observed situation."""
        return tuple(sorted({
            *(fact.subject_ref for fact in self.observed_facts
              if isinstance(fact.subject_ref, str) and fact.subject_ref),
            *(item.target_ref for item in self.affordances
              if isinstance(item.target_ref, str) and item.target_ref),
        }))


@dataclass(frozen=True)
class ActionCandidate:
    """Open-ended proposed attempt; all outcome language is prospective."""

    candidate_id: str
    owner_id: str
    goal_id: str | None
    intent: str
    target: str | None
    method: str
    tools: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    expected_result: str
    uncertainties: tuple[str, ...]
    estimated_risk: float | None
    estimated_cost: float | None
    commitment: float
    source_refs: tuple[str, ...]
    strategy: str
    domain_payload: CandidateExtension | None = None

    def __post_init__(self) -> None:
        for name in ("candidate_id", "owner_id", "intent", "method", "expected_result", "strategy"):
            _text(getattr(self, name), required=True)
        if self.goal_id is not None:
            _text(self.goal_id, required=True)
        if self.domain_payload is not None and type(self.domain_payload) is not CandidateExtension:
            raise TypeError("domain_payload must be a versioned CandidateExtension")
        if self.target is not None:
            _text(self.target)
        for name in ("tools", "required_capabilities", "preconditions", "steps", "uncertainties", "source_refs"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item for item in values):
                raise TypeError(f"{name} must be a tuple of non-empty strings")
            if len(values) > (MAX_PLAN_STEPS if name == "steps" else 8):
                raise ValueError(f"{name} exceeds the candidate bound")
            for item in values:
                _text(item, required=True)
        if self.estimated_risk is not None and (
            isinstance(self.estimated_risk, bool)
            or not isinstance(self.estimated_risk, (int, float))
            or not math.isfinite(float(self.estimated_risk))
            or not 0.0 <= float(self.estimated_risk) <= 1.0
        ):
            raise ValueError("estimated_risk must be finite and in [0,1]")
        if self.estimated_cost is not None and (
            isinstance(self.estimated_cost, bool)
            or not isinstance(self.estimated_cost, (int, float))
            or not math.isfinite(float(self.estimated_cost))
            or not 0.0 <= float(self.estimated_cost) <= 1.0
        ):
            raise ValueError("estimated_cost must be finite and in [0,1]")
        if (
            isinstance(self.commitment, bool)
            or not isinstance(self.commitment, (int, float))
            or not math.isfinite(float(self.commitment))
            or not 0.0 <= float(self.commitment) <= 1.0
        ):
            raise ValueError("commitment must be finite and in [0,1]")


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    score: float
    factors: tuple[tuple[str, float], ...]
    uncertainty: tuple[str, ...]


class SituationAssessmentPolicy(Protocol):
    def assess(self, context: Any) -> SituationAssessment: ...


class ActionCandidateGenerationPolicy(Protocol):
    def generate(
        self, situation: SituationAssessment
    ) -> tuple[ActionCandidate, ...] | tuple[tuple[ActionCandidate, ...], str]: ...


class ActionEvaluationPolicy(Protocol):
    def evaluate(
        self, situation: SituationAssessment, candidates: tuple[ActionCandidate, ...]
    ) -> tuple[CandidateEvaluation, ...]: ...


class DecisionLanguageModelProvider(Protocol):
    def generate_candidates(
        self,
        situation: SituationAssessment,
        *,
        max_candidates: int,
        max_output_chars: int,
    ) -> str: ...


@dataclass(frozen=True)
class DeterministicSituationAssessmentPolicy:
    """Project owner-scoped frozen cognition into a compact subjective view."""

    def assess(self, context: Any) -> SituationAssessment:
        from cognitive_world.decision.context import DecisionContext

        if not isinstance(context, DecisionContext):
            raise TypeError("situation assessment requires DecisionContext")
        owner = context.cognition_state.agent_id
        facts: list[SituationFact] = []
        uncertainties: list[str] = [
            "Only the listed owner-authorized observations are known; unobserved world state is unavailable."
        ]
        for percept in context.percepts[:MAX_CONTEXT_ITEMS]:
            if getattr(percept, "observer_id", None) != owner:
                raise PermissionError("situation contains another Agent's Percept")
            content = percept.content
            source_event = getattr(content, "source_event_id", None)
            fact_type = getattr(content, "fact_type", None)
            predicate = getattr(content, "predicate", None)
            value = getattr(content, "value", None)
            if isinstance(source_event, str) and source_event and isinstance(fact_type, str) and isinstance(predicate, str):
                facts.append(SituationFact(
                    percept.percept_id, source_event, _text(fact_type, required=True),
                    _text(predicate, required=True), _text(_plain_value(value)),
                    getattr(content, "fact_id", None),
                    getattr(content, "subject_ref", None),
                ))
            else:
                uncertainties.append(f"Percept {percept.percept_id} has no supported typed fact view.")

        working: list[str] = []
        if context.working_memory is not None:
            if context.working_memory.owner_id != owner:
                raise PermissionError("WorkingMemory belongs to another Agent")
            working.extend(_text_atoms(context.working_memory.focus)[:MAX_CONTEXT_ITEMS])
            working.extend(_text_atoms(context.working_memory.context)[:MAX_CONTEXT_ITEMS])
            working.extend(f"recent percept reference: {item}" for item in context.working_memory.percept_ids)

        memories: list[SituationMemory] = []
        for memory in context.long_term_memories[:MAX_CONTEXT_ITEMS]:
            if memory.owner_id != owner:
                raise PermissionError("Memory belongs to another Agent")
            memories.append(SituationMemory(
                memory.id,
                _text(" ".join(_text_atoms(memory.content))[:MAX_TEXT_CHARS]) or "[recollection has no text]",
                memory.source_event,
            ))

        beliefs: list[SituationBelief] = []
        for belief in context.beliefs[:MAX_CONTEXT_ITEMS]:
            if belief.owner_id != owner:
                raise PermissionError("Belief belongs to another Agent")
            confidence = belief.confidence
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
                uncertainties.append(f"Belief {belief.belief_id} has no usable confidence value.")
                confidence = 0.0
            else:
                confidence = max(0.0, min(1.0, float(confidence)))
            claim = _text(" ".join(_text_atoms(belief.content))[:MAX_TEXT_CHARS]) or "[belief content unavailable]"
            beliefs.append(SituationBelief(
                belief.belief_id, claim, confidence, tuple(belief.source_refs),
                next((b for b in context.contextual_beliefs if b.matches_belief(belief)), None),
                isinstance(belief.content, Mapping) and "fact_type" in belief.content,
            ))
            if confidence < 0.5:
                uncertainties.append(f"Belief {belief.belief_id} is held with limited confidence.")

        capabilities: list[tuple[str, bool | None]] = []
        limitations: list[str] = []
        if context.self_model is not None:
            if context.self_model.owner_id != owner:
                raise PermissionError("SelfModel belongs to another Agent")
            model_capabilities = context.self_model.capabilities
            if isinstance(model_capabilities, Mapping) or hasattr(model_capabilities, "items"):
                capabilities = [
                    (_text(str(name)), value if type(value) is bool else None)
                    for name, value in tuple(model_capabilities.items())[:MAX_CONTEXT_ITEMS]
                ]
            limitations.extend(_text_atoms(context.self_model.limitations)[:MAX_CONTEXT_ITEMS])

        personality = context.personality
        if personality is not None and personality.owner_id != owner:
            raise PermissionError("Personality belongs to another Agent")
        preferences = () if personality is None else tuple(dict.fromkeys(_text_atoms(personality.preferences)))[:MAX_CONTEXT_ITEMS]
        values = () if personality is None else tuple(dict.fromkeys(_text_atoms(personality.values)))[:MAX_CONTEXT_ITEMS]
        traits = () if personality is None else tuple(dict.fromkeys(_text_atoms(personality.traits)))[:MAX_CONTEXT_ITEMS]

        motivation = context.motivation_assessment
        modulation = context.decision_modulation
        if motivation is not None and motivation.owner_id != owner:
            raise PermissionError("MotivationAssessment belongs to another Agent")
        if modulation is not None and modulation.owner_id != owner:
            raise PermissionError("DecisionModulation belongs to another Agent")
        scores = () if motivation is None else tuple(motivation.goal_scores)
        conflicts = () if motivation is None else tuple(motivation.conflict_pairs)
        blocked = set(() if motivation is None else motivation.blocked_goal_ids)
        score_by_goal = dict(scores)
        goals: list[SituationGoal] = []
        for goal in context.goals[:MAX_CONTEXT_ITEMS]:
            if goal.owner_id != owner:
                raise PermissionError("Goal belongs to another Agent")
            try:
                priority = float(goal.priority)
            except (TypeError, ValueError):
                priority = 0.0
                uncertainties.append(f"Goal {goal.goal_id} has no usable priority value.")
            if not math.isfinite(priority):
                priority = 0.0
                uncertainties.append(f"Goal {goal.goal_id} has no finite priority value.")
            goals.append(SituationGoal(
            goal.goal_id, _text(goal.description[:MAX_TEXT_CHARS]), priority,
                float(score_by_goal.get(goal.goal_id, priority)), goal.goal_id in blocked,
                tuple(goal.source_refs), goal.status,
            ))

        emotion = context.emotion
        if emotion is not None and emotion.owner_id != owner:
            raise PermissionError("Emotion belongs to another Agent")
        emotion_levels = () if emotion is None else tuple(sorted(
            (name, float(value)) for name, value in emotion.levels.items()
        ))[:MAX_CONTEXT_ITEMS]
        cues = ()
        queries: tuple[str, ...] = ()
        if context.metacognitive_feedback is not None:
            if context.metacognitive_feedback.owner_id != owner:
                raise PermissionError("MetacognitiveFeedback belongs to another Agent")
            cues = tuple(_text(item) for item in context.metacognitive_feedback.review_cues[:MAX_CONTEXT_ITEMS])
            queries = tuple(_text(query.query[:MAX_TEXT_CHARS])
                            for query in context.metacognitive_feedback.memory_queries[:8])
            for query in context.metacognitive_feedback.memory_queries[:8]:
                if query.owner_id != owner:
                    raise PermissionError("metacognitive query belongs to another Agent")

        latest_environment_facts: dict[tuple[str, str], SituationFact] = {}
        for fact in facts:
            if fact.fact_type != "environment_state":
                continue
            percept = next(
                (item for item in context.percepts if item.percept_id == fact.percept_id),
                None,
            )
            content = None if percept is None else percept.content
            subject_ref = getattr(content, "subject_ref", None)
            if isinstance(subject_ref, str) and subject_ref:
                latest_environment_facts[(fact.predicate, subject_ref)] = fact

        affordances: list[ObservedAffordance] = []
        for fact in latest_environment_facts.values():
            if fact.fact_type != "environment_state" or fact.percept_id == "":
                continue
            percept_refs = (fact.percept_id, fact.source_event_id)
            if (
                fact.predicate == "door_open"
                and fact.value == "False"
                and fact.percept_id
            ):
                # The policy exposes a door interaction possibility only
                # after a trusted, owner-scoped observation of its current
                # closed state. Resolution still checks the live state,
                # position, operability, and physical capability.
                matching = next(
                    (p for p in context.percepts if p.percept_id == fact.percept_id),
                    None,
                )
                content = None if matching is None else matching.content
                target_ref = getattr(content, "subject_ref", None)
                location_id = getattr(content, "location_id", None)
                if isinstance(target_ref, str) and isinstance(location_id, str):
                    affordances.append(ObservedAffordance(
                        "door_operation", target_ref, location_id,
                        "push the observed closed door open by hand",
                        ("manual_manipulation",), percept_refs,
                    ))
            elif fact.predicate == "passage_destination" and fact.value:
                matching = next(
                    (p for p in context.percepts if p.percept_id == fact.percept_id),
                    None,
                )
                content = None if matching is None else matching.content
                target_ref = getattr(content, "subject_ref", None)
                location_id = getattr(content, "location_id", None)
                if isinstance(target_ref, str) and isinstance(location_id, str):
                    affordances.append(ObservedAffordance(
                        "passage_traversal", target_ref, location_id,
                        f"walk through the observed passage toward {fact.value}",
                        ("locomotion",), percept_refs,
                    ))

        return SituationAssessment(
            owner_id=owner,
            observed_facts=tuple(facts),
            working_memory=tuple(dict.fromkeys(working)),
            memories=tuple(memories),
            beliefs=tuple(beliefs),
            capabilities=tuple(sorted(capabilities)),
            limitations=tuple(dict.fromkeys(limitations)),
            personality_preferences=preferences,
            personality_values=values,
            personality_traits=traits,
            goals=tuple(goals),
            emotion_levels=emotion_levels,
            motivation_scores=scores,
            goal_conflicts=conflicts,
            attention_bias=() if modulation is None else tuple(modulation.attention_bias),
            risk_bias=0.0 if modulation is None else float(modulation.risk_bias),
            impulse_bias=0.0 if modulation is None else float(modulation.impulse_bias),
            impulse_ceiling=0.0 if modulation is None else float(modulation.impulse_probability_ceiling),
            review_bias=0.0 if modulation is None else float(modulation.review_bias),
            metacognitive_cues=cues,
            metacognitive_queries=queries,
            uncertainties=tuple(dict.fromkeys(uncertainties)),
            affordances=tuple(sorted(
                affordances,
                key=lambda item: (item.domain, item.target_ref, item.source_refs),
            )),
        )


def _candidate(
    situation: SituationAssessment,
    *,
    index: int,
    goal: SituationGoal | None,
    intent: str,
    target: str | None,
    method: str,
    tools: tuple[str, ...] = (),
    required_capabilities: tuple[str, ...] = (),
    preconditions: tuple[str, ...] = (),
    steps: tuple[str, ...] = (),
    expected_result: str,
    uncertainties: tuple[str, ...] = (),
    estimated_risk: float | None = None,
    estimated_cost: float | None = None,
    commitment: float = 0.5,
    strategy: str,
) -> ActionCandidate:
    if estimated_risk is not None and (not math.isfinite(estimated_risk) or not 0.0 <= estimated_risk <= 1.0):
        raise ValueError("candidate risk estimate must be in [0,1]")
    if not math.isfinite(commitment) or not 0.0 <= commitment <= 1.0:
        raise ValueError("candidate commitment must be in [0,1]")
    return ActionCandidate(
        candidate_id=f"{situation.owner_id}:candidate:{index}",
        owner_id=situation.owner_id,
        goal_id=None if goal is None else goal.goal_id,
        intent=_text(intent, required=True), target=None if target is None else _text(target),
        method=_text(method, required=True),
        tools=tuple(_text(item, required=True) for item in tools),
        required_capabilities=tuple(_text(item, required=True) for item in required_capabilities),
        preconditions=tuple(_text(item, required=True) for item in preconditions),
        steps=tuple(_text(item, required=True) for item in steps),
        expected_result=_text(expected_result, required=True),
        uncertainties=tuple(_text(item, required=True) for item in uncertainties),
        estimated_risk=estimated_risk, estimated_cost=estimated_cost,
        commitment=commitment,
        source_refs=tuple(sorted({
            *(fact.percept_id for fact in situation.observed_facts),
            *(fact.source_event_id for fact in situation.observed_facts),
            *(memory.source_event_id for memory in situation.memories),
            *(ref for belief in situation.beliefs for ref in belief.source_refs),
        })[:8]),
        strategy=strategy,
    )


@dataclass(frozen=True)
class DeterministicOpenEndedCandidatePolicy:
    """Small transparent fallback that derives attempts from current Goals.

    It emits at most one goal-directed candidate per active Goal. If the
    situation contains explicit uncertainty, it also emits one generic
    information-first alternative. These are fallback patterns, not an action
    taxonomy; new methods are never rejected for being absent from this policy.
    """

    maximum_candidates: int = MAX_CANDIDATES

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_candidates <= MAX_CANDIDATES:
            raise ValueError("maximum_candidates exceeds the trusted bound")

    def generate(self, situation: SituationAssessment) -> tuple[ActionCandidate, ...]:
        active = sorted(
            (goal for goal in situation.goals if not goal.blocked),
            key=lambda goal: (-goal.motivation_score, goal.goal_id),
        )
        result: list[ActionCandidate] = []
        for goal in active:
            goal_words = _tokens(goal.description)
            for affordance in situation.affordances:
                target_words = _tokens(affordance.target_ref)
                if affordance.domain == "door_operation":
                    relevant = (
                        bool(goal_words & target_words)
                        or "door" in goal_words
                    ) and bool(goal_words & {"open", "unlock", "enter", "access"})
                    if not relevant:
                        continue
                    result.append(_candidate(
                        situation, index=len(result), goal=goal,
                        intent=f"{goal.description}: try opening the observed door",
                        target=affordance.target_ref,
                        method=affordance.method_hint,
                        required_capabilities=affordance.required_capabilities,
                        preconditions=(
                            "This Agent's authorized Percept reported the door closed; "
                            "current reachability and success remain for Resolution."
                        ,),
                        steps=(affordance.method_hint,),
                        expected_result="The door opens only if current authoritative conditions support the attempt.",
                        uncertainties=("Resolution must recheck current door and actor state.",),
                        estimated_risk=0.2, commitment=0.55,
                        strategy="observed_affordance_goal_match",
                    ))
                elif affordance.domain == "passage_traversal":
                    destination_words = _tokens(affordance.method_hint)
                    mentions_destination = bool(goal_words & destination_words)
                    if not mentions_destination and not ({"move", "travel", "reach", "go"} & goal_words):
                        continue
                    result.append(_candidate(
                        situation, index=len(result), goal=goal,
                        intent=f"{goal.description}: try the observed route",
                        target=affordance.target_ref,
                        method=affordance.method_hint,
                        required_capabilities=affordance.required_capabilities,
                        preconditions=(
                            "This Agent's authorized Percept reported this route; "
                            "current location and traversability remain for Resolution."
                        ,),
                        steps=(affordance.method_hint,),
                        expected_result="Movement occurs only if current authoritative route and actor state permit it.",
                        uncertainties=("Resolution must recheck current passage and actor state.",),
                        estimated_risk=0.1, commitment=0.5,
                        strategy="observed_affordance_goal_match",
                    ))
                if len(result) >= self.maximum_candidates:
                    return tuple(result[:self.maximum_candidates])
            result.append(_candidate(
                situation, index=len(result), goal=goal,
                intent=f"Advance the goal: {goal.description}", target=None,
                method=("Make a bounded next attempt toward this goal using only known information and capabilities; "
                        "pause for reassessment if a prerequisite is not established."),
                preconditions=(f"Goal {goal.goal_id} is active for this Agent",),
                steps=("Attempt one next step, then use the resolved result to decide whether to continue.",),
                expected_result="Make progress toward the stated goal if Resolution confirms the attempt.",
                uncertainties=("Feasibility and outcome remain for Resolution to determine.",),
                estimated_risk=None, commitment=0.55, strategy="deterministic_goal_fallback",
            ))
            if len(result) >= self.maximum_candidates:
                break
        if situation.uncertainties and len(result) < self.maximum_candidates:
            cue = situation.metacognitive_cues[0] if situation.metacognitive_cues else situation.uncertainties[0]
            result.append(_candidate(
                situation, index=len(result), goal=active[0] if active else None,
                intent="Reduce uncertainty relevant to the current situation",
                target=None,
                method=f"Seek a low-commitment, available source of information about: {cue}; then reassess.",
                preconditions=("An appropriate information source is available; otherwise stop without assuming one exists.",),
                steps=("Attempt to obtain relevant information.", "Reassess after the actual result is observed."),
                expected_result="Reduce uncertainty if the information-seeking attempt succeeds under Resolution.",
                uncertainties=(cue,), estimated_risk=0.2, commitment=0.2,
                strategy="deterministic_information_fallback",
            ))
        if not result:
            result.append(_candidate(
                situation, index=0, goal=None,
                intent="Respond to the currently perceived situation",
                target=None,
                method="Form a limited attempt based only on the available perception, and stop if more knowledge is needed.",
                preconditions=(), steps=("Attempt only a reversible next step.",),
                expected_result="Obtain a resolved response to the attempt, if any.",
                uncertainties=("No active Goal supplied a more specific intention.",),
                estimated_risk=0.25, commitment=0.25,
                strategy="deterministic_no_goal_fallback",
            ))
        return tuple(result[: self.maximum_candidates])


_FORBIDDEN_MODEL_FIELDS = frozenset({
    "npc_reactions", "other_agent_reactions", "permissions", "visible_scopes",
    "audience", "agent_id", "owner_id", "observations", "memories", "beliefs",
    "emotion", "world_state", "world_fact", "world_facts", "events", "event",
    "prompt", "debug", "reasoning_trace", "tool_call", "facts", "observed_facts",
    "private_memory", "self_model", "cognition", "scopes", "director",
    "success", "confirmed", "outcome", "world_changes", "result",
})
_CANDIDATE_FIELDS = frozenset({
    "goal_id", "intent", "target", "method", "tools", "required_capabilities",
    "preconditions", "steps", "expected_result", "uncertainties", "estimated_risk",
    "estimated_cost", "commitment",
})


def parse_untrusted_candidates(
    payload: str, situation: SituationAssessment, *, maximum: int = MAX_CANDIDATES
) -> tuple[ActionCandidate, ...]:
    """Validate model JSON, reject authority claims, and locally issue IDs/refs."""
    if not isinstance(payload, str) or len(payload) > MAX_MODEL_OUTPUT_CHARS:
        raise ValueError("model output exceeds the configured size bound")
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("model JSON contains a duplicate field")
            result[key] = value
        return result

    try:
        decoded = json.loads(payload, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("model output is not valid JSON") from error
    if not isinstance(decoded, dict) or "candidates" not in decoded:
        raise ValueError("model output must contain a candidates array")
    root_keys = {str(key).casefold() for key in decoded}
    if root_keys & _FORBIDDEN_MODEL_FIELDS:
        raise PermissionError("model output attempted to provide protected cognition or authority data")
    if root_keys - {"candidates"}:
        raise ValueError("model output contains unsupported root fields")
    entries = decoded["candidates"]
    if not isinstance(entries, list) or not entries or len(entries) > min(maximum, MAX_CANDIDATES):
        raise ValueError("model candidate count is invalid")
    known_goals = {goal.goal_id: goal for goal in situation.goals}
    authorized_targets = set(situation.authorized_target_refs)
    candidates: list[ActionCandidate] = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("each model candidate must be an object")
        keys = {str(key).casefold() for key in raw}
        if keys & _FORBIDDEN_MODEL_FIELDS:
            raise PermissionError("model candidate attempted to provide protected cognition or authority data")
        clean = raw
        if {str(key) for key in clean} - _CANDIDATE_FIELDS:
            raise ValueError("model candidate contains unsupported fields")
        goal_id = clean.get("goal_id")
        if goal_id is not None and (not isinstance(goal_id, str) or goal_id not in known_goals):
            raise PermissionError("model candidate references a Goal outside this Agent's context")
        goal = known_goals.get(goal_id)
        if goal is not None and goal.blocked:
            raise PermissionError("model candidate requires a Goal blocked by known capability limits")
        def strings(key: str, limit: int) -> tuple[str, ...]:
            value = clean.get(key, [])
            if not isinstance(value, list) or len(value) > limit:
                raise ValueError(f"model {key} list exceeds its schema bound")
            return tuple(_text(item, required=True) for item in value)
        target = clean.get("target")
        if target is not None:
            target = _text(target, required=True)
            if target not in authorized_targets:
                raise PermissionError(
                    "model candidate target is not present in this Agent's authorized situation"
                )
        risk = clean.get("estimated_risk")
        cost = clean.get("estimated_cost")
        commitment = clean.get("commitment", 0.5)
        for name, value in (("estimated_risk", risk), ("estimated_cost", cost), ("commitment", commitment)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0):
                raise ValueError(f"model {name} must be a finite number in [0,1]")
        candidates.append(_candidate(
            situation, index=len(candidates), goal=goal,
            intent=_text(clean.get("intent"), required=True), target=target,
            method=_text(clean.get("method"), required=True),
            tools=strings("tools", 8), required_capabilities=strings("required_capabilities", 8),
            preconditions=strings("preconditions", 8), steps=strings("steps", MAX_PLAN_STEPS),
            expected_result=_text(clean.get("expected_result", "The attempt's result remains unresolved until Resolution."), required=True),
            uncertainties=strings("uncertainties", 8),
            estimated_risk=None if risk is None else float(risk),
            estimated_cost=None if cost is None else float(cost), commitment=float(commitment),
            strategy="language_model_candidate",
        ))
    return tuple(candidates)


@dataclass(frozen=True)
class ModelAssistedCandidatePolicy:
    """One bounded provider call with deterministic fallback on any bad output."""

    provider: DecisionLanguageModelProvider | None = None
    fallback: DeterministicOpenEndedCandidatePolicy = DeterministicOpenEndedCandidatePolicy()
    maximum_model_calls: int = MAX_MODEL_CALLS_PER_TURN
    maximum_output_chars: int = MAX_MODEL_OUTPUT_CHARS

    def __post_init__(self) -> None:
        if self.maximum_model_calls != MAX_MODEL_CALLS_PER_TURN:
            raise ValueError("model call budget is fixed at one per Agent turn")
        if not 1 <= self.maximum_output_chars <= MAX_MODEL_OUTPUT_CHARS:
            raise ValueError("model output bound exceeds the trusted limit")

    def generate(self, situation: SituationAssessment) -> tuple[tuple[ActionCandidate, ...], str]:
        if self.provider is None:
            return self.fallback.generate(situation), "deterministic_no_provider"
        try:
            payload = self.provider.generate_candidates(
                situation, max_candidates=MAX_CANDIDATES,
                max_output_chars=self.maximum_output_chars,
            )
            return parse_untrusted_candidates(payload, situation), "language_model_validated"
        except PermissionError:
            # Authority-shaped output is a rejected proposal, not an ordinary
            # availability/schema failure eligible for transparent fallback.
            raise
        except Exception:
            # Availability and schema errors never suppress the safe baseline.
            return self.fallback.generate(situation), "deterministic_fallback_after_provider_error"


@dataclass(frozen=True)
class OpenAICompatibleDecisionProvider:
    """Optional local/remote OpenAI-compatible HTTP adapter using stdlib only."""

    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        validate_provider_endpoint(self.base_url)
        if not self.model or len(self.model) > 160:
            raise ValueError("model must be a non-empty identifier")
        if not math.isfinite(self.timeout_seconds) or not 0.1 <= self.timeout_seconds <= 30.0:
            raise ValueError("timeout_seconds must be within [0.1,30]")

    def generate_candidates(
        self,
        situation: SituationAssessment,
        *,
        max_candidates: int,
        max_output_chars: int,
    ) -> str:
        from cognitive_world.decision.contextual_belief import model_belief_view
        view = {
            "observed_facts": [fact.__dict__ for fact in situation.observed_facts],
            "authorized_target_refs": situation.authorized_target_refs,
            "working_memory": situation.working_memory,
            "personal_memories": [memory.__dict__ for memory in situation.memories],
            "subjective_beliefs": [model_belief_view(belief) for belief in situation.beliefs],
            "known_capabilities": situation.capabilities,
            "limitations": situation.limitations,
            "preferences": situation.personality_preferences,
            "values": situation.personality_values,
            "traits": situation.personality_traits,
            "goals": [goal.__dict__ for goal in situation.goals],
            "emotion_levels": situation.emotion_levels,
            "motivation_scores": situation.motivation_scores,
            "goal_conflicts": situation.goal_conflicts,
            "modulation": {
                "attention_bias": situation.attention_bias,
                "risk_bias": situation.risk_bias,
                "impulse_bias": situation.impulse_bias,
                "impulse_ceiling": situation.impulse_ceiling,
                "review_bias": situation.review_bias,
            },
            "metacognitive_cues": situation.metacognitive_cues,
            "metacognitive_queries": situation.metacognitive_queries,
            "uncertainties": situation.uncertainties,
        }
        instruction = (
            "Return one JSON object with a candidates array. Each candidate may contain only: "
            "goal_id, intent, target, method, tools, required_capabilities, preconditions, "
            "steps, expected_result, uncertainties, estimated_risk, estimated_cost, commitment. "
            f"Return at most {max_candidates} candidates and keep the response under {max_output_chars} characters. "
            "Describe attempts, never assert that an attempt succeeded or that any world change or NPC reaction occurred. "
            "Use only the supplied character-local view; unknown information must remain uncertain. "
            "A target, when supplied, must exactly equal one of authorized_target_refs; never invent or infer a reference. "
            "Methods are open-ended natural language, not a predefined action list."
        )
        prompt = instruction + "\n\nSituation:\n" + json.dumps(view, ensure_ascii=False)
        if len(prompt) > MAX_MODEL_INPUT_CHARS:
            raise ValueError("bounded cognition view exceeds the model input budget")
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 2048,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response_body = post_provider_json(
            self.base_url, "/chat/completions", body, headers=headers,
            timeout_seconds=self.timeout_seconds,
            maximum_bytes=max_output_chars * 4,
        )
        decoded = json.loads(response_body.decode("utf-8"))
        content = decoded["choices"][0]["message"]["content"]
        if not isinstance(content, str) or len(content) > max_output_chars:
            raise ValueError("provider content exceeded output bound")
        return content


def _tokens(text: str) -> frozenset[str]:
    import re
    return frozenset(re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE))


@dataclass(frozen=True)
class DeterministicActionEvaluationPolicy:
    """Stable, explainable subjective candidate ranking; never predicts success."""

    def evaluate(
        self, situation: SituationAssessment, candidates: tuple[ActionCandidate, ...]
    ) -> tuple[CandidateEvaluation, ...]:
        # SituationGoal already carries the profile-derived drive, or the
        # authoritative Goal priority when no individual profile is present.
        # Read that one resolved value for both generation and evaluation.
        goal_scores = {goal.goal_id: goal.motivation_score for goal in situation.goals}
        capabilities = dict(situation.capabilities)
        evaluations: list[CandidateEvaluation] = []
        for candidate in candidates:
            if candidate.owner_id != situation.owner_id:
                raise PermissionError("candidate belongs to another Agent")
            factors: dict[str, float] = {"base": 0.0}
            if candidate.goal_id is not None:
                factors["goal_drive"] = goal_scores.get(candidate.goal_id, 0.0)
                for left, right in situation.goal_conflicts:
                    if candidate.goal_id in (left, right) and len(situation.goals) > 1:
                        factors["goal_conflict_caution"] = -0.15
                        break
            else:
                factors["goal_drive"] = 0.0

            required_missing = [name for name in candidate.required_capabilities if capabilities.get(name) is not True]
            if required_missing:
                # Missing/negative self-knowledge reduces confidence, but an
                # attempt remains legal and is not rejected as impossible.
                factors["capability_uncertainty"] = -0.25 * len(required_missing)
            unavailable_tools = [name for name in candidate.tools if capabilities.get(name) is not True]
            if unavailable_tools:
                factors["tool_resource_uncertainty"] = -0.1 * len(unavailable_tools)
            candidate_text = " ".join((candidate.intent, candidate.method, *candidate.preconditions, *candidate.steps)).casefold()
            factors["observed_affordance_goal_alignment"] = (
                0.25 if candidate.strategy == "observed_affordance_goal_match" else 0.0
            )
            scheduler_matches = tuple(
                finding for finding in situation.scheduler_findings
                if finding.owner_id == situation.owner_id
                and candidate.candidate_id in finding.candidate_ids
            )
            factors["scheduler_relevance"] = min(
                0.12,
                max((finding.importance * finding.relevance * 0.12 for finding in scheduler_matches), default=0.0),
            )
            attention_match = sum(
                bias for focus, bias in situation.attention_bias
                if focus.casefold() in candidate_text or _tokens(focus) & _tokens(candidate_text)
            )
            factors["attention_alignment"] = max(-0.5, min(0.5, attention_match))

            if candidate.estimated_risk is None:
                factors["risk_uncertainty"] = -0.03 if situation.risk_bias < 0 else 0.0
            else:
                factors["risk_preference"] = situation.risk_bias * (candidate.estimated_risk - 0.5)
            if candidate.estimated_cost is not None:
                factors["estimated_cost"] = -0.2 * candidate.estimated_cost
            bounded_impulse = max(
                -situation.impulse_ceiling,
                min(situation.impulse_ceiling, situation.impulse_bias),
            )
            raw_impulse_factor = bounded_impulse * (candidate.commitment - 0.5)
            impulse_factor_limit = situation.impulse_ceiling * abs(candidate.commitment - 0.5)
            if impulse_factor_limit > 0.0:
                # Move the representable cap inward by one ULP so rounding in
                # the multiply cannot exceed the configured individual limit.
                impulse_factor_limit = math.nextafter(impulse_factor_limit, 0.0)
            factors["bounded_impulse"] = math.copysign(
                min(abs(raw_impulse_factor), impulse_factor_limit), raw_impulse_factor
            )

            candidate_tokens = _tokens(candidate_text)
            working_matches = sum(
                bool(candidate_tokens & _tokens(item)) for item in situation.working_memory
            )
            factors["working_memory_relevance"] = min(0.15, 0.05 * working_matches)
            memory_matches = sum(
                bool(candidate_tokens & _tokens(memory.recollection))
                for memory in situation.memories
            )
            factors["long_term_memory_relevance"] = min(0.15, 0.05 * memory_matches)
            belief_matches = sum(
                bool(candidate_tokens & _tokens(belief.claim)) * min(1.0, belief.confidence)
                for belief in situation.beliefs if not belief.structured_judgment
            )
            factors["subjective_belief_alignment"] = min(0.1, 0.05 * belief_matches)
            limitation_matches = sum(
                bool(candidate_tokens & _tokens(limitation)) for limitation in situation.limitations
            )
            if limitation_matches:
                factors["self_model_limitation_caution"] = -0.2 * limitation_matches
            preference_terms = (
                *situation.personality_preferences,
                *situation.personality_values,
                *situation.personality_traits,
            )
            value_overlap = sum(bool(candidate_tokens & _tokens(term)) for term in preference_terms)
            factors["personality_alignment"] = min(0.3, value_overlap * 0.1)
            uncertainty_overlap = sum(
                bool(candidate_tokens & _tokens(cue)) for cue in situation.uncertainties
            )
            factors["review_alignment"] = min(0.25, situation.review_bias * 0.2 * uncertainty_overlap)
            total = sum(factors.values())
            if not math.isfinite(total):
                raise ValueError("candidate evaluation produced a non-finite score")
            uncertainty = tuple(dict.fromkeys((*candidate.uncertainties, *(
                f"Capability {name} is not confirmed by SelfModel." for name in required_missing
            ), *(
                f"Tool or resource {name} is not confirmed by SelfModel." for name in unavailable_tools
            ), *(
                f"A known SelfModel limitation may affect this attempt: {limitation}"
                for limitation in situation.limitations
                if _tokens(limitation) & _tokens(candidate_text)
            ))))
            evaluations.append(CandidateEvaluation(
                candidate.candidate_id, total, tuple(sorted(factors.items())), uncertainty
            ))
        return tuple(evaluations)


@dataclass(frozen=True)
class BoundedDecisionReviewPolicy:
    """One finite reassessment pass, reusing prior L5 cues without new authority."""

    maximum_rounds: int = MAX_DECISION_REVIEWS

    def __post_init__(self) -> None:
        if self.maximum_rounds != MAX_DECISION_REVIEWS:
            raise ValueError("decision review budget is fixed at one round")

    def should_review(
        self, situation: SituationAssessment, evaluations: tuple[CandidateEvaluation, ...]
    ) -> bool:
        if len(evaluations) < 2:
            return bool(situation.uncertainties and situation.review_bias > 0.5)
        scores = sorted((item.score for item in evaluations), reverse=True)
        close_choice = scores[0] - scores[1] <= max(0.1, 0.35 - situation.review_bias * 0.2)
        return bool(situation.uncertainties or situation.goal_conflicts or close_choice)

    def reassess(
        self, situation: SituationAssessment, candidates: tuple[ActionCandidate, ...],
        evaluations: tuple[CandidateEvaluation, ...],
    ) -> tuple[CandidateEvaluation, ...]:
        """Apply one uncertainty-sensitive pass; no retrieval/store/model loop."""
        if not self.should_review(situation, evaluations):
            return evaluations
        evaluated = {item.candidate_id: item for item in evaluations}
        reviewed: list[CandidateEvaluation] = []
        for candidate in candidates:
            item = evaluated[candidate.candidate_id]
            factors = dict(item.factors)
            if candidate.estimated_risk is not None and situation.uncertainties:
                factors["bounded_review_caution"] = max(0.0, situation.review_bias) * (0.5 - candidate.estimated_risk) * 0.2
            else:
                factors["bounded_review_caution"] = 0.0
            reviewed.append(CandidateEvaluation(
                item.candidate_id, sum(factors.values()), tuple(sorted(factors.items())), item.uncertainty
            ))
        return tuple(reviewed)


# All defaults are frozen, stateless policy values. Reusing them lets legacy
# AgentDecision subclasses that omit super().__init__ remain callable without
# introducing mutable process-wide strategy state.
DEFAULT_SITUATION_ASSESSMENT_POLICY = DeterministicSituationAssessmentPolicy()
DEFAULT_CANDIDATE_GENERATION_POLICY = ModelAssistedCandidatePolicy()
DEFAULT_ACTION_EVALUATION_POLICY = DeterministicActionEvaluationPolicy()
DEFAULT_DECISION_REVIEW_POLICY = BoundedDecisionReviewPolicy()
