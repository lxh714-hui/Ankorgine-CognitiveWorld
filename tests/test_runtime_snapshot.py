from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime import (
    EventScheduler,
    RuntimeContext,
    RuntimeSnapshot,
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
    clock = SimulationClock(current_time=7)
    context = RuntimeContext(clock, WorldState(), EventHistory(), EventScheduler())
    return SimulationRuntime(context, event_processor=event_processor), clock


def test_runtime_snapshot_can_be_created():
    runtime, _ = make_runtime()

    assert isinstance(runtime.snapshot(), RuntimeSnapshot)


def test_snapshot_captures_current_time_and_running_state():
    runtime, _ = make_runtime()
    runtime.start()

    snapshot = runtime.snapshot()

    assert snapshot.simulation_time == 7
    assert snapshot.running is True


def test_later_runtime_changes_do_not_change_existing_snapshot():
    runtime, clock = make_runtime()
    snapshot = runtime.snapshot()

    runtime.start()
    clock.tick()

    assert snapshot.simulation_time == 7
    assert snapshot.running is False
    assert runtime.snapshot().simulation_time == 8
    assert runtime.snapshot().running is True


def test_snapshot_does_not_advance_or_dispatch_events():
    processor = RecordingProcessor()
    runtime, clock = make_runtime(processor)
    scheduled = ScheduledEvent(
        execute_time=8,
        event=Event(id="event_001", type="generic", timestamp="t8"),
    )
    runtime.context.scheduler.schedule(scheduled)
    before_events = runtime.context.event_history.get_events()

    snapshot = runtime.snapshot()

    assert snapshot.simulation_time == 7
    assert clock.current_time == 7
    assert processor.dispatched == []
    assert runtime.context.scheduler.get_due_events(8) == (scheduled,)
    assert runtime.context.event_history.get_events() == before_events
