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


def make_runtime():
    clock = SimulationClock()
    world_state = WorldState()
    event_history = EventHistory()
    scheduler = EventScheduler()
    context = RuntimeContext(clock, world_state, event_history)
    runtime = SimulationRuntime(context, scheduler)
    return runtime, clock, world_state, event_history, scheduler


def make_scheduled(event_id, execute_time):
    event = Event(id=event_id, type="scheduled", timestamp=f"t{execute_time}")
    return ScheduledEvent(execute_time=execute_time, event=event)


def test_runtime_accepts_an_injected_scheduler():
    runtime, _, _, _, scheduler = make_runtime()

    assert runtime.scheduler is scheduler


def test_step_advances_the_clock_and_returns_due_events():
    runtime, clock, _, _, scheduler = make_runtime()
    due = make_scheduled("event_due", 1)
    scheduler.schedule(due)

    assert runtime.step() == (due,)
    assert clock.current_time == 1


def test_step_does_not_return_events_that_are_not_due():
    runtime, clock, _, _, scheduler = make_runtime()
    future = make_scheduled("event_future", 2)
    scheduler.schedule(future)

    assert runtime.step() == ()
    assert clock.current_time == 1


def test_step_does_not_change_world_state_or_event_history():
    runtime, _, world_state, event_history, scheduler = make_runtime()
    recorded = Event(id="event_recorded", type="recorded", timestamp="t0")
    event_history.append(recorded)
    scheduled = make_scheduled("event_due", 1)
    scheduler.schedule(scheduled)
    before_entities = world_state.entities
    before_facts = world_state.facts
    before_events = event_history.get_events()

    runtime.step()

    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
