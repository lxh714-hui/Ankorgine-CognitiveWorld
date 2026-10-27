"""Transient, evidence-qualified contextual judgments; no persisted record types."""

from dataclasses import dataclass, field
from math import isfinite
from collections.abc import Mapping
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.decision.snapshot import freeze_value

_SEAL = object()


@dataclass(frozen=True)
class ContextualBeliefRule:
    version: int
    fact_type: str
    predicate: str
    value: bool
    adjustment: float
    max_age_ticks: int = 0

    def __post_init__(self):
        if (
            type(self.version) is not int
            or self.version != 1
            or type(self.fact_type) is not str
            or not 1 <= len(self.fact_type) <= 160
            or type(self.predicate) is not str
            or not 1 <= len(self.predicate) <= 160
            or type(self.value) is not bool
            or type(self.adjustment) not in (int, float)
            or not isfinite(self.adjustment)
            or not -1 <= self.adjustment <= 1
            or type(self.max_age_ticks) is not int
            or not 0 <= self.max_age_ticks <= 32
        ):
            raise ValueError("unsupported contextual Belief rule")


@dataclass(frozen=True)
class ContextualBeliefBinding:
    version: int
    belief_id: str
    owner_id: str
    target: str
    operation: str
    method: str
    location_id: str
    evidence_tick: int
    source_event_id: str
    fact_id: str
    observation_id: str
    fact_type: str
    predicate: str
    value: bool
    timeline_id: str | None
    scope: str
    adjustment: float
    belief_snapshot: object = field(repr=False)
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        if (
            type(self.version) is not int
            or self.version != 1
            or self.scope != "unchanged_history_frontier"
            or any(
                type(s) is not str or not s
                for s in (
                    self.belief_id,
                    self.owner_id,
                    self.target,
                    self.operation,
                    self.method,
                    self.location_id,
                    self.source_event_id,
                    self.fact_id,
                    self.observation_id,
                    self.fact_type,
                    self.predicate,
                )
            )
            or type(self.evidence_tick) is not int
            or self.evidence_tick < 0
            or type(self.value) is not bool
            or (
                self.timeline_id is not None
                and (type(self.timeline_id) is not str or not self.timeline_id)
            )
            or type(self.adjustment) not in (int, float)
            or not isfinite(self.adjustment)
            or not -1 <= self.adjustment <= 1
        ):
            raise ValueError("unsupported transient contextual binding")

    def matches_belief(self, belief):
        return (
            self._seal is _SEAL
            and self.version == 1
            and self.scope == "unchanged_history_frontier"
            and freeze_value(belief) == self.belief_snapshot
        )


def validate_rules(rules):
    if (
        type(rules) is not tuple
        or len(rules) > 8
        or any(type(r) is not ContextualBeliefRule for r in rules)
    ):
        raise ValueError("bounded typed contextual rules required")
    for rule in rules:
        rule.__post_init__()


def _target(reference):
    address = InteractionReference.parse(reference)
    return (address.namespace, address.identifier)


