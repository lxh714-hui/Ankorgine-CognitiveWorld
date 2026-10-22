import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cognitive_world.core.door import DoorState
from cognitive_world.core.persistence import HmacPersistenceTrust, PersistedValueCodec, sha256_hex
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState, WorldStateSlot
from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest, VerifiedSnapshotBundle
from cognitive_world.decision.behavior_feedback import BehaviorFeedback
from cognitive_world.core.timeline import TimelineForkManifest
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.event.persistence import PersistedEventRecord, verify_and_restore_event_records
from cognitive_world.event.processor import EventProcessor


class DoorUpdateHandler(EventHandler):
    def handle(self, event):
        raise AssertionError("authoritative WorldState required")

    def handle_with_world_state(self, event, world_state):
        state = event.changes[0]["state"]
        return WorldUpdate("environment", "update", {state.door_id: state})


def setup_world(*, trust=None, timeline_id="timeline-a"):
    world = WorldState()
    world.load_environment_data("door-a", DoorState("door-a", "room-a", False, False, True))
    history = EventHistory(timeline_id=timeline_id if trust is not None else None)
    processor = EventProcessor(event_history=history, world_state=world,
                               persistence_trust=trust)
    processor.register_handler("door-update", DoorUpdateHandler())
    return world, history, processor


def submit(processor, *, event_id, opened):
    state = DoorState("door-a", "room-a", opened, False, True)
    event = SystemEventFactory().create(
        event_id=event_id, event_type="door-update", timestamp=event_id,
        changes=[{"state": state}], simulation_tick=3,
    )
    processor.process(event, processor.world_state)
    return event


