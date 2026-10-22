from cognitive_world.observation import Observation


def test_observation_can_be_created_with_information_and_metadata():
    observation = Observation(
        observation_id="observation_001",
        observer_id="agent_001",
        source_event_id="event_001",
        content={"seen": ["event detail"]},
        metadata={"channel": "visual"},
    )

    assert observation.observation_id == "observation_001"
    assert observation.observer_id == "agent_001"
    assert observation.source_event_id == "event_001"
    assert observation.content == {"seen": ["event detail"]}
    assert observation.metadata == {"channel": "visual"}