def derive_bindings(cognitive, owner, beliefs, observations, rules, tick):
    """Requalify exact history AND consumption, never trust receipt/metadata alone."""
    validate_rules(rules)
    if not rules or type(tick) is not int:
        return ()
    context = cognitive._history_context
    if context is None:
        return ()
    index, reason = context.evidence_index()
    if index is None:
        return ()
    history = context.history
    events = history.get_events()
    if not events:
        return ()
    head = events[-1].id
    from cognitive_world.event.attempt_source import verify_confirmed_failure_event

    result = []
    for belief in beliefs:
        if belief.owner_id != owner:
            continue
        matches = []
        for observation in observations:
            if (
                observation.source_event_id != head
                or observation.observer_id != owner
                or not observation.has_trusted_provenance()
                or context.classify(observation, index)[0] != "eligible"
                or not cognitive.has_consumed_observation(
                    owner, observation, source_event_id=observation.source_event_id
                )
            ):
                continue
            event, evidence = index[head]
            if not verify_confirmed_failure_event(event):
                continue
            source = event.metadata["confirmed_attempt_failure"]
            fact = observation.content
            if (
                source["owner_id"] != owner
                or len(source["target_refs"]) != 1
                or fact.location_id is None
                or type(fact.value) is not bool
            ):
                continue
            content = dict(
                fact_type=fact.fact_type,
                predicate=fact.predicate,
                value=fact.value,
                subject_ref=fact.subject_ref,
                location_id=fact.location_id,
            )
            # This is the already supported CognitiveReview evidence projection,
            # not an inferred meaning for arbitrary text or a new durable value.
            if (
                not isinstance(belief.content, Mapping)
                or set(belief.content) != set(content)
                or any(
                    type(belief.content[k]) is not type(v) or belief.content[k] != v
                    for k, v in content.items()
                )
                or tuple(belief.source_refs) != (observation.observation_id,)
                or tuple(belief.metadata.get("source_event_ids", ())) != (event.id,)
                or tuple(belief.metadata.get("source_observation_ids", ()))
                != (observation.observation_id,)
            ):
                continue
            for rule in rules:
                if (
                    (fact.fact_type, fact.predicate, fact.value)
                    != (rule.fact_type, rule.predicate, rule.value)
                    or type(event.simulation_tick) is not int
                    or not 0 <= tick - event.simulation_tick <= rule.max_age_ticks
                ):
                    continue
                binding = ContextualBeliefBinding(
                    1,
                    belief.belief_id,
                    owner,
                    source["target_refs"][0],
                    source["action_type"],
                    source["method"],
                    fact.location_id,
                    event.simulation_tick,
                    event.id,
                    fact.fact_id,
                    observation.observation_id,
                    fact.fact_type,
                    fact.predicate,
                    fact.value,
                    history.timeline_id,
                    "unchanged_history_frontier",
                    float(rule.adjustment),
                    freeze_value(belief),
                )
                object.__setattr__(binding, "_seal", _SEAL)
                matches.append(binding)
        # Conflicting/duplicate rules or evidence never accumulate authority.
        if len(matches) == 1:
            result.append(matches[0])
    return tuple(result)


def adjust_evaluations(situation, candidates, evaluations):
    from cognitive_world.decision.autonomous import CandidateEvaluation

    output = []
    for candidate, evaluation in zip(candidates, evaluations, strict=True):
        matches = []
        for belief in situation.beliefs:
            binding = belief.contextual_binding
            if binding is None:
                continue
            try:
                same_target = candidate.target is not None and _target(
                    candidate.target
                ) == _target(binding.target)
            except (TypeError, ValueError):
                same_target = False
            if (
                same_target
                and candidate.owner_id == binding.owner_id
                and candidate.intent == binding.operation
                and candidate.method == binding.method
                and not candidate.tools
            ):
                matches.append((binding, belief.confidence))
        if len(matches) != 1:
            output.append(evaluation)
            continue
        binding, confidence = matches[0]
        change = binding.adjustment * confidence
        output.append(
            CandidateEvaluation(
                evaluation.candidate_id,
                evaluation.score + change,
                (*evaluation.factors, ("typed_contextual_belief", change)),
                evaluation.uncertainty,
            )
        )
    return tuple(output)


def model_belief_view(belief):
    """Explicit owner-local provider projection; never serialize seals/snapshots."""
    view = dict(
        belief_id=belief.belief_id,
        claim=belief.claim,
        confidence=belief.confidence,
        source_refs=belief.source_refs,
    )
    binding = belief.contextual_binding
    if binding is not None:
        view["contextual_judgment"] = {
            name: getattr(binding, name)
            for name in (
                "version",
                "target",
                "operation",
                "method",
                "location_id",
                "evidence_tick",
                "source_event_id",
                "fact_id",
                "fact_type",
                "predicate",
                "value",
                "scope",
            )
        }
    return view
