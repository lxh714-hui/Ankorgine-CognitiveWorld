from dataclasses import replace
import os
from pathlib import Path
import json
import subprocess
import sys
from threading import Event, Thread
import time

import pytest

from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.emotion import Emotion
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.memory import Memory, MemoryDecisionProvenance
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
from cognitive_world.cognition.personality import Personality
from cognitive_world.cognition.self_model import SelfModel
from cognitive_world.cognition.snapshot import (
    CognitiveAgentManifestEntry, CognitiveStateSnapshot,
    cognitive_snapshot_codec, reconstruct_isolated,
    _COGNITIVE_SNAPSHOT_PURPOSE_V2, _COGNITIVE_SNAPSHOT_PURPOSE_V3,
)
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.core.world_state import WorldState
from cognitive_world.core.persistence import sha256_hex, WindowsDpapiPersistenceTrust
from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
from cognitive_world.core.timeline import TimelineForkManifest
from cognitive_world.decision.behavior_feedback import BehaviorFailure, BehaviorFeedback
from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
from _trusted_event_support import make_system_event


class FakeTrust:
    def __init__(self):
        self.key = b"snapshot-test-only-key"

    def sign(self, purpose, payload):
        import hashlib, hmac
        return hmac.new(self.key, purpose.encode() + b"\0" + payload, hashlib.sha256).digest()

    def verify(self, purpose, payload, signature):
        import hmac
        return hmac.compare_digest(self.sign(purpose, payload), signature)


def _fixture():
    cognition = CognitionContainer()
    cognition.add_belief(Belief("belief-a", "agent-a", "door is shut", ["event-not-loaded"], .7))
    cognition.add_goal(Goal("goal-a", "agent-a", "inspect", .8, source_refs=["obs-a"]))
    cognition.add_self_model(SelfModel("agent-a", self_beliefs=[{
        "claim": "careful", "status": "tentative", "source_refs": ["obs-a"],
        "source_event_ids": ["event-not-loaded"],
    }]))
    cognition.add_personality(Personality("agent-a", traits={"steady": True}))
    cognition.add_personality(Personality("agent-b", traits={"steady": False}))
    cognition.add_emotion(Emotion("emotion-a", "agent-a", levels={"concern": .4},
                                 last_update_tick=4, processed_sources=("event-not-loaded",)))
    cognition.add_belief(Belief("belief-b", "agent-b", "unknown", [], .2))
    memory_store = MemoryStore.from_isolated_snapshot((
        Memory("memory-a", "agent-a", "experience", {"summary": "observed"}, .5,
               "event-not-loaded"),
    ))
    contexts = (
        CognitionContext.from_character(Character(
            "character-a", "agent-a", "agent-a", ["memory-a"], ["belief-a"],
            "emotion-a", goal_ids=["goal-a"],
        ), cognition, memory_store),
        CognitionContext.from_character(Character(
            "character-b", "agent-b", "agent-b", [], ["belief-b"], "", goal_ids=[]
        ), cognition, memory_store),
    )
    fence = RuntimeWriteFence("snapshot-session")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a", "character-a"))
    registry.register(RuntimeAgent("agent-b", "character-b"))
    runtime = SimulationRuntime(RuntimeContext(
        SimulationClock(9), WorldState(), EventHistory(timeline_id="timeline-alpha"),
        agent_registry=registry
    ), write_fence=fence)
    for context in contexts:
        context.bind_write_fence(fence)
    return cognition, memory_store, contexts, runtime


def _capture(runtime, cognition, memory_store, contexts, *, trust=None):
    with runtime.write_fence.operation():
        return CognitiveStateSnapshot.capture(
            cognition=cognition, memory_store=memory_store, runtime=runtime,
            agent_contexts=contexts, timeline_id="timeline-alpha",
            trust=trust,
        )


def _expected_manifest():
    return (
        CognitiveAgentManifestEntry("agent-a", "character-a"),
        CognitiveAgentManifestEntry("agent-b", "character-b"),
    )


def test_all_canonical_stores_capture_consistently_and_rebuild_in_isolation():
    cognition, memories, contexts, runtime = _fixture()
    snapshot = _capture(runtime, cognition, memories, contexts)
    restored_bytes = CognitiveStateSnapshot.from_bytes(snapshot.to_bytes())
    restored = reconstruct_isolated(restored_bytes, expected_agents=_expected_manifest())

    assert restored.completeness == "complete-for-verified-Agent-manifest-and-supported-stores"
    assert restored.authenticity == "content-digest-only"
    assert restored.timeline_id == "timeline-alpha" and restored.simulation_tick == 9
    assert set(restored.agent_ids) == {"agent-a", "agent-b"}
    assert {(item.agent_id, item.character_id) for item in restored.expected_agents} == {
        ("agent-a", "character-a"), ("agent-b", "character-b")
    }
    assert restored.agent_registry_revision == 2
    assert {store.store_name for store in snapshot.body.stores} == {
        "beliefs", "goals", "self_models", "memories", "emotions", "personalities"
    }
    assert restored.cognition.belief_store.get_by_id("belief-a").content == "door is shut"
    assert restored.cognition.goal_store.get_owned("agent-a", "goal-a").description == "inspect"
    assert restored.cognition.self_model_store.get("agent-a").self_beliefs[0]["claim"] == "careful"
    assert restored.cognition.personality_store.get("agent-a").traits == {"steady": True}
    assert restored.cognition.get_emotion("emotion-a").last_update_tick == 4
    assert restored.memory_store.get_memory("memory-a").source_event == "event-not-loaded"
    assert all(store.revision_semantics == "canonical-content-digest" for store in snapshot.body.stores)
    assert snapshot.body.stores[0].records[0].sources[0].verification == "unverified_reference"
    assert cognition.belief_store.get_by_id("belief-a").content == "door is shut"


def test_snapshot_signature_requires_external_trust_and_is_verified():
    cognition, memories, contexts, runtime = _fixture()
    trust = FakeTrust()
    snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    with pytest.raises(PermissionError, match="trust verifier"):
        CognitiveStateSnapshot.from_bytes(snapshot.to_bytes())
    verified = CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust)
    restored = reconstruct_isolated(verified, trust=trust, expected_agents=_expected_manifest())
    assert restored.authenticity == "signature-verified"


