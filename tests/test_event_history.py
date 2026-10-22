import pytest

from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def test_event_history_appends_and_retrieves_events():
    history = EventHistory()
    first = Event(id="event_001", type="generic", timestamp="t1")
    second = Event(id="event_002", type="generic", timestamp="t2")

    history.append(first)
    history.append(second)

    assert history.get_events() == (first, second)
    assert history.get_event("event_001") == first
    assert history.get_event("missing") is None


def test_event_history_does_not_modify_or_expose_stored_event():
    history = EventHistory()
    event = Event(
        id="event_001",
        type="generic",
        timestamp="t1",
        changes=[{"nested": [1]}],
    )

    history.append(event)
    event.changes[0]["nested"].append(2)
    retrieved = history.get_event("event_001")
    retrieved.changes[0]["nested"].append(3)

    assert history.get_event("event_001").changes == [{"nested": [1]}]


def test_event_history_accepts_only_events():
    with pytest.raises(TypeError, match="event must be an Event"):
        EventHistory().append(object())
