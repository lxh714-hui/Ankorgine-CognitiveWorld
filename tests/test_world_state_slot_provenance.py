from dataclasses import replace

import pytest

from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState, WorldStateSlot
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor


class UpdateFromEventHandler(EventHandler):
    def handle(self, event):
        raise AssertionError("the authoritative WorldState is required")

    def handle_with_world_state(self, event, world_state):
        update = event.changes[0]
        return WorldUpdate(update["collection"], update["operation"], update["payload"])


def _event(event_id, collection, operation, payload):
    return SystemEventFactory().create(
        event_id=event_id,
        event_type="slot-update",
        timestamp=event_id,
        changes=[{"collection": collection, "operation": operation, "payload": payload}],
    )


def _processor(world):
    history = EventHistory()
    processor = EventProcessor(event_history=history, world_state=world)
    processor.register_handler("slot-update", UpdateFromEventHandler())
    return processor, history


def test_per_slot_latest_event_updates_and_unaffected_slots_keep_their_origin():
    world = WorldState()
    world.load_environment_data("door-a", DoorState("door-a", "room", False, False, True))
    processor, history = _processor(world)
    is_open = WorldStateSlot("environment", "door-a", ("is_open",))
    is_locked = WorldStateSlot("environment", "door-a", ("is_locked",))

    initial = world.read_state_slot(is_open, event_history=history)
    assert initial.value is False
    assert initial.origin_kind == "initialization"
    assert initial.source_event_id is None

    first = _event("open-door", "environment", "update", {
        "door-a": DoorState("door-a", "room", True, False, True),
    })
    processor.process(first, world)
    opened = world.read_state_slot(is_open, event_history=history)
    lock = world.read_state_slot(is_locked, event_history=history)
    assert opened.value is True and opened.source_event_id == first.id
    assert opened.origin_kind == "event" and history.get_event(first.id) is not None
    assert lock.value is False and lock.origin_kind == "initialization"

    same_value = _event("repeat-open", "environment", "update", {
        "door-a": DoorState("door-a", "room", True, False, True),
    })
    processor.process(same_value, world)
    assert world.read_state_slot(is_open, event_history=history).source_event_id == first.id

    second = _event("close-door", "environment", "update", {
        "door-a": DoorState("door-a", "room", False, False, True),
    })
    processor.process(second, world)
    closed = world.read_state_slot(is_open, event_history=history)
    assert closed.value is False and closed.source_event_id == second.id
    assert world.read_state_slot(is_locked, event_history=history).origin_kind == "initialization"


def test_slots_for_different_records_and_fields_keep_distinct_origins_even_when_values_match():
    world = WorldState()
    world.load_fact("left", {"value": "same"})
    world.load_fact("right", {"value": "same"})
    processor, history = _processor(world)
    left = WorldStateSlot("facts", "left", ("value",))
    right = WorldStateSlot("facts", "right", ("value",))
    left_event = _event("left-change", "facts", "update", {"left": {"value": "new"}})
    right_event = _event("right-change", "facts", "update", {"right": {"value": "new"}})
    processor.process(left_event, world)
    processor.process(right_event, world)
    left_read = world.read_state_slot(left, event_history=history)
    right_read = world.read_state_slot(right, event_history=history)
    assert left_read.value == right_read.value == "new"
    assert left_read.source_event_id == left_event.id
    assert right_read.source_event_id == right_event.id


def test_multi_slot_event_records_one_source_and_rejected_event_changes_neither_value_nor_source():
    world = WorldState()
    world.load_fact("record", {"first": 1, "second": 2})
    processor, history = _processor(world)
    one = WorldStateSlot("facts", "record", ("first",))
    two = WorldStateSlot("facts", "record", ("second",))
    change = _event("multi-change", "facts", "update", {"record": {"first": 10, "second": 20}})
    processor.process(change, world)
    for slot in (one, two):
        assert world.read_state_slot(slot, event_history=history).source_event_id == change.id

    class Reject(EventHandler):
        def handle(self, event):
            raise AssertionError

        def handle_with_world_state(self, event, world_state):
            raise ValueError("reject before update")

    processor.register_handler("reject", Reject())
    rejected = SystemEventFactory().create(event_id="reject-event", event_type="reject", timestamp="t")
    before = (world.read_state_slot(one, event_history=history), world.read_state_slot(two, event_history=history))
    with pytest.raises(ValueError, match="reject before update"):
        processor.process(rejected, world)
    assert (world.read_state_slot(one, event_history=history), world.read_state_slot(two, event_history=history)) == before
    assert world.facts["record"] == {"first": 10, "second": 20}


def test_uninitialized_and_unverifiable_origins_remain_unknown_or_unverified():
    with pytest.raises(TypeError, match="_slot_origins"):
        WorldState(_slot_origins={})
    world = WorldState(_facts={"preloaded": {"value": 3}})
    slot = WorldStateSlot("facts", "preloaded", ("value",))
    assert world.read_state_slot(slot).origin_kind == "unknown"
    world.load_fact("initialized", {"value": 4})
    initialized = world.read_state_slot(WorldStateSlot("facts", "initialized", ("value",)))
    assert initialized.origin_kind == "initialization" and initialized.source_event_id is None

    forged = initialized.to_record()
    forged["origin_kind"] = "event"
    forged["source_event_id"] = "not-in-history"
    assert not world.verify_state_slot_record(forged, event_history=EventHistory())


def test_event_origin_requires_same_authoritative_history_and_processor_receipt():
    world = WorldState()
    processor, history = _processor(world)
    event = _event("authoritative-origin", "facts", "update", {"f": {"value": 1}})
    processor.process(event, world)
    read = world.read_state_slot(WorldStateSlot("facts", "f", ("value",)), event_history=history)
    assert read.source_event_id == event.id
    assert world.verify_state_slot_read(read, event_history=history)
    assert not world.verify_state_slot_read(read, event_history=EventHistory())
    assert not world.verify_state_slot_record(replace(read, source_event_id="missing").to_record(), event_history=history)


def test_failed_multi_slot_world_update_does_not_publish_partial_state_or_provenance():
    world = WorldState()
    world.load_fact("record", {"a": 1, "b": 2})
    processor, history = _processor(world)
    a, b = WorldStateSlot("facts", "record", ("a",)), WorldStateSlot("facts", "record", ("b",))
    previous = (world.read_state_slot(a, event_history=history), world.read_state_slot(b, event_history=history))
    bad = _event("bad-multi", "facts", "unsupported", {"record": {"a": 3, "b": 4}})
    with pytest.raises(ValueError, match="Unsupported WorldUpdate operation"):
        processor.process(bad, world)
    assert world.facts["record"] == {"a": 1, "b": 2}
    assert (world.read_state_slot(a, event_history=history), world.read_state_slot(b, event_history=history)) == previous


def test_processor_applied_event_origin_is_not_reported_as_event_until_history_receipt_exists():
    # A foreign History cannot authenticate the stored source, even when an
    # Event with the same ID is merely appended without a processor receipt.
    world = WorldState()
    processor, history = _processor(world)
    event = _event("receipt-required", "facts", "update", {"f": {"v": 1}})
    processor.process(event, world)
    foreign = EventHistory()
    foreign.append(event)
    read = world.read_state_slot(WorldStateSlot("facts", "f", ("v",)), event_history=foreign)
    assert read.origin_kind == "unverified" and read.source_event_id is None
    assert history.get_event(event.id) is not None