def test_capture_requires_all_stores_on_same_fence_and_current_operation():
    cognition, memories, contexts, runtime = _fixture()
    fence = runtime.write_fence
    other_store = MemoryStore()
    other_store.bind_write_fence(RuntimeWriteFence("other-session"))
    with pytest.raises(PermissionError, match="RuntimeWriteFence"):
        CognitiveStateSnapshot.capture(
            cognition=cognition, memory_store=other_store, runtime=runtime,
                agent_contexts=contexts, timeline_id="timeline-alpha",
        )
    with pytest.raises(PermissionError, match="captured runtime context"):
        CognitiveStateSnapshot.capture(
            cognition=cognition, memory_store=memories, runtime=runtime,
                agent_contexts=contexts, timeline_id="timeline-alpha",
        )


def test_snapshot_scope_serializes_capture_with_canonical_commit():
    cognition, memories, contexts, runtime = _fixture()
    fence = runtime.write_fence
    entered = Event()
    release = Event()
    original_get_all = cognition.belief_store.get_all

    def blocked_get_all():
        entered.set()
        assert release.wait(3)
        return original_get_all()

    cognition.belief_store.get_all = blocked_get_all
    captured = []
    capture_thread = Thread(target=lambda: captured.append(
        _capture(runtime, cognition, memories, contexts)
    ))
    capture_thread.start()
    assert entered.wait(3)
    committed = Event()

    def writer():
        with fence.operation():
            cognition.belief_store.add(Belief("late", "agent-a", "after snapshot"))
        committed.set()

    write_thread = Thread(target=writer)
    write_thread.start()
    time.sleep(.03)
    assert not committed.is_set()
    release.set()
    capture_thread.join(3)
    write_thread.join(3)
    assert not capture_thread.is_alive() and not write_thread.is_alive()
    assert "late" not in {item.record_id for store in captured[0].body.stores
                           if store.store_name == "beliefs" for item in store.records}
    assert cognition.belief_store.get_by_id("late") is not None


def test_registry_membership_change_waits_for_capture_and_cannot_mix_roster():
    cognition, memories, contexts, runtime = _fixture()
    registry = runtime.context.agent_registry
    assert registry is not None
    entered = Event()
    release = Event()
    original_get_all = cognition.belief_store.get_all

    def blocked_get_all():
        entered.set()
        assert release.wait(3)
        return original_get_all()

    cognition.belief_store.get_all = blocked_get_all
    captured = []
    capture_thread = Thread(target=lambda: captured.append(
        _capture(runtime, cognition, memories, contexts)
    ))
    capture_thread.start()
    assert entered.wait(3)
    registering = Event()
    registered = Event()

    def add_agent():
        registering.set()
        registry.register(RuntimeAgent("agent-c", "character-c"))
        registered.set()

    registration_thread = Thread(target=add_agent)
    registration_thread.start()
    assert registering.wait(3)
    time.sleep(.03)
    assert not registered.is_set()
    release.set()
    capture_thread.join(3)
    registration_thread.join(3)
    assert not capture_thread.is_alive() and not registration_thread.is_alive()
    assert captured[0].body.agent_ids == ("agent-a", "agent-b")
    assert tuple(item.agent_id for item in captured[0].body.expected_agents) == (
        "agent-a", "agent-b"
    )
    assert registered.is_set()


def test_missing_linked_state_owner_mismatch_and_duplicate_context_fail_closed():
    cognition, memories, contexts, runtime = _fixture()
    with pytest.raises(ValueError, match="missing=\\['agent-b'\\]"):
        _capture(runtime, cognition, memories, contexts[:1])
    bad_context = CognitionContext.from_character(Character(
        "character-missing", "agent-c", "missing-personality", [], ["missing-belief"], ""
    ), cognition, memories)
    with pytest.raises(ValueError, match="unregistered=\\['agent-c'\\]"):
        _capture(runtime, cognition, memories, contexts + (bad_context,))
    with pytest.raises(ValueError, match="duplicate CognitionContext owners"):
        _capture(runtime, cognition, memories, contexts + (contexts[0],))
    wrong_character = CognitionContext.from_character(Character(
        "character-wrong", "agent-a", "agent-a", [], ["belief-a"], "emotion-a",
        goal_ids=["goal-a"],
    ), cognition, memories)
    with pytest.raises(ValueError, match="Character does not match"):
        _capture(runtime, cognition, memories, (wrong_character, contexts[1]))


def test_capture_requires_runtime_authoritative_registry():
    cognition, memories, contexts, runtime = _fixture()
    runtime.context.agent_registry = None
    with pytest.raises(PermissionError, match="authoritative AgentRegistry"):
        _capture(runtime, cognition, memories, contexts)


def test_missing_context_linked_canonical_record_prevents_complete_capture():
    cognition, memories, contexts, runtime = _fixture()
    cognition.belief_store._beliefs.pop("belief-a")
    with pytest.raises(ValueError, match="references missing beliefs state"):
        _capture(runtime, cognition, memories, contexts)


def test_unknown_canonical_container_state_is_not_silently_omitted():
    cognition, memories, contexts, runtime = _fixture()
    cognition.future_canonical_state = {"owner": "agent-a"}
    with pytest.raises(TypeError, match="unsupported state outside the snapshot contract"):
        _capture(runtime, cognition, memories, contexts)


