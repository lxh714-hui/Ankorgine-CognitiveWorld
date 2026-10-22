from copy import deepcopy

import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.memory import (
    EventMemoryProposalFactory,
    MemoryCandidate,
    MemoryConsolidator,
)


def test_confirmed_event_produces_memory_candidate_with_source_and_scores():
    event = Event(
        id="event-1",
        type="world_change",
        timestamp="t1",
        changes=[{"fact": "bridge opened"}],
    )
    context = {
        "owner_id": "agent-1",
        "memory_type": "experience",
        "content": {"experience": "saw bridge open"},
        "importance": 0.75,
        "confidence": 0.9,
        "metadata": {"source": "direct observation"},
    }

    candidate = EventMemoryProposalFactory().propose(event, context)

    assert isinstance(candidate, MemoryCandidate)
    assert candidate.owner_id == "agent-1"
    assert candidate.memory_type == "experience"
    assert candidate.content == {"experience": "saw bridge open"}
    assert candidate.source_event_ids == ["event-1"]
    assert candidate.importance == 0.75
    assert candidate.confidence == 0.9


def test_candidate_defaults_to_event_changes_without_summarizing():
    changes = [{"fact": "door opened", "detail": [1]}]
    event = Event("event-2", "change", "t2", changes=changes)

    candidate = EventMemoryProposalFactory().propose(
        event, {"owner_id": "agent-1"}
    )

    assert candidate.content == changes
    assert candidate.source_event_ids == [event.id]
    assert candidate.importance == 0.0
    assert candidate.confidence == 0.0


def test_candidate_creation_does_not_modify_event_or_world_state():
    event = Event(
        "event-1", "change", "t1", changes=[{"nested": ["fact"]}], metadata={"x": 1}
    )
    event_before = deepcopy(event)
    world_state = WorldState()
    world_state.load_fact("unchanged", {"value": 1})
    facts_before = world_state.facts

    candidate = EventMemoryProposalFactory().propose(
        event,
        {
            "owner_id": "agent-1",
            "content": {"nested": ["candidate"]},
            "metadata": {"nested": ["metadata"]},
        },
    )
    candidate.content["nested"].append("mutated")
    candidate.metadata["nested"].append("mutated")

    assert event == event_before
    assert world_state.facts == facts_before
    assert candidate.content == {"nested": ["candidate", "mutated"]}
    assert candidate.metadata == {"nested": ["metadata", "mutated"]}


def test_consolidator_only_proposes_and_requires_a_confirmed_event_record():
    consolidator = EventMemoryProposalFactory()
    assert not hasattr(consolidator, "memory_store")
    assert not hasattr(consolidator, "save")

    with pytest.raises(TypeError, match="confirmed Event"):
        consolidator.propose({"id": "not-an-event"}, {"owner_id": "agent-1"})

    assert MemoryConsolidator is EventMemoryProposalFactory
