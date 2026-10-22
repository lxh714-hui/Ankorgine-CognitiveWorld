import pytest

from cognitive_world.core.event import Event
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.processor import EventProcessor
from cognitive_world.core.world_state import WorldState
from cognitive_world.core.update import WorldUpdate


class FixedUpdateHandler(EventHandler):
    def __init__(self, update):
        self.update = update

    def handle(self, event):
        return self.update


def _apply_through_processor(world_state, update, event_id, changes=None):
    event = SystemEventFactory().create(
        event_id=event_id, event_type="test-update", timestamp="runtime",
        changes=changes,
    )
    processor = EventProcessor()
    processor.register_handler("test-update", FixedUpdateHandler(update))
    processor.process(event, world_state)
    return event, processor


def test_apply_event_sets_target_state_from_world_update():
    world_state = WorldState()
    update = WorldUpdate(
        target_id="facts",
        operation="set",
        payload={"confirmed": {"value": 1}},
    )

    _apply_through_processor(world_state, update, "event_001")

    assert world_state.facts == {"confirmed": {"value": 1}}


def test_apply_event_update_merges_payload_and_ignores_event_semantics():
    world_state = WorldState()
    world_state.load_fact("existing", {"retained": True})
    update = WorldUpdate(
        target_id="facts",
        operation="update",
        payload={"added": ["value"]},
    )

    _, processor = _apply_through_processor(
        world_state, update, "event_002", [{"this": "is not interpreted"}]
    )

    assert world_state.facts == {
        "existing": {"retained": True},
        "added": ["value"],
    }
    assert processor.event_history.get_events()[0].changes == [
        {"this": "is not interpreted"}
    ]


def test_apply_event_deep_copies_update_payload():
    world_state = WorldState()
    payload = {"nested": {"values": [1]}}
    update = WorldUpdate(target_id="environment", operation="set", payload=payload)

    _apply_through_processor(world_state, update, "event_003")
    payload["nested"]["values"].append(2)
    update.payload["nested"]["values"].append(3)

    assert world_state.environment == {"nested": {"values": [1]}}


def test_apply_event_rejects_unsupported_operations():
    world_state = WorldState()
    update = WorldUpdate(target_id="facts", operation="delete", payload={})

    with pytest.raises(ValueError, match="Unsupported WorldUpdate operation"):
        _apply_through_processor(world_state, update, "event_004")


def test_public_world_write_without_processor_capability_is_rejected():
    world_state = WorldState()
    event = SystemEventFactory().create(
        event_id="event_direct", event_type="test-update", timestamp="runtime"
    )
    update = WorldUpdate("facts", "update", {"unauthorized": True})
    with pytest.raises(PermissionError, match="EventProcessor"):
        world_state.apply_event(event, update)
    assert world_state.facts == {}


def test_event_handler_cannot_use_initialization_loader_during_runtime_processing():
    class LoaderMisuseHandler(EventHandler):
        def handle(self, event):
            return WorldUpdate("facts", "update", {})

        def handle_with_world_state(self, event, world_state):
            world_state.load_fact("untracked", True)
            return WorldUpdate("facts", "update", {})

    world_state = WorldState()
    event = SystemEventFactory().create(
        event_id="event_loader_misuse", event_type="loader-misuse", timestamp="runtime"
    )
    processor = EventProcessor()
    processor.register_handler("loader-misuse", LoaderMisuseHandler())

    with pytest.raises(PermissionError, match="initialization is closed"):
        processor.process(event, world_state)

    assert world_state.facts == {}
    assert processor.event_history.get_events() == ()
