"""Save and recovery acceptance for real L1-issued system proof records."""

import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from dataclasses import replace

import pytest

from cognitive_world.cognition.l1_consumption_proof import (
    PROOF_MEMORY_TYPE, PROOF_PURPOSE, verify_proof,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.snapshot import (
    CognitiveStateSnapshot, CognitiveStoreSnapshot, cognitive_snapshot_codec,
    reconstruct_isolated, _COGNITIVE_SNAPSHOT_PURPOSE,
)
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.event.history import EventHistory
from cognitive_world.core.persistence import sha256_hex

from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest


def test_pre_consumption_checkpoint_does_not_gain_later_in_memory_proof(tmp_path):
    trust = HmacPersistenceTrust(b"l1-before-consumption-save-test-key-32")
    manager = SaveManager(tmp_path / "saves", trust=trust)
    memory = MemoryStore()
    parent, cognition, _, _, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory,
    )
    contexts = tuple(parent.cognition_context_provider(agent)
                     for agent in parent.context.agent_registry.all_agents())
    for context in contexts:
        context.bind_write_fence(parent.write_fence)
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory,
        agent_contexts=contexts,
    )
    assert not any(item.type == PROOF_MEMORY_TYPE for item in memory.get_all_memories())
    parent.step()
    assert any(item.type == PROOF_MEMORY_TYPE for item in memory.get_all_memories())
    staged = manager.stage_restore(
        saved.save_id, timeline_id="social-timeline", active_runtime=parent,
        assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="social-before-consumption-child",
    )
    slot = ActiveRuntimeSlot(parent)
    restored = RestoreCoordinator(slot).activate(staged)
    assert slot.current is restored
    child_store = restored.cognition_context_provider(
        restored.context.agent_registry.get("npc-b"),
    ).memory_store
    assert not any(item.type == PROOF_MEMORY_TYPE for item in child_store.get_all_memories())
    assert parent.write_fence.retired
    with pytest.raises(PermissionError):
        with parent.write_fence.operation():
            pass


def test_ordinary_memory_governance_cannot_create_or_overwrite_l1_system_record():
    trust = HmacPersistenceTrust(b"l1-memory-separation-test-key-material-32")
    memory = MemoryStore()
    runtime, _, _, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory,
    )
    runtime.step()
    proof_record = next(item for item in memory.get_all_memories()
                        if item.type == PROOF_MEMORY_TYPE)
    persistence = MemoryPersistence(memory, history, write_fence=runtime.write_fence)

    def request(proposal):
        decision = MemoryDecisionAuthority().issue(
            proposal, accepted=True, importance=proposal.importance,
            memory_type=proposal.memory_type,
        )
        return MemoryWriteFactory().create_request(decision, proposal)

    with runtime.write_fence.operation():
        forged = MemoryProposal("forged-proof", proof_record.source_event, "npc-b",
                                PROOF_MEMORY_TYPE, "model-declared-consumption", 1.0)
        with pytest.raises(PermissionError):
            persistence.save(request(forged))
        ordinary = MemoryProposal(proof_record.id, proof_record.source_event,
                                  "npc-b", "experience", "ordinary experience", 0.5)
        saved = persistence.save(request(ordinary))
    assert saved.id != proof_record.id
    assert memory.get_memory(proof_record.id) == proof_record
    npc_b = runtime.context.agent_registry.get("npc-b")
    context = runtime.cognition_context_provider(npc_b)
    assert all(item.type != PROOF_MEMORY_TYPE for item in context.get_memories())


