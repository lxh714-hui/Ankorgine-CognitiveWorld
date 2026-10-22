from cognitive_world.agent import AgentContext
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory


def test_agent_context_can_be_created():
    context = AgentContext(agent_id="agent_001")

    assert isinstance(context, AgentContext)


def test_agent_context_preserves_initial_references_and_state():
    context = AgentContext(
        agent_id="agent_001",
        character_id="character_001",
        personality_id="personality_001",
        goal_ids=["goal_001"],
        relationship_ids=["relationship_001"],
        memory_refs=["memory_001"],
        belief_refs=["belief_001"],
        emotion_state={"state": "calm", "intensity": 0.2},
        metadata={"source": "scenario"},
    )

    assert context.get_identity() == {
        "agent_id": "agent_001",
        "character_id": "character_001",
        "personality_id": "personality_001",
    }
    assert context.goal_ids == ["goal_001"]
    assert context.relationship_ids == ["relationship_001"]
    assert context.memory_refs == ["memory_001"]
    assert context.belief_refs == ["belief_001"]
    assert context.emotion_state == {"state": "calm", "intensity": 0.2}
    assert context.metadata == {"source": "scenario"}


def test_agent_context_isolates_mutable_inputs_and_query_results():
    goals = ["goal_001"]
    relationships = ["relationship_001"]
    memories = ["memory_001"]
    beliefs = ["belief_001"]
    emotion = {"state": "calm", "details": ["initial"]}
    metadata = {"nested": {"labels": ["initial"]}}
    context = AgentContext(
        agent_id="agent_001",
        goal_ids=goals,
        relationship_ids=relationships,
        memory_refs=memories,
        belief_refs=beliefs,
        emotion_state=emotion,
        metadata=metadata,
    )

    goals.append("outside_goal")
    relationships.append("outside_relationship")
    memories.append("outside_memory")
    beliefs.append("outside_belief")
    emotion["details"].append("outside")
    metadata["nested"]["labels"].append("outside")

    context.goal_ids.append("returned_goal")
    context.relationship_ids.append("returned_relationship")
    context.memory_refs.append("returned_memory")
    context.belief_refs.append("returned_belief")
    context.emotion_state["details"].append("returned")
    context.metadata["nested"]["labels"].append("returned")
    context.get_identity()["agent_id"] = "outside_agent"

    assert context.goal_ids == ["goal_001"]
    assert context.relationship_ids == ["relationship_001"]
    assert context.memory_refs == ["memory_001"]
    assert context.belief_refs == ["belief_001"]
    assert context.emotion_state == {"state": "calm", "details": ["initial"]}
    assert context.metadata == {"nested": {"labels": ["initial"]}}
    assert context.agent_id == "agent_001"


def test_agent_context_has_no_world_event_or_cognition_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event(id="existing", type="record", timestamp="t0"))
    before_facts = world_state.facts
    before_events = event_history.get_events()
    context = AgentContext(
        agent_id="agent_001",
        goal_ids=["goal_001"],
        metadata={"custom": True},
    )

    context.get_identity()
    context.get_goal_ids()
    context.get_metadata()

    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
    assert not hasattr(context, "world_state")
    assert not hasattr(context, "event_history")
    assert not hasattr(context, "cognition_store")
    assert not hasattr(context, "create_event")
