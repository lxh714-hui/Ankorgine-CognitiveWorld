"""Bounded take operation: no provider-owned canonical state."""

from dataclasses import dataclass
from copy import deepcopy
import json
from cognitive_world.core.persistence import sha256_hex
from cognitive_world.core.physical import (
    PhysicalRelation,
    PossessionTransition,
    PhysicalStateSet,
    identity,
)
from cognitive_world.core.world_state import WorldStateSlot
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.update import WorldUpdate
from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision
from cognitive_world.observation.observable import ObservableFactDraft
from cognitive_world.decision.attempt import Attempt


@dataclass(frozen=True)
class TakePolicy:
    version: int
    eligibility_property: str
    capability: str

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported take policy")
        identity(self.eligibility_property)
        identity(self.capability)

    def record(self):
        return dict(
            version=self.version,
            eligibility_property=self.eligibility_property,
            capability=self.capability,
        )


def policy_fingerprint(policy):
    """Content identity, not Python identity or an installation epoch."""
    policy.__post_init__()
    payload = {"contract": "TakePolicy/v1", **policy.record()}
    return sha256_hex(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


@dataclass(frozen=True)
class TakeAdjudicationContext:
    """v1 values in the existing metadata envelope, never a codec capability."""

    attempt_snapshot: tuple
    policy: TakePolicy
    reads: tuple
    relations: tuple
    expected_no_holder: bool
    tick: int

    def __post_init__(self):
        snapshot = self.attempt_snapshot
        if (
            type(snapshot) is not tuple
            or len(snapshot) != 9
            or type(self.policy) is not TakePolicy
            or type(self.tick) is not int
            or self.tick < 0
            or type(self.reads) is not tuple
            or not 1 <= len(self.reads) <= 128
            or any(type(r) is not dict for r in self.reads)
            or type(self.relations) is not tuple
            or len(self.relations) > 16
            or type(self.expected_no_holder) is not bool
        ):
            raise ValueError("invalid take adjudication context")
        self.policy.__post_init__()
        Attempt.fingerprint_snapshot(snapshot)
        if (
            snapshot[3] != "take"
            or type(snapshot[4]) not in {tuple, list}
            or len(snapshot[4]) != 1
            or type(snapshot[5]) is not dict
            or snapshot[5].get("item_operation") != "take"
        ):
            raise PermissionError("take context requires its exact action")
        target = InteractionReference.parse(snapshot[4][0])
        if target.namespace != "object":
            raise PermissionError("take context requires object target")
        identity(snapshot[0])
        identity(snapshot[1])
        pairs = []
        for relation in self.relations:
            if type(relation) is not PhysicalRelation:
                raise TypeError("typed take context relation required")
            relation.__post_init__()
            if target.identifier not in (relation.source, relation.target) or set(
                relation.kinds
            ) & {"part_of", "attached_to"}:
                raise PermissionError("unsupported take context structure")
            pairs.append((relation.source, relation.target))
        if pairs != sorted(set(pairs)):
            raise ValueError("noncanonical take context relations")
        held = any(
            r.source == target.identifier and "held_by" in r.kinds
            for r in self.relations
        )
        if self.expected_no_holder != (not held):
            raise PermissionError("inconsistent take holder condition")

    def record(self):
        self.__post_init__()
        return dict(
            version=1,
            attempt_snapshot=deepcopy(self.attempt_snapshot),
            policy=self.policy.record(),
            policy_fingerprint=policy_fingerprint(self.policy),
            reads=deepcopy(self.reads),
            relations=self.relations,
            expected_no_holder=self.expected_no_holder,
            tick=self.tick,
        )

    @classmethod
    def from_record(cls, record):
        keys = {
            "version",
            "attempt_snapshot",
            "policy",
            "policy_fingerprint",
            "reads",
            "relations",
            "expected_no_holder",
            "tick",
        }
        if (
            type(record) is not dict
            or set(record) != keys
            or type(record["version"]) is not int
            or record["version"] != 1
            or type(record["policy"]) is not dict
        ):
            raise ValueError("unsupported take adjudication context")
        policy = TakePolicy(**record["policy"])
        if record["policy_fingerprint"] != policy_fingerprint(policy):
            raise PermissionError("take policy fingerprint mismatch")
        return cls(
            record["attempt_snapshot"],
            policy,
            record["reads"],
            record["relations"],
            record["expected_no_holder"],
            record["tick"],
        )


@dataclass(frozen=True)
class TakeRequest:
    actor_id: str
    item_id: str

    def __post_init__(self):
        identity(self.actor_id)
        identity(self.item_id)


@dataclass(frozen=True)
class TakeView:
    actor_id: str
    item_id: str
    actor_location: str | None
    item_location: str | None
    owner: str | None
    eligible: bool
    capable: bool
    held: bool
    prior_relation: PhysicalRelation | None
    related_relations: tuple[PhysicalRelation, ...]


@dataclass(frozen=True)
class TakeOutcome:
    status: str
    transition: PossessionTransition | None

    def __post_init__(self):
        if (
            self.status not in {"changed", "ineligible"}
            or (self.status == "changed")
            != (type(self.transition) is PossessionTransition)
            or self.status == "ineligible"
            and self.transition is not None
        ):
            raise ValueError("invalid take outcome")
        if self.transition is not None:
            self.transition.__post_init__()


class TakeModel:
    def evaluate(self, request, view, policy):
        if (
            type(request) is not TakeRequest
            or type(view) is not TakeView
            or type(policy) is not TakePolicy
            or (view.actor_id, view.item_id) != (request.actor_id, request.item_id)
        ):
            raise TypeError("typed take inputs required")
        if (
            not view.eligible
            or not view.capable
            or view.held
            or view.actor_location is None
            or view.item_location != view.actor_location
        ):
            return TakeOutcome("ineligible", None)
        relation = PhysicalRelation(
            1,
            request.item_id,
            request.actor_id,
            (() if view.prior_relation is None else view.prior_relation.kinds)
            + ("held_by",),
        )
        return TakeOutcome(
            "changed",
            PossessionTransition(
                1,
                request.item_id,
                request.actor_id,
                view.item_location,
                view.owner,
                view.prior_relation,
                relation,
            ),
        )


def capture(world, history, registry, request, policy):
    if type(policy) is not TakePolicy:
        raise TypeError("installed take policy required")
    policy.__post_init__()
    actor, item = world.get_entity(request.actor_id), world.get_entity(request.item_id)
    if (
        actor is None
        or item is None
        or registry is None
        or registry.get(request.actor_id) is None
        or actor.type not in {"character", "agent"}
        or item.type in {"character", "agent", "location"}
    ):
        raise PermissionError("unsupported take actor/item")
    state = item.state.get("physical")
    value = (
        state.get(policy.eligibility_property)
        if type(state) is PhysicalStateSet
        else None
    )
    if value is None or value.definition.value_type != "boolean":
        return None
    relations = world.relationships
    related = [
        (k, r)
        for k, r in relations.items()
        if request.item_id in k and type(r) is PhysicalRelation
    ]
    if len(related) > 16:
        return None
    if any(set(r.kinds) & {"part_of", "attached_to"} for _, r in related):
        return None
    prior = relations.get((request.item_id, request.actor_id))
    if prior is not None and type(prior) is not PhysicalRelation:
        return None
    held = any(r.source == request.item_id and "held_by" in r.kinds for _, r in related)
    actor_location, item_location = world.get_location(
        request.actor_id
    ), world.get_location(request.item_id)
    if not held and (
        world.get_entity(item_location) is None
        or world.get_entity(item_location).type != "location"
    ):
        return None
    slots = [
        WorldStateSlot("locations", x) for x in (request.actor_id, request.item_id)
    ]
    slots += [
        WorldStateSlot("entities", request.actor_id, (field,))
        for field in ("id", "type", "physical_capabilities")
    ]
    slots += [
        WorldStateSlot("entities", request.item_id, (field,))
        for field in ("id", "type", "owner_id")
    ]
    slots += [
        WorldStateSlot("entities", request.item_id, ("state", "physical", field))
        for field in ("version", "entity_id", "properties")
    ]
    if actor_location is not None:
        slots.append(WorldStateSlot("entities", actor_location, ("type",)))
    pairs = {key for key, _ in related} | {(request.item_id, request.actor_id)}
    for key in pairs:
        relation = relations.get(key)
        paths = (
            [(f,) for f in ("version", "source", "target", "kinds")]
            if type(relation) is PhysicalRelation
            else [()]
        )
        slots += [WorldStateSlot("relationships", key, path) for path in paths]
    reads = tuple(
        world.read_state_slot(s, event_history=history).to_record()
        for s in sorted(slots, key=repr)
    )
    if any(
        not world.verify_state_slot_record(r, event_history=history)
        or r["present"]
        and r["origin_kind"] not in {"initialization", "event"}
        for r in reads
    ):
        raise PermissionError("take input lacks authoritative provenance")
    view = TakeView(
        request.actor_id,
        request.item_id,
        actor_location,
        item_location,
        item.owner_id,
        value.value is True,
        actor.physical_capabilities is not None
        and policy.capability in actor.physical_capabilities,
        held,
        prior,
        tuple(r for _, r in sorted(related)),
    )
    return view, reads


def is_registered_take_operation(action_type, operation):
    """The existing explicit take operation identity, never narrative text."""
    return action_type == "take" and operation == "take"


class ItemTakeResolutionEngine(ResolutionEngine):
    def __init__(self, world, history, registry, policy, model=None):
        self.world, self.history, self.registry, self.policy = (
            world,
            history,
            registry,
            policy,
        )
        self.model = model or TakeModel()
        self.simulation_time = None

    def resolve(self, attempt):
        # This is a new-operation boundary: persisted Events never enter resolve.
        # Validate the *returned* adjudication, including faulty implementations,
        # before a confirmed result can escape to EventFactory.
        result = super().resolve(attempt)
        if not result.confirmed:
            return result
        try:
            context = TakeAdjudicationContext.from_record(
                result.metadata.get("take_adjudication_context")
            )
        except (TypeError, ValueError) as exc:
            raise PermissionError(
                "new take result requires a supported adjudication context"
            ) from exc
        if (
            context.attempt_snapshot != attempt._resolution_snapshot()
            or context.policy != self.policy
            or self.simulation_time is None
            or context.tick != self.simulation_time.tick
        ):
            raise PermissionError("new take context does not bind its adjudication")
        return result

    def _adjudicate(self, attempt):
        if (
            self.simulation_time is None
            or len(attempt.target_refs) != 1
            or not is_registered_take_operation(
                attempt.action_type, attempt.parameters.get("item_operation")
            )
        ):
            return None
        target = InteractionReference.parse(attempt.target_refs[0])
        if target.namespace != "object":
            raise ValueError("object target required")
        request = TakeRequest(attempt.agent_id, target.identifier)
        captured = capture(
            self.world, self.history, self.registry, request, self.policy
        )
        if captured is None:
            return None
        view, reads = captured
        outcome = self.model.evaluate(request, view, self.policy)
        expected = TakeModel().evaluate(request, view, self.policy)
        if type(outcome) is not TakeOutcome or outcome != expected:
            raise PermissionError("unjustified take candidate")
        context = TakeAdjudicationContext(
            attempt._resolution_snapshot(),
            self.policy,
            reads,
            view.related_relations,
            not view.held,
            self.simulation_time.tick,
        ).record()
        if outcome.status != "changed":
            return ResolutionDecision(
                False,
                "take preconditions not met",
                metadata={
                    "simulation_tick": self.simulation_time.tick,
                    "take_adjudication_context": context,
                    "physical_effect_provenance": [
                        {"state_slot_reads": reads[i : i + 32]}
                        for i in range(0, len(reads), 32)
                    ],
                },
            )
        effect = dict(
            effect_type="item_take_v1",
            transition=outcome.transition,
            policy=self.policy.record(),
            expected_no_holder=True,
            reads=reads,
            attempt_snapshot=attempt._resolution_snapshot(),
            tick=self.simulation_time.tick,
        )
        return ResolutionDecision(
            True,
            "item taken into physical custody",
            metadata={
                "simulation_tick": self.simulation_time.tick,
                "take_adjudication_context": context,
            },
            world_effects=(effect,),
        )


def validate_event(event):
    if (
        not event.has_trusted_source("resolution")
        or len(event.changes) != 2
        or event.changes[0]
        != {"success": True, "outcome": "item taken into physical custody"}
    ):
        raise PermissionError("committed take source/summary required")
    effect = event.changes[1]
    if type(effect) is not dict or set(effect) != {
        "effect_type",
        "transition",
        "policy",
        "expected_no_holder",
        "reads",
        "attempt_snapshot",
        "tick",
    }:
        raise ValueError("closed take effect required")
    if (
        effect["effect_type"] != "item_take_v1"
        or effect["expected_no_holder"] is not True
        or type(effect["tick"]) is not int
        or effect["tick"] != event.simulation_tick
        or type(effect["transition"]) is not PossessionTransition
    ):
        raise PermissionError("take effect binding mismatch")
    t = effect["transition"]
    t.__post_init__()
    policy = TakePolicy(**effect["policy"])
    snapshot = effect["attempt_snapshot"]
    if (
        Attempt.fingerprint_snapshot(snapshot)
        != event.metadata.get("attempt_fingerprint")
        or snapshot[0] != event.cause
        or snapshot[0] != event.metadata.get("attempt_id")
        or snapshot[1] != t.actor_id
        or snapshot[3] != "take"
        or len(snapshot[4]) != 1
        or InteractionReference.parse(snapshot[4][0]).identifier != t.item_id
        or InteractionReference.parse(snapshot[4][0]).namespace != "object"
        or snapshot[5].get("item_operation") != "take"
    ):
        raise PermissionError("take does not match original Attempt")
    return effect, t, policy


def validate_adjudication_event(event):
    """Historical validation only: no current world, policy or re-adjudication."""
    context = TakeAdjudicationContext.from_record(
        event.metadata["take_adjudication_context"]
    )
    snapshot = context.attempt_snapshot
    if (
        not event.has_trusted_source("resolution")
        or event.type != "resolution"
        or context.tick != event.simulation_tick
        or snapshot[0] != event.cause
        or snapshot[0] != event.metadata.get("attempt_id")
        or Attempt.fingerprint_snapshot(snapshot)
        != event.metadata.get("attempt_fingerprint")
    ):
        raise PermissionError("take adjudication Attempt binding mismatch")
    if len(event.changes) == 1:
        if event.changes[0] != {
            "success": False,
            "outcome": "take preconditions not met",
        }:
            raise PermissionError("invalid no-effect take result")
        entries = event.metadata.get("physical_effect_provenance")
        if (
            type(entries) not in {list, tuple}
            or not 1 <= len(entries) <= 4
            or any(
                type(e) is not dict
                or set(e) != {"state_slot_reads"}
                or type(e["state_slot_reads"]) is not tuple
                or not 1 <= len(e["state_slot_reads"]) <= 32
                for e in entries
            )
            or tuple(r for e in entries for r in e["state_slot_reads"]) != context.reads
        ):
            raise PermissionError("take failure read binding mismatch")
    else:
        effect, transition, policy = validate_event(event)
        if (
            context.policy != policy
            or context.reads != effect["reads"]
            or snapshot != effect["attempt_snapshot"]
            or not context.expected_no_holder
        ):
            raise PermissionError("take success/context mismatch")
    return context


def validate_current_adjudication(event, processor, world):
    """Recheck exact dependencies pre-apply; never call a provider or retry."""
    context = validate_adjudication_event(event)
    if context.policy != processor.take_policy:
        raise PermissionError("take policy changed or is not installed")
    snapshot = context.attempt_snapshot
    target = InteractionReference.parse(snapshot[4][0])
    captured = capture(
        world,
        processor.event_history,
        processor.agent_registry,
        TakeRequest(snapshot[1], target.identifier),
        context.policy,
    )
    if captured is None:
        raise PermissionError("original take context is no longer supported")
    view, reads = captured
    if (
        reads != context.reads
        or view.related_relations != context.relations
        or (not view.held) != context.expected_no_holder
    ):
        raise PermissionError("stale take adjudication dependencies")


class ItemTakeHandler:
    def __init__(self, processor):
        self.processor = processor

    def handle_with_world_state(self, event, world):
        # Called only for a new apply. Recorded replay returns evidence before
        # invoking handlers; historical validation/Observation use validate_event.
        if "take_adjudication_context" not in event.metadata:
            raise PermissionError("new take effect requires its adjudication context")
        effect, t, policy = validate_event(event)
        if policy != self.processor.take_policy:
            raise PermissionError("take policy is not installed")
        captured = capture(
            world,
            self.processor.event_history,
            self.processor.agent_registry,
            TakeRequest(t.actor_id, t.item_id),
            policy,
        )
        if captured is None:
            raise PermissionError("take context unavailable")
        view, reads = captured
        if (
            reads != effect["reads"]
            or TakeModel()
            .evaluate(TakeRequest(t.actor_id, t.item_id), view, policy)
            .transition
            != t
        ):
            raise PermissionError("stale take candidate")
        world.prepare_possession_transition(t)
        return WorldUpdate("item_possession", "take", t)

    def observable_facts_with_world_state(self, event, update, world):
        _, t, _ = validate_event(event)
        return (
            ObservableFactDraft(
                "action_result", "item_taken", True, t.item_id, t.expected_location
            ),
        )


def allows_result(event, evidence, observer_id, fact=None, event_history=None):
    from cognitive_world.event.history import EventHistory, EventProcessingStatus

    if (
        not isinstance(event_history, EventHistory)
        or event_history.requires_recovery()
        or not evidence.has_trusted_source(event)
    ):
        return False
    try:
        effect, t, policy = validate_event(event)
    except (TypeError, ValueError, PermissionError, KeyError, IndexError):
        return False
    committed = event_history.get_event(event.id)
    if (
        committed is None
        or committed._source_snapshot() != event._source_snapshot()
        or event_history.get_processing_evidence(event.id) != evidence
        or observer_id != t.actor_id
    ):
        return False
    status = event_history.get_processing_status(event.id)
    if status not in {
        EventProcessingStatus.COMPLETE,
        EventProcessingStatus.OBSERVATIONS_PENDING,
        EventProcessingStatus.RECORDED,
    } and not (
        status is None and event_history.get_persistence_record(event.id) is not None
    ):
        return False
    context = evidence.event_time_context
    if (
        context.simulation_time != event.simulation_tick
        or context.fact_location_id != t.expected_location
        or [(p) for o, p, _ in context.observer_positions if o == observer_id]
        != [t.expected_location]
    ):
        return False
    return any(
        f.has_trusted_source(event)
        and f.fact_type == "action_result"
        and f.predicate == "item_taken"
        and f.value is True
        and f.subject_ref == t.item_id
        and f.location_id == t.expected_location
        and (fact is None or f == fact)
        for f in evidence.observable_facts
    )