def test_schema_source_and_owner_tampering_are_rejected_without_touching_live_stores():
    cognition, memories, contexts, runtime = _fixture()
    snapshot = _capture(runtime, cognition, memories, contexts)
    before = cognition.belief_store.get_all()
    body = snapshot.body
    belief_store = next(item for item in body.stores if item.store_name == "beliefs")
    record = belief_store.records[0]
    changed_record = replace(record, owner_id="agent-b")
    changed_beliefs = replace(belief_store, records=(changed_record,) + belief_store.records[1:])
    changed_stores = tuple(changed_beliefs if item is belief_store else item for item in body.stores)
    changed_body = replace(body, stores=changed_stores)
    tampered = replace(snapshot, body=changed_body)
    with pytest.raises(ValueError, match="digest mismatch"):
        reconstruct_isolated(tampered, expected_agents=_expected_manifest())
    assert cognition.belief_store.get_all() == before

    with pytest.raises(ValueError, match="unsupported CognitiveStateSnapshot"):
        replace(body, schema_version=99)

    # Recompute ordinary hashes to distinguish schema/owner checks from mere
    # digest protection. Without a production trust root this remains an
    # unauthenticated document and must still reject internal inconsistency.
    codec = cognitive_snapshot_codec()
    wrong_owner = replace(record, owner_id="agent-b")
    altered_records = (wrong_owner,) + belief_store.records[1:]
    unsigned_store = replace(belief_store, records=altered_records,
                             state_version="sha256:pending")
    signed_store_digest = "sha256:" + sha256_hex(codec.dumps(unsigned_store))
    altered_store = replace(unsigned_store, state_version=signed_store_digest)
    altered_stores = tuple(altered_store if item.store_name == "beliefs" else item
                            for item in body.stores)
    altered_body = replace(body, stores=altered_stores)
    untrusted_but_rehashed = replace(
        snapshot, body=altered_body,
        content_digest="sha256:" + sha256_hex(codec.dumps(altered_body)),
    )
    with pytest.raises(ValueError, match="record owner mismatch"):
        reconstruct_isolated(untrusted_but_rehashed, expected_agents=_expected_manifest())


def test_source_marked_in_event_history_must_be_present_during_validation():
    cognition, memories, contexts, runtime = _fixture()
    runtime.context.event_history.append(make_system_event("event-not-loaded"))
    snapshot = _capture(runtime, cognition, memories, contexts)
    assert any(source.verification == "event_history_reference_present"
               for store in snapshot.body.stores for record in store.records
               for source in record.sources)
    with pytest.raises(PermissionError, match="absent from supplied EventHistory"):
        reconstruct_isolated(snapshot, expected_agents=_expected_manifest())
    restored = reconstruct_isolated(
        snapshot, expected_agents=_expected_manifest(),
        event_history=runtime.context.event_history,
    )
    assert restored.completeness == "complete-for-verified-Agent-manifest-and-supported-stores"


def test_reconstruction_requires_independent_roster_even_for_well_formed_snapshot():
    cognition, memories, contexts, runtime = _fixture()
    snapshot = _capture(runtime, cognition, memories, contexts)
    with pytest.raises(PermissionError, match="independent expected Agent manifest"):
        reconstruct_isolated(snapshot)
    with pytest.raises(ValueError, match="does not match independent expected manifest"):
        reconstruct_isolated(snapshot, expected_agents=(
            CognitiveAgentManifestEntry("agent-a", "character-a"),
        ))


def test_unsupported_canonical_payload_fails_capture_instead_of_partial_snapshot():
    cognition, memories, contexts, runtime = _fixture()
    with runtime.write_fence.operation():
        cognition.belief_store.add(Belief("bad", "agent-a", object(), [], .1))
    with runtime.write_fence.operation():
        with pytest.raises(TypeError, match="unsupported persisted value"):
            CognitiveStateSnapshot.capture(
                cognition=cognition, memory_store=memories, runtime=runtime,
                agent_contexts=contexts, timeline_id="timeline-alpha",
            )


def test_signed_bundle_binds_world_and_cognition_timeline_tick_and_roster():
    cognition, memories, contexts, runtime = _fixture()
    trust = FakeTrust()
    cognitive_snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    world_checkpoint = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=world_checkpoint, cognitive_snapshot=cognitive_snapshot,
        expected_agents=_expected_manifest(), trust=trust,
    )
    assert manifest.version == 1
    restored_manifest = SnapshotBundleManifest.from_bytes(manifest.to_bytes())
    staged = restored_manifest.verify_and_stage(
        world_checkpoint=world_checkpoint,
        cognitive_snapshot=cognitive_snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
    )
    assert staged.timeline_id == "timeline-alpha" and staged.simulation_tick == 9
    assert staged.cognition.agent_ids == ("agent-a", "agent-b")
    assert staged.behavior_feedback_status == "legacy_not_captured"
    assert staged.behavior_feedback.history == []

    other_timeline = runtime.context.world_state.export_persisted_snapshot(
        event_history=EventHistory(timeline_id="timeline-beta"), simulation_tick=9,
        timeline_id="timeline-beta", trust=trust,
    )
    with pytest.raises(PermissionError, match="component digest"):
        restored_manifest.verify_and_stage(
            world_checkpoint=other_timeline,
            cognitive_snapshot=cognitive_snapshot.to_bytes(),
            expected_agents=_expected_manifest(), trust=trust,
        )
    other_tick = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=10,
        timeline_id="timeline-alpha", trust=trust,
    )
    with pytest.raises(PermissionError, match="component digest"):
        restored_manifest.verify_and_stage(
            world_checkpoint=other_tick,
            cognitive_snapshot=cognitive_snapshot.to_bytes(),
            expected_agents=_expected_manifest(), trust=trust,
        )


def test_timeline_fork_manifest_is_checkpoint_anchored_and_does_not_relabel_history():
    cognition, memories, contexts, runtime = _fixture()
    trust = FakeTrust()
    cognitive_snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    world_checkpoint = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    bundle = SnapshotBundleManifest.create(
        world_checkpoint=world_checkpoint, cognitive_snapshot=cognitive_snapshot,
        expected_agents=_expected_manifest(), trust=trust,
    )
    staged = bundle.verify_and_stage(
        world_checkpoint=world_checkpoint,
        cognitive_snapshot=cognitive_snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
    )
    fork = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=bundle, verified_bundle=staged,
        trust=trust, timeline_id="timeline-beta",
    )

    verified = TimelineForkManifest.from_bytes(fork.to_bytes())
    verified.verify_against_checkpoint(bundle, verified_bundle=staged, trust=trust)
    assert verified.timeline_id == "timeline-beta"
    assert verified.parent_timeline_id == "timeline-alpha"
    assert verified.simulation_tick == 9
    assert verified.fork_checkpoint_id != "timeline-alpha"
    # This metadata proves the parent checkpoint relationship only. It does
    # not alter or assign branch ownership to the flat EventHistory.
    assert runtime.context.event_history.get_events() == ()

    with pytest.raises(PermissionError, match="signature"):
        replace(verified, parent_timeline_id="timeline-other").verify_against_checkpoint(
            bundle, verified_bundle=staged, trust=trust,
        )
    with pytest.raises(PermissionError, match="signature"):
        replace(verified, timeline_id="timeline-forged").verify_against_checkpoint(
            bundle, verified_bundle=staged, trust=trust,
        )


