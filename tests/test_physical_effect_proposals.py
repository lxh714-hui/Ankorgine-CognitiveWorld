"""Production-bound physical effects remain proposals until EventProcessor applies them."""

from dataclasses import replace

import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.passage import PassageState
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState, WorldStateSlot
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution import (
    ActionInterpreter,
    ActionResolutionFlow,
    AssessmentStatus,
    CausalAssessment,
    MethodBasedResolutionEngine,
    PhysicalEffectProposal,
)
from cognitive_world.resolution.causal import CausalAssessmentPolicy
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.decision.action_proposal import ActionProposal


class _DoorStateUpdateHandler(EventHandler):
    def handle(self, event):
        raise AssertionError("WorldState-aware handler expected")

    def handle_with_world_state(self, event, world_state):
        return WorldUpdate("environment", "update", {"door-x": event.changes[0]["state"]})


def _door_case(*, target="object:door-x", method="push the door"):
    world = WorldState()
    world.load_environment_data(
        "door-x", DoorState("door-x", "room-x", False, False, True)
    )
    world.load_entity(Entity(
        "actor-x", "character", sensory_capabilities=("sight",),
        physical_capabilities=("manual_manipulation",),
    ))
    world.load_location("actor-x", "room-x")
    attempt = ActionInterpreter().interpret(
        ActionProposal("proposal-x", "actor-x", "open", [target], {"method": method}),
        actor_id="actor-x",
    )
    return world, attempt


def test_real_door_proposal_is_bound_to_attempt_sources_and_tick_then_committed_by_processor():
    world, attempt = _door_case()
    clock = SimulationClock(11)
    engine = MethodBasedResolutionEngine(world_state=world, simulation_time=clock.capture())

    result = engine.resolve(attempt)

    assert result.confirmed and result.success
    assert world.environment["door-x"].is_open is False
    provenance = result.metadata["physical_effect_provenance"]
    assert len(provenance) == 1
    binding = provenance[0]
    assert binding["attempt_id"] == attempt.attempt_id
    assert binding["attempt_fingerprint"] == attempt.content_fingerprint()
    assert binding["target_ref"] == "object:door-x"
    assert binding["simulation_tick"] == 11
    assert "world_state:environment:door-x" in binding["source_refs"]
    assert binding["verified_conditions"]
    assert binding["unknown_conditions"] == ()
    assert binding["state_slot_reads"]

    from cognitive_world.event.factory import EventFactory

    event = EventFactory().create_from_resolution(result)
    registry = AgentRegistry()
    registry.register(RuntimeAgent("actor-x"))
    store = ObservationStore()
    processor = EventProcessor(
        world_state=world, event_history=EventHistory(), simulation_clock=clock,
        agent_registry=registry, observation_store=store,
    )
    processor.dispatch_with_evidence(event)

    assert world.environment["door-x"].is_open is True
    observations = store.get_by_observer("actor-x")
    assert observations
    assert observations[0].source_event_id == event.id


def test_door_effect_slot_read_cites_prior_changing_event_and_commit_updates_latest_source():
    world, attempt = _door_case()
    world.load_environment_data(
        "door-x", DoorState("door-x", "room-x", False, False, False)
    )
    history = EventHistory()
    clock = SimulationClock(3)
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock)
    processor.register_handler("door-state-update", _DoorStateUpdateHandler())
    prior = SystemEventFactory().create(
        event_id="door-handrail-updated", event_type="door-state-update", timestamp="t2",
        changes=[{"state": DoorState("door-x", "room-x", False, False, True)}],
    )
    processor.process(prior, world)

    flow = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world), world_state=world,
        event_history=history,
    )
    result, event = flow.execute_with_result(attempt, simulation_tick=clock.capture())
    assert result.confirmed and event is not None
    reads = result.metadata["physical_effect_provenance"][0]["state_slot_reads"]
    operable = next(row for row in reads if row["slot"] == {
        "collection": "environment", "record_id": "door-x", "path": ("hand_operable",)
    })
    assert operable["origin_kind"] == "event"
    assert operable["source_event_id"] == prior.id
    assert history.get_event(operable["source_event_id"]) is not None

    processor.process_with_evidence(event, world)
    current = world.read_state_slot(
        WorldStateSlot("environment", "door-x", ("is_open",)), event_history=history
    )
    assert current.value is True
    assert current.source_event_id == event.id


