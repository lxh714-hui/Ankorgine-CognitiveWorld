"""Create candidate memory records from confirmed event data."""

from copy import deepcopy
from dataclasses import dataclass

from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


@dataclass
class MemoryFormer:
    """Wrap a history-confirmed Event as a proposal without interpreting it."""

    event_history: EventHistory

    def create_proposal(self, event: Event, owner_id: str) -> MemoryProposal:
        """Return a raw event-backed proposal for a memory owner.

        This boundary does not summarize or interpret the event and does not
        persist the returned proposal.
        """
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        confirmed_event = self.event_history.get_event(event.id)
        if confirmed_event is None or confirmed_event != event:
            raise ValueError("event must be present in EventHistory")

        return MemoryProposal(
            id=f"memory-proposal:{owner_id}:{event.id}",
            source_event_id=event.id,
            owner_id=owner_id,
            memory_type="event",
            content={
                "type": event.type,
                "timestamp": event.timestamp,
                "participants": deepcopy(event.participants),
                "cause": event.cause,
                "changes": deepcopy(event.changes),
            },
            importance=0.0,
            metadata=deepcopy(event.metadata),
        )
