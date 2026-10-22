from cognitive_world.core.event import Event


def test_event_can_be_created():
    event = Event(id="event_001", type="change", timestamp="2026-10-14T12:00:00Z")

    assert isinstance(event, Event)


def test_event_saves_all_fields_and_multiple_participants():
    participants = ["entity_001", "entity_002", "entity_003"]
    changes = [
        {"field": "status", "value": {"before": "closed", "after": "open"}},
        ["additional", "arbitrary", "change"],
    ]
    metadata = {"source": "system", "details": {"revision": 2}}
    event = Event(
        id="event_001",
        type="change",
        timestamp="2026-10-14T12:00:00Z",
        participants=participants,
        cause="cause_001",
        changes=changes,
        metadata=metadata,
    )

    assert event.id == "event_001"
    assert event.type == "change"
    assert event.timestamp == "2026-10-14T12:00:00Z"
    assert event.participants == participants
    assert event.cause == "cause_001"
    assert event.changes == changes
    assert event.metadata == metadata
