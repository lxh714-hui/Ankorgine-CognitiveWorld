"""Scheduled opportunities exercised through the real Runtime authority path."""

import pytest

from cognitive_world.core.persistence import HmacPersistenceTrust, PersistedValueCodec
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import (
    EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory,
)
from cognitive_world.event.history import EventProcessingStatus
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent


@pytest.fixture
def scheduled_light():
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    history = EventHistory(timeline_id="scheduled-opportunity-tests")
    clock = SimulationClock()
    trust = HmacPersistenceTrust(b"scheduled-opportunity-test-key-0000")
    processor = EventProcessor(
        world_state=world, event_history=history, simulation_clock=clock,
        persistence_trust=trust,
    )
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    scheduler = EventScheduler()
    runtime = SimulationRuntime(
        RuntimeContext(clock, world, history, scheduler=scheduler),
        event_processor=processor,
    )
    event = SystemEventFactory().create(
        event_id="scheduled-light", event_type="room_light_changed",
        timestamp="scheduled-description",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
    )
    return runtime, event, trust


def assert_unprocessed(runtime, event):
    history = runtime.context.event_history
    assert history.get_event(event.id) is None
    assert history.get_events() == ()
    assert history.get_processing_evidence(event.id) is None
    assert history.get_persistence_record(event.id) is None
    assert runtime.context.world_state.environment["room-a"] == {"light_on": False}


def test_enqueueing_is_not_formal_commitment(scheduled_light):
    runtime, event, _ = scheduled_light
    runtime.context.scheduler.schedule(ScheduledEvent(1, event))

    assert_unprocessed(runtime, event)
    assert runtime.context.clock.current_time == 0
    assert runtime.last_scheduled_event_results == ()


def test_future_opportunity_is_unprocessed_until_due(scheduled_light):
    runtime, event, _ = scheduled_light
    runtime.context.scheduler.schedule(ScheduledEvent(2, event))

    runtime.step()

    assert runtime.context.clock.current_time == 1
    assert runtime.last_scheduled_event_results == ()
    assert_unprocessed(runtime, event)
    # Advancing the real Runtime to the due tick demonstrates retention without
    # reading or draining the scheduler's private queue.
    runtime.step()
    assert runtime.context.event_history.get_events() == (event,)
    assert runtime.context.world_state.environment["room-a"] == {"light_on": True}


def test_zero_budget_does_not_commit_due_opportunity(scheduled_light):
    runtime, event, _ = scheduled_light
    runtime.maximum_events_this_step = 0
    runtime.context.scheduler.schedule(ScheduledEvent(1, event))

    runtime.step()

    record, = runtime.last_scheduled_event_results
    assert record.event_id == event.id
    assert record.committed is False
    assert record.failure_type == "event_budget_exhausted"
    assert runtime.context.clock.current_time == 1
    assert_unprocessed(runtime, event)


def test_budget_skipped_opportunity_is_not_automatically_retried(scheduled_light):
    runtime, event, _ = scheduled_light
    runtime.maximum_events_this_step = 0
    runtime.context.scheduler.schedule(ScheduledEvent(1, event))
    runtime.step()
    skipped, = runtime.last_scheduled_event_results
    assert skipped.event_id == event.id and skipped.committed is False
    assert skipped.failure_type == "event_budget_exhausted"
    assert_unprocessed(runtime, event)

    # Restore capacity without submitting a second scheduling operation.
    runtime.maximum_events_this_step = 1
    runtime.step()

    assert runtime.context.clock.current_time == 2
    assert runtime.last_scheduled_event_results == ()
    assert_unprocessed(runtime, event)


def test_due_opportunity_commits_only_through_real_event_processor(scheduled_light):
    runtime, event, trust = scheduled_light
    runtime.maximum_events_this_step = 1
    runtime.context.scheduler.schedule(ScheduledEvent(1, event))
    assert_unprocessed(runtime, event)

    runtime.step()

    record, = runtime.last_scheduled_event_results
    assert record.event_id == event.id and record.committed is True
    assert record.failure_type is None
    history = runtime.context.event_history
    assert history.get_events() == (event,)
    assert history.get_processing_status(event.id) is EventProcessingStatus.RECORDED
    evidence = history.get_processing_evidence(event.id)
    assert evidence is not None and evidence.has_trusted_source(event)
    assert evidence.event_time_context.simulation_time == 1
    assert runtime.context.world_state.environment["room-a"] == {"light_on": True}
    assert history.get_persistence_record(event.id) is not None
    history.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)