def test_verified_bundle_cannot_be_cross_paired_with_another_signed_manifest():
    trust = FakeTrust()
    cognition_a, memories_a, contexts_a, runtime_a = _fixture()
    snapshot_a = _capture(runtime_a, cognition_a, memories_a, contexts_a, trust=trust)
    feedback_a = BehaviorFeedbackSnapshot.capture(
        feedback=BehaviorFeedback(), event_history=runtime_a.context.event_history,
        timeline_id="timeline-alpha", simulation_tick=9,
        session_id="snapshot-session", restore_generation=0,
        agent_ids=("agent-a", "agent-b"),
    )
    world_a = runtime_a.context.world_state.export_persisted_snapshot(
        event_history=runtime_a.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest_a = SnapshotBundleManifest.create(
        world_checkpoint=world_a, cognitive_snapshot=snapshot_a,
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_a,
    )
    verified_a = manifest_a.verify_and_stage(
        world_checkpoint=world_a, cognitive_snapshot=snapshot_a.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_a,
    )

    cognition_b, memories_b, contexts_b, runtime_b = _fixture()
    memories_b._memories["memory-a"] = replace(
        memories_b.get_memory("memory-a"), content={"summary": "different canonical content"},
    )
    snapshot_b = _capture(runtime_b, cognition_b, memories_b, contexts_b, trust=trust)
    feedback_b = BehaviorFeedbackSnapshot.capture(
        feedback=BehaviorFeedback(), event_history=runtime_b.context.event_history,
        timeline_id="timeline-alpha", simulation_tick=9,
        session_id="snapshot-session", restore_generation=0,
        agent_ids=("agent-a", "agent-b"),
    )
    world_b = runtime_b.context.world_state.export_persisted_snapshot(
        event_history=runtime_b.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest_b = SnapshotBundleManifest.create(
        world_checkpoint=world_b, cognitive_snapshot=snapshot_b,
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_b,
    )
    verified_b = manifest_b.verify_and_stage(
        world_checkpoint=world_b, cognitive_snapshot=snapshot_b.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_b,
    )

    assert manifest_a.version == manifest_b.version == 2
    assert manifest_a.timeline_id == manifest_b.timeline_id
    assert manifest_a.simulation_tick == manifest_b.simulation_tick
    assert manifest_a.event_chain_head_sha256 == manifest_b.event_chain_head_sha256
    assert manifest_a.cognitive_snapshot_sha256 != manifest_b.cognitive_snapshot_sha256
    fork_b = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=manifest_b, verified_bundle=verified_b,
        trust=trust, timeline_id="timeline-child-b",
    )
    with pytest.raises(PermissionError, match="exact manifest"):
        fork_b.verify_against_checkpoint(
            manifest_b, verified_bundle=verified_a, trust=trust,
        )
    with pytest.raises(PermissionError, match="exact manifest"):
        MemoryRevisionLineage.fork_from_verified_bundle(
            verified_bundle=verified_a, checkpoint_manifest=manifest_b,
            timeline_id=fork_b.timeline_id, fork_manifest=fork_b, trust=trust,
        )

    fork_a = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=manifest_a, verified_bundle=verified_a,
        trust=trust, timeline_id="timeline-child-a",
    )
    lineage_a = MemoryRevisionLineage.fork_from_verified_bundle(
        verified_bundle=verified_a, checkpoint_manifest=manifest_a,
        timeline_id=fork_a.timeline_id, fork_manifest=fork_a, trust=trust,
    )
    assert lineage_a.timeline_id == fork_a.timeline_id


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_dpapi_verified_bundle_rejects_cross_paired_signed_manifest(tmp_path):
    trust = WindowsDpapiPersistenceTrust.initialize(tmp_path / "dpapi-trust.json")
    cognition_a, memories_a, contexts_a, runtime_a = _fixture()
    snapshot_a = _capture(runtime_a, cognition_a, memories_a, contexts_a, trust=trust)
    world_a = runtime_a.context.world_state.export_persisted_snapshot(
        event_history=runtime_a.context.event_history,
        simulation_tick=9, timeline_id="timeline-alpha", trust=trust,
    )
    feedback_a = BehaviorFeedbackSnapshot.capture(
        feedback=BehaviorFeedback(), event_history=runtime_a.context.event_history,
        timeline_id="timeline-alpha", simulation_tick=9,
        session_id="snapshot-session", restore_generation=0,
        agent_ids=("agent-a", "agent-b"),
    )
    manifest_a = SnapshotBundleManifest.create(
        world_checkpoint=world_a, cognitive_snapshot=snapshot_a,
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_a,
    )
    verified_a = manifest_a.verify_and_stage(
        world_checkpoint=world_a, cognitive_snapshot=snapshot_a.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_a,
    )
    fork_a = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=manifest_a, verified_bundle=verified_a,
        trust=trust, timeline_id="timeline-child-a",
    )
    lineage_a = MemoryRevisionLineage.fork_from_verified_bundle(
        verified_bundle=verified_a, checkpoint_manifest=manifest_a,
        timeline_id=fork_a.timeline_id, fork_manifest=fork_a, trust=trust,
    )
    lineage_a.validate_records(verified_a.cognition.memory_store.get_all_memories())

    cognition_b, memories_b, contexts_b, runtime_b = _fixture()
    with runtime_b.write_fence.operation():
        cognition_b.add_belief(Belief("belief-extra", "agent-a", "different", [], .2))
    snapshot_b = _capture(runtime_b, cognition_b, memories_b, contexts_b, trust=trust)
    world_b = runtime_b.context.world_state.export_persisted_snapshot(
        event_history=runtime_b.context.event_history,
        simulation_tick=9, timeline_id="timeline-alpha", trust=trust,
    )
    feedback_b = BehaviorFeedbackSnapshot.capture(
        feedback=BehaviorFeedback(), event_history=runtime_b.context.event_history,
        timeline_id="timeline-alpha", simulation_tick=9,
        session_id="snapshot-session", restore_generation=0,
        agent_ids=("agent-a", "agent-b"),
    )
    manifest_b = SnapshotBundleManifest.create(
        world_checkpoint=world_b, cognitive_snapshot=snapshot_b,
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_b,
    )
    verified_b = manifest_b.verify_and_stage(
        world_checkpoint=world_b, cognitive_snapshot=snapshot_b.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_b,
    )
    fork_b = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=manifest_b, verified_bundle=verified_b,
        trust=trust, timeline_id="timeline-child-b",
    )
    lineage_b = MemoryRevisionLineage.fork_from_verified_bundle(
        verified_bundle=verified_b, checkpoint_manifest=manifest_b,
        timeline_id=fork_b.timeline_id, fork_manifest=fork_b, trust=trust,
    )
    lineage_b.validate_records(verified_b.cognition.memory_store.get_all_memories())

    assert manifest_a.timeline_id == manifest_b.timeline_id
    assert manifest_a.simulation_tick == manifest_b.simulation_tick
    assert manifest_a.event_chain_head_sha256 == manifest_b.event_chain_head_sha256
    assert manifest_a.cognitive_snapshot_sha256 != manifest_b.cognitive_snapshot_sha256
    with pytest.raises(PermissionError, match="exact manifest"):
        TimelineForkManifest.create_from_checkpoint(
            checkpoint_manifest=manifest_b, verified_bundle=verified_a,
            trust=trust, timeline_id="timeline-cross-paired",
        )
    with pytest.raises(PermissionError, match="exact manifest"):
        fork_b.verify_against_checkpoint(
            manifest_b, verified_bundle=verified_a, trust=trust,
        )
    with pytest.raises(PermissionError, match="exact manifest"):
        MemoryRevisionLineage.fork_from_verified_bundle(
            verified_bundle=verified_a, checkpoint_manifest=manifest_b,
            timeline_id=fork_b.timeline_id, fork_manifest=fork_b, trust=trust,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_dpapi_signed_cognitive_bundle_verifies_in_a_new_process(tmp_path):
    trust_path = tmp_path / "trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    cognition, memories, contexts, runtime = _fixture()
    _add_memory_v2_chain(memories)
    cognitive = _capture(runtime, cognition, memories, contexts, trust=trust)
    world = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=world, cognitive_snapshot=cognitive,
        expected_agents=_expected_manifest(), trust=trust,
    )
    world_path, cognition_path, manifest_path = (
        tmp_path / "world.json", tmp_path / "cognition.json", tmp_path / "manifest.json",
    )
    world_path.write_bytes(world)
    cognition_path.write_bytes(cognitive.to_bytes())
    manifest_path.write_bytes(manifest.to_bytes())
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    script = (
        "import sys; from pathlib import Path; "
        "from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust; "
        "from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest; "
        "from cognitive_world.cognition.snapshot import CognitiveAgentManifestEntry; "
        "trust=WindowsDpapiPersistenceTrust.open(sys.argv[1]); "
        "manifest=SnapshotBundleManifest.from_bytes(Path(sys.argv[4]).read_bytes()); "
        "roster=(CognitiveAgentManifestEntry('agent-a','character-a'), "
        "CognitiveAgentManifestEntry('agent-b','character-b')); "
        "staged=manifest.verify_and_stage(world_checkpoint=Path(sys.argv[2]).read_bytes(), "
        "cognitive_snapshot=Path(sys.argv[3]).read_bytes(), expected_agents=roster, trust=trust); "
        "assert staged.timeline_id=='timeline-alpha' and staged.simulation_tick==9; "
        "memory=staged.cognition.memory_store.get_memory('memory-revision-2'); "
        "assert memory.schema_version==2 and memory.decision_provenance.policy_id=='host-memory-policy'"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(trust_path), str(world_path),
         str(cognition_path), str(manifest_path)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, env=env,
    )
    assert completed.returncode == 0, completed.stderr