def _signed_fork_metadata(checkpoint, trust, timeline_id):
    body = {
        "schema": "cognitive-world/timeline-fork",
        "version": 1,
        "timeline_id": timeline_id,
        "parent_timeline_id": checkpoint.timeline_id,
        "fork_checkpoint_id": sha256_hex(checkpoint.to_bytes()),
        "inherited_event_chain_head_sha256": checkpoint.event_chain_head_sha256,
        "simulation_tick": checkpoint.simulation_tick,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return TimelineForkManifest(
        1, timeline_id, checkpoint.timeline_id, body["fork_checkpoint_id"],
        checkpoint.event_chain_head_sha256, checkpoint.simulation_tick,
        trust.sign("cognitive-world/timeline-fork/v1", encoded),
    )


def test_signed_processor_path_exports_and_restores_isolated_world_and_event_history():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    codec = PersistedValueCodec()
    world, history, processor = setup_world(trust=trust, timeline_id="timeline-dpapi")
    event = submit(processor, event_id="door-open", opened=True)

    payload = world.export_persisted_snapshot(
        event_history=history, simulation_tick=3, timeline_id="timeline-dpapi", trust=trust, codec=codec
    )
    restored, restored_history, tick = WorldState.restore_persisted_snapshot(
        payload, trust=trust, codec=PersistedValueCodec()
    )

    slot = WorldStateSlot("environment", "door-a", ("is_open",))
    read = restored.read_state_slot(slot, event_history=restored_history)
    assert tick == 3
    assert restored is not world and restored_history is not history
    assert read.value is True
    assert read.origin_kind == "event" and read.source_event_id == event.id
    assert restored_history.get_event(event.id).has_trusted_source()
    assert restored_history.get_processing_evidence(event.id).has_trusted_source(
        restored_history.get_event(event.id)
    )


def test_signed_confirmed_failure_retains_verifiable_attempt_source_without_slot_change():
    from cognitive_world.decision.attempt import Attempt
    from cognitive_world.event.attempt_source import verify_confirmed_failure_event
    from cognitive_world.event.factory import EventFactory
    from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine

    class LockedDoorEngine(ResolutionEngine):
        def __init__(self, failure_conditions):
            self.failure_conditions = failure_conditions

        def _adjudicate(self, attempt):
            return ResolutionDecision(False, "confirmed locked door", metadata={
                "timestamp": "3", "simulation_tick": 3,
                "confirmed_failure_conditions": self.failure_conditions,
            })

    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    world = WorldState()
    world.load_environment_data("door-a", DoorState("door-a", "room-a", False, True, True))
    history = EventHistory(timeline_id="timeline-a")
    processor = EventProcessor(event_history=history, world_state=world, persistence_trust=trust)
    source_ref = "event:door-initial-state"
    reads = (world.read_state_slot(
        WorldStateSlot("environment", "door-a", ("is_locked",)), event_history=history
    ).to_record(),)
    attempt = Attempt(
        "attempt:locked", "agent-a", "proposal:open", "operate",
        ["door-a"], {"method": "push the door open"},
        {"action_proposal_reasoning_refs": [source_ref]},
    )
    result = LockedDoorEngine({
        "conditions": ("door_locked", "attempt_method_does_not_unlock"),
        "source_refs": ("world_state:environment:door-a",),
        "state_slot_reads": reads,
    }).resolve(attempt)
    event = EventFactory().create_from_resolution(result)
    processor.process(event, world)
    assert world.environment["door-a"].is_locked is True
    assert not world.changed_slot_records_for_event(event.id)
    assert verify_confirmed_failure_event(history.get_event(event.id), attempt=attempt)

    restored_events, _, _ = verify_and_restore_event_records(
        history.export_persisted_records(), codec=PersistedValueCodec(), trust=trust,
        expected_timeline_id="timeline-a",
    )
    assert len(restored_events) == 1
    assert verify_confirmed_failure_event(restored_events[0])


def test_initialization_origins_remain_distinct_from_event_origins():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    world, history, _ = setup_world(trust=trust)
    payload = world.export_persisted_snapshot(
        event_history=history, simulation_tick=0, timeline_id="timeline-a", trust=trust
    )
    restored, restored_history, _ = WorldState.restore_persisted_snapshot(payload, trust=trust)
    read = restored.read_state_slot(
        WorldStateSlot("environment", "door-a", ("is_open",)),
        event_history=restored_history,
    )
    assert read.origin_kind == "initialization"
    assert read.source_event_id is None


def test_same_value_event_does_not_replace_the_latest_slot_origin():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    world, history, processor = setup_world(trust=trust)
    first = submit(processor, event_id="door-open-first", opened=True)
    submit(processor, event_id="door-open-repeat", opened=True)
    slot = WorldStateSlot("environment", "door-a", ("is_open",))
    assert world.read_state_slot(slot, event_history=history).source_event_id == first.id
    restored, restored_history, _ = WorldState.restore_persisted_snapshot(
        world.export_persisted_snapshot(event_history=history, simulation_tick=4, timeline_id="timeline-a", trust=trust),
        trust=trust,
    )
    assert restored.read_state_slot(slot, event_history=restored_history).source_event_id == first.id


def test_legacy_unattested_event_history_cannot_be_exported_as_trusted_snapshot():
    world, history, processor = setup_world()
    submit(processor, event_id="legacy-door-open", opened=True)
    with pytest.raises(PermissionError, match="not durably attestable"):
        world.export_persisted_snapshot(
            event_history=history, simulation_tick=3,
            timeline_id="timeline-a", trust=HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!"),
        )


def test_corrupt_checkpoint_and_unknown_version_fail_without_touching_active_world():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    world, history, processor = setup_world(trust=trust)
    submit(processor, event_id="door-open", opened=True)
    payload = world.export_persisted_snapshot(event_history=history, simulation_tick=3, timeline_id="timeline-a", trust=trust)
    before = world.environment

    envelope = json.loads(payload)
    raw_body = bytearray(base64.b64decode(envelope["body"]))
    raw_body[-1] ^= 1
    envelope["body"] = base64.b64encode(raw_body).decode("ascii")
    with pytest.raises(PermissionError):
        WorldState.restore_persisted_snapshot(json.dumps(envelope).encode(), trust=trust)
    assert world.environment == before

    unknown = json.loads(payload)
    unknown["version"] = 99
    with pytest.raises(ValueError, match="unsupported"):
        WorldState.restore_persisted_snapshot(json.dumps(unknown).encode(), trust=trust)


def test_event_payload_tampering_fails_signed_processing_verification():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    codec = PersistedValueCodec()
    world, history, processor = setup_world(trust=trust)
    submit(processor, event_id="door-open", opened=True)
    record = history.export_persisted_records()[0]
    event = codec.loads(record.event_payload)
    event.cause = "tampered"
    changed = PersistedEventRecord(
        record.version, codec.dumps(event), record.processing_evidence_payload,
        record.attestation_payload, record.signature,
    )
    with pytest.raises(PermissionError, match="changed"):
        verify_and_restore_event_records((changed,), codec=codec, trust=trust)


def test_event_timeline_ownership_and_legacy_credential_versions_fail_closed():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    codec = PersistedValueCodec()
    _, history, processor = setup_world(trust=trust)
    submit(processor, event_id="owned-event", opened=True)
    record = history.export_persisted_records()[0]
    attestation = json.loads(record.attestation_payload)
    assert attestation["timeline_id"] == "timeline-a"

    attestation["timeline_id"] = "timeline-other"
    tampered_payload = json.dumps(
        attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    tampered = PersistedEventRecord(
        record.version, record.event_payload, record.processing_evidence_payload,
        tampered_payload, record.signature,
    )
    with pytest.raises(PermissionError, match="attestation"):
        verify_and_restore_event_records(
            (tampered,), codec=codec, trust=trust,
            expected_timeline_id="timeline-a",
        )
    with pytest.raises(ValueError, match="unsupported"):
        PersistedEventRecord.from_json_record({
            **record.to_json_record(), "version": 1,
        })


def test_reordering_event_attestation_chain_is_rejected():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    world, history, processor = setup_world(trust=trust)
    submit(processor, event_id="door-open", opened=True)
    submit(processor, event_id="door-close", opened=False)
    records = history.export_persisted_records()
    with pytest.raises(ValueError, match="chain"):
        EventHistory.from_persisted_records(tuple(reversed(records)),
                                            codec=PersistedValueCodec(), trust=trust)


def test_timeline_history_fork_shares_frozen_ancestor_and_keeps_local_suffixes_isolated(tmp_path):
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    codec = PersistedValueCodec()
    parent_world, parent, parent_processor = setup_world(
        trust=trust, timeline_id="timeline-parent"
    )
    submit(parent_processor, event_id="parent-at-fork", opened=True)
    parent_prefix = parent._immutable_snapshot_copy()
    head = parent.last_persistence_record_digest()
    checkpoint = SnapshotBundleManifest(
        1, "timeline-parent", 3, "a" * 64, "b" * 64, head, "c" * 64, b"placeholder"
    )
    checkpoint = replace(
        checkpoint,
        signature=trust.sign(
            "cognitive-world/snapshot-bundle-manifest/v1",
            json.dumps(checkpoint._body(), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode("utf-8"),
        ),
    )
    fork = _signed_fork_metadata(checkpoint, trust, "timeline-child")
    child = EventHistory.fork_from_checkpoint_metadata(
        parent, timeline_id=fork.timeline_id, fork_bytes=fork.to_bytes(),
        checkpoint_bytes=checkpoint.to_bytes(),
        parent_records=parent.export_persisted_records(),
    )
    parent_at_fork = child._parent_history
    parent_checkpoint = parent_world.export_persisted_snapshot(
        event_history=parent, simulation_tick=3, timeline_id="timeline-parent",
        trust=trust, codec=codec,
    )
    child_world, _, _ = WorldState.restore_persisted_snapshot(
        parent_checkpoint, trust=trust, codec=codec,
    )
    child_processor = EventProcessor(
        event_history=child, world_state=child_world, persistence_trust=trust,
    )
    child_processor.register_handler("door-update", DoorUpdateHandler())
    submit(child_processor, event_id="child-event", opened=False)
    submit(parent_processor, event_id="parent-after-fork", opened=False)

    assert [event.id for event in child.get_events()] == ["parent-at-fork", "child-event"]
    assert [event.id for event in parent.get_events()] == [
        "parent-at-fork", "parent-after-fork"
    ]
    assert child.timeline_id == "timeline-child"
    assert parent.last_persistence_record_digest() != child.last_persistence_record_digest()
    assert child._parent_history.last_persistence_record_digest() == head

    child_checkpoint = child_world.export_persisted_snapshot(
        event_history=child, simulation_tick=4, timeline_id="timeline-child",
        trust=trust, codec=codec,
    )
    restored_world, restored_branch, restored_tick = WorldState.restore_persisted_snapshot(
        child_checkpoint, trust=trust, codec=codec,
        event_history_resolver=lambda checkpoint_id: (
            parent_at_fork if checkpoint_id == fork.fork_checkpoint_id else None
        ),
    )
    restored_slot = restored_world.read_state_slot(
        WorldStateSlot("environment", "door-a", ("is_open",)),
        event_history=restored_branch,
    )
    assert restored_tick == 4 and restored_branch.timeline_id == "timeline-child"
    assert restored_slot.value is False and restored_slot.source_event_id == "child-event"

    state = child.export_persisted_state()
    restored = EventHistory.from_persisted_state(
        state, codec=codec, trust=trust,
        parent_history_resolver=lambda checkpoint_id: (
            parent_at_fork if checkpoint_id == fork.fork_checkpoint_id else None
        ),
    )
    assert [event.id for event in restored.get_events()] == [
        "parent-at-fork", "child-event"
    ]
    assert restored.get_persistence_record("parent-at-fork") == parent.get_persistence_record(
        "parent-at-fork"
    )
    assert restored.timeline_id == "timeline-child"

    parent_path = tmp_path / "parent-checkpoint.json"
    child_path = tmp_path / "child-checkpoint.json"
    parent_path.write_bytes(parent_checkpoint)
    child_path.write_bytes(child_checkpoint)
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    script = (
        "import sys; from pathlib import Path; "
        "from cognitive_world.core.persistence import HmacPersistenceTrust; "
        "from cognitive_world.core.world_state import WorldState, WorldStateSlot; "
        "trust=HmacPersistenceTrust(bytes.fromhex(sys.argv[3])); "
        "_, parent, _=WorldState.restore_persisted_snapshot(Path(sys.argv[1]).read_bytes(),trust=trust); "
        "world, child, tick=WorldState.restore_persisted_snapshot(Path(sys.argv[2]).read_bytes(),"
        "trust=trust,event_history_resolver=lambda _: parent); "
        "read=world.read_state_slot(WorldStateSlot('environment','door-a',('is_open',)),event_history=child); "
        "assert tick==4 and child.timeline_id=='timeline-child' and read.value is False "
        "and read.source_event_id=='child-event'"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(parent_path), str(child_path),
         b"test-only-signing-key-material-32-bytes!".hex()],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, env=env,
    )
    assert completed.returncode == 0, completed.stderr


def test_branch_history_rejects_tampered_fork_manifest_and_wrong_parent_head():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    codec = PersistedValueCodec()
    _, parent, processor = setup_world(trust=trust, timeline_id="timeline-parent")
    submit(processor, event_id="parent-event", opened=True)
    parent_prefix = parent._immutable_snapshot_copy()
    checkpoint = SnapshotBundleManifest(
        1, "timeline-parent", 3, "a" * 64, "b" * 64,
        parent.last_persistence_record_digest(), "c" * 64, b"placeholder"
    )
    checkpoint = replace(checkpoint, signature=trust.sign(
        "cognitive-world/snapshot-bundle-manifest/v1",
        json.dumps(checkpoint._body(), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode("utf-8"),
    ))
    fork = _signed_fork_metadata(checkpoint, trust, "timeline-child")
    child = EventHistory.fork_from_checkpoint_metadata(
        parent, timeline_id=fork.timeline_id, fork_bytes=fork.to_bytes(),
        checkpoint_bytes=checkpoint.to_bytes(),
        parent_records=parent.export_persisted_records(),
    )
    state = child.export_persisted_state()
    tampered = json.loads(json.dumps(state))
    raw_fork = json.loads(base64.b64decode(tampered["fork_manifest"]))
    raw_fork["parent_timeline_id"] = "timeline-other"
    tampered["fork_manifest"] = base64.b64encode(
        json.dumps(raw_fork, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(PermissionError):
        EventHistory.from_persisted_state(
            tampered, codec=codec, trust=trust,
            parent_history_resolver=lambda _: parent_prefix,
        )

    child.fork_manifest_bytes = fork.to_bytes()
    child.fork_checkpoint_manifest_bytes = replace(
        checkpoint, event_chain_head_sha256="d" * 64
    ).to_bytes()
    with pytest.raises(PermissionError):
        child.verify_persisted_lineage(codec=codec, trust=trust)


def test_checkpoint_round_trips_in_a_separate_python_process(tmp_path):
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    world, history, processor = setup_world(trust=trust)
    submit(processor, event_id="door-open", opened=True)
    checkpoint = world.export_persisted_snapshot(
        event_history=history, simulation_tick=3, timeline_id="timeline-a", trust=trust
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_bytes(checkpoint)
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    script = (
        "import sys; from pathlib import Path; "
        "from cognitive_world.core.persistence import HmacPersistenceTrust; "
        "from cognitive_world.core.world_state import WorldState, WorldStateSlot; "
        "trust=HmacPersistenceTrust(bytes.fromhex(sys.argv[2])); "
        "world,history,tick=WorldState.restore_persisted_snapshot(Path(sys.argv[1]).read_bytes(),trust=trust); "
        "read=world.read_state_slot(WorldStateSlot('environment','door-a',('is_open',)),event_history=history); "
        "assert tick==3 and read.value is True and read.origin_kind=='event' and read.source_event_id=='door-open'"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(checkpoint_path),
         b"test-only-signing-key-material-32-bytes!".hex()],
        # Pytest's Windows capture can leave the parent process's inherited
        # stdin handle invalid. The child needs no input, so give it the
        # supported null device while retaining captured stdout/stderr.
        stdin=subprocess.DEVNULL, env=env, capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_dpapi_signed_world_checkpoint_and_event_chain_verify_in_new_process(tmp_path):
    trust_path = tmp_path / "trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    world, history, processor = setup_world(trust=trust, timeline_id="timeline-dpapi")
    event = submit(processor, event_id="dpapi-door-open", opened=True)
    checkpoint = world.export_persisted_snapshot(
        event_history=history, simulation_tick=3, timeline_id="timeline-dpapi", trust=trust,
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_bytes(checkpoint)
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    script = (
        "import sys; from pathlib import Path; "
        "from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust; "
        "from cognitive_world.core.world_state import WorldState, WorldStateSlot; "
        "trust=WindowsDpapiPersistenceTrust.open(sys.argv[1]); "
        "world,history,tick=WorldState.restore_persisted_snapshot(Path(sys.argv[2]).read_bytes(),trust=trust); "
        "read=world.read_state_slot(WorldStateSlot('environment','door-a',('is_open',)),event_history=history); "
        "assert tick==3 and read.value is True and read.source_event_id=='dpapi-door-open'"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(trust_path), str(checkpoint_path)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, env=env,
    )
    assert completed.returncode == 0, completed.stderr


def test_authenticated_but_inconsistent_slot_record_is_rejected_before_return():
    trust = HmacPersistenceTrust(b"test-only-signing-key-material-32-bytes!")
    codec = PersistedValueCodec()
    world, history, processor = setup_world(trust=trust)
    submit(processor, event_id="door-open", opened=True)
    envelope = json.loads(world.export_persisted_snapshot(
        event_history=history, simulation_tick=3, timeline_id="timeline-a", trust=trust, codec=codec
    ))
    body = codec.loads(base64.b64decode(envelope["body"]))
    body["environment"]["door-a"] = DoorState("door-a", "room-a", False, False, True)
    body_bytes = codec.dumps(body)
    envelope["body"] = base64.b64encode(body_bytes).decode("ascii")
    envelope["body_sha256"] = __import__("hashlib").sha256(body_bytes).hexdigest()
    signed = json.dumps({
        "schema": envelope["schema"], "version": envelope["version"],
        "timeline_id": envelope["timeline_id"],
        "simulation_tick": envelope["simulation_tick"],
        "body_sha256": envelope["body_sha256"],
    }, sort_keys=True, separators=(",", ":")).encode()
    envelope["signature"] = base64.b64encode(
        trust.sign("cognitive-world/world-state-checkpoint/v3", signed)
    ).decode("ascii")
    with pytest.raises(PermissionError, match="slot value"):
        WorldState.restore_persisted_snapshot(
            json.dumps(envelope).encode(), trust=trust, codec=PersistedValueCodec()
        )
