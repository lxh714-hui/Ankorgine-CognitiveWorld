import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event.factory import SystemEventFactory


def system_event(event_id, event_type):
    return SystemEventFactory().create(event_id=event_id, event_type=event_type, timestamp="t1")


class StubHandler(EventHandler):
    def __init__(self, request):
        self.request = request
        self.received_event = None

    def handle(self, event: Event) -> WorldUpdate:
        self.received_event = event
        return self.request


def test_handler_can_be_registered():
    processor = EventProcessor()
    handler = StubHandler(request=WorldUpdate(target_id="facts", operation="update", payload={}))

    processor.register_handler("generic", handler)

    assert processor._handlers["generic"] is handler


def test_processor_calls_registered_handler_and_forwards_request():
    event = system_event("event_001", "generic")
    request = WorldUpdate(target_id="facts", operation="update", payload={"key": "value"})
    handler = StubHandler(request=request)
    applied = []

    class CapturingWorldState:
        def apply_event(self, received_event, update_request):
            applied.append((received_event, update_request))

    processor = EventProcessor()
    processor.register_handler("generic", handler)

    processor.process(event, CapturingWorldState())

    assert handler.received_event is event
    assert applied == [(event, request)]


def test_processor_reports_unregistered_event_type():
    processor = EventProcessor()
    event = system_event("event_001", "unregistered")

    with pytest.raises(LookupError, match="No handler registered for event type: unregistered"):
        processor.process(event, object())