@pytest.mark.parametrize("change", ("signature_hex", "fact_id", "visibility_rule", "version"))
def test_resigned_outer_snapshot_cannot_launder_invalid_inner_consumption_proof(change):
    trust = HmacPersistenceTrust(b"l1-inner-proof-verification-test-key-32")
    memory = MemoryStore()
    runtime, cognition, _, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory,
    )
    runtime.step()
    snapshot = _capture_cognition(runtime, cognition, memory, trust)
    codec = cognitive_snapshot_codec()
    stores = list(snapshot.body.stores)
    index = next(i for i, item in enumerate(stores) if item.store_name == "memories")
    old_store = stores[index]
    proof_record = next(item for item in old_store.records
                        if item.value.type == PROOF_MEMORY_TYPE)
    proof = proof_record.value.content
    bad_value = {
        "signature_hex": "00" * 32,
        "fact_id": "unrelated-fact",
        "visibility_rule": "unsupported-policy",
        "version": 99,
    }[change]
    changed_memory = replace(proof_record.value,
                             content=replace(proof, **{change: bad_value}))
    records = tuple(replace(item, value=changed_memory)
                    if item is proof_record else item for item in old_store.records)
    unsigned_store = replace(old_store, records=records, state_version="sha256:pending")
    stores[index] = replace(unsigned_store,
                            state_version="sha256:" + sha256_hex(codec.dumps(unsigned_store)))
    body = replace(snapshot.body, stores=tuple(stores))
    body_bytes = codec.dumps(body)
    forged_outer = CognitiveStateSnapshot(
        body, "sha256:" + sha256_hex(body_bytes),
        trust.sign(_COGNITIVE_SNAPSHOT_PURPOSE, body_bytes).hex(),
    )
    with pytest.raises((PermissionError, ValueError)):
        reconstruct_isolated(forged_outer, trust=trust,
                             expected_agents=body.expected_agents,
                             event_history=history)
    with pytest.raises(PermissionError):
        reconstruct_isolated(snapshot, trust=trust,
                             expected_agents=body.expected_agents,
                             event_history=EventHistory(timeline_id="social-timeline"))


@pytest.mark.parametrize("failure_stage", ("sign", "commit"))
def test_failed_l1_issuance_never_creates_canonical_or_snapshot_proof(
    failure_stage, monkeypatch,
):
    trust = HmacPersistenceTrust(b"l1-failure-window-test-key-material-32")
    memory = MemoryStore()
    runtime, cognition, _, _, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory,
    )
    original_sign = HmacPersistenceTrust.sign
    original_commit = MemoryStore._commit_system_proof
    signed = []

    def fail_sign(self, purpose, payload):
        if purpose == PROOF_PURPOSE:
            raise RuntimeError("injected post-consumption signing failure")
        return original_sign(self, purpose, payload)

    def fail_commit(self, *args, **kwargs):
        if self is memory:
            signed.append(True)
            raise RuntimeError("injected post-signing canonical commit failure")
        return original_commit(self, *args, **kwargs)

    if failure_stage == "sign":
        monkeypatch.setattr(HmacPersistenceTrust, "sign", fail_sign)
    else:
        monkeypatch.setattr(MemoryStore, "_commit_system_proof", fail_commit)
    try:
        runtime.step()
    except RuntimeError as error:
        assert "injected" in str(error)
    assert not any(item.type == PROOF_MEMORY_TYPE for item in memory.get_all_memories())
    assert signed == ([True] if failure_stage == "commit" else [])
    snapshot = _capture_cognition(runtime, cognition, memory, trust)
    assert not any(record.value.type == PROOF_MEMORY_TYPE
                   for item in snapshot.body.stores if item.store_name == "memories"
                   for record in item.records)


def test_nonverbal_observation_without_complete_historical_visibility_is_not_proven():
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_MEMORY_TYPE

    trust = HmacPersistenceTrust(b"d2-incomplete-visibility-test-key-32")
    memory = MemoryStore()
    runtime, _, _, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=False,
    )
    assert not history.get_processing_evidence(
        "light-observed",
    ).event_time_context.environment_snapshot_complete
    runtime.step()
    receiver = next(item for item in runtime.last_agent_turn_results
                    if item.agent_id == "npc-b")
    assert receiver.newly_consumed_percept_ids
    assert not any(item.type == NONVERBAL_PROOF_MEMORY_TYPE
                   for item in memory.get_all_memories())


def test_signed_nonverbal_proof_is_not_canonical_when_store_commit_fails(monkeypatch):
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE, NONVERBAL_PROOF_PURPOSE,
    )
    from cognitive_world.observation.generator import ObservationGenerator

    trust = HmacPersistenceTrust(b"d2-commit-failure-test-key-material-32")
    memory = MemoryStore()
    runtime, cognition, observations, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    runtime.context.agent_scheduler.get_due_agents(runtime.context.clock.current_time + 1)
    event = history.get_event("light-observed")
    evidence = history.get_processing_evidence(event.id)
    observation = ObservationGenerator().generate_authorized(
        event, evidence, observer_id="npc-b",
    )[0]
    observations.add(observation)
    runtime.context.agent_scheduler.schedule_agent("npc-b", 1)
    signed = []
    attempted_commits = []
    original_sign = HmacPersistenceTrust.sign
    original_commit = MemoryStore._commit_system_proof

    def track_sign(authority, purpose, payload):
        result = original_sign(authority, purpose, payload)
        if purpose == NONVERBAL_PROOF_PURPOSE:
            signed.append(result)
        return result

    def fail_d2_commit(store, record, *args, **kwargs):
        if record.type == NONVERBAL_PROOF_MEMORY_TYPE:
            attempted_commits.append((record.owner_id, record.id))
            raise RuntimeError("injected D2 canonical commit failure")
        return original_commit(store, record, *args, **kwargs)

    monkeypatch.setattr(HmacPersistenceTrust, "sign", track_sign)
    monkeypatch.setattr(MemoryStore, "_commit_system_proof", fail_d2_commit)
    runtime.step()
    # HMAC verification recomputes the MAC through sign(); the second call is
    # verification, while exactly one canonical Store commit is attempted.
    assert len(signed) == 2 and signed[0] == signed[1]
    assert len(attempted_commits) == 1
    assert not any(item.type == NONVERBAL_PROOF_MEMORY_TYPE
                   for item in memory.get_all_memories())
    snapshot = _capture_cognition(runtime, cognition, memory, trust)
    assert not any(
        record.value.type == NONVERBAL_PROOF_MEMORY_TYPE
        for store in snapshot.body.stores if store.store_name == "memories"
        for record in store.records
    )


