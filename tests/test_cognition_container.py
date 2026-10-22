import pytest

from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    Emotion,
    Goal,
    Personality,
)


def test_container_registers_and_gets_all_cognition_types():
    container = CognitionContainer()
    personality = Personality(id="personality_001", traits={"tendency": ["a"]})
    belief = Belief(
        id="belief_001",
        owner_id="owner_001",
        content={"claim": True},
        confidence=0.7,
        source="observation",
    )
    goal = Goal(
        id="goal_001",
        owner_id="owner_001",
        description="general goal",
        priority=0.6,
        status="active",
    )
    emotion = Emotion(
        id="emotion_001",
        owner_id="owner_001",
        state="calm",
        intensity=0.2,
    )

    container.add_personality(personality)
    container.add_belief(belief)
    container.add_goal(goal)
    container.add_emotion(emotion)

    assert container.get_personality(personality.id) == personality
    assert container.get_belief(belief.id) == belief
    assert container.get_goal(goal.id) == goal
    assert container.get_emotion(emotion.id) == emotion


def test_container_does_not_manage_memory():
    container = CognitionContainer()

    assert not hasattr(container, "add_memory")
    assert not hasattr(container, "get_memory")
    assert not hasattr(container, "memories")


def test_long_term_cognition_accessors_share_dedicated_stores():
    container = CognitionContainer()
    belief = Belief(
        belief_id="belief_001",
        owner_id="owner_001",
        content={"claim": True},
    )
    goal = Goal(goal_id="goal_001", owner_id="owner_001")

    container.add_belief(belief)
    container.add_goal(goal)

    assert container.get_belief(belief.id) == container.belief_store.get_by_id(
        belief.id
    )
    assert container.get_goal(goal.id) == container.goal_store.get_by_id(goal.id)
    assert not hasattr(container, "_beliefs")
    assert not hasattr(container, "_goals")
    assert not hasattr(container, "_personalities")


def test_external_objects_and_reads_cannot_mutate_container_data():
    container = CognitionContainer()
    personality = Personality(
        id="personality_001",
        traits={"nested": {"values": [1]}},
        metadata={"extension": ["original"]},
    )

    container.add_personality(personality)
    personality.traits["nested"]["values"].append(2)
    personality.metadata["extension"].append("external")

    retrieved = container.get_personality("personality_001")
    retrieved.traits["nested"]["values"].append(3)
    retrieved.metadata["extension"].append("read")

    assert container.get_personality("personality_001").traits == {
        "nested": {"values": [1]}
    }
    assert container.get_personality("personality_001").metadata == {
        "extension": ["original"]
    }

    with pytest.raises(TypeError):
        container.personalities["personality_002"] = Personality(id="personality_002")
