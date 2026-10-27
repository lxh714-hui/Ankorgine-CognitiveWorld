"""Adapters into the existing Resolution and EventProcessor authority boundaries."""

from dataclasses import replace
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.world_state import WorldStateSlot
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.physical import PhysicalRelation, validate_physical_rule
from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision
from cognitive_world.event.handler import EventHandler
from .engine import (
    InteractionRequest,
    PhysicsContext,
    BooleanTransitionEngine,
    PhysicsOutcome,
)


def capture(world, history, request):
    target = world.get_entity(request.target_id)
    actor = world.get_entity(request.actor_id)
    if target is None or actor is None:
        return None
    rules = target.attributes.get("physical_rules", ())
    selected = [r for r in rules if r.operation == request.operation]
    if len(selected) != 1:
        return None
    rule = selected[0]
    location = world.get_location(request.actor_id)
    if location is None or location != world.get_location(request.target_id):
        return None
    ids = {request.target_id, rule.receiver_id, *(c.entity_id for c in rule.conditions)}
    ids.update(x for r in rule.relations for x in (r.source, r.target))
    entities = {i: world.get_entity(i) for i in ids | {request.actor_id}}
    if any(v is None for v in entities.values()):
        return None
    relation_map = world.relationships
    # Whole-world graph validation remains at content/world commit and restore.
    # Only the selected rule's dependencies belong in this engine's evidence.
    validate_physical_rule(rule, entities)
    state_ids = {rule.receiver_id, *(c.entity_id for c in rule.conditions)}
    states = tuple(entities[i].state["physical"] for i in sorted(state_ids))
    slots = [
        WorldStateSlot("entities", i, ("state", "physical", field))
        for i in sorted(state_ids)
        for field in ("version", "entity_id", "properties")
    ]
    slots.extend(
        [
            WorldStateSlot(
                "entities", request.target_id, ("attributes", "physical_rules")
            ),
            WorldStateSlot("entities", request.actor_id, ("physical_capabilities",)),
            WorldStateSlot("locations", request.actor_id),
            WorldStateSlot("locations", request.target_id),
        ]
    )
    for r in rule.relations:
        actual = relation_map.get((r.source, r.target))
        paths = (
            [(name,) for name in ("version", "source", "target", "kinds")]
            if type(actual) is PhysicalRelation
            else [()]
        )
        slots.extend(
            WorldStateSlot("relationships", (r.source, r.target), path)
            for path in paths
        )
    reads = tuple(
        world.read_state_slot(s, event_history=history).to_record()
        for s in dict.fromkeys(slots)
    )
    relations = tuple(
        r
        for r in relation_map.values()
        if type(r) is PhysicalRelation and r.source in ids and r.target in ids
    )
    if any(
        not world.verify_state_slot_record(r, event_history=history)
        or (r["present"] and r["origin_kind"] not in ("event", "initialization"))
        for r in reads
    ):
        raise PermissionError("physical state lacks authoritative slot provenance")
    return (
        PhysicsContext(states, relations, actor.physical_capabilities or (), rule),
        reads,
    )


class StateTransitionResolutionEngine(ResolutionEngine):
    def __init__(self, world_state, event_history, physics_engine=None):
        self.world_state = world_state
        self.event_history = event_history
        self.physics_engine = physics_engine or BooleanTransitionEngine()
        self.simulation_time = None

    def _adjudicate(self, attempt):
        if len(attempt.target_refs) != 1 or self.simulation_time is None:
            return None
        address = InteractionReference.parse(attempt.target_refs[0])
        if address.namespace != "object":
            return None
        operation = attempt.parameters.get("physical_operation")
        if type(operation) is not str or not operation or len(operation) > 160:
            return None
        request = InteractionRequest(attempt.agent_id, address.identifier, operation)
        captured = capture(self.world_state, self.event_history, request)
        if captured is None:
            return None
        context, reads = captured
        outcome = self.physics_engine.evaluate(request, context)
        if type(outcome) is not PhysicsOutcome or outcome.status == "unsupported":
            return None
        expected = BooleanTransitionEngine().evaluate(request, context)
        if outcome != expected:
            raise PermissionError(
                "engine output violates the installed transition contract"
            )
        if outcome.status != "changed":
            return ResolutionDecision(
                False,
                "physical preconditions not met",
                metadata={
                    "simulation_tick": self.simulation_time.tick,
                    # Reuse the existing pre-commit read guard. These are read
                    # bindings, not effects, private result facts or B2 proofs.
                    # v1 needs at most 119 reads (17 states, 16 relations and
                    # four entry slots), within the existing 4 x 32 limits.
                    "physical_effect_provenance": [
                        {"state_slot_reads": reads[start : start + 32]}
                        for start in range(0, len(reads), 32)
                    ],
                },
            )
        effect = {
            "effect_type": "physical_state_transition_v1",
            "actor_id": request.actor_id,
            "target_id": request.target_id,
            "operation": operation,
            "rule_id": context.rule.rule_id,
            "tick": self.simulation_time.tick,
            "reads": reads,
            "delta": outcome.delta,
        }
        return ResolutionDecision(
            True,
            "physical state changed",
            metadata={"simulation_tick": self.simulation_time.tick},
            world_effects=(effect,),
        )


class PhysicalTransitionHandler(EventHandler):
    def handle_with_world_state(self, event, world_state):
        from cognitive_world.event.environment import _validate_resolution_summary

        if not event.has_trusted_source("resolution"):
            raise PermissionError("Resolution source required")
        _validate_resolution_summary(event, effect_present=True)
        if len(event.changes) != 2:
            raise ValueError("one physical effect required")
        effect = event.changes[1]
        if type(effect) is not dict or set(effect) != {
            "effect_type",
            "actor_id",
            "target_id",
            "operation",
            "rule_id",
            "tick",
            "reads",
            "delta",
        }:
            raise ValueError("closed physical effect required")
        if (
            effect["effect_type"] != "physical_state_transition_v1"
            or effect["tick"] != event.simulation_tick
        ):
            raise PermissionError("physical effect tick/type mismatch")
        request = InteractionRequest(
            effect["actor_id"], effect["target_id"], effect["operation"]
        )
        # EventFactory's issued result binds these effects to the exact Attempt;
        # capture rechecks current capabilities, reach, rule and state evidence.
        processor = self.processor
        captured = capture(world_state, processor.event_history, request)
        if captured is None:
            raise PermissionError("physical context no longer available")
        context, reads = captured
        if reads != effect["reads"] or context.rule.rule_id != effect["rule_id"]:
            raise PermissionError("stale physical read evidence")
        expected = BooleanTransitionEngine().evaluate(request, context)
        if expected.status != "changed" or expected.delta != effect["delta"]:
            raise PermissionError("physical delta is not justified")
        delta = expected.delta
        entity = world_state.get_entity(delta.entity_id)
        state = dict(entity.state)
        state["physical"] = delta.replacement
        entity = replace(entity, state=state)
        return WorldUpdate("entities", "update", {entity.id: entity})

    def __init__(self, processor):
        self.processor = processor