def _capture_cognition(runtime, cognition, memory, trust):
    contexts = tuple(runtime.cognition_context_provider(agent)
                     for agent in runtime.context.agent_registry.all_agents())
    with runtime.write_fence.operation():
        return CognitiveStateSnapshot.capture(
            runtime=runtime, cognition=cognition, memory_store=memory,
            agent_contexts=contexts, timeline_id="social-timeline", trust=trust,
        )


@pytest.mark.parametrize("commit_first", (True, False))
def test_l1_commit_and_cognition_capture_have_a_consistent_order(commit_first, monkeypatch):
    trust = HmacPersistenceTrust(b"l1-snapshot-race-test-key-material-32")
    memory = MemoryStore()
    runtime, cognition, _, _, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory,
    )
    if not commit_first:
        failures = []

        def run_after_capture():
            try:
                runtime.step()
            except BaseException as error:
                failures.append(error)

        contexts = tuple(runtime.cognition_context_provider(agent)
                         for agent in runtime.context.agent_registry.all_agents())
        for context in contexts:
            context.bind_write_fence(runtime.write_fence)
        with runtime.write_fence.operation():
            with runtime.write_fence.snapshot_scope():
                worker = Thread(target=run_after_capture)
                worker.start()
                before = CognitiveStateSnapshot.capture(
                    runtime=runtime, cognition=cognition, memory_store=memory,
                    agent_contexts=contexts, timeline_id="social-timeline", trust=trust,
                )
                assert not any(record.value.type == PROOF_MEMORY_TYPE
                               for item in before.body.stores if item.store_name == "memories"
                               for record in item.records)
        worker.join(10)
        assert not worker.is_alive() and failures == []
        after = _capture_cognition(runtime, cognition, memory, trust)
        assert any(record.value.type == PROOF_MEMORY_TYPE
                   for item in after.body.stores if item.store_name == "memories"
                   for record in item.records)
        return
    reached = Event()
    release = Event()
    original = MemoryStore._commit_system_proof
    failures = []

    def gated_commit(store, *args, **kwargs):
        if store is not memory:
            return original(store, *args, **kwargs)
        with runtime.write_fence.commit_scope():
            reached.set()
            if not release.wait(10):
                raise AssertionError("commit gate was not released")
            return original(store, *args, **kwargs)

    monkeypatch.setattr(MemoryStore, "_commit_system_proof", gated_commit)

    def run_turn():
        try:
            runtime.step()
        except BaseException as error:
            failures.append(error)

    worker = Thread(target=run_turn)
    worker.start()
    assert reached.wait(10)
    if commit_first:
        snapshots = []

        def capture():
            try:
                snapshots.append(_capture_cognition(runtime, cognition, memory, trust))
            except BaseException as error:
                failures.append(error)

        capture_worker = Thread(target=capture)
        capture_worker.start()
        release.set()
        worker.join(10)
        capture_worker.join(10)
        assert not worker.is_alive() and not capture_worker.is_alive()
        assert failures == []
        snapshot = snapshots[0]
        assert len(tuple(item for item in snapshot.body.stores
                         if item.store_name == "memories" for record in item.records
                         if record.value.type == PROOF_MEMORY_TYPE)) == 1
    assert failures == []