def _memory_v2(owner="agent-a", *, record_id="memory-revision-2",
               supersedes="memory-revision-1", decision_id="decision-2"):
    provenance = MemoryDecisionProvenance(
        schema_version=1,
        decision_id=decision_id,
        policy_id="host-memory-policy",
        policy_version="1.0",
        proposal_id="proposal-2",
        proposal_digest="a" * 64,
        input_digest="b" * 64,
        reason_code="accepted.by-policy",
        owner_id=owner,
        source_event_ids=("event-not-loaded", "event-context"),
        timeline_id="timeline-alpha",
        session_id="snapshot-session",
        restore_generation=0,
        supersedes_record_id=supersedes,
    )
    return Memory(
        id=record_id, owner_id=owner, type="experience",
        content={"summary": "revised"}, importance=0.6,
        source_event="event-not-loaded", schema_version=2,
        decision_provenance=provenance, logical_record_id="logical-memory-a",
        supersedes_record_id=supersedes,
    )


def _add_memory_v2_chain(memory_store):
    first = _memory_v2(record_id="memory-revision-1", supersedes=None,
                       decision_id="decision-1")
    second = _memory_v2()
    memory_store._memories[first.id] = first
    memory_store._memories[second.id] = second
    return first, second


def test_memory_v1_codec_preserves_legacy_canonical_fields_and_semantics():
    codec = cognitive_snapshot_codec()
    legacy = Memory("legacy", "agent-a", "experience", {"note": "old"}, .4, "event-old")
    encoded = codec.encode(legacy)
    assert set(encoded["fields"]) == {
        "id", "owner_id", "type", "content", "importance", "source_event", "metadata",
    }
    legacy_fields = {
        "id": legacy.id,
        "owner_id": legacy.owner_id,
        "type": legacy.type,
        "content": codec.encode(legacy.content),
        "importance": legacy.importance,
        "source_event": legacy.source_event,
        "metadata": codec.encode(legacy.metadata),
    }
    expected_legacy_bytes = json.dumps(
        {"$record": "cognitive_world.cognition.memory:Memory", "fields": legacy_fields},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    assert codec.dumps(legacy) == expected_legacy_bytes
    restored = codec.loads(codec.dumps(legacy))
    assert restored.schema_version == 1
    assert restored.decision_provenance is None
    assert restored.supersedes_record_id is None
    assert codec.dumps(restored) == codec.dumps(legacy)


def test_memory_v2_provenance_has_strict_canonical_roundtrip():
    codec = cognitive_snapshot_codec()
    memory = _memory_v2()
    restored = codec.loads(codec.dumps(memory))
    assert restored == memory
    assert restored.schema_version == 2
    assert restored.id == "memory-revision-2"
    assert restored.logical_record_id == "logical-memory-a"
    assert restored.decision_provenance.owner_id == restored.owner_id
    assert restored.supersedes_record_id == "memory-revision-1"
    assert codec.dumps(restored) == codec.dumps(memory)
    with pytest.raises(ValueError, match="unsupported MemoryDecisionProvenance"):
        replace(memory.decision_provenance, schema_version=2)
    with pytest.raises(ValueError, match="owner mismatch"):
        replace(memory, owner_id="agent-b")
    encoded = codec.encode(memory)
    encoded["fields"]["unrecognized"] = True
    with pytest.raises(ValueError, match="schema mismatch"):
        codec.decode(encoded)


def test_snapshot_v2_keeps_legacy_signature_purpose_and_v1_memory_encoding():
    trust = FakeTrust()
    cognition, memories, contexts, runtime = _fixture()
    captured = _capture(runtime, cognition, memories, contexts)
    body = replace(captured.body, schema_version=2)
    codec = cognitive_snapshot_codec()
    body_bytes = codec.dumps(body)
    legacy = CognitiveStateSnapshot(
        body, "sha256:" + sha256_hex(body_bytes),
        trust.sign(_COGNITIVE_SNAPSHOT_PURPOSE_V2, body_bytes).hex(),
    )
    decoded = CognitiveStateSnapshot.from_bytes(legacy.to_bytes(), trust=trust)
    restored = reconstruct_isolated(decoded, trust=trust, expected_agents=_expected_manifest())
    assert decoded.body.schema_version == 2
    assert restored.authenticity == "signature-verified"
    assert restored.memory_store.get_memory("memory-a").schema_version == 1
    assert decoded.to_bytes() == legacy.to_bytes()


def test_snapshot_v3_signs_memory_provenance_and_bundle_digest_can_bind_it():
    trust = FakeTrust()
    cognition, memories, contexts, runtime = _fixture()
    _, latest = _add_memory_v2_chain(memories)
    snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    assert snapshot.body.schema_version == 3
    assert snapshot.validate(trust=trust) == "signature-verified"
    decoded = CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust)
    restored = reconstruct_isolated(decoded, trust=trust, expected_agents=_expected_manifest())
    assert restored.memory_store.get_memory("memory-revision-2").decision_provenance == (
        latest.decision_provenance
    )
    memory_record = next(
        item for store in snapshot.body.stores if store.store_name == "memories"
        for item in store.records if item.record_id == "memory-revision-2"
    )
    assert tuple(source.reference for source in memory_record.sources) == (
        "event-not-loaded", "event-context",
    )

    codec = cognitive_snapshot_codec()
    memory_store_snapshot = next(item for item in snapshot.body.stores if item.store_name == "memories")
    index = next(i for i, item in enumerate(memory_store_snapshot.records)
                 if item.record_id == "memory-revision-2")
    record = memory_store_snapshot.records[index]
    altered_memory = replace(
        record.value,
        decision_provenance=replace(record.value.decision_provenance, reason_code="tampered"),
    )
    altered_records = list(memory_store_snapshot.records)
    altered_records[index] = replace(record, value=altered_memory)
    unsigned_store = replace(memory_store_snapshot, records=tuple(altered_records),
                             state_version="sha256:pending")
    updated_store = replace(
        unsigned_store,
        state_version="sha256:" + sha256_hex(codec.dumps(unsigned_store)),
    )
    body_stores = tuple(updated_store if item.store_name == "memories" else item
                         for item in snapshot.body.stores)
    altered_body = replace(snapshot.body, stores=body_stores)
    tampered = replace(
        snapshot, body=altered_body,
        content_digest="sha256:" + sha256_hex(codec.dumps(altered_body)),
    )
    with pytest.raises(PermissionError, match="signature verification failed"):
        tampered.validate(trust=trust)

    world = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    feedback_bytes = BehaviorFeedbackSnapshot.capture(
        feedback=BehaviorFeedback(), event_history=runtime.context.event_history,
        timeline_id="timeline-alpha", simulation_tick=9,
        session_id="snapshot-session", restore_generation=0,
        agent_ids=("agent-a", "agent-b"),
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=world, cognitive_snapshot=snapshot,
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_bytes,
    )
    # The signed component set and manifest meaning are unchanged; the exact
    # cognition bytes (now schema v3) remain protected by the existing Bundle.
    assert manifest.version == 2
    staged = manifest.verify_and_stage(
        world_checkpoint=world, cognitive_snapshot=snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback_bytes,
    )
    assert staged.cognition.memory_store.get_memory("memory-revision-2").schema_version == 2


