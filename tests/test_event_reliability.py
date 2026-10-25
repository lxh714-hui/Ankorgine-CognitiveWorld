import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.core.entity import Entity
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import (
    EventHistory,
    EventProcessor,
    RoomLightChangedHandler,
    SystemEventFactory,
)
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventProcessingStatus
from cognitive_world.observation import ObservationStore
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent
from cognitive_world.runtime.write_fence import RuntimeWriteFence


def _event(event_id="light-event"):
    return SystemEventFactory().create(
        event_id=event_id,
        event_type="room_light_changed",
        timestamp="event-time",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
    )


def _light_world():
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    world.load_entity(Entity("near", "agent", sensory_capabilities=("sight",)))
    world.load_location("near", "room-a")
    return world


def _light_processor(world, history=None, observation_store=None):
    registry = AgentRegistry()
    registry.register(RuntimeAgent("near"))
    processor = EventProcessor(
        event_history=history or EventHistory(),
        world_state=world,
        simulation_clock=SimulationClock(current_time=7),
        agent_registry=registry,
        observation_store=observation_store,
    )
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    return processor


def test_duplicate_event_returns_recorded_evidence_without_reapplying_world_update():
    world = _light_world()
    history = EventHistory()
    processor = _light_processor(world, history)
    event = _event()

    first = processor.process_with_evidence(event, world)
    second = processor.process_with_evidence(event, world)

    assert second == first
    assert world.environment["room-a"] == {"light_on": True}
    assert history.get_events() == (event,)
    assert history.get_processing_status(event.id) is EventProcessingStatus.RECORDED


def test_history_failure_after_world_update_is_explicit_and_replay_is_blocked():
    class FailingHistory(EventHistory):
        def append(self, event, *, processing_evidence=None):
            raise OSError("history unavailable")

    world = _light_world()
    history = FailingHistory()
    processor = _light_processor(world, history)
    event = _event()

    with pytest.raises(OSError, match="history unavailable"):
        processor.process_with_evidence(event, world)

    assert world.environment["room-a"] == {"light_on": True}
    assert (
        history.get_processing_status(event.id)
        is EventProcessingStatus.RECOVERY_REQUIRED
    )
    with pytest.raises(RuntimeError, match="explicit recovery is required"):
        processor.process_with_evidence(event, world)
    assert world.environment["room-a"] == {"light_on": True}


class _FailFirstSignature:
    """Fail only the first Event attestation, after WorldState has been written."""

    def __init__(self):
        self.calls = 0

    def sign(self, purpose, payload):
        self.calls += 1
        if self.calls == 1:
            raise OSError("event attestation unavailable")
        return b"test-only-signature"

    def verify(self, purpose, payload, signature):
        return signature == b"test-only-signature"


def _runtime_with_signature_failure():
    world = _light_world()
    history = EventHistory(timeline_id="faulted-timeline")
    fence = RuntimeWriteFence("faulted-session")
    clock = SimulationClock()
    schedule = EventScheduler()
    first = _event("first")
    later = SystemEventFactory().create(
        event_id="later", event_type="room_light_changed", timestamp="later",
        changes=[{"room_id": "room-a", "from_light_on": True, "to_light_on": False}],
    )
    schedule.schedule(ScheduledEvent(1, first))
    schedule.schedule(ScheduledEvent(2, later))
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        persistence_trust=_FailFirstSignature(), write_fence=fence,
    )
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    runtime = SimulationRuntime(
        RuntimeContext(clock, world, history, scheduler=schedule),
        event_processor=processor, write_fence=fence,
    )
    return runtime, processor, first, later


def test_signature_failure_latches_runtime_and_final_event_boundary():
    runtime, processor, first, later = _runtime_with_signature_failure()
    world, history = runtime.context.world_state, runtime.context.event_history
    old_generation = runtime.write_fence.restore_generation

    runtime.start()
    assert runtime.step() == ()
    assert world.environment["room-a"] == {"light_on": True}
    assert history.get_processing_status(first.id) is EventProcessingStatus.RECOVERY_REQUIRED
    assert history.get_events() == ()
    assert history.requires_recovery()
    assert runtime.write_fence.recovery_required and runtime.write_fence.frozen
    assert runtime.write_fence.restore_generation == old_generation + 1
    assert not runtime.running

    for action in (runtime.step, lambda: runtime.run(1), runtime.start,
                   runtime.unfreeze_writes):
        with pytest.raises((PermissionError, RuntimeError), match="recovery"):
            action()
    with pytest.raises(PermissionError, match="frozen"):
        processor.dispatch_with_evidence(later)
    # An independently constructed, unfenced Processor sharing this History
    # still cannot append a different Event or rewrite the WorldState.
    other = EventProcessor(event_history=history, world_state=world)
    other.register_handler("room_light_changed", RoomLightChangedHandler())
    with pytest.raises(RuntimeError, match="explicit recovery is required"):
        other.process_with_evidence(later, world)
    assert runtime.context.clock.current_time == 1
    assert history.get_processing_status(later.id) is None
    assert history.get_events() == ()
    assert world.environment["room-a"] == {"light_on": True}


