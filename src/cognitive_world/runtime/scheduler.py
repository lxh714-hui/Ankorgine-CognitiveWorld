"""Time-based scheduling records for future Events."""

from dataclasses import dataclass, field

from cognitive_world.core.event import Event


@dataclass
class ScheduledEvent:
    """Pair an execution time with an already-created Event."""

    execute_time: int
    event: Event


@dataclass
class EventScheduler:
    """Queue Events until their scheduled simulation time is due."""

    _scheduled_events: list[ScheduledEvent] = field(default_factory=list, repr=False)

    def schedule(self, scheduled_event: ScheduledEvent) -> None:
        """Add a scheduled Event to the queue."""
        if not isinstance(scheduled_event, ScheduledEvent):
            raise TypeError("scheduled_event must be a ScheduledEvent")
        self._scheduled_events.append(scheduled_event)

    def get_due_events(self, current_time: int) -> tuple[ScheduledEvent, ...]:
        """Remove and return all scheduled Events due at ``current_time``."""
        due_events = sorted(
            (
                scheduled_event
                for scheduled_event in self._scheduled_events
                if scheduled_event.execute_time <= current_time
            ),
            key=lambda scheduled_event: scheduled_event.execute_time,
        )
        self._scheduled_events = [
            scheduled_event
            for scheduled_event in self._scheduled_events
            if scheduled_event.execute_time > current_time
        ]
        return tuple(due_events)
