from cognitive_world.agent import AgentRegistry
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime import (
    AgentScheduler,
    EventScheduler,
    RuntimeContext,
    SimulationClock,
)


def test_context_stores_scheduler_and_registry_references():
    event_scheduler = EventScheduler()
    agent_scheduler = AgentScheduler()
    agent_registry = AgentRegistry()

    context = RuntimeContext(
        clock=SimulationClock(),
        world_state=WorldState(),
        event_history=EventHistory(),
        event_scheduler=event_scheduler,
        agent_scheduler=agent_scheduler,
        agent_registry=agent_registry,
    )

    assert context.event_scheduler is event_scheduler
    assert context.scheduler is event_scheduler
    assert context.agent_scheduler is agent_scheduler
    assert context.agent_registry is agent_registry


def test_legacy_scheduler_argument_remains_an_alias():
    scheduler = EventScheduler()
    context = RuntimeContext(SimulationClock(), WorldState(), EventHistory(), scheduler)

    assert context.scheduler is scheduler
    assert context.event_scheduler is scheduler


def test_context_only_holds_dependencies_and_does_not_schedule_or_advance():
    clock = SimulationClock(current_time=7)
    world_state = WorldState()
    event_history = EventHistory()
    event_scheduler = EventScheduler()
    agent_scheduler = AgentScheduler()
    context = RuntimeContext(
        clock,
        world_state,
        event_history,
        event_scheduler=event_scheduler,
        agent_scheduler=agent_scheduler,
        agent_registry=AgentRegistry(),
    )

    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    assert context.clock.current_time == 7
    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
    assert not hasattr(context, "schedule_agent")
    assert not hasattr(context, "get_due_agents")
    assert not hasattr(context, "get_due_events")
