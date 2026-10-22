from typing import get_type_hints

import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState


def test_world_state_rejects_direct_event_application():
    world_state = WorldState()
    event = Event(id="event_001", type="change", timestamp="2026-10-14T12:00:00Z")

    update = WorldUpdate(target_id="facts", operation="set", payload={})
    with pytest.raises(PermissionError, match="EventProcessor"):
        world_state.apply_event(event, update)


def test_apply_event_accepts_event_type_annotation():
    hints = get_type_hints(WorldState.apply_event)

    assert hints["event"] is Event
