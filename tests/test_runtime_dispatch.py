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


def make_scheduled(event_id, execute_time):
    return ScheduledEvent(
        execute_time=execute_time,
        event=Event(id=event_id, type="generic", timestamp=f"t{execute_time}"),
    )


def make_runtime(event_processor=None):
    clock = SimulationClock()
    world_state = WorldState()
    event_history = EventHistory()
    scheduler = EventScheduler()
    context = RuntimeContext(clock, world_state, event_history)
    runtime = SimulationRuntime(context, scheduler, event_processor)
    return runtime, clock, world_state, event_history, scheduler


def test_runtime_without_processor_returns_due_events():
    runtime, clock, _, _, scheduler = make_runtime()
    due = make_scheduled("event_due", 1)
    scheduler.schedule(due)

    assert runtime.step() == (due,)
    assert clock.current_time == 1


def test_runtime_passes_due_events_to_injected_processor():
    processor = RecordingProcessor()
    runtime, _, _, _, scheduler = make_runtime(processor)
    due = make_scheduled("event_due", 1)
    scheduler.schedule(due)

    assert runtime.step() == ("event_due",)
    assert processor.dispatched == [due]


def test_runtime_does_not_pass_not_yet_due_events_to_processor():
    processor = RecordingProcessor()
    runtime, _, _, _, scheduler = make_runtime(processor)
    future = make_scheduled("event_future", 2)
    scheduler.schedule(future)

    assert runtime.step() == ()
    assert processor.dispatched == []


def test_dispatch_does_not_modify_world_state_or_event_history():
    processor = RecordingProcessor()
    runtime, _, world_state, event_history, scheduler = make_runtime(processor)
    recorded = Event(id="event_recorded", type="recorded", timestamp="t0")
    event_history.append(recorded)
    scheduler.schedule(make_scheduled("event_due", 1))
    before_entities = world_state.entities
    before_facts = world_state.facts
    before_events = event_history.get_events()

    runtime.step()

    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