def test_memory_revision_lineage_is_branch_local_and_binds_exact_checkpoint_records():
    trust = FakeTrust()
    cognition, memories, contexts, runtime = _fixture()
    root, tip = _add_memory_v2_chain(memories)
    snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    world = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    feedback = BehaviorFeedbackSnapshot.capture(
        feedback=BehaviorFeedback(), event_history=runtime.context.event_history,
        timeline_id="timeline-alpha", simulation_tick=9,
        session_id="snapshot-session", restore_generation=0,
        agent_ids=("agent-a", "agent-b"),
    )
    bundle = SnapshotBundleManifest.create(
        world_checkpoint=world, cognitive_snapshot=snapshot,
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback,
    )
    verified = bundle.verify_and_stage(
        world_checkpoint=world, cognitive_snapshot=snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
        behavior_feedback_snapshot=feedback,
    )
    fork_a = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=bundle, verified_bundle=verified,
        trust=trust, timeline_id="timeline-child-a",
    )
    fork_b = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=bundle, verified_bundle=verified,
        trust=trust, timeline_id="timeline-child-b",
    )
    branch_a = MemoryRevisionLineage.fork_from_verified_bundle(
        verified_bundle=verified, checkpoint_manifest=bundle,
        timeline_id=fork_a.timeline_id, fork_manifest=fork_a, trust=trust,
    )
    branch_b = MemoryRevisionLineage.fork_from_verified_bundle(
        verified_bundle=verified, checkpoint_manifest=bundle,
        timeline_id=fork_b.timeline_id, fork_manifest=fork_b, trust=trust,
    )
    parent_history = EventHistory(timeline_id="timeline-alpha")
    branch_history = EventHistory.fork_from_checkpoint(
        parent_history, fork_manifest=fork_a, checkpoint_manifest=bundle,
        verified_bundle=verified, trust=trust,
    )
    branch_a.verify_event_history(branch_history)
    saved_fork_bytes = branch_history.fork_manifest_bytes
    saved_checkpoint_bytes = branch_history.fork_checkpoint_manifest_bytes
    branch_history.fork_manifest_bytes = None
    branch_history.fork_checkpoint_manifest_bytes = None
    with pytest.raises(PermissionError):
        MemoryRevisionLineage.root("timeline-child-a").verify_event_history(
            branch_history,
        )
    branch_history.fork_manifest_bytes = saved_fork_bytes
    branch_history.fork_checkpoint_manifest_bytes = saved_checkpoint_bytes
    with pytest.raises(PermissionError):
        branch_a.verify_event_history(EventHistory(timeline_id="timeline-child-a"))
    with pytest.raises(PermissionError):
        branch_a.verify_event_history(EventHistory.fork_from_checkpoint(
            parent_history, fork_manifest=fork_b, checkpoint_manifest=bundle,
            verified_bundle=verified, trust=trust,
        ))
    with pytest.raises(PermissionError, match="incomplete fork metadata"):
        branch_a.verify_event_history(EventHistory(
            timeline_id="timeline-child-a",
            fork_checkpoint_manifest_bytes=bundle.to_bytes(),
        ))
    altered_boundary = EventHistory.fork_from_checkpoint(
        parent_history, fork_manifest=fork_a, checkpoint_manifest=bundle,
        verified_bundle=verified, trust=trust,
    )
    altered_boundary.fork_checkpoint_manifest_bytes = b"{}"
    with pytest.raises((ValueError, PermissionError)):
        branch_a.verify_event_history(altered_boundary)
    with pytest.raises(PermissionError, match="signature is invalid"):
        MemoryRevisionLineage.fork_from_verified_bundle(
            verified_bundle=verified, checkpoint_manifest=bundle,
            timeline_id=fork_a.timeline_id,
            fork_manifest=replace(fork_a, signature=b"tampered"), trust=trust,
        )

    def successor(record_id, timeline):
        provenance = replace(
            tip.decision_provenance, decision_id=f"decision-{record_id}",
            proposal_id=f"proposal-{record_id}", timeline_id=timeline,
            supersedes_record_id=tip.id,
        )
        return replace(
            tip, id=record_id, content={"summary": record_id},
            decision_provenance=provenance, supersedes_record_id=tip.id,
        )

    inherited = verified.cognition.memory_store.get_all_memories()
    child_a = successor("child-a-revision", fork_a.timeline_id)
    child_b = successor("child-b-revision", fork_b.timeline_id)
    branch_a.validate_records((*inherited, child_a))
    branch_b.validate_records((*inherited, child_b))
    with pytest.raises(PermissionError, match="not authored on this Timeline"):
        branch_a.validate_records((*inherited, successor("parent-suffix", "timeline-alpha")))
    with pytest.raises(PermissionError, match="not authored on this Timeline"):
        branch_a.validate_records((*inherited, child_b))
    with pytest.raises(PermissionError, match="changed or omitted an inherited"):
        branch_a.validate_records((*(item for item in inherited if item.id != tip.id), child_a))
    with pytest.raises(PermissionError, match="ambiguous"):
        branch_a.validate_records((*inherited, child_a,
                                   successor("child-a-second-successor", fork_a.timeline_id)))

    changed_tip = replace(tip, content={"summary": "changed ancestor"})
    altered = tuple(changed_tip if item.id == tip.id else item for item in inherited)
    with pytest.raises(PermissionError, match="changed or omitted an inherited"):
        branch_a.validate_records((*altered, child_a))


