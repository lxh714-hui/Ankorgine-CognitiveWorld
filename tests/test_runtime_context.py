from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime import RuntimeContext, SimulationClock


def test_runtime_context_can_be_created():
    context = RuntimeContext(
        clock=SimulationClock(),
        world_state=WorldState(),
        event_history=EventHistory(),
    )

    assert isinstance(context, RuntimeContext)


def test_runtime_context_preserves_dependency_references():
    clock = SimulationClock()
    world_state = WorldState()
    event_history = EventHistory()

    context = RuntimeContext(clock, world_state, event_history)

    assert context.clock is clock
    assert context.world_state is world_state
    assert context.event_history is event_history


def test_runtime_context_does_not_contain_simulation_logic():
    context = RuntimeContext(
        clock=SimulationClock(),
        world_state=WorldState(),
        event_history=EventHistory(),
    )

    assert not hasattr(context, "tick")
    assert not hasattr(context, "advance")
    assert not hasattr(context, "process_event")
