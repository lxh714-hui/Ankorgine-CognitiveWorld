"""Test-only issuers for explicitly authorized event-source paths."""

from cognitive_world.core.event import Event
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine


class FixedResolutionEngine(ResolutionEngine):
    def __init__(self, decision=None):
        self.decision = decision or ResolutionDecision(True, "completed")

    def _adjudicate(self, attempt):
        return self.decision


def make_system_event(event_id="system-event", event_type="system", timestamp="t1", **kwargs) -> Event:
    return SystemEventFactory().create(
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp,
        **kwargs,
    )
