"""Crash and branch acceptance for addressed L1 consumption proofs."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE, verify_proof
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.dialogue.runtime import DialogueInputHandler
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.observation.generator import ObservationGenerator
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.save_manager import SaveManager

from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest


def _records(runtime):
    context = runtime.cognition_context_provider(runtime.context.agent_registry.get("npc-b"))
    return tuple(item.content for item in context.memory_store.get_all_memories()
                 if item.type == PROOF_MEMORY_TYPE)


def _nonverbal_records(runtime, owner_id="npc-b"):
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE,
    )

    context = runtime.cognition_context_provider(
        runtime.context.agent_registry.get(owner_id)
    )
    return tuple(item.content for item in context.memory_store.get_all_memories()
                 if item.owner_id == owner_id
                 and item.type == NONVERBAL_PROOF_MEMORY_TYPE)


def _contexts(runtime):
    return tuple(runtime.cognition_context_provider(agent)
                 for agent in runtime.context.agent_registry.all_agents())


def _save(manager, runtime):
    contexts = _contexts(runtime)
    for context in contexts:
        context.bind_write_fence(runtime.write_fence)
    return manager.create_manual_save(
        runtime=runtime, cognition=contexts[0].cognition_container,
        memory_store=contexts[0].memory_store, agent_contexts=contexts,
    )


def _deliver(runtime, event_id):
    runtime.event_processor.register_handler("dialogue_input", DialogueInputHandler())
    tick = runtime.context.clock.current_time
    event = SystemEventFactory().create(
        event_id=event_id, event_type="dialogue_input", timestamp=str(tick),
        simulation_tick=tick, participants=["npc-a", "npc-b"],
        cause="trusted-host-delivery", changes=[{"utterance": event_id}],
        metadata={"sender_id": "npc-a", "recipient_id": "npc-b", "location_id": "room"},
    )
    with runtime.write_fence.operation():
        runtime.event_processor.dispatch_with_evidence(event)
    return event


def _reissue(runtime, event_id):
    history = runtime.context.event_history
    event = history.get_event(event_id)
    evidence = history.get_processing_evidence(event_id)
    issued = ObservationGenerator().generate_authorized(event, evidence, observer_id="npc-b")
    assert len(issued) == 1 and issued[0].has_trusted_provenance()
    runtime.context.observation_store.add(issued[0])
    return issued[0]


def _reissue_nonverbal(runtime, owner_id="npc-b"):
    """Rebuild a trusted historical Observation from recorded event evidence."""
    history = runtime.context.event_history
    event = history.get_event("light-observed")
    evidence = history.get_processing_evidence("light-observed")
    issued = ObservationGenerator().generate_authorized(
        event, evidence, observer_id=owner_id,
    )
    assert len(issued) == 1 and issued[0].has_trusted_provenance()
    runtime.context.observation_store.add(issued[0])
    return issued[0]


def _consume(runtime, event_id):
    observation = _reissue(runtime, event_id)
    runtime.context.agent_scheduler.schedule_agent("npc-b", runtime.context.clock.current_time + 1)
    runtime.step()
    matches = tuple(item for item in _records(runtime)
                    if item.observation_id == observation.observation_id)
    assert len(matches) == 1
    return matches[0]


def _fork(manager, save, active, trust, timeline):
    staged = manager.stage_restore(
        save.save_id, timeline_id=save.timeline_id, active_runtime=active,
        assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id=timeline,
    )
    return RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)


def _worker_env():
    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(repo / "src"), str(repo / "tests"), env.get("PYTHONPATH", "")))
    return env


def _toggle_light_and_consume(runtime, event_prefix):
    """Create a fresh trusted lit-room Observation through EventProcessor and consume it."""
    from cognitive_world.event.factory import SystemEventFactory
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE,
    )

    processor = runtime.event_processor
    tick = runtime.context.clock.current_time
    for suffix, previous, current in (("off", True, False), ("on", False, True)):
        event = SystemEventFactory().create(
            event_id=f"{event_prefix}-{suffix}",
            event_type="room_light_changed", timestamp=str(tick),
            simulation_tick=tick,
            changes=[{"room_id": "room", "from_light_on": previous,
                      "to_light_on": current}],
        )
        with runtime.write_fence.operation():
            processor.dispatch_with_evidence(event)
    source_id = f"{event_prefix}-on"
    runtime.context.agent_scheduler.schedule_agent(
        "npc-b", runtime.context.clock.current_time + 1,
    )
    runtime.step()
    matches = tuple(item for item in _nonverbal_records(runtime)
                    if item.source_event_id == source_id)
    assert len(matches) == 1
    assert matches[0].consumption_timeline_id == runtime.context.event_history.timeline_id
    assert any(item.type == NONVERBAL_PROOF_MEMORY_TYPE
               and item.content.proof_id == matches[0].proof_id
               for item in runtime.cognition_context_provider(
                   runtime.context.agent_registry.get("npc-b")
               ).memory_store.get_all_memories())
    return matches[0]


def _restore_nonverbal_in_fresh_process(
    trust_path, save_root, save_id, source_timeline, new_timeline,
    expected_proof_ids, *, ancestor_timeline=None,
    repeat_ancestor_consumption=False,
):
    script = r'''
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.cognition.l1_consumption_proof import (
    NONVERBAL_PROOF_MEMORY_TYPE, verify_nonverbal_proof,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.observation.generator import ObservationGenerator
from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
saved = manager.load_verified(sys.argv[3], timeline_id=sys.argv[4])
active, _, _, _, _ = _world(
    communication=False, trust=trust, shared_memory_store=MemoryStore(),
    timeline_id=sys.argv[4], complete_environment=True,
)
staged = manager.stage_restore(
    sys.argv[3], timeline_id=sys.argv[4], active_runtime=active,
    assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    new_timeline_id=sys.argv[5],
)
slot = ActiveRuntimeSlot(active)
restored = RestoreCoordinator(slot).activate(staged)
assert slot.current is restored
assert restored.running and not restored.write_fence.frozen
assert restored.context.event_history.timeline_id == sys.argv[5]
context = restored.cognition_context_provider(
    restored.context.agent_registry.get('npc-b')
)
records = tuple(item.content for item in context.memory_store.get_all_memories()
                if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
assert {item.proof_id for item in records} == set(sys.argv[6].split(','))
for proof in records:
    verify_nonverbal_proof(
        proof, history=restored.context.event_history, trust=trust,
        checkpoint_timeline_id=sys.argv[5],
        checkpoint_tick=restored.context.clock.current_time,
    )
if sys.argv[8] == 'repeat':
    # Reconstruct the same authorized ancestor Observation from its signed
    # EventProcessingEvidence, then consume twice in this new child Timeline.
    event = restored.context.event_history.get_event('light-observed')
    evidence = restored.context.event_history.get_processing_evidence('light-observed')
    observations = ObservationGenerator().generate_authorized(
        event, evidence, observer_id='npc-b',
    )
    assert len(observations) == 1
    restored.context.observation_store.add(observations[0])
    restored.context.agent_scheduler.schedule_agent(
        'npc-b', restored.context.clock.current_time + 1,
    )
    restored.step()
    after_first = tuple(item.content for item in context.memory_store.get_all_memories()
                        if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
    child_proofs = tuple(item for item in after_first
                         if item.consumption_timeline_id == sys.argv[5])
    assert len(child_proofs) == 1
    assert child_proofs[0].source_timeline_id == sys.argv[7]
    restored.context.observation_store.add(observations[0])
    restored.context.agent_scheduler.schedule_agent(
        'npc-b', restored.context.clock.current_time + 1,
    )
    restored.step()
    after_second = tuple(item.content for item in context.memory_store.get_all_memories()
                         if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
    assert {item.proof_id for item in after_second} == {item.proof_id for item in after_first}
else:
    # Activation must leave the staged Runtime usable, not merely decodable.
    restored.step()
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(trust_path), str(save_root),
         save_id, source_timeline, new_timeline, ",".join(sorted(expected_proof_ids)),
         ancestor_timeline or source_timeline,
         "repeat" if repeat_ancestor_consumption else "continue"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=60, env=_worker_env(),
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI subprocess acceptance")
def test_ancestor_observation_consumed_independently_on_parent_and_child(tmp_path):
    trust_path = tmp_path / "trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    memory = MemoryStore()
    parent, _, _, _, _ = _world(communication=False, trust=trust, shared_memory_store=memory)
    parent.context.agent_scheduler.get_due_agents(1)
    source = _deliver(parent, "ancestor-speech")
    before = _save(manager, parent)
    assert _records(parent) == ()
    parent_proof = _consume(parent, source.id)
    parent_save = _save(manager, parent)
    assert parent_proof.source_timeline_id == parent_proof.consumption_timeline_id == "social-timeline"

    child = _fork(manager, before, parent, trust, "child-reconsumption")
    assert _records(child) == ()
    child_proof = _consume(child, source.id)
    assert child_proof.source_timeline_id == "social-timeline"
    assert child_proof.consumption_timeline_id == "child-reconsumption"
    assert child_proof.proof_id != parent_proof.proof_id
    assert child_proof.observation_id == parent_proof.observation_id
    assert child_proof.observation_sha256 == parent_proof.observation_sha256
    assert _consume(child, source.id) == child_proof
    child_save = _save(manager, child)

    # Parent and child checkpoints are independently verified in a fresh process.
    script = '''
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE, verify_proof
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.cognition.memory_store import MemoryStore
from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
for save_id, timeline, expected_consumption in ((sys.argv[3], 'social-timeline', 'social-timeline'), (sys.argv[4], 'child-reconsumption', 'child-reconsumption')):
    verified = manager.load_verified(save_id, timeline_id=timeline)
    active, _, _, _, _ = _world(communication=False, trust=trust, shared_memory_store=MemoryStore(), timeline_id=timeline)
    restored_timeline = 'reopened-' + timeline
    staged = manager.stage_restore(save_id, timeline_id=timeline, active_runtime=active, assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(), new_timeline_id=restored_timeline)
    restored = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
    context = restored.cognition_context_provider(restored.context.agent_registry.get('npc-b'))
    records = tuple(item.content for item in context.memory_store.get_all_memories() if item.type == PROOF_MEMORY_TYPE)
    assert len(records) == 1
    proof = records[0]
    assert proof.source_timeline_id == 'social-timeline'
    assert proof.consumption_timeline_id == expected_consumption
    verify_proof(proof, history=restored.context.event_history, trust=trust, checkpoint_timeline_id=restored_timeline, checkpoint_tick=restored.context.clock.current_time)
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(trust_path), str(manager.root),
         parent_save.save_id, child_save.save_id],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=40,
        env=_worker_env(),
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI branch acceptance")
def test_post_fork_parent_and_child_consumption_suffixes_remain_isolated(tmp_path):
    trust = WindowsDpapiPersistenceTrust.initialize(tmp_path / "trust.json")
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, _, _, _, _ = _world(
        communication=False, trust=trust, shared_memory_store=MemoryStore(),
    )
    parent.context.agent_scheduler.get_due_agents(1)
    ancestor_event = _deliver(parent, "shared-ancestor")
    ancestor_proof = _consume(parent, ancestor_event.id)
    fork_save = _save(manager, parent)

    parent_event = _deliver(parent, "parent-only")
    parent_suffix = _consume(parent, parent_event.id)
    parent_save = _save(manager, parent)

    child = _fork(manager, fork_save, parent, trust, "branch-child")
    assert {item.proof_id for item in _records(child)} == {ancestor_proof.proof_id}
    child_event = _deliver(child, "child-only")
    child_suffix = _consume(child, child_event.id)
    child_save = _save(manager, child)
    assert {item.proof_id for item in _records(child)} == {
        ancestor_proof.proof_id, child_suffix.proof_id,
    }
    assert parent_suffix.proof_id not in {item.proof_id for item in _records(child)}
    assert ancestor_proof.source_timeline_id == ancestor_proof.consumption_timeline_id == "social-timeline"
    assert parent_suffix.source_timeline_id == parent_suffix.consumption_timeline_id == "social-timeline"
    assert child_suffix.source_timeline_id == child_suffix.consumption_timeline_id == "branch-child"

    # Restore each checkpoint through the supported coordinator, including
    # after the parent slot is removed and the child's ancestor remains needed.
    for saved, expected, new_timeline in (
        (parent_save, {ancestor_proof.proof_id, parent_suffix.proof_id}, "parent-reopened"),
        (child_save, {ancestor_proof.proof_id, child_suffix.proof_id}, "child-reopened"),
    ):
        active, _, _, _, _ = _world(
            communication=False, trust=trust, shared_memory_store=MemoryStore(),
            timeline_id=saved.timeline_id,
        )
        restored = _fork(manager, saved, active, trust, new_timeline)
        assert {item.proof_id for item in _records(restored)} == expected
        for proof in _records(restored):
            verify_proof(proof, history=restored.context.event_history, trust=trust,
                         checkpoint_timeline_id=new_timeline,
                         checkpoint_tick=restored.context.clock.current_time)
        _deliver(restored, "continued-" + new_timeline)
        new_proof = _consume(restored, "continued-" + new_timeline)
        assert new_proof.consumption_timeline_id == new_timeline
    manager.delete_manual_save(fork_save.save_id)
    manager.delete_manual_save(parent_save.save_id)
    manager.collect_garbage()
    assert manager.load_verified(child_save.save_id, timeline_id="branch-child")
    assert manager.verify_consistency()


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI SaveManager acceptance")
def test_nonverbal_proofs_survive_save_restore_fork_parent_gc_and_fresh_process(tmp_path):
    """Exercise D2 proofs through published saves, branch ancestry and DPAPI reopen."""
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE, verify_nonverbal_proof,
    )

    trust_path = tmp_path / "nonverbal-trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, _, _, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=MemoryStore(),
        complete_environment=True,
    )
    parent.step()
    ancestor_proofs = _nonverbal_records(parent)
    assert len(ancestor_proofs) == 1
    ancestor = ancestor_proofs[0]
    memory_records = parent.cognition_context_provider(
        parent.context.agent_registry.get("npc-b")
    ).memory_store.get_all_memories()
    ancestor_ids = {item.content.proof_id for item in memory_records
                    if item.type == NONVERBAL_PROOF_MEMORY_TYPE}
    assert len(ancestor_ids) == 2
    assert ancestor.source_timeline_id == ancestor.consumption_timeline_id == "social-timeline"
    verify_nonverbal_proof(
        ancestor, history=history, trust=trust,
        checkpoint_timeline_id="social-timeline",
        checkpoint_tick=parent.context.clock.current_time,
    )
    fork_save = _save(manager, parent)
    assert manager.load_verified(
        fork_save.save_id, timeline_id="social-timeline",
    ).metadata.save_id == fork_save.save_id

    parent_suffix = _toggle_light_and_consume(parent, "parent-post-fork-l1")
    parent_save = _save(manager, parent)
    parent_all = tuple(item.content for item in parent.cognition_context_provider(
        parent.context.agent_registry.get("npc-b")
    ).memory_store.get_all_memories() if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
    parent_ids = {item.proof_id for item in parent_all}
    assert parent_ids == ancestor_ids | {parent_suffix.proof_id}
    assert {item.proof_id for item in _nonverbal_records(parent)} == {
        ancestor.proof_id, parent_suffix.proof_id,
    }
    assert parent_suffix.source_timeline_id == parent_suffix.consumption_timeline_id == "social-timeline"

    # Use a separate supported host composition as the active slot for child
    # reconstruction; the source Runtime remains an independent parent line.
    child_active, _, _, _, _ = _world(
        communication=False, trust=trust, shared_memory_store=MemoryStore(),
        complete_environment=True,
    )
    child = _fork(manager, fork_save, child_active, trust, "nonverbal-child")
    # Event-handler policy is a required host-reinjected Runtime dependency.
    from cognitive_world.event.environment import RoomLightChangedHandler
    child.event_processor.register_handler(
        "room_light_changed", RoomLightChangedHandler(),
    )
    assert {item.proof_id for item in _nonverbal_records(child)} == {ancestor.proof_id}
    child_suffix = _toggle_light_and_consume(child, "child-post-fork-l1")
    child_save = _save(manager, child)
    child_all = tuple(item.content for item in child.cognition_context_provider(
        child.context.agent_registry.get("npc-b")
    ).memory_store.get_all_memories() if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
    child_ids = {item.proof_id for item in child_all}
    assert child_ids == ancestor_ids | {child_suffix.proof_id}
    assert {item.proof_id for item in _nonverbal_records(child)} == {
        ancestor.proof_id, child_suffix.proof_id,
    }
    assert parent_suffix.proof_id not in child_ids
    assert ancestor.source_timeline_id == ancestor.consumption_timeline_id == "social-timeline"
    assert child_suffix.source_timeline_id == child_suffix.consumption_timeline_id == "nonverbal-child"

    # Before removing source slots, independently reopen and activate the
    # parent checkpoint. This is a real SaveManager/DPAPI/assembler path.
    _restore_nonverbal_in_fresh_process(
        trust_path, manager.root, parent_save.save_id, "social-timeline",
        "nonverbal-parent-reopened", parent_ids,
    )

    # The child save has signed ancestry dependencies. Removing both parent
    # slots and collecting must retain those immutable ancestor resources.
    manager.delete_manual_save(fork_save.save_id)
    manager.delete_manual_save(parent_save.save_id)
    manager.collect_garbage()
    assert manager.verify_consistency()
    assert manager.load_verified(
        child_save.save_id, timeline_id="nonverbal-child",
    ).metadata.save_id == child_save.save_id

    _restore_nonverbal_in_fresh_process(
        trust_path, manager.root, child_save.save_id, "nonverbal-child",
        "nonverbal-child-reopened", child_ids,
        ancestor_timeline="social-timeline",
        repeat_ancestor_consumption=True,
    )
    assert manager.verify_consistency()


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI subprocess acceptance")
@pytest.mark.parametrize("phase", (
    "before_consumption", "before_signature", "before_commit",
    "after_commit", "catalog_published",
))
def test_abnormal_process_exit_obeys_published_checkpoint_boundary(tmp_path, phase):
    trust_path = tmp_path / "trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    memory = MemoryStore()
    parent, _, _, _, _ = _world(communication=False, trust=trust, shared_memory_store=memory)
    parent.context.agent_scheduler.get_due_agents(1)
    source = _deliver(parent, "pre-consumption-speech")
    baseline = _save(manager, parent)
    assert _records(parent) == ()

    script = r'''
import os, sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.l1_consumption_proof import PROOF_PURPOSE
from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest
from test_l1_consumption_crash_branch import _fork, _reissue, _records, _save
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
active, _, _, _, _ = _world(communication=False, trust=trust, shared_memory_store=MemoryStore())
child = _fork(manager, manager.load_verified(sys.argv[3], timeline_id='social-timeline').metadata,
              active, trust, 'crash-child')
observation = _reissue(child, 'pre-consumption-speech')
phase = sys.argv[4]
def die(marker):
    print(marker, flush=True)
    os._exit(73)
if phase == 'before_consumption':
    die('BEFORE_CONSUMPTION')
original_sign = WindowsDpapiPersistenceTrust.sign
if phase == 'before_signature':
    def crash_sign(self, purpose, payload):
        if purpose == PROOF_PURPOSE: die('AFTER_L1_BEFORE_SIGNATURE')
        return original_sign(self, purpose, payload)
    WindowsDpapiPersistenceTrust.sign = crash_sign
original_commit = MemoryStore._commit_system_proof
if phase in ('before_commit', 'after_commit'):
    def crash_commit(self, *args, **kwargs):
        if phase == 'before_commit': die('SIGNED_BEFORE_CANONICAL_COMMIT')
        result = original_commit(self, *args, **kwargs)
        die('CANONICAL_COMMIT_BEFORE_SAVE')
    MemoryStore._commit_system_proof = crash_commit
child.context.agent_scheduler.schedule_agent('npc-b', child.context.clock.current_time + 1)
child.step()
assert len(_records(child)) == 1
assert phase == 'catalog_published'
original_append = manager._append_journal
def crash_journal(record):
    if record.get('phase') == 'COMMITTED': die('CATALOG_PUBLISHED_BEFORE_COMMIT_JOURNAL')
    return original_append(record)
manager._append_journal = crash_journal
_save(manager, child)
raise AssertionError('crash hook did not fire')
'''
    crash = subprocess.run(
        [sys.executable, "-u", "-c", script, str(trust_path), str(manager.root),
         baseline.save_id, phase], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=40, env=_worker_env(),
    )
    assert crash.returncode == 73, crash.stderr
    assert len(crash.stdout.strip().splitlines()) == 1
    reopened = SaveManager(manager.root, trust=WindowsDpapiPersistenceTrust.open(trust_path))
    assert reopened.load_verified(baseline.save_id, timeline_id="social-timeline")
    child_saves = reopened.list_saves(timeline_id="crash-child")
    assert len(child_saves) == (1 if phase == "catalog_published" else 0)
    assert reopened.verify_consistency()

    # A fresh activation must use only a published checkpoint, then accept a
    # new legal consumption. The dead process's unsigned/unsaved state is absent.
    selected = child_saves[0] if child_saves else baseline
    recovery_trust = reopened.trust
    active, _, _, _, _ = _world(
        communication=False, trust=recovery_trust, shared_memory_store=MemoryStore(),
        timeline_id=selected.timeline_id,
    )
    old_permit = active.write_fence.capture()
    restored = _fork(reopened, selected, active, recovery_trust, "recovered-after-" + phase)
    assert len(_records(restored)) == (1 if phase == "catalog_published" else 0)
    with pytest.raises(PermissionError):
        active.write_fence.require_candidate_origin(old_permit)
    with pytest.raises(PermissionError):
        with restored.write_fence.operation():
            restored.write_fence.require_candidate_origin(old_permit)
    _deliver(restored, "new-after-crash-" + phase)
    fresh = _consume(restored, "new-after-crash-" + phase)
    assert fresh.consumption_timeline_id == "recovered-after-" + phase
    for proof in _records(restored):
        verify_proof(proof, history=restored.context.event_history, trust=recovery_trust,
                     checkpoint_timeline_id=restored.context.event_history.timeline_id,
                     checkpoint_tick=restored.context.clock.current_time)


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI D2 crash-window acceptance")
@pytest.mark.parametrize(("phase", "expected_markers", "published"), (
    ("before_consumption", ("OBSERVATION_READY",), False),
    ("before_signature", ("L1_CONSUMED",), False),
    ("before_commit", ("D2_SIGNED", "BEFORE_CANONICAL_COMMIT"), False),
    ("after_commit", ("CANONICALLY_COMMITTED",), False),
    ("catalog_published", ("CATALOG_PUBLISHED",), True),
))
def test_nonverbal_proof_crash_windows_restore_only_published_checkpoint(
    tmp_path, phase, expected_markers, published,
):
    """D2 issuance, canonical commit and published-checkpoint boundaries survive exits."""
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE, NONVERBAL_PROOF_PURPOSE,
        verify_nonverbal_proof,
    )
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec

    trust_path = tmp_path / "d2-trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    manager = SaveManager(tmp_path / "d2-saves", trust=trust)
    memory = MemoryStore()
    parent, _, _, _, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    baseline = _save(manager, parent)
    assert _nonverbal_records(parent) == ()

    script = r'''
import os, sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.l1_consumption_proof import (
    NONVERBAL_PROOF_MEMORY_TYPE, NONVERBAL_PROOF_PURPOSE,
)
from test_npc_social_interaction import _world
from test_l1_consumption_crash_branch import (
    _fork, _nonverbal_records, _reissue_nonverbal, _save,
)
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
baseline = manager.load_verified(sys.argv[3], timeline_id='social-timeline').metadata
active, _, _, _, _ = _world(
    communication=False, trust=trust, shared_memory_store=MemoryStore(),
    complete_environment=True,
)
child = _fork(manager, baseline, active, trust, 'd2-crash-child')
child.context.agent_scheduler.get_due_agents(child.context.clock.current_time + 1)
observation = _reissue_nonverbal(child)
phase = sys.argv[4]
def die(marker):
    print(marker, flush=True)
    os._exit(73)
if phase == 'before_consumption':
    die('OBSERVATION_READY')
child.context.agent_scheduler.schedule_agent(
    observation.observer_id, child.context.clock.current_time + 1,
)
original_sign = WindowsDpapiPersistenceTrust.sign
signed = {'d2': False}
def tracked_sign(self, purpose, payload):
    result = original_sign(self, purpose, payload)
    if purpose == NONVERBAL_PROOF_PURPOSE:
        signed['d2'] = True
    return result
WindowsDpapiPersistenceTrust.sign = tracked_sign
original_commit = MemoryStore._commit_system_proof
if phase == 'before_signature':
    def crash_before_signature(self, *args, **kwargs):
        die('L1_CONSUMED')
    WindowsDpapiPersistenceTrust.sign = crash_before_signature
elif phase == 'before_commit':
    def crash_before_commit(self, memory, *args, **kwargs):
        if memory.type == NONVERBAL_PROOF_MEMORY_TYPE:
            assert signed['d2']
            print('D2_SIGNED', flush=True)
            die('BEFORE_CANONICAL_COMMIT')
        return original_commit(self, memory, *args, **kwargs)
    MemoryStore._commit_system_proof = crash_before_commit
elif phase == 'after_commit':
    def crash_after_commit(self, memory, *args, **kwargs):
        result = original_commit(self, memory, *args, **kwargs)
        if memory.type == NONVERBAL_PROOF_MEMORY_TYPE:
            die('CANONICALLY_COMMITTED')
        return result
    MemoryStore._commit_system_proof = crash_after_commit
child.step()
assert len(_nonverbal_records(child)) == 1
assert phase == 'catalog_published'
original_append = manager._append_journal
def crash_after_catalog_publication(record):
    if record.get('phase') == 'COMMITTED':
        die('CATALOG_PUBLISHED')
    return original_append(record)
manager._append_journal = crash_after_catalog_publication
_save(manager, child)
raise AssertionError('crash hook did not fire')
'''
    crash = subprocess.run(
        [sys.executable, "-u", "-c", script, str(trust_path), str(manager.root),
         baseline.save_id, phase], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=60, env=_worker_env(),
    )
    assert crash.returncode == 73, crash.stderr
    for marker in expected_markers:
        assert marker in crash.stdout

    reopened = SaveManager(manager.root, trust=WindowsDpapiPersistenceTrust.open(trust_path))
    child_saves = reopened.list_saves(timeline_id="d2-crash-child")
    assert len(child_saves) == int(published)
    assert reopened.verify_consistency()
    selected = child_saves[0] if published else reopened.load_verified(
        baseline.save_id, timeline_id="social-timeline",
    ).metadata
    checkpoint = reopened.load_verified(
        selected.save_id, timeline_id=selected.timeline_id,
    )
    signed_snapshot = cognitive_snapshot_codec().loads(checkpoint.cognitive_snapshot)
    selected_proofs = tuple(
        record.value.content
        for store in signed_snapshot.body.stores if store.store_name == "memories"
        for record in store.records
        if record.value.type == NONVERBAL_PROOF_MEMORY_TYPE
    )
    assert len(selected_proofs) == int(published)

    recovery_trust = reopened.trust
    active, _, _, _, _ = _world(
        communication=False, trust=recovery_trust, shared_memory_store=MemoryStore(),
        complete_environment=True, timeline_id=selected.timeline_id,
    )
    old_permit = active.write_fence.capture()
    restored = _fork(
        reopened, selected, active, recovery_trust, "d2-recovered-" + phase,
    )
    restored_proofs = _nonverbal_records(restored)
    assert len(restored_proofs) == int(published)
    for proof in restored_proofs:
        verify_nonverbal_proof(
            proof, history=restored.context.event_history, trust=recovery_trust,
            checkpoint_timeline_id=restored.context.event_history.timeline_id,
            checkpoint_tick=restored.context.clock.current_time,
        )
    with pytest.raises(PermissionError):
        active.write_fence.require_candidate_origin(old_permit)

    recovered_observation = _reissue_nonverbal(restored)
    restored.context.agent_scheduler.get_due_agents(
        restored.context.clock.current_time + 1,
    )
    restored.context.agent_scheduler.schedule_agent(
        recovered_observation.observer_id, restored.context.clock.current_time + 1,
    )
    restored.step()
    after_resume = _nonverbal_records(restored)
    assert len(after_resume) == int(published) + 1
    assert after_resume[-1].consumption_timeline_id == "d2-recovered-" + phase


def test_nonverbal_late_l1_issuance_cannot_cross_restore_generation(tmp_path, monkeypatch):
    from threading import Event, Thread

    from cognitive_world.core.persistence import HmacPersistenceTrust
    from cognitive_world.runtime.write_fence import RuntimeWriteFence

    trust = HmacPersistenceTrust(b"d2-late-permit-test-key-material-32")
    manager = SaveManager(tmp_path / "saves", trust=trust)
    memory = MemoryStore()
    active, _, _, _, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    baseline = _save(manager, active)
    active.context.agent_scheduler.get_due_agents(active.context.clock.current_time + 1)
    observation = _reissue_nonverbal(active)
    active.context.agent_scheduler.schedule_agent(
        observation.observer_id, active.context.clock.current_time + 1,
    )
    issuer = active.agent_action_loop.agent_turn.l1_consumption_issuer
    original_issue = issuer.issue_after_l1
    issuance_reached = Event()
    allow_issue = Event()
    captured_permits = []
    failures = []

    def delay_after_real_l1_consumption(**kwargs):
        permit = RuntimeWriteFence.bind_current_permit()
        captured_permits.append(permit)
        issuance_reached.set()
        if not allow_issue.wait(10):
            raise AssertionError("delayed L1 issuance was not released")
        return original_issue(**kwargs)

    monkeypatch.setattr(issuer, "issue_after_l1", delay_after_real_l1_consumption)

    def execute_old_turn():
        try:
            active.step()
        except BaseException as error:
            failures.append(error)

    worker = Thread(target=execute_old_turn)
    worker.start()
    assert issuance_reached.wait(10)
    assert len(captured_permits) == 1 and captured_permits[0] is not None

    staged = manager.stage_restore(
        baseline.save_id, timeline_id=baseline.timeline_id,
        active_runtime=active, assembler=LocalRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="d2-late-child",
    )
    restored = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
    allow_issue.set()
    worker.join(10)
    assert not worker.is_alive()
    assert active.write_fence.retired
    with pytest.raises(PermissionError):
        active.write_fence.require_candidate_origin(captured_permits[0])
    with pytest.raises(PermissionError):
        with restored.write_fence.operation():
            restored.write_fence.require_candidate_origin(captured_permits[0])
    assert _nonverbal_records(active) == ()
    assert _nonverbal_records(restored) == ()
    assert not failures