@pytest.mark.parametrize("commit_first", (True, False))
def test_nonverbal_l1_commit_and_cognition_capture_have_a_consistent_order(
    commit_first, monkeypatch,
):
    """A D2 record is captured wholly before or after its fenced Store commit."""
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_MEMORY_TYPE
    from cognitive_world.observation.generator import ObservationGenerator

    trust = HmacPersistenceTrust(b"d2-snapshot-race-test-key-material-32")
    memory = MemoryStore()
    runtime, cognition, observations, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    runtime.context.agent_scheduler.get_due_agents(runtime.context.clock.current_time + 1)
    source = history.get_event("light-observed")
    evidence = history.get_processing_evidence("light-observed")
    issued = ObservationGenerator().generate_authorized(
        source, evidence, observer_id="npc-b",
    )
    assert len(issued) == 1 and issued[0].has_trusted_provenance()
    observations.add(issued[0])
    runtime.context.agent_scheduler.schedule_agent(
        "npc-b", runtime.context.clock.current_time + 1,
    )

    contexts = tuple(runtime.cognition_context_provider(agent)
                     for agent in runtime.context.agent_registry.all_agents())
    for context in contexts:
        context.bind_write_fence(runtime.write_fence)

    def d2_records(snapshot):
        return tuple(
            record.value.content
            for store in snapshot.body.stores if store.store_name == "memories"
            for record in store.records
            if record.value.type == NONVERBAL_PROOF_MEMORY_TYPE
        )

    if not commit_first:
        step_started = Event()
        failures = []

        def run_step():
            step_started.set()
            try:
                runtime.step()
            except BaseException as error:
                failures.append(error)

        with runtime.write_fence.operation():
            with runtime.write_fence.snapshot_scope():
                worker = Thread(target=run_step)
                worker.start()
                assert step_started.wait(10)
                before = CognitiveStateSnapshot.capture(
                    runtime=runtime, cognition=cognition, memory_store=memory,
                    agent_contexts=contexts, timeline_id="social-timeline", trust=trust,
                )
                assert d2_records(before) == ()
        worker.join(10)
        assert not worker.is_alive() and failures == []
        after = _capture_cognition(runtime, cognition, memory, trust)
        assert len(d2_records(after)) == 1
        return

    reached_commit = Event()
    release_commit = Event()
    capture_started = Event()
    failures = []
    original = MemoryStore._commit_system_proof

    def gated_commit(store, *args, **kwargs):
        if store is memory and args and args[0].type == NONVERBAL_PROOF_MEMORY_TYPE:
            reached_commit.set()
            if not release_commit.wait(10):
                raise AssertionError("D2 canonical commit gate was not released")
        return original(store, *args, **kwargs)

    monkeypatch.setattr(MemoryStore, "_commit_system_proof", gated_commit)

    def run_step():
        try:
            runtime.step()
        except BaseException as error:
            failures.append(error)

    worker = Thread(target=run_step)
    worker.start()
    assert reached_commit.wait(10)
    snapshots = []

    def capture_after_commit_attempt():
        capture_started.set()
        try:
            snapshots.append(_capture_cognition(runtime, cognition, memory, trust))
        except BaseException as error:
            failures.append(error)

    capture_worker = Thread(target=capture_after_commit_attempt)
    capture_worker.start()
    assert capture_started.wait(10)
    release_commit.set()
    worker.join(10)
    capture_worker.join(10)
    assert not worker.is_alive() and not capture_worker.is_alive()
    assert failures == []
    assert len(snapshots) == 1 and len(d2_records(snapshots[0])) == 1


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI acceptance")
def test_published_l1_proof_is_revalidated_during_independent_process_restore(tmp_path):
    key_path = tmp_path / "trust-ring.json"
    trust = WindowsDpapiPersistenceTrust.initialize(key_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    memory = MemoryStore()
    parent, cognition, _, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory,
    )
    assert not any(item.type == PROOF_MEMORY_TYPE for item in memory.get_all_memories())
    parent.step()
    record = next(item for item in memory.get_all_memories()
                  if item.type == PROOF_MEMORY_TYPE)
    contexts = tuple(parent.cognition_context_provider(agent)
                     for agent in parent.context.agent_registry.all_agents())
    save = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory,
        agent_contexts=contexts,
    )
    assert manager.load_verified(save.save_id, timeline_id="social-timeline")
    assert record.content.source_event_id in save.event_ids
    assert verify_proof(record.content, history=history, trust=trust,
                        checkpoint_timeline_id="social-timeline",
                        checkpoint_tick=save.simulation_tick) is None
    parent.freeze_writes()
    assert parent.write_fence.frozen
    with pytest.raises(PermissionError):
        with parent.write_fence.operation():
            pass

    script = """
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE, verify_proof
from cognitive_world.cognition.memory_store import MemoryStore
from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
save = manager.load_verified(sys.argv[3], timeline_id="social-timeline")
active, _, _, _, _ = _world(communication=False, trust=trust,
                            shared_memory_store=MemoryStore())
staged = manager.stage_restore(
    sys.argv[3], timeline_id="social-timeline", active_runtime=active,
    assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    new_timeline_id="social-restored-child",
)
slot = ActiveRuntimeSlot(active)
child = RestoreCoordinator(slot).activate(staged)
assert slot.current is child
proofs = tuple(item.content for item in child.cognition_context_provider(
    child.context.agent_registry.get("npc-b")).memory_store.get_all_memories()
    if item.type == PROOF_MEMORY_TYPE)
assert len(proofs) == 1
proof = proofs[0]
assert proof.owner_id == "npc-b"
assert proof.source_timeline_id == "social-timeline"
assert proof.consumption_timeline_id == "social-timeline"
verify_proof(proof, history=child.context.event_history, trust=trust,
             checkpoint_timeline_id="social-restored-child",
             checkpoint_tick=child.context.clock.current_time)
child.context.agent_scheduler.schedule_agent("npc-b", child.context.clock.current_time + 1)
child.step()
assert child.write_fence.frozen is False
from cognitive_world.dialogue.runtime import DialogueInputHandler
from cognitive_world.event.factory import SystemEventFactory
child.event_processor.register_handler("dialogue_input", DialogueInputHandler())
tick = child.context.clock.current_time
local_speech = SystemEventFactory().create(
    event_id="child-directed-utterance", event_type="dialogue_input",
    timestamp=str(tick), simulation_tick=tick,
    participants=["npc-a", "npc-b"], cause="test-host-delivery",
    changes=[{"utterance": "New child-line utterance"}],
    metadata={"sender_id": "npc-a", "recipient_id": "npc-b", "location_id": "room"},
)
with child.write_fence.operation():
    child.event_processor.dispatch_with_evidence(local_speech)
child.context.agent_scheduler.schedule_agent("npc-b", tick + 1)
child.step()
local_proofs = tuple(item.content for item in child.cognition_context_provider(
    child.context.agent_registry.get("npc-b")).memory_store.get_all_memories()
    if item.type == PROOF_MEMORY_TYPE)
assert len(local_proofs) == 2
assert {item.consumption_timeline_id for item in local_proofs} == {
    "social-timeline", "social-restored-child",
}
contexts = tuple(child.cognition_context_provider(agent)
                 for agent in child.context.agent_registry.all_agents())
child_save = manager.create_manual_save(
    runtime=child, cognition=contexts[0].cognition_container,
    memory_store=contexts[0].memory_store, agent_contexts=contexts,
)
manager.delete_manual_save(sys.argv[3])
manager.collect_garbage()
assert manager.verify_consistency()
print(child_save.save_id)
"""
    env = os.environ.copy()
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join((str(repo / "src"), str(repo / "tests"),
                                           env.get("PYTHONPATH", "")))
    result = subprocess.run(
        [sys.executable, "-c", script, str(key_path), str(manager.root), save.save_id],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=40, env=env,
    )
    assert result.returncode == 0, result.stderr
    child_save_id = result.stdout.strip().splitlines()[-1]
    reopened = subprocess.run(
        [sys.executable, "-c", """
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE, verify_proof
from cognitive_world.cognition.memory_store import MemoryStore
from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
save = manager.load_verified(sys.argv[3], timeline_id="social-restored-child")
active, _, _, _, _ = _world(communication=False, trust=trust,
                            shared_memory_store=MemoryStore(),
                            timeline_id="social-restored-child")
staged = manager.stage_restore(
    sys.argv[3], timeline_id="social-restored-child", active_runtime=active,
    assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    new_timeline_id="social-grandchild",
)
grandchild = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
records = tuple(item.content for item in grandchild.cognition_context_provider(
    grandchild.context.agent_registry.get("npc-b")).memory_store.get_all_memories()
    if item.type == PROOF_MEMORY_TYPE)
assert len(records) == 2
assert {(item.source_timeline_id, item.consumption_timeline_id) for item in records} == {
    ("social-timeline", "social-timeline"),
    ("social-restored-child", "social-restored-child"),
}
for proof in records:
    verify_proof(proof, history=grandchild.context.event_history, trust=trust,
                 checkpoint_timeline_id="social-grandchild",
                 checkpoint_tick=grandchild.context.clock.current_time)
assert manager.verify_consistency()
""", str(key_path), str(manager.root), child_save_id],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=40, env=env,
    )
    assert reopened.returncode == 0, reopened.stderr
