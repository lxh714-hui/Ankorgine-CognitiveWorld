"""Attempt-scoped interaction state views preserve authority and uncertainty."""

import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution import (
    ActionInterpreter,
    ActionResolutionFlow,
    InteractionStateAggregator,
    MethodBasedResolutionEngine,
)
from cognitive_world.resolution.evidence import AuthorizedStateQuery
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding, RuntimeContext


def _attempt(actor_id="actor-a", targets=("object:door-a",)):
    return ActionInterpreter().interpret(
        ActionProposal("proposal-aggregation", actor_id, "interact", list(targets),
                       {"method": "push the closed door"}),
        actor_id=actor_id,
    )


def _world():
    world = WorldState()
    world.load_environment_data("door-a", DoorState("door-a", "room-a", False, False, True))
    world.load_environment_data("door-b", DoorState("door-b", "room-b", False, False, True))
    world.load_entity(Entity("actor-a", "character", physical_capabilities=("manual_manipulation",), sensory_capabilities=("sight",)))
    world.load_entity(Entity("actor-b", "character", physical_capabilities=("manual_manipulation",), sensory_capabilities=("sight",)))
    world.load_location("actor-a", "room-a")
    world.load_location("actor-b", "room-b")
    return world


def _runtime(world):
    registry = AgentRegistry()
    registry.register(RuntimeAgent("actor-a", "character:a"))
    registry.register(RuntimeAgent("actor-b", "character:b"))
    clock, history, observations = SimulationClock(3), EventHistory(), ObservationStore()
    context = RuntimeContext(
        clock, world, history, agent_registry=registry, observation_store=observations,
        player_session=PlayerSessionBinding("session", "player", PlayerMode.ROLEPLAY, "actor-a"),
    )
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock,
                               agent_registry=registry, observation_store=observations)
    for door_id in ("door-a", "door-b"):
        event = SystemEventFactory().create(
            event_id=f"snapshot:{door_id}", event_type="environment_state_observed",
            timestamp="", simulation_tick=clock.current_time,
            changes=[{"environment_id": door_id}],
        )
        processor.dispatch_with_evidence(event)
    return context, processor


def test_physical_view_is_attempt_target_time_bound_and_unknown_stays_unknown():
    world = _world()
    clock = SimulationClock(7)
    attempt = _attempt()
    aggregate = InteractionStateAggregator().aggregate(attempt, world, clock.capture())

    assert aggregate.attempt_id == attempt.attempt_id
    assert aggregate.attempt_fingerprint == attempt.content_fingerprint()
    assert aggregate.actor_id == "actor-a"
    assert aggregate.simulation_tick == 7
    assert aggregate.physical.target_ref == "object:door-a"
    assert aggregate.physical.target == world.environment["door-a"]
    door_open_read = next(
        item for item in aggregate.physical.slot_reads
        if item.slot.collection == "environment"
        and item.slot.record_id == "door-a"
        and item.slot.path == ("is_open",)
    )
    assert door_open_read.value is False
    assert door_open_read.origin_kind == "initialization"
    assert door_open_read.source_event_id is None
    assert "world_state:environment:door-a" in aggregate.physical.source_refs
    assert aggregate.cognitive is None
    assert world.environment["door-a"].is_open is False

    missing = InteractionStateAggregator().aggregate(
        _attempt(targets=("object:missing",)), world, clock.capture()
    )
    assert missing.physical.target is None
    assert "target_state" in missing.physical.unknown_fields

    agent_target = InteractionStateAggregator().aggregate(
        _attempt(targets=("agent:actor-b",)), world, clock.capture()
    )
    assert agent_target.physical.target is None
    assert "agent_target_state" in agent_target.physical.unknown_fields


def test_aggregation_uses_targeted_worldstate_reads_not_full_world_snapshots():
    class TargetedReadWorldState(WorldState):
        @property
        def entities(self):
            raise AssertionError("aggregation must not copy the full entity map")

        @property
        def locations(self):
            raise AssertionError("aggregation must not copy the full location map")

        @property
        def environment(self):
            raise AssertionError("aggregation must not copy the full environment map")

    world = TargetedReadWorldState()
    world.load_environment_data("door-a", DoorState("door-a", "room-a", False, False, True))
    world.load_entity(Entity("actor-a", "character", physical_capabilities=("manual_manipulation",)))
    world.load_entity(Entity("key-a", "tool", owner_id="actor-a"))
    world.load_entity(Entity("unrelated", "tool", owner_id="actor-b"))
    world.load_location("actor-a", "room-a")

    aggregate = InteractionStateAggregator().aggregate(
        _attempt(), world, SimulationClock(4).capture()
    )
    assert aggregate.physical.held_tool_ids == ("key-a",)
    assert aggregate.physical.target.door_id == "door-a"


