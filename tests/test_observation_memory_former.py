from copy import deepcopy

from cognitive_world.cognition import (
    MemoryStore,
    ObservationMemoryFormer,
)
from cognitive_world.observation import Observation


def test_observation_can_create_a_proposal_with_source_references():
    observation = Observation(
        observation_id="observation_001",
        observer_id="agent_001",
        source_event_id="event_001",
        content={"noticed": ["door opened"]},
        metadata={"channel": "visual"},
    )

    proposal = ObservationMemoryFormer().create(observation)

    assert proposal.source_event_id == "event_001"
    assert proposal.owner_id == "agent_001"
    assert proposal.memory_type == "observation"
    assert proposal.content == {"noticed": ["door opened"]}
    assert proposal.metadata["source"] == "observation"
    assert proposal.metadata["source_observation_id"] == "observation_001"
    assert proposal.metadata["channel"] == "visual"


def test_creation_does_not_modify_observation_or_write_memory():
    observation = Observation(
        observation_id="observation_001",
        observer_id="agent_001",
        source_event_id="event_001",
        content={"nested": ["original"]},
        metadata={"nested": {"value": "original"}},
    )
    original = deepcopy(observation)
    memory_store = MemoryStore()

    proposal = ObservationMemoryFormer().create(observation)
    proposal.content["nested"].append("proposal change")
    proposal.metadata["nested"]["value"] = "proposal change"

    assert observation == original
    assert memory_store.get_all_memories() == ()
