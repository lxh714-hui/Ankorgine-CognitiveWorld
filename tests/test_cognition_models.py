from cognitive_world.cognition import Belief, Emotion, Goal, Memory, Personality


def test_personality_creation_fields_and_metadata():
    metadata = {"schema": {"revision": 1}, "tags": ["extended"]}
    personality = Personality(
        id="personality_001",
        traits={"trait": {"level": 2}},
        values={"value": ["one", "two"]},
        preferences={"preference": True},
        metadata=metadata,
    )

    assert personality.id == "personality_001"
    assert personality.traits == {"trait": {"level": 2}}
    assert personality.values == {"value": ["one", "two"]}
    assert personality.preferences == {"preference": True}
    assert personality.metadata == metadata


def test_belief_creation_fields_and_metadata():
    metadata = {"evidence": ["record_1"], "extension": {"key": "value"}}
    belief = Belief(
        id="belief_001",
        owner_id="agent_001",
        content={"proposition": ["nested", 1]},
        confidence=0.7,
        source="observation",
        metadata=metadata,
    )

    assert belief.id == "belief_001"
    assert belief.owner_id == "agent_001"
    assert belief.content == {"proposition": ["nested", 1]}
    assert belief.confidence == 0.7
    assert belief.source == "observation"
    assert belief.metadata == metadata


def test_goal_creation_fields_and_metadata():
    metadata = {"custom": [1, {"enabled": True}]}
    goal = Goal(
        id="goal_001",
        owner_id="agent_001",
        description="A general objective",
        priority=0.5,
        status="active",
        metadata=metadata,
    )

    assert goal.id == "goal_001"
    assert goal.owner_id == "agent_001"
    assert goal.description == "A general objective"
    assert goal.priority == 0.5
    assert goal.status == "active"
    assert goal.metadata == metadata


def test_emotion_creation_fields_and_metadata():
    metadata = {"dimensions": {"custom_axis": 0.25}}
    emotion = Emotion(
        id="emotion_001",
        owner_id="agent_001",
        state="calm",
        intensity=0.25,
        metadata=metadata,
    )

    assert emotion.id == "emotion_001"
    assert emotion.owner_id == "agent_001"
    assert emotion.state == "calm"
    assert emotion.intensity == 0.25
    assert emotion.metadata == metadata


def test_memory_creation_fields_and_metadata():
    content = {"experience": ["detail", {"retained": True}]}
    metadata = {"custom": {"category": "extension"}}
    memory = Memory(
        id="memory_001",
        owner_id="agent_001",
        type="experience",
        content=content,
        importance=0.8,
        source_event="event_001",
        metadata=metadata,
    )

    assert memory.id == "memory_001"
    assert memory.owner_id == "agent_001"
    assert memory.type == "experience"
    assert memory.content == content
    assert memory.importance == 0.8
    assert memory.source_event == "event_001"
    assert memory.metadata == metadata