def test_passage_effect_uses_the_same_bound_proposal_path():
    world = WorldState()
    world.load_environment_data("passage-x", PassageState("passage-x", "a", "b", True))
    world.load_entity(Entity("actor-x", "character", physical_capabilities=("locomotion",)))
    world.load_location("actor-x", "a")
    attempt = ActionInterpreter().interpret(
        ActionProposal("proposal-move", "actor-x", "move", ["object:passage-x"], {"method": "walk through"}),
        actor_id="actor-x",
    )
    clock = SimulationClock(2)
    flow = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world), world_state=world)

    result, event = flow.execute_with_result(attempt, simulation_tick=clock.capture())

    assert result.confirmed and result.success and event is not None
    assert world.locations["actor-x"] == "a"
    assert event.metadata["physical_effect_provenance"][0]["target_ref"] == "object:passage-x"
    processor = EventProcessor(world_state=world, event_history=EventHistory(), simulation_clock=clock)
    processor.process_with_evidence(event, world)
    assert world.locations["actor-x"] == "b"


def test_proposal_cannot_be_reused_for_changed_attempt_or_tick():
    world, first_attempt = _door_case()
    clock = SimulationClock(4)
    engine = MethodBasedResolutionEngine(world_state=world, simulation_time=clock.capture())
    valid_result = engine.resolve(first_attempt)
    binding = valid_result.metadata["physical_effect_provenance"][0]
    aggregate = engine._interaction_state_aggregator.aggregate(
        first_attempt, world, clock.capture()
    ).physical
    proposal = PhysicalEffectProposal(
        attempt_id=binding["attempt_id"],
        attempt_fingerprint=binding["attempt_fingerprint"],
        target_ref=binding["target_ref"],
        simulation_tick=binding["simulation_tick"],
        source_refs=binding["source_refs"],
        verified_conditions=binding["verified_conditions"],
        unknown_conditions=binding["unknown_conditions"],
        state_slot_reads=aggregate.slot_reads,
        effect_payload=valid_result.world_effects[0],
    )
    assert proposal.is_bound_to(first_attempt, aggregate)

    other_attempt = ActionInterpreter().interpret(
        ActionProposal("proposal-y", "actor-x", "open", ["object:door-x"], {"method": "pull the door"}),
        actor_id="actor-x",
    )
    assert not proposal.is_bound_to(other_attempt, aggregate)
    other_target = ActionInterpreter().interpret(
        ActionProposal("proposal-z", "actor-x", "open", ["object:other-door"], {"method": "push the door"}),
        actor_id="actor-x",
    )
    assert not proposal.is_bound_to(other_target, aggregate)
    later_context = replace(aggregate, simulation_tick=5)
    assert not proposal.is_bound_to(first_attempt, later_context)


def test_unbound_or_raw_effect_mapping_cannot_be_confirmed_by_method_engine():
    world, attempt = _door_case()
    raw_effect = {
        "effect_type": "door_state_changed",
        "door_id": "door-x",
        "expected": world.environment["door-x"],
        "state": DoorState("door-x", "room-x", True, False, True),
        "actor_id": "actor-x",
        "actor_location": "room-x",
        "key_id": None,
    }

    class RawEffectPolicy(CausalAssessmentPolicy):
        def assess(self, attempt, context):
            return CausalAssessment(
                AssessmentStatus.FEASIBLE, "unbound", world_effects=(raw_effect,)
            )

    result = MethodBasedResolutionEngine(
        world_state=world, assessment_policy=RawEffectPolicy(),
        simulation_time=SimulationClock().capture(),
    ).resolve(attempt)

    assert result.confirmed is False
    assert result.outcome == "unresolved"
    assert world.environment["door-x"].is_open is False


def test_bound_proposal_with_unsupported_effect_is_not_signed_or_committed():
    world, attempt = _door_case()

    class UnsupportedEffectPolicy(CausalAssessmentPolicy):
        def assess(self, attempt, context):
            proposal = PhysicalEffectProposal.from_context(
                attempt, context,
                {"effect_type": "npc_reaction", "actor_id": attempt.agent_id},
                verified_conditions=("claimed by provider",),
            )
            return CausalAssessment(
                AssessmentStatus.FEASIBLE, "unsupported", effect_proposals=(proposal,)
            )

    result = MethodBasedResolutionEngine(
        world_state=world, assessment_policy=UnsupportedEffectPolicy(),
        simulation_time=SimulationClock().capture(),
    ).resolve(attempt)

    assert result.confirmed is False
    assert world.environment["door-x"].is_open is False


def test_effect_proposal_rejects_mutable_untyped_payload_values():
    with pytest.raises(TypeError, match="unsupported mutable"):
        PhysicalEffectProposal(
            attempt_id="attempt", attempt_fingerprint="a" * 64,
            target_ref="object:x", simulation_tick=0,
            source_refs=("world_state:environment:x",),
            verified_conditions=("condition",), effect_payload={"data": {"fake": True}},
        )
