"""Observer capture timing and byte-exact signed historical reconstruction."""
import json

import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.entity import Entity
from cognitive_world.core.persistence import HmacPersistenceTrust, PersistedValueCodec
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.persistence import make_persisted_event_record, verify_and_restore_event_records
from cognitive_world.observation import EventStatePhase
from cognitive_world.observation.observable import _issue_processing_evidence
from cognitive_world.runtime import EventScheduler, ScheduledEvent, SimulationClock, SimulationRuntime, RuntimeContext


class RelocateObserver(EventHandler):
    def handle(self, event):
        return WorldUpdate("locations", "update", {"observer": "room-b"})


def moved_observer():
    world = WorldState()
    world.load_entity(Entity("observer", "agent", sensory_capabilities=("sight",)))
    world.load_location("observer", "room-a")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("observer"))
    history = EventHistory(timeline_id="observer-phase-test")
    trust = HmacPersistenceTrust(b"observer-phase-regression-key-0000")
    processor = EventProcessor(persistence_trust=trust)
    processor.register_handler("relocate_observer", RelocateObserver())
    scheduler = EventScheduler()
    runtime = SimulationRuntime(RuntimeContext(
        SimulationClock(), world, history, scheduler=scheduler, agent_registry=registry,
    ), event_processor=processor)
    event = SystemEventFactory().create(
        event_id="observer-moved", event_type="relocate_observer", timestamp="descriptive",
    )
    scheduler.schedule(ScheduledEvent(1, event))
    assert world.locations["observer"] == "room-a"
    assert history.get_events() == ()
    runtime.step()
    record, = runtime.last_scheduled_event_results
    assert record.committed and record.failure_type is None
    assert world.locations["observer"] == "room-b"
    assert history.get_events() == (event,)
    assert not history.requires_recovery() and not runtime.write_fence.recovery_required
    return runtime, event, trust


def test_real_runtime_samples_observer_after_position_change():
    runtime, event, trust = moved_observer()
    evidence = runtime.context.event_history.get_processing_evidence(event.id)
    assert evidence.has_trusted_source(event)
    context = evidence.event_time_context
    assert context.observer_positions == (("observer", "room-b", ("sight",)),)
    assert context.observer_state_phase is EventStatePhase.AFTER_WORLD_UPDATE
    assert context.state_phase is EventStatePhase.AFTER_WORLD_UPDATE
    assert context.simulation_time == 1
    runtime.context.event_history.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)


@pytest.mark.parametrize("legacy", [False, True], ids=["new-post-update", "legacy-default-label"])
def test_signed_phase_payload_restores_exactly_without_resigning(legacy):
    runtime, event, trust = moved_observer()
    history = runtime.context.event_history
    record = history.get_persistence_record(event.id)
    codec = PersistedValueCodec()
    phase = EventStatePhase.AFTER_WORLD_UPDATE
    if legacy:
        # Model the old issuer: post-update data with the retained BEFORE default.
        # This is signed historical fixture construction, not live authorization.
        context = history.get_processing_evidence(event.id).event_time_context
        old_evidence = _issue_processing_evidence(
            event, (), simulation_time=context.simulation_time,
            observer_positions=context.observer_positions,
            environment_conditions=context.environment_conditions,
            environment_snapshot_complete=context.environment_snapshot_complete,
        )
        phase = EventStatePhase.BEFORE_WORLD_UPDATE
        assert old_evidence.event_time_context.observer_state_phase is phase
        attestation = json.loads(record.attestation_payload)
        record = make_persisted_event_record(
            event, old_evidence, update_digest=attestation["update_sha256"],
            changed_slots=tuple(attestation["changed_slots"]), previous_record_digest=None,
            timeline_id=history.timeline_id, codec=codec, trust=trust,
        )
    original_bytes = record.to_json_record()

    class VerifyOnly:
        def sign(self, purpose, payload):
            raise AssertionError("restore must not sign historical evidence")

        def verify(self, purpose, payload, signature):
            return trust.verify(purpose, payload, signature)

    events, evidences, _ = verify_and_restore_event_records(
        (record,), codec=codec, trust=VerifyOnly(), expected_timeline_id=history.timeline_id,
    )
    restored, = evidences
    restored_event, = events
    assert restored.has_trusted_source(restored_event)
    assert restored.event_time_context.observer_state_phase is phase
    assert restored.event_time_context.observer_positions == (("observer", "room-b", ("sight",)),)
    assert codec.dumps(restored) == record.processing_evidence_payload
    assert codec.dumps(restored_event) == record.event_payload
    assert record.to_json_record() == original_bytes
