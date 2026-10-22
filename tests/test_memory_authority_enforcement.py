import pytest

from cognitive_world.cognition import (
    MemoryDecisionAuthority,
    MemoryPersistence,
    MemoryProposal,
    MemoryStore,
    MemoryWriteFactory,
    MemoryWriteRequest,
)
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def make_request(source_event_id="event_001"):
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id=source_event_id,
        owner_id="owner_001",
        memory_type="experience",
        content={"record": "event-backed"},
        importance=0.7,
    )
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.8,
        memory_type=proposal.memory_type,
    )
    return MemoryWriteFactory().create_request(decision, proposal)


def test_event_history_request_can_be_saved_and_queried():
    store = MemoryStore()
    history = EventHistory()
    event = Event(id="event_001", type="generic", timestamp="t1")
    history.append(event)
    persistence = MemoryPersistence(store, history)

    memory = persistence.save(make_request())

    assert store.get_memory(memory.id) == memory
    assert memory.source_event == event.id


def test_request_with_missing_source_event_is_rejected_without_write():
    store = MemoryStore()
    persistence = MemoryPersistence(store, EventHistory())

    with pytest.raises(ValueError, match="source Event not found in EventHistory"):
        persistence.save(make_request("missing_event"))

    assert store.get_all_memories() == ()


def test_memory_store_reads_are_unchanged_and_write_is_private():
    store = MemoryStore()
    history = EventHistory()
    history.append(Event(id="event_001", type="generic", timestamp="t1"))
    persistence = MemoryPersistence(store, history)
    memory = persistence.save(make_request())
    retrieved = store.get_memory(memory.id)

    retrieved.content["record"] = "changed outside store"

    assert store.get_memory(memory.id).content == {"record": "event-backed"}
    assert not hasattr(store, "commit_memory")
    assert not hasattr(store, "add_memory")
