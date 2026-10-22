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


def test_memory_authority_flow_writes_request_to_store():
    store = MemoryStore()
    history = EventHistory()
    history.append(Event(id="event_001", type="generic", timestamp="t1"))
    persistence = MemoryPersistence(store, history)
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id="event_001",
        owner_id="owner_001",
        memory_type="experience",
        content={"confirmed": {"items": ["event data"]}},
        importance=0.7,
        metadata={"approval": "accepted"},
    )
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.85,
        memory_type=proposal.memory_type,
    )
    request = MemoryWriteFactory().create_request(decision, proposal)

    written = persistence.save(request)

    assert isinstance(written, Memory)
    assert written == store.get_memory(request.memory_id)
    assert written.id == request.memory_id
    assert written.owner_id == request.owner_id
    assert written.source_event == request.source_event_id
    assert written.content == request.content
    assert written.type == request.memory_type
    assert written.importance == request.importance
    assert written.metadata == request.metadata
    assert request.source_event_id == "event_001"


def test_memory_store_has_no_add_memory_business_write_path():
    store = MemoryStore()

    assert not hasattr(store, "add_memory")
    assert not hasattr(store, "commit_memory")
    assert callable(store._commit_memory)
    assert store.get_all_memories() == ()
