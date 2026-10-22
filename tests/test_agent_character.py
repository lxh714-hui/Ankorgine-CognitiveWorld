from cognitive_world.agent import Agent, Character


def test_agent_fields_and_metadata_are_preserved():
    cognition_ids = ["belief_001", "emotion_001"]
    goal_ids = ["goal_001"]
    metadata = {"extension": {"source": "test"}, "tags": ["custom"]}
    agent = Agent(
        id="agent_001",
        entity_id="entity_001",
        cognition_ids=cognition_ids,
        goal_ids=goal_ids,
        metadata=metadata,
    )

    assert agent.id == "agent_001"
    assert agent.entity_id == "entity_001"
    assert agent.cognition_ids == cognition_ids
    assert agent.goal_ids == goal_ids
    assert agent.metadata == metadata


def test_character_fields_and_metadata_are_preserved():
    memory_ids = ["memory_001", "memory_002"]
    belief_ids = ["belief_001"]
    metadata = {"extension": [1, {"custom": True}]}
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
        memory_ids=memory_ids,
        belief_ids=belief_ids,
        emotion_id="emotion_001",
        metadata=metadata,
    )

    assert character.id == "character_001"
    assert character.agent_id == "agent_001"
    assert character.personality_id == "personality_001"
    assert character.memory_ids == memory_ids
    assert character.belief_ids == belief_ids
    assert character.emotion_id == "emotion_001"
    assert character.metadata == metadata


def test_agent_and_character_defaults_are_independent():
    first_agent = Agent(id="agent_001", entity_id="entity_001")
    second_agent = Agent(id="agent_002", entity_id="entity_002")
    first_character = Character(
        id="character_001", agent_id="agent_001", personality_id="personality_001"
    )
    second_character = Character(
        id="character_002", agent_id="agent_002", personality_id="personality_002"
    )

    first_agent.metadata["custom"] = True
    first_character.memory_ids.append("memory_001")

    assert second_agent.metadata == {}
    assert second_character.memory_ids == []
