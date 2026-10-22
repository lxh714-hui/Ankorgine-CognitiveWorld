"""Form short-term cognitive experience records from confirmed Events."""

from copy import deepcopy
from dataclasses import dataclass

from cognitive_world.cognition.short_term_memory import ShortTermMemory
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


@dataclass
class ShortTermMemoryFormation:
    """Create isolated short-term records from Events in EventHistory."""

    event_history: EventHistory

    def create(self, event: Event, owner_id: str) -> ShortTermMemory:
        """Create a short-term experience from a matching confirmed Event."""
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        confirmed_event = self.event_history.get_event(event.id)
        if confirmed_event is None or confirmed_event != event:
            raise ValueError("event must be present in EventHistory")

        return ShortTermMemory(
            id=f"short-term:{owner_id}:{event.id}",
            owner_id=owner_id,
            source_event_id=event.id,
            content={
                "type": event.type,
                "timestamp": event.timestamp,
                "participants": deepcopy(event.participants),
                "cause": event.cause,
                "changes": deepcopy(event.changes),
            },
            timestamp=event.timestamp,
            metadata=deepcopy(event.metadata),
        )
