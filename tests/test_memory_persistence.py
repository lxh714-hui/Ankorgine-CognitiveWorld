import pytest

from cognitive_world.cognition import (
    Memory,
    MemoryDecisionAuthority,
    MemoryPersistence,
    MemoryProposal,
    MemoryStore,
    MemoryWriteFactory,
    MemoryWriteRequest,
)
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def make_history(event_id="event_001"):
    history = EventHistory()
    history.append(Event(id=event_id, type="generic", timestamp="t1"))
    return history


def make_authorized_request(source_event_id="event_001"):
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id=source_event_id,
        owner_id="owner_001",
        memory_type="experience",
        content={"detail": "candidate"},
        importance=0.5,
    )
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.7,
        memory_type=proposal.memory_type,
    )
    return MemoryWriteFactory().create_request(decision, proposal)


def test_memory_persistence_save_interface_exists():
    assert callable(MemoryPersistence(MemoryStore(), make_history()).save)
    assert MemoryPersistence.save.__annotations__["request"] is MemoryWriteRequest
    assert MemoryPersistence.save.__annotations__["return"] is Memory


def test_memory_persistence_saves_memory_from_request():
    store = MemoryStore()
    persistence = MemoryPersistence(store, make_history())
    request = make_authorized_request()

    memory = persistence.save(request)

    assert memory == store.get_memory(request.memory_id)
    assert memory.source_event == "event_001"


def test_memory_v1_new_record_and_exact_retry_are_compatible():
    store = MemoryStore()
    persistence = MemoryPersistence(store, make_history())
    request = make_authorized_request()

    first = persistence.save(request)
    retry = persistence.save(request)

    assert first == retry == store.get_memory(request.memory_id)
    assert len(store.get_all_memories()) == 1


def test_memory_v1_conflicting_immutable_identity_is_rejected_without_mutation():
    store = MemoryStore()
    persistence = MemoryPersistence(store, make_history())
    original = persistence.save(make_authorized_request())
    conflicting_proposal = MemoryProposal(
        id="proposal_001", source_event_id="event_001", owner_id="owner_001",
        memory_type="experience", content={"detail": "different"}, importance=0.5,
    )
    conflicting_decision = MemoryDecisionAuthority().issue(
        conflicting_proposal, accepted=True, importance=0.7,
        memory_type=conflicting_proposal.memory_type,
    )
    conflicting_request = MemoryWriteFactory().create_request(
        conflicting_decision, conflicting_proposal,
    )

    with pytest.raises(PermissionError, match="conflicting immutable Memory identity"):
        persistence.save(conflicting_request)

    assert store.get_memory(original.id) == original
    assert store.get_all_memories() == (original,)


def test_memory_v1_retry_requires_identical_canonical_encoding():
    store = MemoryStore()
    persistence = MemoryPersistence(store, make_history())
    first_proposal = MemoryProposal(
        "proposal_001", "event_001", "owner_001", "experience", {"value": 1}, 0.5,
    )
    first_decision = MemoryDecisionAuthority().issue(
        first_proposal, accepted=True, importance=0.7, memory_type="experience",
    )
    first = MemoryWriteFactory().create_request(first_decision, first_proposal)
    persistence.save(first)

    different_proposal = MemoryProposal(
        "proposal_001", "event_001", "owner_001", "experience", {"value": 1.0}, 0.5,
    )
    different_decision = MemoryDecisionAuthority().issue(
        different_proposal, accepted=True, importance=0.7, memory_type="experience",
    )
    different_encoding = MemoryWriteFactory().create_request(
        different_decision, different_proposal,
    )
    with pytest.raises(PermissionError, match="conflicting immutable Memory identity"):
        persistence.save(different_encoding)

    assert store.get_memory(first.memory_id).content == {"value": 1}


def test_memory_persistence_rejects_direct_memory_input():
    persistence = MemoryPersistence(MemoryStore(), make_history())
    memory = Memory(
        id="memory_001",
        owner_id="owner_001",
        type="experience",
        content={"detail": "candidate"},
        importance=0.7,
        source_event="event_001",
    )

    with pytest.raises(TypeError, match="request must be a MemoryWriteRequest"):
        persistence.save(memory)


def test_memory_persistence_rejects_unissued_write_request():
    persistence = MemoryPersistence(MemoryStore(), make_history())
    request = MemoryWriteRequest(
        memory_id="memory_001",
        owner_id="owner_001",
        source_event_id="event_001",
        content={"detail": "unverified"},
        memory_type="experience",
        importance=0.7,
    )

    with pytest.raises(ValueError, match="must be issued by MemoryWriteFactory"):
        persistence.save(request)