def test_pre_world_rejection_does_not_latch_runtime_or_block_later_event():
    runtime, processor, _, later = _runtime_with_signature_failure()
    # A missing handler is rejected before WorldState.apply_event.
    runtime.context.scheduler._scheduled_events.clear()
    bad = SystemEventFactory().create(
        event_id="unhandled", event_type="unhandled", timestamp="t",
    )
    good = _event("valid-after-rejection")
    runtime.context.scheduler.schedule(ScheduledEvent(1, bad))
    runtime.context.scheduler.schedule(ScheduledEvent(2, good))
    # The first valid Event must have a working signer in this test.
    processor.persistence_trust = None
    processor.persistence_codec = None

    runtime.start()
    assert runtime.step() == ()
    assert not runtime.context.event_history.requires_recovery()
    assert runtime.context.event_history.get_processing_status(bad.id) is None
    assert not runtime.write_fence.recovery_required
    assert not runtime.write_fence.frozen and runtime.running
    assert runtime.context.world_state.environment["room-a"] == {"light_on": False}
    runtime.step()
    assert runtime.context.world_state.environment["room-a"] == {"light_on": True}
    assert [event.id for event in runtime.context.event_history.get_events()] == [good.id]


def test_observation_save_failure_retries_delivery_without_reapplying_event():
    class FailOnceStore(ObservationStore):
        failed = False

        def add(self, observation):
            if not self.failed:
                self.failed = True
                raise OSError("observation store unavailable")
            super().add(observation)

    world = _light_world()
    history = EventHistory()
    store = FailOnceStore()
    processor = _light_processor(world, history, store)
    event = _event()

    with pytest.raises(RuntimeError, match="retry dispatch to resume"):
        processor.dispatch_with_evidence(event)
    assert (
        history.get_processing_status(event.id)
        is EventProcessingStatus.OBSERVATIONS_PENDING
    )
    assert world.environment["room-a"] == {"light_on": True}

    processor.dispatch_with_evidence(event)
    assert history.get_processing_status(event.id) is EventProcessingStatus.COMPLETE
    assert len(store.get_by_observer("near")) == 1
    assert world.environment["room-a"] == {"light_on": True}


class _FactsHandler(EventHandler):
    def __init__(self):
        self.calls = 0

    def handle(self, event):
        self.calls += 1
        return WorldUpdate("facts", "update", {"applied": True})


def test_event_without_history_uses_processor_history_for_duplicate_guard():
    world = WorldState()
    handler = _FactsHandler()
    processor = EventProcessor(event_history=None)
    processor.register_handler("custom", handler)
    event = SystemEventFactory().create(
        event_id="custom-1", event_type="custom", timestamp="t"
    )

    processor.process(event, world)
    processor.process(event, world)

    assert handler.calls == 1
    assert world.facts == {"applied": True}


def test_repeat_observation_consumption_is_idempotent_and_scoped_by_agent_and_event():
    world, history, store, agents = WorldState(), EventHistory(), ObservationStore(), AgentRegistry()
    world.load_environment_data("room-a", {"light_on": False})
    for owner in ("agent-a", "agent-b"):
        world.load_entity(Entity(owner, "agent", sensory_capabilities=("sight",)))
        world.load_location(owner, "room-a")
        agents.register(RuntimeAgent(owner))
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=SimulationClock(7), agent_registry=agents, observation_store=store)
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    processor.dispatch_with_evidence(_event("event-1"))
    processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id="light-off-between", event_type="room_light_changed", timestamp="event-time",
        changes=[{"room_id": "room-a", "from_light_on": True, "to_light_on": False}]))
    processor.dispatch_with_evidence(_event("event-2"))
    obs_one, = [o for o in store.get_by_observer("agent-a") if o.source_event_id == "event-1"]
    obs_two, = [o for o in store.get_by_observer("agent-a") if o.source_event_id == "event-2"]
    obs_one_other_agent, = [o for o in store.get_by_observer("agent-b") if o.source_event_id == "event-1"]
    assert obs_one.content.predicate == obs_two.content.predicate
    assert obs_one.content.value is obs_two.content.value is True
    runtime = CognitiveRuntime()
    runtime._bind_observation_history(history)

    first_ingestion = runtime.process("agent-a", [obs_one])
    repeated_ingestion = runtime.process("agent-a", [obs_one])
    second_event_ingestion = runtime.process("agent-a", [obs_two])
    runtime.process("agent-b", [obs_one_other_agent])

    assert first_ingestion.percept_ids == ["percept:" + obs_one.observation_id]
    assert repeated_ingestion.percept_ids == []
    assert second_event_ingestion.percept_ids == ["percept:" + obs_two.observation_id]
    assert runtime.working_memory_store.get("agent-a").percept_ids == [
        "percept:" + obs_one.observation_id,
        "percept:" + obs_two.observation_id,
    ]
    assert runtime.working_memory_store.get("agent-b").percept_ids == [
        "percept:" + obs_one_other_agent.observation_id
    ]
    assert len(history.get_events()) == 3
