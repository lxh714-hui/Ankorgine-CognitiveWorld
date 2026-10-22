import pytest

from cognitive_world.cognition import ShortTermMemoryFormation
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def test_confirmed_event_creates_short_term_memory():
    event = Event(
        id="event_001",
        type="generic",
        timestamp="t1",
        participants=["entity_001"],
        changes=[{"fact": {"nested": [1]}}],
        metadata={"extension": ["source"]},
    )
    history = EventHistory()
    history.append(event)

    experience = ShortTermMemoryFormation(history).create(event, "owner_001")

    assert experience.id == "short-term:owner_001:event_001"
    assert experience.owner_id == "owner_001"
    assert experience.source_event_id == event.id
    assert experience.timestamp == event.timestamp
    assert experience.content["changes"] == event.changes
    assert experience.metadata == event.metadata


def test_unrecorded_event_is_rejected_without_modifying_event():
    event = Event(id="event_001", type="generic", timestamp="t1")
    history = EventHistory()

    with pytest.raises(ValueError, match="event must be present in EventHistory"):
        ShortTermMemoryFormation(history).create(event, "owner_001")

    assert history.get_events() == ()
    assert event.id == "event_001"
