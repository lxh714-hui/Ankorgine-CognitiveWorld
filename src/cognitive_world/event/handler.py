"""Boundary interface for translating events into state update requests."""

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.observation.observable import ObservableFactDraft


class EventHandler:
    """Defines the handler interface without event-specific rules."""

    def handle(self, event: Event) -> WorldUpdate:
        """Return a request for a WorldState update based on an event."""
        raise NotImplementedError("Event handling rules are not implemented yet")

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        """Context-aware hook; legacy handlers remain compatible by default."""
        return self.handle(event)

    def observable_facts(
        self, event: Event, update: WorldUpdate
    ) -> tuple[ObservableFactDraft, ...]:
        """Declare only explicit objective facts supported by this handler.

        The default is empty. Generic WorldUpdate payloads and Event metadata
        are never interpreted as ObservableFacts automatically.
        """
        return ()
