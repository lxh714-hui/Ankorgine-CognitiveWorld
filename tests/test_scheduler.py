from cognitive_world.core.event import Event
from cognitive_world.runtime import EventScheduler, ScheduledEvent


def make_scheduled_event(event_id, execute_time):
    event = Event(
        id=event_id,
        type="generic",
        timestamp=f"t{execute_time}",
        changes=[{"nested": [1]}],
    )
    return ScheduledEvent(execute_time=execute_time, event=event)


def test_event_scheduler_can_be_created():
    assert isinstance(EventScheduler(), EventScheduler)


def test_scheduler_accepts_scheduled_events():
    scheduler = EventScheduler()
    scheduled = make_scheduled_event("event_001", 5)

    scheduler.schedule(scheduled)

    assert scheduler.get_due_events(5) == (scheduled,)


def test_events_not_yet_due_are_not_returned():
    scheduler = EventScheduler()
    scheduled = make_scheduled_event("event_001", 5)
    scheduler.schedule(scheduled)

    assert scheduler.get_due_events(4) == ()


def test_due_events_are_returned_and_removed_from_queue():
    scheduler = EventScheduler()
    scheduled = make_scheduled_event("event_001", 5)
    scheduler.schedule(scheduled)

    assert scheduler.get_due_events(5) == (scheduled,)
    assert scheduler.get_due_events(5) == ()


def test_multiple_due_events_are_sorted_by_execution_time():
    scheduler = EventScheduler()
    later = make_scheduled_event("event_later", 8)
    earlier = make_scheduled_event("event_earlier", 3)
    same_time = make_scheduled_event("event_same_time", 3)
    scheduler.schedule(later)
    scheduler.schedule(earlier)
    scheduler.schedule(same_time)

    assert scheduler.get_due_events(8) == (earlier, same_time, later)


def test_scheduling_does_not_modify_event_contents():
    scheduler = EventScheduler()
    scheduled = make_scheduled_event("event_001", 2)
    original_event = Event(
        id=scheduled.event.id,
        type=scheduled.event.type,
        timestamp=scheduled.event.timestamp,
        changes=[{"nested": [1]}],
    )
    scheduler.schedule(scheduled)

    due = scheduler.get_due_events(2)

    assert due[0].event == original_event
    assert scheduled.event.changes == [{"nested": [1]}]
