from copy import deepcopy

import pytest

from cognitive_world.cognition import (
    MemoryDecision,
    MemoryDecisionAuthority,
    MemoryFormer,
    MemoryPersistence,
    MemoryProposal,
    MemoryStore,
    MemoryWriteFactory,
    MemoryWriteRequest,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.memory import MemoryCandidate, MemoryConsolidator


def test_event_candidate_is_the_canonical_proposal_and_preserves_source():
    event = Event(
        "event-1",
        "world_change",
        "t1",
        changes=[{"fact": "bridge opened"}],
    )

    candidate = MemoryConsolidator().propose(
        event,
        {
            "owner_id": "agent-1",
            "content": {"experience": "bridge opened"},
            "importance": 0.7,
            "confidence": 0.8,
        },
    )

    assert type(candidate) is MemoryProposal
    assert isinstance(candidate, MemoryCandidate)
    assert candidate.source_event_id == event.id
    assert candidate.source_event_ids == [event.id]
    assert candidate.importance == 0.7
    assert candidate.confidence == 0.8


def test_confirmed_event_proposal_flows_through_decision_factory_and_persistence():
    event = Event(
        "event-1",
        "world_change",
        "t1",
        participants=["agent-1"],
        changes=[{"fact": "bridge opened"}],
    )
    history = EventHistory()
    history.append(event)
    event_before = deepcopy(event)
    world_state = WorldState()
    world_state.load_fact("unrelated", {"value": "stable"})
    world_before = world_state.facts
    proposal = MemoryFormer(history).create_proposal(event, "agent-1")
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.9,
        memory_type=proposal.memory_type,
        metadata={"basis": "explicitly accepted"},
    )
    store = MemoryStore()
    persistence = MemoryPersistence(store, history)
    request = MemoryWriteFactory().create_request(decision, proposal)

    memory = persistence.save(request)

    assert memory.source_event == event.id
    assert store.get_memory(memory.id) == memory
    assert memory.source_event == proposal.source_event_id
    assert world_state.facts == world_before
    assert event == event_before


def test_proposal_cannot_skip_decision_factory_or_event_authority():
    event = Event("event-1", "fact", "t1")
    history = EventHistory()
    history.append(event)
    proposal = MemoryFormer(history).create_proposal(event, "agent-1")
    store = MemoryStore()
    persistence = MemoryPersistence(store, history)
    rejected = MemoryDecision(
        proposal_id=proposal.id,
        accepted=False,
        importance=0.0,
        memory_type=proposal.memory_type,
        proposal=proposal,
    )

    with pytest.raises(ValueError, match="accepted decision"):
        MemoryWriteFactory().create_request(rejected, proposal)

    unsigned_request = MemoryWriteRequest(
        memory_id="memory-1",
        owner_id="agent-1",
        source_event_id=event.id,
        content={},
        memory_type="experience",
        importance=0.0,
    )
    with pytest.raises(ValueError, match="issued by MemoryWriteFactory"):
        persistence.save(unsigned_request)

    assert store.get_all_memories() == ()
    assert not hasattr(store, "add_memory")


def test_candidate_compatibility_name_is_not_a_parallel_model():
    assert MemoryCandidate is MemoryProposal