def test_snapshot_v3_rejects_memory_v2_inside_legacy_snapshot_v2():
    trust = FakeTrust()
    cognition, memories, contexts, runtime = _fixture()
    _add_memory_v2_chain(memories)
    captured = _capture(runtime, cognition, memories, contexts)
    body = replace(captured.body, schema_version=2)
    codec = cognitive_snapshot_codec()
    body_bytes = codec.dumps(body)
    signed = CognitiveStateSnapshot(
        body, "sha256:" + sha256_hex(body_bytes),
        trust.sign(_COGNITIVE_SNAPSHOT_PURPOSE_V2, body_bytes).hex(),
    )
    with pytest.raises(PermissionError, match="cannot contain Memory/v2"):
        signed.validate(trust=trust)


def test_snapshot_v3_rejects_missing_or_cross_logical_memory_predecessor():
    cognition, memories, contexts, runtime = _fixture()
    memories._memories["memory-revision-2"] = _memory_v2()
    with runtime.write_fence.operation():
        with pytest.raises(ValueError, match="predecessor is absent"):
            CognitiveStateSnapshot.capture(
                cognition=cognition, memory_store=memories, runtime=runtime,
                agent_contexts=contexts, timeline_id="timeline-alpha",
            )
    _add_memory_v2_chain(memories)
    revision_one = memories.get_memory("memory-revision-1")
    memories._memories["memory-revision-1"] = replace(
        revision_one, logical_record_id="different-logical-record",
    )
    with runtime.write_fence.operation():
        with pytest.raises(ValueError, match="crosses owner/logical identity"):
            CognitiveStateSnapshot.capture(
                cognition=cognition, memory_store=memories, runtime=runtime,
                agent_contexts=contexts, timeline_id="timeline-alpha",
            )