def test_cognitive_view_only_contains_owner_authorized_observation_evidence():
    world = _world()
    runtime, processor = _runtime(world)
    attempt = _attempt()
    service = AuthorizedStateQuery(runtime)
    aggregate = InteractionStateAggregator().aggregate(
        attempt, world, runtime.clock.capture(), query_service=service
    )

    assert aggregate.cognitive is not None
    assert aggregate.cognitive.owner_id == "actor-a"
    assert aggregate.cognitive.evidence
    assert all(item.observer_id == "actor-a" for item in aggregate.cognitive.evidence)
    assert aggregate.cognitive.source_refs == ("snapshot:door-a",)
    assert all(item.reference == "object:door-a" for item in aggregate.cognitive.evidence)
    assert world.environment["door-a"].is_open is False
    assert len(runtime.event_history.get_events()) == 2

    with pytest.raises(PermissionError):
        InteractionStateAggregator().aggregate(
            _attempt(actor_id="actor-b", targets=("object:door-a",)),
            world, runtime.clock.capture(), query_service=service,
        )


def test_unknown_hidden_or_unobserved_target_is_not_filled_from_world_truth():
    world = _world()
    runtime, _ = _runtime(world)
    aggregate = InteractionStateAggregator().aggregate(
        _attempt(targets=("object:door-b", "object:missing")), world,
        runtime.clock.capture(), query_service=AuthorizedStateQuery(runtime),
    )
    assert aggregate.physical.target == world.environment["door-b"]
    # Door B is in WorldState for physical Resolution, but actor A has no
    # authorized Observation of it, so the cognitive view remains unknown.
    assert aggregate.cognitive is not None
    assert aggregate.cognitive.evidence == ()
    assert set(aggregate.cognitive.unknown_refs) == {"object:door-b", "object:missing"}


def test_cognitive_aggregation_respects_existing_query_budget_for_many_targets():
    world = _world()
    runtime, _ = _runtime(world)

    class CountingQuery(AuthorizedStateQuery):
        calls = 0

        def query(self, *args, **kwargs):
            self.calls += 1
            return super().query(*args, **kwargs)

    service = CountingQuery(runtime)
    aggregate = InteractionStateAggregator().aggregate(
        _attempt(targets=("object:door-a", "object:door-b", "object:missing")),
        world, runtime.clock.capture(), query_service=service,
    )
    assert service.calls == 2
    assert aggregate.cognitive is not None
    assert aggregate.cognitive.evidence
    assert "object:missing" in aggregate.cognitive.unknown_refs


def test_resolution_uses_fresh_aggregation_after_trusted_world_change_without_writes():
    world = _world()
    runtime, processor = _runtime(world)
    aggregator = InteractionStateAggregator()
    attempt = _attempt()
    before = aggregator.aggregate(attempt, world, runtime.clock.capture()).physical
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world), world_state=world,
        event_history=runtime.event_history,
    ).execute(attempt, simulation_tick=runtime.clock.capture())
    processor.dispatch_with_evidence(event)
    after = aggregator.aggregate(
        attempt, world, runtime.clock.capture(), event_history=runtime.event_history
    ).physical

    assert before.target.is_open is False
    assert after.target.is_open is True
    assert after.attempt_fingerprint == before.attempt_fingerprint
    assert after.simulation_tick == runtime.clock.current_time
    assert world.environment["door-a"].is_open is True
    door_open_read = next(
        item for item in after.slot_reads
        if item.slot.collection == "environment"
        and item.slot.record_id == "door-a"
        and item.slot.path == ("is_open",)
    )
    assert door_open_read.value is True
    assert door_open_read.source_event_id == event.id
    assert runtime.event_history.get_event(door_open_read.source_event_id) is not None
    assert len(runtime.event_history.get_events()) == 3
    assert runtime.observation_store.get_by_observer("actor-a")
    assert not hasattr(after, "world_state")


@pytest.mark.parametrize("placement,expected", [
    ("absent", ("key-a",)), ("held", ("key-a",)),
    ("elsewhere", ()), ("explicit_none", ("key-a",)),
])
def test_targeted_tool_location_preserves_legacy_missing_and_explicit_values(placement, expected):
    class NoFullLocations(WorldState):
        @property
        def locations(self):
            raise AssertionError("must use bounded location reads")
    world = NoFullLocations()
    world.load_entity(Entity("actor-a", "character", physical_capabilities=("manual_manipulation",)))
    world.load_entity(Entity("key-a", "tool", owner_id="actor-a"))
    world.load_environment_data("door-a", DoorState("door-a", "room-a", False, False, True))
    world.load_location("actor-a", "room-a")
    if placement == "explicit_none":
        with pytest.raises(ValueError):
            world.load_location("key-a", None)
    elif placement != "absent":
        world.load_location("key-a", {"held": "actor-a", "elsewhere": "room-a"}[placement])
    aggregate = InteractionStateAggregator().aggregate(_attempt(), world, SimulationClock().capture())
    assert aggregate.physical.held_tool_ids == expected
