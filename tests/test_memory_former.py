from cognitive_world.cognition import MemoryFormer, MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def test_memory_former_creates_proposal_linked_to_confirmed_event():
    event = Event(
        id="event_001",
        type="generic",
        timestamp="t1",
        participants=["entity_001", "entity_002"],
        cause="event_000",
        changes=[{"target": "entity_001", "value": {"items": [1]}}],
        metadata={"extension": ["preserved"]},
    )

    history = EventHistory()
    history.append(event)
    proposal = MemoryFormer(history).create_proposal(event, "owner_001")

    assert proposal.source_event_id == event.id
    assert proposal.owner_id == "owner_001"
    assert proposal.memory_type == "event"
    assert proposal.content == {
        "type": event.type,
        "timestamp": event.timestamp,
        "participants": event.participants,
        "cause": event.cause,
        "changes": event.changes,
    }
    assert proposal.metadata == event.metadata


def test_proposal_creation_does_not_write_to_memory_store_or_mutate_event():
    event = Event(
        id="event_001",
        type="generic",
        timestamp="t1",
        changes=[{"nested": [1]}],
        metadata={"nested": ["original"]},
    )
    memory_store = MemoryStore()

    history = EventHistory()
    history.append(event)
    proposal = MemoryFormer(history).create_proposal(event, "owner_001")
    proposal.content["changes"][0]["nested"].append(2)
    proposal.metadata["nested"].append("proposal")

    assert memory_store.get_all_memories() == ()
    assert event.changes == [{"nested": [1]}]
    assert event.metadata == {"nested": ["original"]}


def test_memory_former_rejects_event_missing_from_history():
    event = Event(id="event_001", type="generic", timestamp="t1")

    try:
        MemoryFormer(EventHistory()).create_proposal(event, "owner_001")
    except ValueError as error:
        assert str(error) == "event must be present in EventHistory"
    else:
        raise AssertionError("unrecorded Event should not form a proposal")
