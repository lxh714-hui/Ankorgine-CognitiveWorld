import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import ObservationAuthorizationError, ObservationGenerator
from tests._trusted_event_support import make_system_event


def test_untrusted_event_cannot_generate_observation():
    event = Event(
        id="event_001",
        type="door_opened",
        timestamp="t1",
        participants=["agent_001"],
        changes=[{"door": {"state": "open"}}],
        metadata={"source": "resolution_001"},
    )
    history = EventHistory()
    history.append(event)

    with pytest.raises(ObservationAuthorizationError, match="controlled provenance"):
        ObservationGenerator().generate(event, "agent_001")
    assert history.get_event(event.id) == event


def test_trusted_event_without_event_time_context_cannot_generate_observation():
    event = make_system_event(
        event_id="event_001",
        event_type="change",
        participants=["agent_001"],
        changes=[{"nested": ["original"]}],
        metadata={"nested": {"value": "original"}, "private_cognition": "secret"},
    )
    original_event = Event(
        event.id,
        event.type,
        event.timestamp,
        event.participants,
        event.cause,
        event.changes,
        event.metadata,
    )
    history = EventHistory()
    history.append(event)
    original_history = history.get_events()
    world_state = WorldState()
    original_world = (world_state.entities, world_state.facts)

    with pytest.raises(ObservationAuthorizationError, match="event-time observer context"):
        ObservationGenerator().generate(event, "agent_001")

    assert event == original_event
    assert history.get_events() == original_history
    assert (world_state.entities, world_state.facts) == original_world
