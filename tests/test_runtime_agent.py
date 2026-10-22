from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.agent.context import AgentContext
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory


def test_runtime_agent_can_be_created():
    agent = RuntimeAgent(agent_id="agent_001")

    assert isinstance(agent, RuntimeAgent)


def test_runtime_agent_returns_identity_information():
    agent = RuntimeAgent(agent_id="agent_001", character_id="character_001")

    assert agent.get_identity() == {
        "agent_id": "agent_001",
        "character_id": "character_001",
    }


def test_runtime_agent_returns_goal_references():
    goals = ["goal_001", "goal_002"]
    agent = RuntimeAgent(agent_id="agent_001", goal_ids=goals)

    goals.append("goal_external")
    returned_goals = agent.get_goals()
    returned_goals.append("goal_returned")

    assert agent.get_goals() == ["goal_001", "goal_002"]


def test_runtime_agent_metadata_is_isolated():
    metadata = {"extension": {"labels": ["original"]}}
    agent = RuntimeAgent(agent_id="agent_001", metadata=metadata)

    metadata["extension"]["labels"].append("external")

    assert agent.metadata == {"extension": {"labels": ["original"]}}


def test_runtime_agent_binds_and_returns_context_copy():
    context = AgentContext(
        agent_id="agent_001",
        character_id="character_001",
        personality_id="personality_001",
        goal_ids=["goal_001"],
        metadata={"extension": {"labels": ["initial"]}},
    )
    agent = RuntimeAgent(agent_id="agent_001", context=context)

    assert agent.get_context().get_identity() == {
        "agent_id": "agent_001",
        "character_id": "character_001",
        "personality_id": "personality_001",
    }
    assert agent.get_context().goal_ids == ["goal_001"]

    context.agent_id = "source_changed"
    returned_context = agent.get_context()
    returned_context.agent_id = "returned_changed"
    returned_context.metadata["extension"]["labels"].append("returned")
    agent.context.agent_id = "property_changed"

    stored_context = agent.get_context()
    assert stored_context.agent_id == "agent_001"
    assert stored_context.metadata == {"extension": {"labels": ["initial"]}}


def test_runtime_agent_default_context_preserves_existing_identity_and_goals():
    agent = RuntimeAgent(
        agent_id="agent_001",
        character_id="character_001",
        goal_ids=["goal_001"],
    )

    context = agent.get_context()
    assert context.agent_id == "agent_001"
    assert context.character_id == "character_001"
    assert context.goal_ids == ["goal_001"]


def test_runtime_agent_operations_have_no_world_or_event_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event(id="existing", type="record", timestamp="t0"))
    before_entities = world_state.entities
    before_facts = world_state.facts
    before_events = event_history.get_events()
    agent = RuntimeAgent(
        agent_id="agent_001",
        character_id="character_001",
        goal_ids=["goal_001"],
        metadata={"custom": True},
    )

    agent.get_identity()
    agent.get_goals()

    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
    assert not hasattr(agent, "cognition")
