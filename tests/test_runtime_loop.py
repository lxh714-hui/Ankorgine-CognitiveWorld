import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.runtime import (
    EventScheduler,
    RuntimeContext,
    ScheduledEvent,
    SimulationClock,
    SimulationRuntime,
)
from cognitive_world.event.factory import SystemEventFactory


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
    context = RuntimeContext(clock, world_state, event_history)
    runtime = SimulationRuntime(context, scheduler, event_processor)
    return runtime, clock, world_state, event_history, scheduler


def make_scheduled(event_id, execute_time):
    return ScheduledEvent(
        execute_time=execute_time,
        event=SystemEventFactory().create(
            event_id=event_id, event_type="change", timestamp=f"t{execute_time}"
        ),
    )


def test_run_zero_steps_does_not_advance_clock():
    runtime, clock, _, _, _ = make_runtime()

    assert runtime.run(0) == ()
    assert clock.current_time == 0


def test_run_advances_clock_once_per_step_and_returns_each_result():
    processor = RecordingProcessor()
    runtime, clock, _, _, scheduler = make_runtime(processor)
    first = make_scheduled("event_first", 1)
    third = make_scheduled("event_third", 3)
    scheduler.schedule(first)
    scheduler.schedule(third)

    results = runtime.run(3)

    assert clock.current_time == 3
    assert results == (("event_first",), (), ("event_third",))
    assert processor.dispatched == [first, third]


@pytest.mark.parametrize("steps", [-1, -5])
def test_run_rejects_negative_steps(steps):
    runtime, _, _, _, _ = make_runtime()

    with pytest.raises(ValueError, match="non-negative integer"):
        runtime.run(steps)


@pytest.mark.parametrize("steps", [1.5, "2", True])
def test_run_rejects_non_integer_step_counts(steps):
    runtime, _, _, _, _ = make_runtime()

    with pytest.raises(TypeError, match="non-negative integer"):
        runtime.run(steps)


class FactHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate(
            target_id="facts",
            operation="update",
            payload={event.id: {"confirmed": True}},
        )


def test_world_state_changes_only_through_event_processor():
    world_state = WorldState()
    event_history = EventHistory()
    processor = EventProcessor(world_state=world_state, event_history=event_history)
    processor.register_handler("change", FactHandler())
    clock = SimulationClock()
    scheduler = EventScheduler()
    context = RuntimeContext(clock, world_state, event_history)
    runtime = SimulationRuntime(context, scheduler, processor)
    scheduled = make_scheduled("event_confirmed", 1)
    scheduler.schedule(scheduled)

    assert world_state.facts == {}
    runtime.run(1)

    assert world_state.facts == {"event_confirmed": {"confirmed": True}}
    assert event_history.get_events() == (scheduled.event,)
