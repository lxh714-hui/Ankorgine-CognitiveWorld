import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory
from cognitive_world.observation import ObservationStore
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent


def _world(*, unknown_position=False, unknown_senses=False):
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    world.load_environment_data("room-b", {"light_on": False})
    if not unknown_position:
        world.load_entity(
            Entity(
                "agent-near",
                "agent",
                sensory_capabilities=None if unknown_senses else ("sight",),
            )
        )
        world.load_entity(Entity("agent-far", "agent", sensory_capabilities=("sight",)))
        # Location data is a WorldState collection and the sole position authority.
        world.load_location("agent-near", "room-a")
        world.load_location("agent-far", "room-b")
    return world


def _run_runtime(world, *, registry, event, observation_store):
    scheduler = EventScheduler()
    scheduler.schedule(ScheduledEvent(execute_time=1, event=event))
    context = RuntimeContext(
        clock=SimulationClock(),
        world_state=world,
        event_history=EventHistory(),
        scheduler=scheduler,
        agent_registry=registry,
        observation_store=observation_store,
    )
    processor = EventProcessor()
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    runtime = SimulationRuntime(context=context, event_processor=processor)
    runtime.step()
    return context, processor


def _registry():
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-near"))
    registry.register(RuntimeAgent("agent-far"))
    return registry


def _light_event():
    return SystemEventFactory().create(
        event_id="light-event-1",
        event_type="room_light_changed",
        timestamp="not-the-simulation-clock",
        changes=[
            {"room_id": "room-a", "from_light_on": False, "to_light_on": True}
        ],
        metadata={"private_debug": "must-not-enter-observation"},
    )


def test_real_runtime_event_authorizes_only_qualified_agent_and_reaches_l1():
    store = ObservationStore()
    context, processor = _run_runtime(
        _world(), registry=_registry(), event=_light_event(), observation_store=store
    )

    near = store.get_by_observer("agent-near")
    far = store.get_by_observer("agent-far")
    assert len(near) == 1
    assert far == ()
    assert near[0].has_trusted_provenance()
    assert near[0].source_event_id == "light-event-1"
    assert near[0].content.predicate == "room_light_on"
    assert near[0].content.value is True
    assert "private_debug" not in repr(near[0].content)

    percept = CognitiveRuntime().perception_processor.process(
        near[0], observer_id="agent-near"
    )
    assert percept.observer_id == "agent-near"
    cognitive_state = CognitiveRuntime().process("agent-near", near)
    assert cognitive_state.percept_ids == [percept.percept_id]

    evidence = context.event_history.get_processing_evidence("light-event-1")
    assert evidence is not None
    assert evidence.event_time_context.simulation_time == 1
    assert evidence.event_time_context.event_timestamp == "not-the-simulation-clock"
    assert evidence.event_time_context.state_phase.value == "after_world_update"
    assert evidence.event_time_context.observer_state_phase.value == "before_world_update"
    assert evidence.observable_facts[0].location_id == "room-a"

    # Runtime initialization is sealed. Later state changes must use a
    # trusted EventProcessor path; the initialization loader stays closed.
    with pytest.raises(PermissionError, match="initialization is closed"):
        context.world_state.load_environment_data("room-a", {"light_on": False})
    later_event = SystemEventFactory().create(
        event_id="light-event-2",
        event_type="room_light_changed",
        timestamp="later descriptive time",
        changes=[
            {"room_id": "room-a", "from_light_on": True, "to_light_on": False}
        ],
    )
    context.clock.tick()
    later_evidence = processor.process_with_evidence(later_event, context.world_state)
    assert later_evidence.event_time_context.simulation_time == 2
    assert later_evidence.event_time_context.environment_conditions == (
        ("room-a:light_on", False),
    )
    # A later trusted world transition cannot rewrite prior event-time evidence
    # or the already-issued Observation snapshot.
    assert evidence.event_time_context.environment_conditions == (("room-a:light_on", True),)
    assert store.get_by_observer("agent-near")[0].content.value is True


def test_unknown_observer_position_or_senses_fail_closed():
    store = ObservationStore()
    registry = _registry()
    world = _world(unknown_senses=True)
    _run_runtime(world, registry=registry, event=_light_event(), observation_store=store)
    assert store.get_by_observer("agent-near") == ()

    store = ObservationStore()
    world = _world(unknown_position=True)
    _run_runtime(world, registry=registry, event=_light_event(), observation_store=store)
    assert store.all() == ()


def test_manual_or_untrusted_records_cannot_enter_the_production_path():
    from cognitive_world.core.event import Event
    from cognitive_world.observation import (
        EventProcessingEvidence,
        EventStatePhase,
        EventTimeObservationContext,
        ObservableFact,
        Observation,
    )
    from cognitive_world.observation.generator import ObservationAuthorizationError, ObservationGenerator

    event = Event(
        id="forged", type="room_light_changed", timestamp="now",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
    )
    processor = EventProcessor()
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    try:
        processor.process_with_evidence(event, _world())
    except ValueError:
        pass
    else:
        raise AssertionError("manual Event unexpectedly processed")

    manual = Observation("manual", "agent-near", "forged", {"claim": "seen"})
    assert not manual.has_trusted_provenance()
    try:
        ObservationGenerator().generate(event, "agent-near")
    except ObservationAuthorizationError:
        pass
    else:
        raise AssertionError("legacy generator unexpectedly authorized a manual event")

    trusted_event = _light_event()
    hand_built_fact = ObservableFact(
        "manual-fact",
        trusted_event.id,
        "environment_state",
        "room_light_on",
        True,
        "room-a",
        "room-a",
    )
    hand_built_evidence = EventProcessingEvidence(
        trusted_event.id,
        (hand_built_fact,),
        EventTimeObservationContext(
            source_event_id=trusted_event.id,
            event_timestamp=trusted_event.timestamp,
            state_phase=EventStatePhase.AFTER_WORLD_UPDATE,
            simulation_time=1,
            fact_location_id="room-a",
            observer_positions=(("agent-near", "room-a", ("sight",)),),
            environment_conditions=(("room-a:light_on", True),),
        ),
    )
    assert ObservationGenerator().generate_authorized(
        trusted_event, hand_built_evidence, observer_id="agent-near"
    ) == ()
