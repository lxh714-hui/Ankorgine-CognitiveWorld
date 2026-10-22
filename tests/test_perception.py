from copy import deepcopy

import pytest

from cognitive_world.cognition import (
    MemoryStore,
    Percept,
    PerceptionProcessor,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import Observation
from tests._trusted_observation_support import make_trusted_observation


def test_observation_can_be_converted_to_percept_with_source_references():
    observation = make_trusted_observation(
        observation_id="observation_001",
        observer_id="agent_001",
        source_event_id="event_001",
        content={"visual": {"object": "bridge", "state": "damaged"}},
        metadata={"channel": "vision"},
    )

    percept = PerceptionProcessor().process(observation, observer_id="agent_001")

    assert isinstance(percept, Percept)
    assert percept.percept_id == "percept:observation_001"
    assert percept.observer_id == "agent_001"
    assert percept.source_observation_id == "observation_001"
    assert percept.content == {"visual": {"object": "bridge", "state": "damaged"}}
    assert percept.metadata == {"channel": "vision"}


def test_percept_content_is_isolated_from_observation():
    observation = make_trusted_observation(
        "observation_001",
        "agent_001",
        "event_001",
        {"nested": ["observed"]},
        {"nested": {"labels": ["visual"]}},
    )
    original = deepcopy(observation)

    percept = PerceptionProcessor().process(observation, observer_id="agent_001")
    percept.content["nested"].append("percept edit")
    percept.metadata["nested"]["labels"].append("percept edit")

    assert observation == original


def test_perception_has_no_world_event_or_memory_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("event_001", "fact", "t1"))
    memory_store = MemoryStore()
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()
    before_memories = memory_store.get_all_memories()
    observation = Observation("observation_001", "agent_001", "event_001", "seen")

    with pytest.raises(PermissionError, match="trusted provenance"):
        PerceptionProcessor().process(observation, observer_id="agent_001")

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
    assert memory_store.get_all_memories() == before_memories


def test_perception_rejects_an_observation_for_another_subject():
    observation = make_trusted_observation("obs", "agent-2", "event", "private")
    with pytest.raises(PermissionError, match="different observer"):
        PerceptionProcessor().process(observation, observer_id="agent-1")
