"""Synthetic intervening state evolution, never a production operation."""
from dataclasses import replace
from unittest.mock import patch

from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldStateSlot
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler


def evolve(processor, world, life):
    slot = WorldStateSlot("entities", "b", ("state", "life", "value"))
    before = world.read_state_slot(slot, event_history=processor.event_history).to_record()
    assert world.verify_state_slot_record(before, event_history=processor.event_history)
    generation = processor.write_fence.restore_generation
    timeline = processor.event_history.timeline_id
    original = world.apply_event
    event = SystemEventFactory().create(event_id="independent:" + str(len(processor.event_history.get_events())),
                                       event_type="independent", timestamp="", simulation_tick=0)
    class Marker(EventHandler):
        def handle(self, e): return WorldUpdate("facts", "update", {e.id: True})
    processor.register_handler("independent", Marker())
    def synthetic(e, update):
        assert e is event and update.target_id == "facts"
        original(e, update)
        old = dict(world._entities)
        staged = dict(old)
        entity = old["b"]
        staged["b"] = replace(entity, state={**entity.state, "life": life})
        origins = dict(world._slot_origins)
        world._record_event_slot_changes("entities", old, staged, e.id, origins)
        world._entities, world._slot_origins = staged, origins
    # This is fault injection at the application boundary, not a Handler permit
    # or disabled production validator. Real Processor attestation binds the
    # synthetic changed slots; all helpers live exclusively under tests/.
    with patch.object(world, "apply_event", synthetic):
        processor.dispatch_with_evidence(event)
    after = world.read_state_slot(slot, event_history=processor.event_history).to_record()
    assert world.verify_state_slot_record(after, event_history=processor.event_history)
    assert after["source_event_id"] == event.id and before != after
    processor.event_history.verify_persisted_lineage(codec=processor.persistence_codec, trust=processor.persistence_trust)
    assert processor.write_fence.restore_generation == generation
    assert processor.event_history.timeline_id == timeline


def evolve_relationships(processor, world, payload):
    """Synthetic attachment evolution for stale-Take fixtures only."""
    from cognitive_world.core.physical import validate_physical_world
    old = dict(world.relationships)
    staged = {**old, **payload}
    validate_physical_world(world.entities, world.locations, staged)
    original = world.apply_event
    generation = processor.write_fence.restore_generation
    timeline = processor.event_history.timeline_id
    event = SystemEventFactory().create(event_id="take_test_change:" + str(len(processor.event_history.get_events())),
        event_type="take_test_change", timestamp="", simulation_tick=processor.simulation_clock.current_time)
    class Marker(EventHandler):
        def handle(self, e): return WorldUpdate("facts", "update", {e.id: True})
    processor.register_handler("take_test_change", Marker())
    def synthetic(e, update):
        assert e is event and update.target_id == "facts"
        original(e, update)
        origins = dict(world._slot_origins)
        world._record_event_slot_changes("relationships", old, staged, e.id, origins)
        world._relationships, world._slot_origins = staged, origins
    with patch.object(world, "apply_event", synthetic):
        processor.dispatch_with_evidence(event)
    records = world.changed_slot_records_for_event(event.id)
    assert any(r["slot"]["collection"] == "relationships" for r in records)
    for record in records:
        slot = record["slot"]
        read = world.read_state_slot(WorldStateSlot(slot["collection"],slot["record_id"],tuple(slot["path"])),
                                    event_history=processor.event_history).to_record()
        assert world.verify_state_slot_record(read, event_history=processor.event_history)
    processor.event_history.verify_persisted_lineage(codec=processor.persistence_codec,trust=processor.persistence_trust)
    assert processor.write_fence.restore_generation == generation and processor.event_history.timeline_id == timeline
