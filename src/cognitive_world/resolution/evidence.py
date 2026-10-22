"""Bounded actor-visible evidence queries for causal advice, never world authority."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json

from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.decision.attempt import Attempt
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.observation.generator import VisibilityPolicy
from cognitive_world.observation.observable import ObservableFact
from cognitive_world.runtime.context import PlayerMode, RuntimeContext

MAX_QUERY_OUTPUT = 2048
MAX_QUERIES = 2
MAX_EVIDENCE = 4


def _json_object(raw: str) -> dict[str, object]:
    if not isinstance(raw, str) or len(raw) > MAX_QUERY_OUTPUT:
        raise ValueError("causal evidence model output exceeds bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate causal evidence field")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ValueError("causal evidence output must be an object")
    return value


@dataclass(frozen=True)
class StateQueryProposal:
    reference: str
    predicate: str | None = None

    def __post_init__(self) -> None:
        InteractionReference.parse(self.reference)
        if self.predicate is not None and (not isinstance(self.predicate, str) or not self.predicate or len(self.predicate) > 160):
            raise ValueError("query predicate must be bounded text")

    @classmethod
    def from_model(cls, raw: str) -> "StateQueryProposal | None":
        obj = _json_object(raw)
        if obj == {"done": True}:
            return None
        if set(obj) not in ({"reference"}, {"reference", "predicate"}):
            raise PermissionError("query model returned unsupported fields")
        return cls(obj["reference"], obj.get("predicate"))


@dataclass(frozen=True)
class QueryIntent:
    actor_id: str
    intent: str
    method: str
    target_refs: tuple[str, ...]

    @classmethod
    def from_attempt(cls, attempt: Attempt) -> "QueryIntent":
        params = attempt.parameters
        method = params.get("method", "")
        return cls(attempt.agent_id, attempt.action_type, method if isinstance(method, str) else "", tuple(attempt.target_refs))


@dataclass(frozen=True)
class ObservedStateEvidence:
    fact_id: str
    observation_id: str
    source_event_id: str
    observer_id: str
    reference: str
    fact_type: str
    predicate: str
    value: object
    event_tick: int


@dataclass(frozen=True)
class CausalEvidenceAnalysis:
    cited_fact_ids: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    conflicting_fact_ids: tuple[str, ...]
    assessment: str

    @classmethod
    def from_model(cls, raw: str, evidence: tuple[ObservedStateEvidence, ...]) -> "CausalEvidenceAnalysis":
        obj = _json_object(raw)
        if set(obj) != {"cited_fact_ids", "missing_conditions", "conflicting_fact_ids", "assessment"}:
            raise PermissionError("causal analysis returned unsupported fields")
        known = {item.fact_id for item in evidence}
        for key in ("cited_fact_ids", "missing_conditions", "conflicting_fact_ids"):
            values = obj[key]
            if type(values) is not list or len(values) > MAX_EVIDENCE or any(type(x) is not str or not x or len(x) > 160 for x in values):
                raise ValueError("causal analysis list exceeds bounds")
        if any(x not in known for x in (*obj["cited_fact_ids"], *obj["conflicting_fact_ids"])):
            raise PermissionError("causal analysis cites an unavailable fact")
        assessment = obj["assessment"]
        if type(assessment) is not str or len(assessment) > 480:
            raise ValueError("causal analysis assessment exceeds bounds")
        return cls(tuple(obj["cited_fact_ids"]), tuple(obj["missing_conditions"]),
                   tuple(obj["conflicting_fact_ids"]), assessment)


class AuthorizedStateQuery:
    """Read only unchanged, event-time, owner-authorized Observation facts."""

    def __init__(self, context: RuntimeContext, *, cognition_context: CognitionContext | None = None) -> None:
        if not isinstance(context, RuntimeContext) or context.agent_registry is None or context.observation_store is None:
            raise PermissionError("query requires a host-bound runtime with observer registry and store")
        session = context.player_session
        if cognition_context is not None:
            observer = cognition_context.owner_id
            if cognition_context.observation_store is not context.observation_store:
                raise PermissionError("cognition ObservationStore does not match Runtime")
        elif session is not None and session.mode is PlayerMode.ROLEPLAY:
            observer = session.controlled_agent_id
        else:
            raise PermissionError("query has no host-bound observer")
        if not observer or context.agent_registry.get(observer) is None:
            raise PermissionError("query observer is not registered")
        self.context = context
        self.observer_id = observer

    def query(self, attempt: Attempt, proposal: StateQueryProposal, *, simulation_tick: int) -> tuple[ObservedStateEvidence, ...]:
        if not isinstance(attempt, Attempt) or attempt.agent_id != self.observer_id or not isinstance(proposal, StateQueryProposal):
            raise PermissionError("query actor does not match the host-bound observer")
        if self.context.clock.current_time != simulation_tick:
            raise PermissionError("query simulation context is stale")
        requested = InteractionReference.parse(proposal.reference)
        authorized_refs = tuple(InteractionReference.parse(ref) for ref in attempt.target_refs)
        if requested not in authorized_refs and not any(
            requested.namespace == ref.namespace and requested.identifier == ref.identifier for ref in authorized_refs
        ):
            return ()
        if requested.namespace != "object":
            return ()  # Subject-target knowledge needs its own governed read policy.
        observed: list[ObservedStateEvidence] = []
        history = self.context.event_history
        for item in self.context.observation_store.get_by_observer(self.observer_id):
            if not item.has_trusted_provenance() or not isinstance(item.content, ObservableFact):
                continue
            event = history.get_event(item.source_event_id)
            evidence = history.get_processing_evidence(item.source_event_id)
            if event is None or evidence is None or not event.has_trusted_source() or not evidence.has_trusted_source(event):
                continue
            fact = item.content
            if (item.observer_id != self.observer_id or not fact.has_trusted_source(event)
                    or not any(candidate._snapshot() == fact._snapshot() for candidate in evidence.observable_facts)
                    or not VisibilityPolicy().allows(event, evidence, self.observer_id)
                    or fact.subject_ref != requested.identifier
                    or proposal.predicate is not None and fact.predicate != proposal.predicate):
                continue
            tick = evidence.event_time_context.simulation_time
            if tick is None or tick > simulation_tick:
                continue
            observed.append(ObservedStateEvidence(
                fact.fact_id, item.observation_id, event.id, self.observer_id,
                proposal.reference, fact.fact_type, fact.predicate, deepcopy(fact.value), tick,
            ))
            if len(observed) == MAX_EVIDENCE:
                break
        return tuple(observed)


class AuthorizedQuerySession:
    """Per-attempt read budget; no model or world write authority."""

    def __init__(self, service: AuthorizedStateQuery, attempt: Attempt, *, simulation_tick: int) -> None:
        if not isinstance(service, AuthorizedStateQuery) or not isinstance(attempt, Attempt):
            raise TypeError("query session requires an authorized service and Attempt")
        if attempt.agent_id != service.observer_id or service.context.clock.current_time != simulation_tick:
            raise PermissionError("query session actor or time mismatch")
        self._service = service
        self._attempt = attempt
        self._tick = simulation_tick
        self._seen: set[StateQueryProposal] = set()
        self._evidence: dict[str, ObservedStateEvidence] = {}

    @property
    def remaining_queries(self) -> int:
        return MAX_QUERIES - len(self._seen)

    @property
    def evidence(self) -> tuple[ObservedStateEvidence, ...]:
        return tuple(self._evidence.values())

    def query(self, proposal: StateQueryProposal) -> tuple[ObservedStateEvidence, ...]:
        if proposal in self._seen:
            return ()
        if self.remaining_queries == 0:
            raise PermissionError("causal evidence query budget exhausted")
        results = self._service.query(self._attempt, proposal, simulation_tick=self._tick)
        self._seen.add(proposal)
        for item in results:
            if len(self._evidence) >= MAX_EVIDENCE:
                break
            self._evidence.setdefault(item.fact_id, item)
        return tuple(item for item in results if item.fact_id in self._evidence)
