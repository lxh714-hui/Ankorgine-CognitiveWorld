"""Deterministic, proposal-only emotion and motivation policies.

The rules here are an engineering baseline, not a validated psychological
model. Policies consume one Agent's frozen DecisionContext and never write
Stores or WorldState.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import nullcontext
from copy import deepcopy
import math
from threading import RLock
from typing import Any, Protocol, TYPE_CHECKING
from weakref import ref

from cognitive_world.cognition.emotion import Emotion, EmotionProfile
from cognitive_world.cognition.proposal_origin import ProposalOriginMarker, bind_proposal_origin, original_proposal_permit
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.runtime.write_fence import RuntimeWritePermit
if TYPE_CHECKING:
    from cognitive_world.decision.context import DecisionContext


def _bounded(value: float, low: float, high: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < low or number > high:
        raise ValueError(f"{label} must be finite and in [{low}, {high}]")
    return number


@dataclass(frozen=True)
class EmotionAppraisal:
    owner_id: str
    emotion: str
    strength: float
    certainty: float
    source_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    goal_id: str | None = None
    belief_id: str | None = None

    def __post_init__(self) -> None:
        if not self.owner_id or not self.emotion or not self.source_refs:
            raise ValueError("appraisal requires owner, emotion and provenance")
        _bounded(self.strength, 0.0, 1.0, "appraisal strength")
        _bounded(self.certainty, 0.0, 1.0, "appraisal certainty")
        if not isinstance(self.source_refs, tuple) or not isinstance(self.source_event_ids, tuple):
            raise TypeError("appraisal provenance must be immutable tuples")
        if any(not isinstance(item, str) or not item for item in (*self.source_refs, *self.source_event_ids)):
            raise ValueError("appraisal provenance IDs must be non-empty strings")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("appraisal source_refs must be unique")


@dataclass(frozen=True)
class EmotionProposal:
    """Candidate next state bound to an old snapshot and simulation time."""

    owner_id: str
    emotion_id: str
    previous_levels: tuple[tuple[str, float], ...]
    proposed_levels: tuple[tuple[str, float], ...]
    previous_tick: int | None
    simulation_tick: int
    source_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    appraisals: tuple[EmotionAppraisal, ...] = ()
    processed_sources: tuple[str, ...] = ()
    runtime_write_permit: RuntimeWritePermit | None = field(default=None, repr=False, compare=False)
    _origin_marker: ProposalOriginMarker = field(default_factory=ProposalOriginMarker, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.runtime_write_permit is None:
            object.__setattr__(self, "runtime_write_permit", RuntimeWriteFence.bind_current_permit())
        if not self.owner_id or not self.emotion_id:
            raise ValueError("emotion proposal requires owner and emotion ID")
        if isinstance(self.simulation_tick, bool) or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0:
            raise ValueError("simulation_tick must be a non-negative integer")
        if self.previous_tick is not None and self.simulation_tick < self.previous_tick:
            raise ValueError("simulation time cannot move backwards")
        for name in ("previous_levels", "proposed_levels", "source_refs", "source_event_ids", "appraisals", "processed_sources"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be an immutable tuple")
        if not self.source_refs or not self.source_event_ids:
            raise ValueError("emotion proposal must cite verified percept sources")
        for ids in (self.source_refs, self.source_event_ids, self.processed_sources):
            if any(not isinstance(item, str) or not item for item in ids):
                raise ValueError("emotion provenance IDs must be non-empty strings")
            if len(set(ids)) != len(ids):
                raise ValueError("emotion provenance IDs must be unique")
        if any(not isinstance(item, EmotionAppraisal) for item in self.appraisals):
            raise TypeError("appraisals must contain EmotionAppraisal records")
        for levels in (self.previous_levels, self.proposed_levels):
            if tuple(sorted(levels)) != levels:
                raise ValueError("emotion levels must be sorted snapshots")
            if len({name for name, _ in levels}) != len(levels):
                raise ValueError("emotion labels must be unique")
            for name, value in levels:
                if not name:
                    raise ValueError("emotion labels must be non-empty")
                _bounded(value, 0.0, 1.0, "emotion intensity")
        bind_proposal_origin(self)


@dataclass(frozen=True)
class EmotionDecision:
    owner_id: str
    accepted: bool
    reason: str
    _proposal: EmotionProposal | None = None
    _seal: object | None = None
    def authorizes(self, proposal: EmotionProposal) -> bool:
        try:
            with _emotion_issued_lock:
                issued = _emotion_issued.get(id(self))
            return (
                issued is not None and issued[0]() is self
                and self.accepted and self._seal is _EMOTION_VALIDATION_SEAL
                and issued[1]() is proposal
                and issued[2] == proposal
                and issued[3] is original_proposal_permit(proposal)
            )
        except PermissionError:
            return False


_EMOTION_VALIDATION_SEAL = object()
_emotion_issued: dict[int, tuple[Any, Any, EmotionProposal, RuntimeWritePermit | None]] = {}
_emotion_issued_lock = RLock()


def _issue_emotion_decision(result: EmotionDecision, proposal: EmotionProposal) -> EmotionDecision:
    key = id(result)

    def discard(weak_result: Any) -> None:
        with _emotion_issued_lock:
            current = _emotion_issued.get(key)
            if current is not None and current[0] is weak_result:
                _emotion_issued.pop(key, None)

    with _emotion_issued_lock:
        _emotion_issued[key] = (
            ref(result, discard), ref(proposal), deepcopy(proposal),
            original_proposal_permit(proposal),
        )
    return result


_EMOTION_CONTEXT_SEAL = object()


@dataclass(frozen=True)
class EmotionUpdateContext:
    owner_id: str
    authorized_percept_ids: tuple[str, ...]
    authorized_event_ids: tuple[str, ...]
    simulation_tick: int
    allow_clock_only: bool = False
    previous_processed_sources: tuple[str, ...] = ()
    _seal: object | None = None

    def __post_init__(self) -> None:
        for name in ("authorized_percept_ids", "authorized_event_ids", "previous_processed_sources"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
                raise TypeError(f"{name} must be a tuple of non-empty strings")


def _issue_emotion_update_context(
    owner_id: str,
    authorized_percept_ids: tuple[str, ...],
    authorized_event_ids: tuple[str, ...],
    simulation_tick: int,
    *,
    allow_clock_only: bool,
    previous_processed_sources: tuple[str, ...] = (),
) -> EmotionUpdateContext:
    context = EmotionUpdateContext(
        owner_id, authorized_percept_ids, authorized_event_ids,
        simulation_tick, allow_clock_only, previous_processed_sources,
    )
    object.__setattr__(context, "_seal", _EMOTION_CONTEXT_SEAL)
    return context


class EmotionAppraisalPolicy(Protocol):
    def propose(self, context: DecisionContext, *, simulation_tick: int) -> EmotionProposal | None: ...


@dataclass(frozen=True)
class DeterministicEmotionAppraisalPolicy:
    """Exact-match baseline driven by trusted profile rules and typed facts."""

    def propose(self, context: DecisionContext, *, simulation_tick: int) -> EmotionProposal | None:
        owner = context.cognition_state.agent_id
        profile = context.personality.emotion_profile if context.personality is not None else None
        if profile is None or getattr(profile, "owner_id", None) != owner:
            return None
        old = _emotion_state(context, owner)
        if old is None:
            return None
        if old.last_update_tick is not None and simulation_tick < old.last_update_tick:
            raise ValueError("simulation time cannot move backwards")

        source_percepts: list[tuple[str, str, Any]] = []
        for percept in context.percepts:
            if getattr(percept, "observer_id", None) != owner:
                raise PermissionError("cross-Agent Percept in emotion context")
            fact = percept.content
            event_id = getattr(fact, "source_event_id", None)
            if event_id:
                source_percepts.append((percept.percept_id, event_id, fact))

        if not source_percepts:
            # Time-only recovery is permitted only when the runtime supplies
            # simulation time and an existing state timestamp.
            if old.last_update_tick is None:
                return None
            refs = (f"simulation_tick:{simulation_tick}",)
            event_ids: tuple[str, ...] = (f"clock:{simulation_tick}",)
        else:
            refs = tuple(sorted({item[0] for item in source_percepts}))
            event_ids = tuple(sorted({item[1] for item in source_percepts}))

        levels = dict(old.levels)
        elapsed = simulation_tick - old.last_update_tick if old.last_update_tick is not None else 0
        for emotion, intensity in tuple(levels.items()):
            parameters = _profile_dimension(profile, emotion)
            if parameters is not None and elapsed:
                base_retention = 1.0 - parameters.recovery_per_tick
                effective_retention = base_retention ** (elapsed * (1.0 + parameters.regulation))
                levels[emotion] = max(0.0, intensity * effective_retention)

        appraisals: list[EmotionAppraisal] = []
        processed = set(old.processed_sources)
        for percept_id, event_id, fact in source_percepts:
            if event_id in processed:
                continue
            for rule in profile.reactions:
                parameters = _profile_dimension(profile, rule.emotion)
                if parameters is None:
                    continue
                if (
                    getattr(fact, "fact_type", None) != rule.fact_type
                    or getattr(fact, "predicate", None) != rule.predicate
                    or getattr(fact, "value", object()) != rule.expected_value
                ):
                    continue
                if rule.goal_id is not None and not any(
                    getattr(goal, "goal_id", None) == rule.goal_id
                    and getattr(goal, "status", None) == "active"
                    for goal in context.goals
                ):
                    continue
                if rule.belief_id is not None and not any(
                    getattr(belief, "belief_id", None) == rule.belief_id
                    for belief in context.beliefs
                ):
                    continue
                if rule.memory_id is not None and not any(
                    getattr(memory, "id", None) == rule.memory_id
                    for memory in context.long_term_memories
                ):
                    continue
                if rule.self_belief is not None and not (
                    context.self_model is not None
                    and rule.self_belief in tuple(getattr(context.self_model, "self_beliefs", ()))
                ):
                    continue
                if rule.working_memory_percept_id is not None and not (
                    context.working_memory is not None
                    and rule.working_memory_percept_id in tuple(
                        getattr(context.working_memory, "percept_ids", ())
                    )
                ):
                    continue
                if rule.appraisal_strength < parameters.activation_threshold:
                    continue
                change = (
                    (rule.appraisal_strength - parameters.activation_threshold)
                    * parameters.sensitivity
                    * parameters.growth_rate
                )
                levels[rule.emotion] = min(1.0, levels.get(rule.emotion, 0.0) + change * (1.0 - levels.get(rule.emotion, 0.0)))
                refs = tuple(sorted(set((*refs, percept_id))))
                event_ids = tuple(sorted(set((*event_ids, event_id))))
                appraisals.append(EmotionAppraisal(
                    owner, rule.emotion, rule.appraisal_strength, 1.0,
                    (percept_id,), (event_id,), rule.goal_id, rule.belief_id,
                ))
            processed.add(event_id)

        # Cross-dimension influence exists only where the profile explicitly
        # configures it. It is applied after activation and before validation.
        if appraisals or elapsed:
            for target, source, factor in profile.suppression:
                if target in levels and source in levels:
                    levels[target] = max(0.0, levels[target] * (1.0 - factor * levels[source]))
        next_state = tuple(sorted((name, _bounded(value, 0.0, 1.0, "emotion intensity")) for name, value in levels.items() if value > 0.0))
        previous = old.snapshot_levels()
        if next_state == previous and simulation_tick == old.last_update_tick and not appraisals:
            return None
        # Preserve stable source IDs so historical observations cannot
        # reactivate the same Event on a later AgentTurn.
        proposed = EmotionProposal(
            owner, old.id, previous, next_state, old.last_update_tick,
            simulation_tick, tuple(sorted(set(refs))), tuple(sorted(set(event_ids))),
            tuple(appraisals), tuple(sorted(processed)),
        )
        return proposed


@dataclass(frozen=True)
class EmotionUpdateValidator:
    """Validate owner, provenance, monotonic time, and immutable old state."""

    def validate(self, proposal: EmotionProposal, context: EmotionUpdateContext) -> EmotionDecision:
        if (
            not isinstance(proposal, EmotionProposal)
            or not isinstance(context, EmotionUpdateContext)
            or context._seal is not _EMOTION_CONTEXT_SEAL
        ):
            return EmotionDecision(getattr(context, "owner_id", ""), False, "unsupported input")
        if proposal.owner_id != context.owner_id:
            return EmotionDecision(context.owner_id, False, "owner mismatch")
        if proposal.simulation_tick != context.simulation_tick:
            return EmotionDecision(context.owner_id, False, "simulation time mismatch")
        if not set(proposal.source_refs).issubset(set(context.authorized_percept_ids)):
            if not (context.allow_clock_only and proposal.source_refs == (f"simulation_tick:{context.simulation_tick}",)):
                return EmotionDecision(context.owner_id, False, "unverified source reference")
        allowed_events = set(context.authorized_event_ids)
        if not set(proposal.source_event_ids).issubset(allowed_events):
            if not (context.allow_clock_only and proposal.source_event_ids == (f"clock:{context.simulation_tick}",)):
                return EmotionDecision(context.owner_id, False, "unverified source event")
        old_processed = set(context.previous_processed_sources)
        proposed_processed = set(proposal.processed_sources)
        if not old_processed.issubset(proposed_processed):
            return EmotionDecision(context.owner_id, False, "idempotency history was removed")
        if not (proposed_processed - old_processed).issubset(allowed_events):
            return EmotionDecision(context.owner_id, False, "unverified processed source")
        for appraisal in proposal.appraisals:
            if (
                appraisal.owner_id != proposal.owner_id
                or not set(appraisal.source_refs).issubset(set(proposal.source_refs))
                or not set(appraisal.source_event_ids).issubset(set(proposal.source_event_ids))
            ):
                return EmotionDecision(context.owner_id, False, "appraisal provenance mismatch")
        if not proposal.source_refs or not proposal.source_event_ids:
            return EmotionDecision(context.owner_id, False, "missing source references")
        result = EmotionDecision(context.owner_id, True, "owner, source and time validated", proposal, _EMOTION_VALIDATION_SEAL)
        return _issue_emotion_decision(result, proposal)


@dataclass
class EmotionUpdateApplier:
    """Apply only fresh validator-issued proposals to CognitionContainer."""

    cognition_container: Any
    write_fence: RuntimeWriteFence | None = None

    def __post_init__(self) -> None:
        if self.write_fence is not None:
            self.cognition_container.bind_write_fence(self.write_fence)

    def apply(
        self,
        proposal: EmotionProposal,
        decision: EmotionDecision,
        *,
        simulation_tick: int,
    ) -> Emotion:
        scope = (nullcontext() if self.write_fence is None
                 else self.write_fence.commit_scope())
        with scope:
            return self._apply(proposal, decision, simulation_tick=simulation_tick)

    def _apply(
        self, proposal: EmotionProposal, decision: EmotionDecision, *, simulation_tick: int
    ) -> Emotion:
        if self.write_fence is not None:
            self.write_fence.require_candidate_origin(original_proposal_permit(proposal))
        if not isinstance(decision, EmotionDecision) or not decision.authorizes(proposal):
            raise PermissionError("Emotion update requires matching validation")
        if simulation_tick != proposal.simulation_tick:
            raise ValueError("validated Emotion update is stale for the current simulation tick")
        current = self.cognition_container.get_emotion(proposal.emotion_id)
        if current is None or current.owner_id != proposal.owner_id:
            raise PermissionError("Emotion target is missing or belongs to another Agent")
        if current.snapshot_levels() != proposal.previous_levels or current.last_update_tick != proposal.previous_tick:
            raise ValueError("Emotion changed after proposal creation")
        already_processed = set(current.processed_sources)
        newly_processed = set(proposal.processed_sources)
        if not already_processed.issubset(newly_processed):
            raise ValueError("Emotion proposal would erase idempotency history")
        updated = Emotion(
            id=current.id,
            owner_id=current.owner_id,
            levels=dict(proposal.proposed_levels),
            state=current.state,
            intensity=current.intensity,
            metadata=current.metadata,
            last_update_tick=proposal.simulation_tick,
            processed_sources=proposal.processed_sources,
        )
        self.cognition_container.apply_emotion_update(
            updated, proposal, decision, simulation_tick=simulation_tick
        )
        return self.cognition_container.get_emotion(updated.id)


def _emotion_state(context: DecisionContext, owner_id: str) -> Emotion | None:
    value = context.emotion
    if value is None:
        return None
    if getattr(value, "owner_id", None) != owner_id:
        raise PermissionError("Emotion belongs to another Agent")
    # DecisionContext contains a frozen record, so reconstruct the canonical
    # mutable domain value without handing a Store reference to policies.
    levels = dict(getattr(value, "levels", {}) or {})
    return Emotion(
        id=value.id, owner_id=owner_id, state=value.state,
        intensity=value.intensity, metadata={}, levels=levels,
        last_update_tick=value.last_update_tick,
        processed_sources=tuple(getattr(value, "processed_sources", ())),
    )


def _profile_dimension(profile: Any, emotion: str) -> Any | None:
    return next((value for key, value in profile.dimensions if key == emotion), None)


@dataclass(frozen=True)
class MotivationAssessment:
    owner_id: str
    goal_scores: tuple[tuple[str, float], ...]
    conflict_pairs: tuple[tuple[str, str], ...]
    blocked_goal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("goal_scores", "conflict_pairs", "blocked_goal_ids"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be an immutable tuple")


@dataclass(frozen=True)
class DecisionModulation:
    owner_id: str
    attention_bias: tuple[tuple[str, float], ...] = ()
    risk_bias: float = 0.0
    impulse_bias: float = 0.0
    impulse_probability_ceiling: float = 0.0
    review_bias: float = 0.0
    goal_priority_adjustment: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.attention_bias, tuple) or not isinstance(self.goal_priority_adjustment, tuple):
            raise TypeError("DecisionModulation fields must be immutable tuples")
        for name in ("risk_bias", "impulse_bias", "impulse_probability_ceiling", "review_bias"):
            _bounded(getattr(self, name), -1.0 if name != "impulse_probability_ceiling" else 0.0, 1.0, name)
        for entries in (self.attention_bias, self.goal_priority_adjustment):
            for key, value in entries:
                if not key:
                    raise ValueError("modulation keys must be non-empty")
                _bounded(value, -1.0, 1.0, "modulation value")


@dataclass(frozen=True)
class DeterministicDecisionModulationPolicy:
    """Derive bounded modulation only from explicit individual parameters."""

    def assess(self, context: DecisionContext) -> tuple[MotivationAssessment, DecisionModulation]:
        owner = context.cognition_state.agent_id
        profile = context.personality.emotion_profile if context.personality is not None else None
        if profile is None or getattr(profile, "owner_id", None) != owner:
            assessment = MotivationAssessment(owner, (), (), ())
            return assessment, DecisionModulation(owner)
        goals = tuple(goal for goal in context.goals if getattr(goal, "status", None) == "active")
        weights = dict(profile.goal_drive_weights)
        levels = dict(getattr(context.emotion, "levels", {}) or {}) if context.emotion is not None else {}
        emotion_weights = tuple(profile.goal_emotion_weights)
        score_items = []
        for goal in goals:
            base = float(goal.priority)
            if not math.isfinite(base):
                raise ValueError("Goal priority must be finite for Motivation assessment")
            score = base * weights.get(goal.goal_id, 1.0) + sum(
                levels.get(emotion, 0.0) * weight
                for goal_id, emotion, weight in emotion_weights
                if goal_id == goal.goal_id
            )
            if not math.isfinite(score):
                raise ValueError("Motivation score must be finite")
            score_items.append((goal.goal_id, score))
        scores = tuple(sorted(score_items))
        score_map = dict(scores)
        conflicts = tuple(sorted((left, right) for left, right in profile.goal_conflicts if left in score_map and right in score_map))
        capabilities = getattr(context.self_model, "capabilities", {}) if context.self_model is not None else {}
        capability_requirements = dict(profile.goal_capability_requirements)
        blocked = tuple(sorted(
            goal.goal_id for goal in goals
            if goal.goal_id in capability_requirements
            and (not hasattr(capabilities, "get") or capabilities.get(capability_requirements[goal.goal_id]) is not True)
        ))
        impulse = profile.impulse_ceiling * sum(levels.get(name, 0.0) * weight for name, weight in profile.impulse_affinity)
        impulse = max(-profile.impulse_ceiling, min(profile.impulse_ceiling, impulse))
        attention_values: dict[str, float] = {}
        for emotion, focus, weight in profile.attention_affinity:
            attention_values[focus] = attention_values.get(focus, 0.0) + levels.get(emotion, 0.0) * weight * profile.attention_bias_limit
        attention = tuple(sorted((name, max(-1.0, min(1.0, value))) for name, value in attention_values.items()))
        risk = profile.risk_bias_limit * sum(levels.get(name, 0.0) * weight for name, weight in profile.risk_affinity)
        risk = max(-profile.risk_bias_limit, min(profile.risk_bias_limit, risk))
        adjustment = tuple(sorted((
            goal_id,
            max(-1.0, min(1.0, score - float(next(g.priority for g in goals if g.goal_id == goal_id)))),
        ) for goal_id, score in scores))
        assessment = MotivationAssessment(owner, scores, conflicts, blocked)
        modulation = DecisionModulation(
            owner_id=owner, attention_bias=attention,
            risk_bias=risk, impulse_bias=impulse,
            impulse_probability_ceiling=profile.impulse_ceiling,
            review_bias=max(-1.0, min(1.0, sum(levels.get(name, 0.0) * weight for name, weight in profile.review_affinity))),
            goal_priority_adjustment=adjustment,
        )
        return assessment, modulation
