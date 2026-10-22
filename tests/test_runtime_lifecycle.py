import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime import (
    EventScheduler,
    RuntimeContext,
    ScheduledEvent,
    SimulationClock,
    SimulationRuntime,
)


class RecordingProcessor:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, scheduled_event):
        self.dispatched.append(scheduled_event)
        return scheduled_event.event.id


def make_runtime(event_processor=None):
    clock = SimulationClock()
    world_state = WorldState()
    event_history = EventHistory()
    scheduler = EventScheduler()
    context = RuntimeContext(clock, world_state, event_history, scheduler)
    runtime = SimulationRuntime(context, event_processor=event_processor)
    return runtime, clock, world_state, event_history, scheduler


def test_runtime_starts_in_stopped_state():
    runtime, _, _, _, _ = make_runtime()

    assert runtime.running is False


def test_start_and_stop_change_only_lifecycle_state():
    runtime, clock, world_state, event_history, _ = make_runtime()
    event = Event(id="existing", type="generic", timestamp="t0")
    event_history.append(event)
    before_events = event_history.get_events()
    before_entities = world_state.entities
    before_facts = world_state.facts

    runtime.start()

    assert runtime.running is True
    runtime.stop()

    assert runtime.running is False
    assert clock.current_time == 0
    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events


def test_runtime_start_closes_world_initialization_loaders():
    runtime, _, world_state, _, _ = make_runtime()

    runtime.start()

    with pytest.raises(PermissionError, match="initialization is closed"):
        world_state.load_fact("late", {"untrusted": True})


def test_step_behavior_remains_available_without_changing_lifecycle_state():
    runtime, clock, _, _, _ = make_runtime()

    result = runtime.step()

    assert result == ()
    assert clock.current_time == 1
    assert runtime.running is False


def test_run_automatically_starts_and_keeps_existing_step_flow():
    processor = RecordingProcessor()
    runtime, clock, _, _, scheduler = make_runtime(processor)
    first = ScheduledEvent(
        execute_time=1,
        event=Event(id="event_first", type="generic", timestamp="t1"),
    )
    second = ScheduledEvent(
        execute_time=2,
        event=Event(id="event_second", type="generic", timestamp="t2"),
    )
    scheduler.schedule(first)
    scheduler.schedule(second)

    results = runtime.run(2)

    assert runtime.running is True
    assert clock.current_time == 2
    assert results == (("event_first",), ("event_second",))
    assert processor.dispatched == [first, second]