def test_verified_bundle_credentials_are_bound_to_issued_object_and_fields():
    from cognitive_world.core.snapshot_bundle import _require_verified_snapshot_bundle

    cognition, memories, contexts, runtime = _fixture()
    trust = FakeTrust()
    snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    world = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=world, cognitive_snapshot=snapshot,
        expected_agents=_expected_manifest(), trust=trust,
    )
    verified = manifest.verify_and_stage(
        world_checkpoint=world, cognitive_snapshot=snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
    )
    verified.verify_manifest_binding(manifest)
    assert _require_verified_snapshot_bundle(verified) is verified

    # Same-field clones do not inherit the verifier's object-identity issue.
    with pytest.raises(PermissionError, match="not issued"):
        replace(verified).verify_manifest_binding(manifest)
    with pytest.raises(PermissionError, match="not issued"):
        _require_verified_snapshot_bundle(replace(verified))

    for altered in (
        replace(verified, _verified_manifest_sha256="0" * 64),
        replace(verified, timeline_id="timeline-forged"),
        replace(verified, event_history=EventHistory()),
        replace(verified, memory_revision_lineage=MemoryRevisionLineage.root("other")),
    ):
        with pytest.raises(PermissionError):
            _require_verified_snapshot_bundle(altered)


def test_verified_bundle_rejects_in_place_feedback_history_mutation_at_fork_entry():
    from cognitive_world.core.snapshot_bundle import _require_verified_snapshot_bundle

    cognition, memories, contexts, runtime = _fixture()
    trust = FakeTrust()
    snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    world = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=world, cognitive_snapshot=snapshot,
        expected_agents=_expected_manifest(), trust=trust,
    )
    verified = manifest.verify_and_stage(
        world_checkpoint=world, cognitive_snapshot=snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
    )

    verified.verify_manifest_binding(manifest)
    fork = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=manifest, verified_bundle=verified,
        trust=trust, timeline_id="timeline-beta",
    )
    verified.behavior_feedback.history.append(BehaviorFailure(
        "agent-a", "attempt", "target", "method", (), "event:changed", 0, 0.2, 1,
    ))

    with pytest.raises(PermissionError, match="credential"):
        _require_verified_snapshot_bundle(verified)
    with pytest.raises(PermissionError, match="credential"):
        verified.verify_manifest_binding(manifest)
    with pytest.raises(PermissionError, match="credential"):
        TimelineForkManifest.create_from_checkpoint(
            checkpoint_manifest=manifest, verified_bundle=verified,
            trust=trust, timeline_id="timeline-gamma",
        )
    with pytest.raises(PermissionError, match="credential"):
        fork.verify_against_checkpoint(manifest, verified_bundle=verified, trust=trust)


def test_verified_bundle_rejects_in_place_cognition_mutation():
    from cognitive_world.core.snapshot_bundle import _require_verified_snapshot_bundle

    cognition, memories, contexts, runtime = _fixture()
    trust = FakeTrust()
    snapshot = _capture(runtime, cognition, memories, contexts, trust=trust)
    world = runtime.context.world_state.export_persisted_snapshot(
        event_history=runtime.context.event_history, simulation_tick=9,
        timeline_id="timeline-alpha", trust=trust,
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=world, cognitive_snapshot=snapshot,
        expected_agents=_expected_manifest(), trust=trust,
    )
    verified = manifest.verify_and_stage(
        world_checkpoint=world, cognitive_snapshot=snapshot.to_bytes(),
        expected_agents=_expected_manifest(), trust=trust,
    )
    verified.verify_manifest_binding(manifest)

    verified.cognition.cognition.add_emotion(Emotion(
        "credential-mutation", "agent-a", levels={"concern": 0.4},
    ))
    with pytest.raises(PermissionError, match="credential"):
        _require_verified_snapshot_bundle(verified)
    with pytest.raises(PermissionError, match="credential"):
        verified.verify_manifest_binding(manifest)


def test_memory_revision_lineage_credentials_are_bound_at_each_consumer():
    lineage = MemoryRevisionLineage.root("timeline-alpha")
    history = EventHistory(timeline_id="timeline-alpha")
    lineage.verify_event_history(history)
    for invalid_history in (
        object(), None, EventHistory(), EventHistory(timeline_id="timeline-other"),
        EventHistory(timeline_id="timeline-alpha", fork_manifest_bytes=b"{}"),
    ):
        with pytest.raises((TypeError, PermissionError, ValueError)):
            lineage.verify_event_history(invalid_history)
    lineage.validate_records(())
    store = MemoryStore()
    store.bind_revision_lineage(lineage)
    assert store._revision_lineage is lineage

    clones = (
        replace(lineage),
        replace(lineage, inherited_records=(("forged", b"record"),)),
        replace(lineage, timeline_id="timeline-forged"),
        replace(lineage, parent_timeline_id="parent-forged"),
        replace(lineage, fork_checkpoint_id="0" * 64),
        replace(lineage, fork_manifest_sha256="1" * 64),
    )
    for forged in clones:
        with pytest.raises(PermissionError, match="not issued"):
            forged.verify_event_history(history)
        with pytest.raises(PermissionError, match="not issued"):
            forged.validate_records(())
        with pytest.raises(PermissionError, match="not issued"):
            MemoryStore().bind_revision_lineage(forged)

    # Frozen dataclasses can still be altered by low-level same-process code;
    # every protected field, including the factory seal, must remain bound.
    tampered = MemoryRevisionLineage.root("timeline-alpha")
    store = MemoryStore()
    store.bind_revision_lineage(tampered)
    object.__setattr__(tampered, "inherited_records", (("forged", b"record"),))
    for consume in (
        lambda: tampered.verify_event_history(history),
        lambda: tampered.validate_records(()),
        lambda: store.bind_revision_lineage(tampered),
        lambda: store._commit_memory(Memory(
            "memory-legacy", "agent-a", "experience", {"summary": "x"},
            0.4, "event-source",
        )),
    ):
        with pytest.raises(PermissionError):
            consume()

    bad_seal = MemoryRevisionLineage.root("timeline-alpha")
    object.__setattr__(bad_seal, "_seal", object())
    with pytest.raises(PermissionError, match="seal"):
        bad_seal.verify_event_history(history)
