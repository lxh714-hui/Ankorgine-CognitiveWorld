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


class FactHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate(
            target_id="facts",
            operation="update",
            payload={event.id: True},
        )


class RecordingProcessor:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, scheduled_event):
        self.dispatched.append(scheduled_event)
        return scheduled_event.event.id


def test_runtime_uses_clock_and_scheduler_from_context():
    clock = SimulationClock(current_time=4)
    scheduler = EventScheduler()
    due = ScheduledEvent(
        execute_time=5,
        event=Event(id="event_due", type="generic", timestamp="t5"),
    )
    scheduler.schedule(due)
    context = RuntimeContext(clock, WorldState(), EventHistory(), scheduler)
    runtime = SimulationRuntime(context)

    assert runtime.step() == (due,)
    assert context.clock.current_time == 5
    assert runtime.scheduler is context.scheduler


def test_runtime_injected_scheduler_is_stored_in_context_for_compatibility():
    context = RuntimeContext(SimulationClock(), WorldState(), EventHistory())
    scheduler = EventScheduler()
    runtime = SimulationRuntime(context, scheduler)

    assert context.scheduler is scheduler
    assert runtime.scheduler is scheduler


def test_processor_uses_world_state_and_event_history_from_context():
    context_world = WorldState()
    context_history = EventHistory()
    processor = EventProcessor(
        world_state=WorldState(),
        event_history=EventHistory(),
    )
    processor.register_handler("change", FactHandler())
    scheduler = EventScheduler()
    event = SystemEventFactory().create(event_id="event_context", event_type="change", timestamp="t1")
    scheduled = ScheduledEvent(execute_time=1, event=event)
    scheduler.schedule(scheduled)
    context = RuntimeContext(
        SimulationClock(), context_world, context_history, scheduler
    )
    runtime = SimulationRuntime(context, event_processor=processor)

    runtime.step()

    assert processor.world_state is context_world
    assert processor.event_history is context_history
    assert context.world_state.facts == {"event_context": True}
    assert context.event_history.get_events() == (event,)


def test_step_and_run_keep_dispatch_results_and_tick_count():
    clock = SimulationClock()
    scheduler = EventScheduler()
    processor = RecordingProcessor()
    first = ScheduledEvent(
        execute_time=1,
        event=Event(id="event_first", type="generic", timestamp="t1"),
    )
    third = ScheduledEvent(
        execute_time=3,
        event=Event(id="event_third", type="generic", timestamp="t3"),
    )
    scheduler.schedule(first)
    scheduler.schedule(third)
    context = RuntimeContext(clock, WorldState(), EventHistory(), scheduler)
    runtime = SimulationRuntime(context, event_processor=processor)

    assert runtime.step() == ("event_first",)
    assert runtime.run(2) == ((), ("event_third",))
    assert clock.current_time == 3
    assert processor.dispatched == [first, third]


def test_runtime_context_remains_a_dependency_container():
    context = RuntimeContext(
        SimulationClock(), WorldState(), EventHistory(), EventScheduler()
    )

    assert not hasattr(context, "step")
    assert not hasattr(context, "run")
    assert not hasattr(context, "tick")
