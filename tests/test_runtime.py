from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime import (
    RuntimeContext,
    SimulationClock,
    SimulationRuntime,
)


def make_runtime():
    clock = SimulationClock()
    world_state = WorldState()
    event_history = EventHistory()
    context = RuntimeContext(clock, world_state, event_history)
    return SimulationRuntime(context), clock, world_state, event_history


def test_simulation_runtime_can_be_created():
    runtime, _, _, _ = make_runtime()

    assert isinstance(runtime, SimulationRuntime)


def test_simulation_runtime_uses_the_supplied_context():
    runtime, clock, world_state, event_history = make_runtime()

    assert runtime.context.clock is clock
    assert runtime.context.world_state is world_state
    assert runtime.context.event_history is event_history


def test_step_advances_clock_and_returns_current_time():
    runtime, clock, _, _ = make_runtime()

    assert runtime.step() == ()
    assert clock.current_time == 1


def test_step_does_not_modify_world_state_or_event_history():
    runtime, _, world_state, event_history = make_runtime()
    event = Event(id="event_001", type="existing", timestamp="t1")
    event_history.append(event)
    before_entities = world_state.entities
    before_facts = world_state.facts
    before_events = event_history.get_events()

    runtime.step()

    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
