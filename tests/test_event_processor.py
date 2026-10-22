from typing import get_type_hints

import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.processor import EventProcessor
from cognitive_world.runtime.scheduler import ScheduledEvent
from cognitive_world.event.factory import SystemEventFactory


def system_event(event_id, event_type, timestamp="t1", **kwargs):
    return SystemEventFactory().create(event_id=event_id, event_type=event_type, timestamp=timestamp, **kwargs)


def test_event_processor_can_be_created():
    assert isinstance(EventProcessor(), EventProcessor)


def test_process_reports_unregistered_event_type():
    processor = EventProcessor()
    event = system_event("event_001", "change", "2026-10-14T12:00:00Z")
    world_state = WorldState()

    with pytest.raises(LookupError, match="No handler registered for event type: change"):
        processor.process(event, world_state)


def test_process_has_event_and_world_state_type_hints():
    hints = get_type_hints(EventProcessor.process)

    assert hints["event"] is Event
    assert hints["world_state"] is WorldState


class ValidHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate(target_id="facts", operation="update", payload={event.id: True})


def test_processor_records_only_successfully_applied_events():
    history = EventHistory()
    processor = EventProcessor(event_history=history)
    processor.register_handler("change", ValidHandler())
    event = system_event("event_001", "change", "2026-10-14T12:00:00Z")

    processor.process(event, WorldState())

    assert history.get_events() == (event,)


def test_processor_does_not_record_event_when_world_update_fails():
    history = EventHistory()
    processor = EventProcessor(event_history=history)
    class InvalidUpdateHandler(EventHandler):
        def handle(self, event: Event) -> WorldUpdate:
            return WorldUpdate(target_id="facts", operation="unsupported", payload={})

    processor.register_handler("change", InvalidUpdateHandler())
    event = system_event("event_001", "change", "2026-10-14T12:00:00Z")

    with pytest.raises(ValueError, match="Unsupported WorldUpdate operation"):
        processor.process(event, WorldState())

    assert history.get_events() == ()


def test_processor_rejects_handler_result_of_unknown_type():
    class InvalidHandler(EventHandler):
        def handle(self, event: Event) -> WorldUpdate:
            return object()

    processor = EventProcessor(event_history=EventHistory())
    processor.register_handler("change", InvalidHandler())
    event = system_event("event_001", "change", "2026-10-14T12:00:00Z")

    with pytest.raises(TypeError, match="must return a WorldUpdate"):
        processor.process(event, WorldState())

    assert processor.event_history.get_events() == ()


def test_dispatch_accepts_scheduled_event_and_delegates_to_process():
    world_state = WorldState()
    processor = EventProcessor(world_state=world_state)
    event = system_event("event_001", "change", "t1")
    scheduled_event = ScheduledEvent(execute_time=1, event=event)
    calls = []

    def process(event_arg, world_state_arg, cause_id=None):
        calls.append((event_arg, world_state_arg, cause_id))

    processor.process = process

    processor.dispatch(scheduled_event)

    assert calls == [(event, world_state, None)]


def test_dispatch_preserves_event_content_through_existing_process_flow():
    world_state = WorldState()
    processor = EventProcessor(world_state=world_state)
    processor.register_handler("change", ValidHandler())
    event = system_event("event_001", "change", "t1", changes=[{"nested": [1]}])
    scheduled_event = ScheduledEvent(execute_time=1, event=event)
    original_event = Event(id="event_001", type="change", timestamp="t1", changes=[{"nested": [1]}])

    processor.dispatch(scheduled_event)

    assert event == original_event


def test_processor_rejects_hand_built_event_even_if_history_contains_it():
    history = EventHistory()
    processor = EventProcessor(event_history=history)
    processor.register_handler("change", ValidHandler())
    hand_built = Event("forged", "change", "t1")
    history.append(hand_built)
    world = WorldState()

    with pytest.raises(ValueError, match="controlled source"):
        processor.process(hand_built, world)
    assert world.facts == {}


def test_processor_rejects_event_mutated_after_system_issuance():
    processor = EventProcessor()
    processor.register_handler("change", ValidHandler())
    event = system_event("mutated", "change")
    event.changes.append({"tampered": True})
    world = WorldState()

    with pytest.raises(ValueError, match="controlled source"):
        processor.process(event, world)
    assert world.facts == {}
