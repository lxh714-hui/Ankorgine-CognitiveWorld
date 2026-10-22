from cognitive_world.core.world_state import WorldState
from cognitive_world.runtime import AgentScheduler


def test_agent_can_be_scheduled_and_is_returned_when_due():
    scheduler = AgentScheduler()

    scheduler.schedule_agent("agent_001", execute_time=5)

    assert scheduler.get_due_agents(current_time=5) == ("agent_001",)
    assert scheduler.get_due_agents(current_time=5) == ()


def test_agent_not_yet_due_is_not_returned():
    scheduler = AgentScheduler()
    scheduler.schedule_agent("agent_001", execute_time=5)

    assert scheduler.get_due_agents(current_time=4) == ()
    assert scheduler.get_due_agents(current_time=5) == ("agent_001",)


def test_due_agents_are_returned_by_execution_time():
    scheduler = AgentScheduler()
    scheduler.schedule_agent("agent_later", execute_time=8)
    scheduler.schedule_agent("agent_earlier", execute_time=3)
    scheduler.schedule_agent("agent_same_time", execute_time=3)

    assert scheduler.get_due_agents(current_time=8) == (
        "agent_earlier",
        "agent_same_time",
        "agent_later",
    )


def test_scheduler_does_not_execute_agents_or_modify_world_state():
    scheduler = AgentScheduler()
    world_state = WorldState()
    before_entities = world_state.entities
    before_facts = world_state.facts

    scheduler.schedule_agent("agent_001", execute_time=1)
    due_agents = scheduler.get_due_agents(current_time=1)

    assert due_agents == ("agent_001",)
    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert not hasattr(scheduler, "agent_action_loop")
