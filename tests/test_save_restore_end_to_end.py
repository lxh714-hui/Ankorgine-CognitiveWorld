"""End-to-end save, fork and resumed Agent execution over signed resources."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from hashlib import sha256
from threading import Event

import pytest

from cognitive_world.agent import AgentActionLoop, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.cognition import CognitionContainer, Goal, MemoryStore, Personality, SelfModel
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.consolidator import MemoryDecisionEngine
from cognitive_world.memory.decision_policy import MemoryDecisionResult, MemoryPolicyOutput
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.persistence import PersistedValueCodec, WindowsDpapiPersistenceTrust
from cognitive_world.core.world_state import WorldState, WorldStateSlot
from cognitive_world.decision import AgentDecision
from cognitive_world.decision.behavior_feedback import BehaviorFeedback
from cognitive_world.decision.autonomous import ModelAssistedCandidatePolicy
from cognitive_world.decision.evidence_review import DeterministicLocalEvidenceReviewProvider
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory
from cognitive_world.observation import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.write_fence import RuntimeWriteFence

from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest


DOOR_ID = "door:archive"
AGENT_ID = "agent:archivist"
PARENT = "timeline:archive-parent"


class _AcceptMemoryPolicy:
    policy_id = "test-host-memory-policy"
    policy_version = "1.0"

    def evaluate(self, decision_input):
        return MemoryPolicyOutput(MemoryDecisionResult.ACCEPTED, 0.5, "test.accepted")


def _persist_memory_revision(runtime, *, proposal_id, logical_id, predecessor=None,
                             source_event_id):
    history = runtime.context.event_history
    fence = runtime.write_fence
    engine = MemoryDecisionEngine(
        policy=_AcceptMemoryPolicy(), authority=MemoryDecisionAuthority(),
        event_history=history, write_fence=fence,
    )
    persistence = MemoryPersistence(
        memory_store=runtime.cognition_context_provider(
            runtime.context.agent_registry.get(AGENT_ID)
        ).memory_store,
        event_history=history, write_fence=fence,
        memory_revision_lineage=runtime.memory_revision_lineage,
    )
    with fence.operation():
        proposal = MemoryProposal(
            proposal_id, source_event_id, AGENT_ID, "experience",
            {"summary": proposal_id}, 0.5,
            logical_record_id=logical_id, supersedes_record_id=predecessor,
        )
        decision = engine.decide(proposal)
        request = MemoryWriteFactory().create_request(decision, proposal)
        return persistence.save(request)


class DoorRuntimeAssembler(LocalRuntimeAssembler):
    """Reinject the installed physical policy through the host assembly contract."""

    def assemble(self, inputs):
        runtime = super().assemble(inputs)
        for link in inputs.agent_links:
            runtime.context.agent_registry.register(RuntimeAgent(
                link.agent_id, link.character_id, goal_ids=list(link.goal_ids),
            ))
        flow = runtime.agent_action_loop.action_resolution_flow
        flow.resolution_engine = MethodBasedResolutionEngine(world_state=inputs.world_state)
        flow.bind_safety_governance(runtime.context.safety_governance)
        return runtime


def _live_runtime(trust, *, door_locked=False, timeline_id=PARENT):
    world = WorldState()
    world.load_environment_data(DOOR_ID, DoorState(DOOR_ID, "hall", False, door_locked, True))
    world.load_entity(Entity(
        AGENT_ID, "character", sensory_capabilities=("sight",),
        physical_capabilities=("manual_manipulation", "locomotion"),
    ))
    world.load_location(AGENT_ID, "hall")
    cognition = CognitionContainer()
    cognition.add_personality(Personality(AGENT_ID))
    cognition.add_self_model(SelfModel(AGENT_ID, capabilities={"manual_manipulation": True}))
    cognition.add_goal(Goal("goal:open-archive", AGENT_ID, "open the archive door", 1.0, "active"))
    memory = MemoryStore()
    character = Character("character:archivist", AGENT_ID, AGENT_ID,
                          goal_ids=["goal:open-archive"])
    registry = AgentRegistry()
    registry.register(RuntimeAgent(AGENT_ID, character.id, goal_ids=["goal:open-archive"]))
    observations = ObservationStore()
    history = EventHistory(timeline_id=timeline_id)
    clock = SimulationClock(4)
    fence = RuntimeWriteFence(f"session:{timeline_id}")
    cognition_context = CognitionContext.from_character(
        character, cognition, memory, observation_store=observations,
    )
    cognition_context.bind_write_fence(fence)
    context = RuntimeContext(clock, world, history, scheduler=EventScheduler(),
                             agent_scheduler=AgentScheduler(), agent_registry=registry,
                             observation_store=observations)
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
        persistence_trust=trust, persistence_codec=PersistedValueCodec(),
        write_fence=fence,
    )
    loop = AgentActionLoop(
        agent_turn=AgentTurn(write_fence=fence),
        action_resolution_flow=ActionResolutionFlow(
            MethodBasedResolutionEngine(world_state=world), world_state=world,
            event_history=history,
        ), write_fence=fence,
    )
    runtime = SimulationRuntime(
        context, write_fence=fence, event_processor=processor, agent_action_loop=loop,
        cognition_context_provider=lambda agent: cognition_context,
        agent_decision=AgentDecision(),
        evidence_review_provider=DeterministicLocalEvidenceReviewProvider(),
        allow_environment_provider_discovery=False,
    )
    return runtime, cognition, memory


def _observe_door(runtime, label):
    event = SystemEventFactory().create(
        event_id=label, event_type="environment_state_observed", timestamp=label,
        simulation_tick=runtime.context.clock.current_time,
        changes=[{"environment_id": DOOR_ID}],
    )
    runtime.event_processor.dispatch_with_evidence(event)
    return event


def _open_door_in_turn(runtime):
    runtime.context.agent_scheduler.schedule_agent(AGENT_ID, runtime.context.clock.current_time + 1)
    runtime.start()
    runtime.step()
    record = runtime.last_agent_turn_results[0]
    assert record.execution is not None and record.execution.event is not None
    assert record.event_committed
    assert runtime.context.world_state.environment[DOOR_ID].is_open
    return record.execution.event


def _fail_open_door_in_turn(runtime, *, expected_failures=1):
    runtime.context.agent_scheduler.schedule_agent(AGENT_ID, runtime.context.clock.current_time + 1)
    runtime.start()
    runtime.step()
    record = runtime.last_agent_turn_results[0]
    assert record.execution is not None and record.execution.event is not None
    assert record.event_committed and record.execution.resolution.success is False
    assert not runtime.context.world_state.environment[DOOR_ID].is_open
    assert len(runtime.behavior_feedback.history) == expected_failures
    return record.execution.event


def test_fake_trust_behavior_feedback_survives_save_fork_and_restore(tmp_path):
    from test_runtime_reconstruction import FakeTrust

    trust = FakeTrust()
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory = _live_runtime(trust, door_locked=True)
    _observe_door(parent, "event:locked-door-observed")
    failure_event = _fail_open_door_in_turn(parent)
    original_failure = parent.behavior_feedback.history[0]
    assert parent.context.event_history.get_event(failure_event.id) == failure_event
    incomplete_feedback = BehaviorFeedback(
        history=[replace(original_failure, conditions=(("door_locked", "True"),))],
        _seen_events={original_failure.event_id},
    )
    from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
    with pytest.raises(PermissionError, match="does not match"):
        BehaviorFeedbackSnapshot.capture(
            feedback=incomplete_feedback, event_history=parent.context.event_history,
            timeline_id=PARENT, simulation_tick=parent.context.clock.current_time,
            session_id=parent.write_fence.session_id,
                restore_generation=parent.write_fence.restore_generation, agent_ids=(AGENT_ID,),
        )

    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory, agent_contexts=(context,),
    )
    verified = manager.load_verified(saved.save_id, timeline_id=PARENT)
    assert verified.bundle_manifest.version == 2
    assert verified.behavior_feedback_snapshot is not None
    assert f"sha256:{sha256(verified.behavior_feedback_snapshot).hexdigest()}" in saved.resource_ids
    damaged_feedback = verified.behavior_feedback_snapshot + b" "
    with pytest.raises(PermissionError, match="component digest"):
        verified.bundle_manifest.verify_and_stage(
            world_checkpoint=verified.world_checkpoint,
            cognitive_snapshot=verified.cognitive_snapshot,
            expected_agents=verified.expected_agents,
            trust=trust,
            event_history_resolver=manager._resolve_event_history,
            behavior_feedback_snapshot=damaged_feedback,
        )
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:feedback-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    assert child.behavior_feedback_status == "restored"
    assert child.behavior_feedback is not parent.behavior_feedback
    assert child.behavior_feedback.history == [original_failure]
    assert child.behavior_feedback.frustration_for(AGENT_ID, saved.simulation_tick) == pytest.approx(
        parent.behavior_feedback.frustration_for(AGENT_ID, saved.simulation_tick)
    )
    assert child.context.event_history.get_event(failure_event.id) == failure_event

    # The staged Runtime intentionally rebuilds temporary Percepts rather than
    # inheriting the parent's consumed working context. Re-observe before the
    # child independently makes another attempt.
    _observe_door(child, "event:child-locked-door-observed")
    _fail_open_door_in_turn(child, expected_failures=2)
    assert len(child.behavior_feedback.history) == 2
    assert len(parent.behavior_feedback.history) == 1
    assert child.behavior_feedback.history[0].event_id == original_failure.event_id


def test_legacy_memory_write_cannot_overwrite_inherited_signed_checkpoint_record(tmp_path):
    from test_runtime_reconstruction import FakeTrust, _dependency_manifest
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec

    trust = FakeTrust()
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory_store = _live_runtime(trust)
    source = _observe_door(parent, "event:legacy-overwrite-source")
    inherited = _persist_memory_revision(
        parent, proposal_id="proposal:legacy-overwrite",
        logical_id="logical:legacy-overwrite", source_event_id=source.id,
    )
    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory_store,
        agent_contexts=(context,),
    )
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:legacy-overwrite-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    child_store = child.cognition_context_provider(
        child.context.agent_registry.get(AGENT_ID)
    ).memory_store
    original = child_store.get_memory(inherited.id)
    codec = cognitive_snapshot_codec()
    original_bytes = codec.dumps(original)

    with child.write_fence.operation():
        proposal = MemoryProposal(
            "proposal:legacy-overwrite", source.id, AGENT_ID, "experience",
            {"summary": "unauthorized replacement content"}, 0.5,
        )
        legacy_decision = MemoryDecisionAuthority().issue(
            proposal, accepted=True, importance=0.5, memory_type=proposal.memory_type,
        )
        legacy_request = MemoryWriteFactory().create_request(legacy_decision, proposal)
        persistence = MemoryPersistence(
            memory_store=child_store, event_history=child.context.event_history,
            write_fence=child.write_fence,
            memory_revision_lineage=child.memory_revision_lineage,
        )
        with pytest.raises(PermissionError, match="conflicting immutable Memory identity"):
            persistence.save(legacy_request)
        with pytest.raises(PermissionError, match="conflicting immutable Memory identity"):
            child_store._commit_memory(replace(
                original, schema_version=1, decision_provenance=None,
                logical_record_id=None, supersedes_record_id=None,
                content={"summary": "direct Store replacement"},
            ))

    assert codec.dumps(child_store.get_memory(inherited.id)) == original_bytes


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI and independent-process recovery")
def test_dpapi_restored_child_rejects_memory_v1_overwrite_and_keeps_compatibility(tmp_path):
    trust_path = tmp_path / "trust-ring.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory_store = _live_runtime(trust)
    source = _observe_door(parent, "event:dpapi-legacy-memory-source")
    proposal_id = "proposal:dpapi-inherited-legacy-memory"
    with parent.write_fence.operation():
        proposal = MemoryProposal(
            proposal_id, source.id, AGENT_ID, "experience",
            {"summary": "inherited legacy record"}, 0.5,
        )
        decision = MemoryDecisionAuthority().issue(
            proposal, accepted=True, importance=0.5,
            memory_type=proposal.memory_type,
        )
        request = MemoryWriteFactory().create_request(decision, proposal)
        inherited = MemoryPersistence(
            memory_store=memory_store, event_history=parent.context.event_history,
            write_fence=parent.write_fence,
            memory_revision_lineage=parent.memory_revision_lineage,
        ).save(request)

    parent_context = parent.cognition_context_provider(
        parent.context.agent_registry.get(AGENT_ID)
    )
    parent_save = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory_store,
        agent_contexts=(parent_context,),
    )
    staged = manager.stage_restore(
        parent_save.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:dpapi-legacy-memory-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    child_context = child.cognition_context_provider(
        child.context.agent_registry.get(AGENT_ID)
    )
    child_save = manager.create_manual_save(
        runtime=child, cognition=child_context.cognition_container,
        memory_store=child_context.memory_store, agent_contexts=(child_context,),
    )
    child_timeline = child.context.event_history.timeline_id

    script = r"""
import sys
from dataclasses import replace
from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.save_manager import SaveManager
from test_save_restore_end_to_end import (
    AGENT_ID, DoorRuntimeAssembler, _dependency_manifest, _live_runtime,
)
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
save_id, timeline_id, source_id, proposal_id = sys.argv[3:7]
record_id = sys.argv[7]
active, _, _ = _live_runtime(trust, timeline_id=timeline_id)
staged = manager.stage_restore(
    save_id, timeline_id=timeline_id, active_runtime=active,
    assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    new_timeline_id="timeline:dpapi-restored-grandchild",
)
runtime = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
agent = runtime.context.agent_registry.get(AGENT_ID)
store = runtime.cognition_context_provider(agent).memory_store
original = store.get_memory(record_id)
assert original is not None and original.source_event == source_id
codec = cognitive_snapshot_codec()
original_bytes = codec.dumps(original)
lineage = runtime.memory_revision_lineage
lineage.validate_records(store.get_all_memories())
persistence = MemoryPersistence(
    memory_store=store, event_history=runtime.context.event_history,
    write_fence=runtime.write_fence, memory_revision_lineage=lineage,
)
def request(content, proposal_key):
    proposal = MemoryProposal(
        proposal_key, source_id, AGENT_ID, "experience", content, 0.5,
    )
    decision = MemoryDecisionAuthority().issue(
        proposal, accepted=True, importance=0.5, memory_type=proposal.memory_type,
    )
    return MemoryWriteFactory().create_request(decision, proposal)
catalog_save_count = len(manager._load_catalog()["saves"])
with runtime.write_fence.operation():
    assert persistence.save(request(original.content, proposal_id)) == original
    for attempt in range(2):
        try:
            if attempt == 0:
                persistence.save(request({"summary": "forged replacement"}, proposal_id))
            else:
                store._commit_memory(replace(
                    original, content={"summary": "direct Store replacement"},
                ))
        except PermissionError:
            pass
        else:
            raise AssertionError("Memory/v1 overwrite was accepted")
    assert codec.dumps(store.get_memory(record_id)) == original_bytes
    fresh = persistence.save(request(
        {"summary": "new compatible record"}, proposal_id + ":new",
    ))
    assert fresh.id != record_id and store.get_memory(fresh.id) == fresh
lineage.validate_records(store.get_all_memories())
assert codec.dumps(store.get_memory(record_id)) == original_bytes
assert len(manager._load_catalog()["saves"]) == catalog_save_count
"""
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    tests_root = str(Path(__file__).resolve().parent)
    environment["PYTHONPATH"] = os.pathsep.join((
        source_root, tests_root, environment.get("PYTHONPATH", ""),
    ))
    completed = subprocess.run(
        [
            sys.executable, "-c", script, str(trust_path), str(manager.root),
            child_save.save_id, child_timeline, source.id, proposal_id,
            inherited.id,
        ],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=45, env=environment,
    )
    assert completed.returncode == 0, completed.stderr


def test_tampered_memory_revision_lineage_rejects_formal_memory_v2_write():
    from test_runtime_reconstruction import FakeTrust

    runtime, _, _ = _live_runtime(FakeTrust())
    source = _observe_door(runtime, "event:tampered-lineage-source")
    lineage = runtime.memory_revision_lineage
    assert lineage is not None
    store = runtime.cognition_context_provider(
        runtime.context.agent_registry.get(AGENT_ID)
    ).memory_store
    persistence = MemoryPersistence(
        memory_store=store, event_history=runtime.context.event_history,
        write_fence=runtime.write_fence, memory_revision_lineage=lineage,
    )
    engine = MemoryDecisionEngine(
        policy=_AcceptMemoryPolicy(), authority=MemoryDecisionAuthority(),
        event_history=runtime.context.event_history,
        write_fence=runtime.write_fence,
    )
    with runtime.write_fence.operation():
        proposal = MemoryProposal(
            "proposal:tampered-lineage", source.id, AGENT_ID, "experience",
            {"summary": "tampered lineage"}, 0.5,
            logical_record_id="logical:tampered-lineage",
        )
        decision = engine.decide(proposal)
        request = MemoryWriteFactory().create_request(decision, proposal)
        object.__setattr__(lineage, "inherited_records", (("forged", b"record"),))
        with pytest.raises(PermissionError):
            persistence.save(request)
    assert store.get_all_memories() == ()


def test_formal_memory_v2_rejects_event_outside_verified_root_history():
    from test_runtime_reconstruction import FakeTrust

    trust = FakeTrust()
    runtime, _, _ = _live_runtime(trust)
    source = _observe_door(runtime, "event:unsigned-root-memory-source")
    canonical_history = runtime.context.event_history
    unverified_history = EventHistory(timeline_id=canonical_history.timeline_id)
    unverified_history.append(source)

    assert unverified_history.get_event(source.id) == source
    with pytest.raises(
        PermissionError, match="local suffix is not durably attestable",
    ):
        unverified_history.verify_persisted_lineage(
            codec=PersistedValueCodec(), trust=trust,
        )

    lineage = runtime.memory_revision_lineage
    assert lineage is not None
    store = runtime.cognition_context_provider(
        runtime.context.agent_registry.get(AGENT_ID)
    ).memory_store
    memories_before = store.get_all_memories()
    persistence = MemoryPersistence(
        memory_store=store, event_history=unverified_history,
        write_fence=runtime.write_fence, memory_revision_lineage=lineage,
    )
    engine = MemoryDecisionEngine(
        policy=_AcceptMemoryPolicy(), authority=MemoryDecisionAuthority(),
        event_history=unverified_history, write_fence=runtime.write_fence,
    )

    with runtime.write_fence.operation():
        proposal = MemoryProposal(
            "proposal:unsigned-root-memory", source.id, AGENT_ID, "experience",
            {"summary": "unsigned root history source"}, 0.5,
            logical_record_id="logical:unsigned-root-memory",
        )
        decision = engine.decide(proposal)
        assert decision.accepted
        request = MemoryWriteFactory().create_request(decision, proposal)
        assert request.schema_version == 2
        runtime.write_fence.require_candidate_origin(request.runtime_write_permit)
        with pytest.raises(
            PermissionError, match="EventHistory is not bound to this Runtime",
        ):
            persistence.save(request)

    assert store.get_all_memories() == memories_before


def test_formal_memory_v2_rejects_independent_signed_history_on_same_timeline():
    from test_runtime_reconstruction import FakeTrust

    trust = FakeTrust()
    runtime, _, store = _live_runtime(trust)
    other_runtime, _, _ = _live_runtime(trust, timeline_id=PARENT)
    canonical_history = runtime.context.event_history
    other_history = other_runtime.context.event_history
    assert other_history is not canonical_history
    assert other_runtime.write_fence is not runtime.write_fence
    assert runtime.event_processor.persistence_trust is trust
    assert other_runtime.event_processor.persistence_trust is trust
    assert canonical_history.timeline_id == other_history.timeline_id == PARENT

    source = _observe_door(other_runtime, "event:independent-signed-memory-source")
    verified_events, _, _ = other_history.verify_persisted_lineage(
        codec=PersistedValueCodec(), trust=trust,
    )
    assert source.id in {event.id for event in verified_events}
    assert canonical_history.get_event(source.id) is None

    lineage = runtime.memory_revision_lineage
    assert lineage is not None
    lineage.verify_event_history(other_history)
    memories_before = store.get_all_memories()
    persistence = MemoryPersistence(
        memory_store=store, event_history=other_history,
        write_fence=runtime.write_fence, memory_revision_lineage=lineage,
    )
    engine = MemoryDecisionEngine(
        policy=_AcceptMemoryPolicy(), authority=MemoryDecisionAuthority(),
        event_history=other_history, write_fence=runtime.write_fence,
    )

    with runtime.write_fence.operation():
        proposal = MemoryProposal(
            "proposal:independent-signed-memory", source.id, AGENT_ID, "experience",
            {"summary": "independent signed history"}, 0.5,
            logical_record_id="logical:independent-signed-memory",
        )
        decision = engine.decide(proposal)
        assert decision.accepted
        request = MemoryWriteFactory().create_request(decision, proposal)
        assert request.schema_version == 2
        runtime.write_fence.require_candidate_origin(request.runtime_write_permit)
        with pytest.raises(PermissionError, match="EventHistory is not bound to this Runtime"):
            persistence.save(request)

    assert store.get_all_memories() == memories_before
    canonical_source = _observe_door(runtime, "event:canonical-signed-memory-source")
    saved = _persist_memory_revision(
        runtime, proposal_id="proposal:canonical-signed-memory",
        logical_id="logical:canonical-signed-memory",
        source_event_id=canonical_source.id,
    )
    assert saved.schema_version == 2
    assert store.get_memory(saved.id) == saved


def test_formal_memory_v2_rejects_branch_history_without_verified_parent(tmp_path):
    from test_runtime_reconstruction import FakeTrust

    trust = FakeTrust()
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory_store = _live_runtime(trust)
    _observe_door(parent, "event:unsigned-branch-parent-checkpoint")
    parent_context = parent.cognition_context_provider(
        parent.context.agent_registry.get(AGENT_ID)
    )
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory_store,
        agent_contexts=(parent_context,),
    )
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:unsigned-memory-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    source = _observe_door(child, "event:unsigned-branch-memory-source")
    issued_history = child.context.event_history
    unverified_history = EventHistory(
        timeline_id=issued_history.timeline_id,
        fork_manifest_bytes=issued_history.fork_manifest_bytes,
        fork_checkpoint_manifest_bytes=issued_history.fork_checkpoint_manifest_bytes,
    )
    local_evidence = issued_history.get_processing_evidence(source.id)
    local_record = issued_history.get_persistence_record(source.id)
    assert local_evidence is not None
    assert local_record is not None
    assert unverified_history.begin_processing(source)
    unverified_history.mark_applying_world_update(source.id)
    unverified_history.append(
        source, processing_evidence=local_evidence, persistence_record=local_record,
    )

    from cognitive_world.core.timeline import TimelineForkManifest
    from cognitive_world.event.history import EventProcessingStatus
    from cognitive_world.event.persistence import verify_and_restore_event_records

    assert unverified_history.get_processing_status(source.id) is EventProcessingStatus.RECORDED
    local_records = unverified_history.export_local_persisted_records()
    assert local_records == (local_record,)
    fork = TimelineForkManifest.from_bytes(unverified_history.fork_manifest_bytes)
    locally_verified_events, locally_verified_evidence, _ = verify_and_restore_event_records(
        local_records, codec=PersistedValueCodec(), trust=trust,
        expected_timeline_id=unverified_history.timeline_id,
        initial_previous_digest=fork.inherited_event_chain_head_sha256,
    )
    assert tuple(event.id for event in locally_verified_events) == (source.id,)
    assert len(locally_verified_evidence) == 1

    lineage = child.memory_revision_lineage
    assert lineage is not None
    lineage.verify_event_history(unverified_history)
    with pytest.raises(
        PermissionError, match="branch EventHistory requires its verified parent history",
    ):
        unverified_history.verify_persisted_lineage(
            codec=PersistedValueCodec(), trust=trust,
        )

    store = child.cognition_context_provider(
        child.context.agent_registry.get(AGENT_ID)
    ).memory_store
    memories_before = store.get_all_memories()
    persistence = MemoryPersistence(
        memory_store=store, event_history=unverified_history,
        write_fence=child.write_fence, memory_revision_lineage=lineage,
    )
    engine = MemoryDecisionEngine(
        policy=_AcceptMemoryPolicy(), authority=MemoryDecisionAuthority(),
        event_history=unverified_history, write_fence=child.write_fence,
    )

    with child.write_fence.operation():
        proposal = MemoryProposal(
            "proposal:unsigned-branch-memory", source.id, AGENT_ID, "experience",
            {"summary": "branch history without verified parent"}, 0.5,
            logical_record_id="logical:unsigned-branch-memory",
        )
        decision = engine.decide(proposal)
        assert decision.accepted
        request = MemoryWriteFactory().create_request(decision, proposal)
        assert request.schema_version == 2
        child.write_fence.require_candidate_origin(request.runtime_write_permit)
        with pytest.raises(
            PermissionError,
            match="EventHistory is not bound to this Runtime",
        ):
            persistence.save(request)

    assert store.get_all_memories() == memories_before


def test_restored_behavior_feedback_reproduces_checkpoint_decision_scores_and_selection(tmp_path):
    """Reconstruction restores decision influence, not only feedback bytes."""
    from cognitive_world.decision.behavior_feedback import BehaviorFeedback

    trust = __import__("test_runtime_reconstruction").FakeTrust()
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory = _live_runtime(trust, door_locked=True)
    _observe_door(parent, "event:continuity-locked-observation")
    for count in range(1, 4):
        _fail_open_door_in_turn(parent, expected_failures=count)

    def compare_at_current_checkpoint(runtime):
        agent = runtime.context.agent_registry.get(AGENT_ID)
        cognition_context = runtime.cognition_context_provider(agent)
        with runtime.write_fence.operation():
            context, _ = runtime.agent_action_loop.agent_turn.prepare_decision_context(
                agent, cognition_context,
                simulation_tick=runtime.context.clock.capture(),
            )
            tick = runtime.context.clock.current_time
            plain = replace(
                runtime.agent_decision,
                behavior_feedback=BehaviorFeedback(), simulation_tick=tick,
            ).propose(context)
            informed = replace(
                runtime.agent_decision,
                behavior_feedback=runtime.behavior_feedback, simulation_tick=tick,
            ).propose(context)
        return tick, context, plain, informed

    parent_tick, parent_context, parent_plain, parent_informed = compare_at_current_checkpoint(parent)
    assert parent_plain.metadata["selected_candidate_id"] != parent_informed.metadata["selected_candidate_id"]
    assert parent_plain.target_refs == [DOOR_ID]
    assert parent_informed.target_refs != [DOOR_ID]

    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory,
        agent_contexts=(context,),
    )
    assert saved.simulation_tick == parent_tick
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:behavior-decision-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    assert child.context.clock.current_time == parent_tick
    assert child.behavior_feedback_status == "restored"

    # Temporary Percepts are rebuilt after restore. Re-observation supplies
    # equivalent authorized state at the same simulation tick; the old L1
    # context itself is intentionally not carried into the child Runtime.
    _observe_door(child, "event:restored-continuity-locked-observation")
    child_tick, child_context, child_plain, child_informed = compare_at_current_checkpoint(child)
    assert child_tick == parent_tick

    def normalized(proposal):
        return {
            item["candidate_id"]: (
                item["intent"], item["target"], item["method"], item["score"],
                tuple(item["factors"]),
            )
            for item in proposal.metadata["decision_trace"]
        }

    assert normalized(child_plain) == normalized(parent_plain)
    assert normalized(child_informed) == normalized(parent_informed)
    assert child_informed.metadata["selected_candidate_id"] == parent_informed.metadata["selected_candidate_id"]
    assert child_informed.metadata["selected_candidate_id"] != child_plain.metadata["selected_candidate_id"]
    assert child.behavior_feedback.history == parent.behavior_feedback.history
    assert child.behavior_feedback is not parent.behavior_feedback

    # Restored records keep their original event ticks. Querying at the saved
    # tick and one half-life later is read-only and must not rewrite history.
    last_failure = child.behavior_feedback.history[-1]
    situation = child.agent_decision.situation_policy.assess(child_context)
    generated = child.agent_decision.candidate_policy.generate(situation)
    candidates = generated[0] if (
        isinstance(generated, tuple) and len(generated) == 2
        and isinstance(generated[0], tuple)
    ) else generated
    door_candidate = next(item for item in candidates if item.target == DOOR_ID)
    current_penalty = child.behavior_feedback.penalty_for(
        owner_id=AGENT_ID, action_type=last_failure.action_type,
        target=last_failure.target, method=last_failure.method,
        facts=situation.observed_facts, source_refs=door_candidate.source_refs,
        tick=child_tick,
    )
    half_life_penalty = child.behavior_feedback.penalty_for(
        owner_id=AGENT_ID, action_type=last_failure.action_type,
        target=last_failure.target, method=last_failure.method,
        facts=situation.observed_facts, source_refs=door_candidate.source_refs,
        tick=child_tick + child.behavior_feedback.half_life_ticks,
    )
    frustration = child.behavior_feedback.frustration_for(AGENT_ID, child_tick)
    half_life_frustration = child.behavior_feedback.frustration_for(
        AGENT_ID, child_tick + child.behavior_feedback.frustration_half_life_ticks,
    )
    assert current_penalty == pytest.approx(last_failure.penalty)
    assert half_life_penalty == pytest.approx(current_penalty / 2)
    assert half_life_frustration == pytest.approx(frustration / 2)
    assert len(child.behavior_feedback.history) == 3

    # The restored Runtime continues through its normal turn and resolution
    # path. If the selected alternative is unresolved, it must not fabricate
    # an Event or alter the locked door.
    child.context.agent_scheduler.schedule_agent(
        AGENT_ID, child.context.clock.current_time + 1,
    )
    child.start()
    before_events = tuple(child.context.event_history.get_events())
    child.step()
    record = child.last_agent_turn_results[0]
    assert record.execution is not None
    assert record.execution.proposal.metadata["selected_candidate_id"] != child_plain.metadata["selected_candidate_id"]
    if record.event_committed:
        assert record.event_id is not None
        committed = child.context.event_history.get_event(record.event_id)
        assert committed == record.execution.event
    else:
        assert record.execution.resolution.outcome == "unresolved"
        assert record.event_id is None and not record.event_committed
        assert tuple(child.context.event_history.get_events()) == before_events
        assert child.context.world_state.environment[DOOR_ID].is_locked is True


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI acceptance")
def test_dpapi_behavior_feedback_snapshot_reopens_in_independent_process(tmp_path):
    key_path = tmp_path / "trust-ring.json"
    trust = WindowsDpapiPersistenceTrust.initialize(key_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory = _live_runtime(trust, door_locked=True)
    _observe_door(parent, "event:dpapi-locked-observation")
    failure = _fail_open_door_in_turn(parent)
    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory, agent_contexts=(context,),
    )
    save_root = manager.root
    del manager

    script = """
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
save = manager.load_verified(sys.argv[3], timeline_id=sys.argv[4])
assert save.bundle_manifest.version == 2
assert save.behavior_feedback_snapshot is not None
"""
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(key_path), str(save_root), saved.save_id, PARENT],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert completed.returncode == 0, completed.stderr

    manager = SaveManager(save_root, trust=WindowsDpapiPersistenceTrust.open(key_path))
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(manager.trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:dpapi-feedback-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    assert child.behavior_feedback_status == "restored"
    assert [item.event_id for item in child.behavior_feedback.history] == [failure.id]


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI acceptance")
def test_dpapi_save_delete_fork_restore_and_continue_with_agent_turn(tmp_path):
    key_path = tmp_path / "trust-ring.json"
    trust = WindowsDpapiPersistenceTrust.initialize(key_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory = _live_runtime(trust)
    _observe_door(parent, "event:initial-observation")
    inherited_revision = _persist_memory_revision(
        parent, proposal_id="proposal:parent-base",
        logical_id="logical:branch-test", source_event_id="event:initial-observation",
    )
    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    capture = dict(runtime=parent, cognition=cognition, memory_store=memory,
                   agent_contexts=(context,))
    first = manager.create_manual_save(name="keep", **capture)
    duplicate = manager.create_manual_save(name="delete", **capture)
    assert first.resource_ids == duplicate.resource_ids
    manager.delete_manual_save(duplicate.save_id)
    with pytest.raises(KeyError):
        manager.load_verified(duplicate.save_id, timeline_id=PARENT)
    assert manager.load_verified(first.save_id, timeline_id=PARENT).metadata.event_ids == (
        "event:initial-observation",
    )
    assert manager.verify_consistency()
    save_root = manager.root
    del manager

    # A second interpreter opens the exact persisted files and its own DPAPI key ring.
    script = """
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
save = manager.load_verified(sys.argv[3], timeline_id=sys.argv[4])
assert set(save.metadata.event_ids) == set(sys.argv[5].split(','))
assert save.bundle_manifest.simulation_tick == int(sys.argv[6])
assert manager.verify_consistency()
"""
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join((
        src, str(Path(__file__).resolve().parent), env.get("PYTHONPATH", ""),
    ))
    completed = subprocess.run(
        [sys.executable, "-c", script, str(key_path), str(save_root), first.save_id, PARENT,
         "event:initial-observation", "4"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    manager = SaveManager(save_root, trust=WindowsDpapiPersistenceTrust.open(key_path))

    staged = manager.stage_restore(
        first.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(manager.trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:archive-child",
    )
    parent_suffix_revision = _persist_memory_revision(
        parent, proposal_id="proposal:parent-suffix",
        logical_id="logical:branch-test", predecessor=inherited_revision.id,
        source_event_id="event:initial-observation",
    )
    parent_event = _open_door_in_turn(parent)
    old_proposal = parent.last_agent_turn_results[0].execution.proposal
    assert parent.context.event_history.get_event(parent_event.id) is not None
    slot = ActiveRuntimeSlot(parent)
    child = RestoreCoordinator(slot).activate(staged)
    assert slot.current is child
    assert child.context.event_history.timeline_id == "timeline:archive-child"
    assert child.context.clock.current_time == 4
    assert child.context.world_state.environment[DOOR_ID].is_open is False
    assert [item.id for item in child.context.event_history.get_events()] == ["event:initial-observation"]
    child_memories = child.cognition_context_provider(
        child.context.agent_registry.get(AGENT_ID)
    ).memory_store
    assert child_memories.get_memory(inherited_revision.id) == inherited_revision
    assert child_memories.get_memory(parent_suffix_revision.id) is None
    assert parent.context.world_state.environment[DOOR_ID].is_open is True
    with pytest.raises(PermissionError), parent.write_fence.operation():
        pass
    with pytest.raises(PermissionError):
        parent.agent_action_loop.run_proposal_with_result(old_proposal)

    _observe_door(child, "event:child-observation")
    child_suffix_revision = _persist_memory_revision(
        child, proposal_id="proposal:child-suffix",
        logical_id="logical:branch-test", predecessor=inherited_revision.id,
        source_event_id="event:child-observation",
    )
    child_event = _open_door_in_turn(child)
    history = child.context.event_history
    assert history.get_event(child_event.id) is not None
    assert parent.context.event_history.get_event(child_event.id) is None
    assert history.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)
    assert len(history.export_local_persisted_records()) == 2
    local_records = history.export_local_persisted_records()
    first_attestation = json.loads(local_records[0].attestation_payload)
    second_attestation = json.loads(local_records[1].attestation_payload)
    assert first_attestation["timeline_id"] == child.context.event_history.timeline_id
    assert first_attestation["previous_record_sha256"] == first.event_chain_head_sha256
    assert second_attestation["timeline_id"] == child.context.event_history.timeline_id
    slot_read = child.context.world_state.read_state_slot(
        WorldStateSlot("environment", DOOR_ID, ("is_open",)), event_history=history,
    )
    assert slot_read.value is True and slot_read.source_event_id == child_event.id
    assert child.context.world_state.verify_state_slot_read(slot_read, event_history=history)
    child_context = child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID))
    child_save = manager.create_manual_save(
        runtime=child, cognition=child_context.cognition_container,
        memory_store=child_context.memory_store, agent_contexts=(child_context,),
    )
    assert child_memories.get_memory(child_suffix_revision.id) == child_suffix_revision
    assert child_memories.get_memory(parent_suffix_revision.id) is None
    assert child_save.parent_timeline_id == PARENT
    assert child_save.fork_checkpoint_id == first.bundle_sha256

    sibling_parent, _, _ = _live_runtime(trust)
    sibling_staged = manager.stage_restore(
        first.save_id, timeline_id=PARENT, active_runtime=sibling_parent,
        assembler=DoorRuntimeAssembler(manager.trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:archive-sibling",
    )
    sibling = RestoreCoordinator(ActiveRuntimeSlot(sibling_parent)).activate(sibling_staged)
    _observe_door(sibling, "event:sibling-observation")
    sibling_suffix_revision = _persist_memory_revision(
        sibling, proposal_id="proposal:sibling-suffix",
        logical_id="logical:branch-test", predecessor=inherited_revision.id,
        source_event_id="event:sibling-observation",
    )
    sibling_context = sibling.cognition_context_provider(
        sibling.context.agent_registry.get(AGENT_ID)
    )
    sibling_save = manager.create_manual_save(
        runtime=sibling, cognition=sibling_context.cognition_container,
        memory_store=sibling_context.memory_store, agent_contexts=(sibling_context,),
    )
    sibling_store = sibling_context.memory_store
    assert sibling_store.get_memory(sibling_suffix_revision.id) == sibling_suffix_revision
    assert sibling_store.get_memory(child_suffix_revision.id) is None
    assert sibling_store.get_memory(parent_suffix_revision.id) is None

    manager.delete_manual_save(first.save_id)
    assert manager.load_verified(child_save.save_id, timeline_id=child_save.timeline_id)
    assert manager.load_verified(sibling_save.save_id, timeline_id=sibling_save.timeline_id)
    assert manager.verify_consistency()
    child_events = ",".join(item.id for item in history.get_events())
    reopened_child = subprocess.run(
        [sys.executable, "-c", script, str(key_path), str(manager.root),
         child_save.save_id, child_save.timeline_id, child_events,
         str(child_save.simulation_tick)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert reopened_child.returncode == 0, reopened_child.stderr
    reopened_revision = subprocess.run(
        [sys.executable, "-c", """
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.save_manager import SaveManager
from test_save_restore_end_to_end import DoorRuntimeAssembler, _live_runtime
from test_runtime_reconstruction import _dependency_manifest
trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
saved = manager.load_verified(sys.argv[3], timeline_id=sys.argv[4])
lineage = saved.memory_revision_lineage
assert lineage is not None
assert {record_id for record_id, _ in lineage.inherited_records} >= {"memory:proposal:parent-base"}
active, _, _ = _live_runtime(trust, timeline_id=saved.metadata.timeline_id)
staged = manager.stage_restore(
    saved.metadata.save_id, timeline_id=saved.metadata.timeline_id,
    active_runtime=active, assembler=DoorRuntimeAssembler(trust),
    dependencies=_dependency_manifest(),
    new_timeline_id=sys.argv[7],
)
restored = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
store = restored.cognition_context_provider(
    restored.context.agent_registry.get("agent:archivist")
).memory_store
assert store.get_memory("memory:proposal:parent-base") is not None
assert store.get_memory(sys.argv[5]) is not None
assert store.get_memory("memory:proposal:parent-suffix") is None
assert store.get_memory(sys.argv[6]) is None
assert restored.context.event_history.timeline_id == sys.argv[7]
""", str(key_path), str(manager.root), child_save.save_id, child_save.timeline_id,
     "memory:proposal:child-suffix", "memory:proposal:sibling-suffix",
     "timeline:dpapi-reopened-child"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert reopened_revision.returncode == 0, reopened_revision.stderr
    reopened_sibling = subprocess.run(
        [sys.executable, "-c", reopened_revision.args[2], str(key_path), str(manager.root),
         sibling_save.save_id, sibling_save.timeline_id,
         "memory:proposal:sibling-suffix", "memory:proposal:child-suffix",
         "timeline:dpapi-reopened-sibling"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert reopened_sibling.returncode == 0, reopened_sibling.stderr


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI acceptance")
def test_dpapi_other_process_cannot_collect_staged_child_ancestor(tmp_path):
    key_path = tmp_path / "trust-ring.json"
    trust = WindowsDpapiPersistenceTrust.initialize(key_path)
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory = _live_runtime(trust)
    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory,
        agent_contexts=(context,),
    )
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:leased-child",
    )
    script = """
import sys
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
manager = SaveManager(sys.argv[2], trust=WindowsDpapiPersistenceTrust.open(sys.argv[1]))
manager.delete_manual_save(sys.argv[3])
manager.collect_garbage()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script, str(key_path), str(manager.root), saved.save_id],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert all(manager._blob_path(item).exists() for item in saved.resource_ids)
    child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
    child_context = child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID))
    child_save = manager.create_manual_save(
        runtime=child, cognition=child_context.cognition_container,
        memory_store=child_context.memory_store, agent_contexts=(child_context,),
    )
    assert saved.snapshot_id in child_save.resource_ids
    assert manager.load_verified(child_save.save_id, timeline_id="timeline:leased-child")


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI acceptance")
def test_late_candidate_provider_cannot_commit_after_restore(tmp_path):
    trust = WindowsDpapiPersistenceTrust.initialize(tmp_path / "trust-ring.json")
    manager = SaveManager(tmp_path / "saves", trust=trust)
    parent, cognition, memory = _live_runtime(trust)
    _observe_door(parent, "event:initial-observation")
    context = parent.cognition_context_provider(parent.context.agent_registry.get(AGENT_ID))
    saved = manager.create_manual_save(
        runtime=parent, cognition=cognition, memory_store=memory,
        agent_contexts=(context,),
    )
    staged = manager.stage_restore(
        saved.save_id, timeline_id=PARENT, active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:late-child",
    )
    entered, release = Event(), Event()

    class DelayedCandidates:
        def generate(self, situation):
            entered.set()
            assert release.wait(timeout=10), "candidate provider was never released"
            return ModelAssistedCandidatePolicy().generate(situation)

    parent.agent_decision.candidate_policy = DelayedCandidates()
    parent.context.agent_scheduler.schedule_agent(AGENT_ID, 5)
    parent.start()
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(parent.step)
        assert entered.wait(timeout=10)
        try:
            child = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(staged)
        finally:
            release.set()
        pending.result(timeout=10)
    assert [item.id for item in parent.context.event_history.get_events()] == [
        "event:initial-observation",
    ]
    assert [item.id for item in child.context.event_history.get_events()] == [
        "event:initial-observation",
    ]
    assert not parent.context.world_state.environment[DOOR_ID].is_open
    assert not child.context.world_state.environment[DOOR_ID].is_open
    assert parent.last_agent_turn_results[0].event_committed is False


def _multigeneration_memory_saves(
    tmp_path, *, include_independent_ancestor_memory=False, include_second_b_event=False,
):
    """Publish A -> B -> C and A -> S through the supported runtime path."""
    from test_runtime_reconstruction import FakeTrust

    trust = FakeTrust()
    manager = SaveManager(tmp_path / "saves", trust=trust)

    def save(runtime, cognition, store):
        agent = runtime.context.agent_registry.get(AGENT_ID)
        context = runtime.cognition_context_provider(agent)
        return manager.create_manual_save(
            runtime=runtime, cognition=cognition, memory_store=store,
            agent_contexts=(context,),
        )

    a, a_cognition, a_store = _live_runtime(trust)
    a_event = _observe_door(a, "event:ancestor-a")
    a_memory = _persist_memory_revision(
        a, proposal_id="proposal:ancestor-a", logical_id="logical:ancestor-chain",
        source_event_id=a_event.id,
    )
    independent_a_memory = None
    if include_independent_ancestor_memory:
        independent_a_memory = _persist_memory_revision(
            a, proposal_id="proposal:ancestor-a-independent",
            logical_id="logical:independent-ancestor", source_event_id=a_event.id,
        )
    a_save = save(a, a_cognition, a_store)

    b_staged = manager.stage_restore(
        a_save.save_id, timeline_id=a_save.timeline_id, active_runtime=a,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:ancestor-b",
    )
    b = RestoreCoordinator(ActiveRuntimeSlot(a)).activate(b_staged)
    b_event = _observe_door(b, "event:ancestor-b")
    if include_second_b_event:
        _observe_door(b, "event:ancestor-b-followup")
    b_memory = _persist_memory_revision(
        b, proposal_id="proposal:ancestor-b", logical_id="logical:ancestor-chain",
        predecessor=a_memory.id, source_event_id=b_event.id,
    )
    b_context = b.cognition_context_provider(b.context.agent_registry.get(AGENT_ID))
    b_save = save(b, b_context.cognition_container, b_context.memory_store)

    c_staged = manager.stage_restore(
        b_save.save_id, timeline_id=b_save.timeline_id, active_runtime=b,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="timeline:ancestor-c",
    )
    c = RestoreCoordinator(ActiveRuntimeSlot(b)).activate(c_staged)
    c_event = _observe_door(c, "event:ancestor-c")
    c_memory = _persist_memory_revision(
        c, proposal_id="proposal:ancestor-c", logical_id="logical:ancestor-chain",
        predecessor=b_memory.id, source_event_id=c_event.id,
    )
    c_context = c.cognition_context_provider(c.context.agent_registry.get(AGENT_ID))
    c_save = save(c, c_context.cognition_container, c_context.memory_store)

    sibling_parent, _, _ = _live_runtime(trust)
    s_staged = manager.stage_restore(
        a_save.save_id, timeline_id=a_save.timeline_id,
        active_runtime=sibling_parent, assembler=DoorRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="timeline:ancestor-s",
    )
    s = RestoreCoordinator(ActiveRuntimeSlot(sibling_parent)).activate(s_staged)
    s_event = _observe_door(s, "event:ancestor-s")
    s_memory = _persist_memory_revision(
        s, proposal_id="proposal:ancestor-s", logical_id="logical:ancestor-chain",
        predecessor=a_memory.id, source_event_id=s_event.id,
    )
    s_context = s.cognition_context_provider(s.context.agent_registry.get(AGENT_ID))
    s_save = save(s, s_context.cognition_container, s_context.memory_store)

    all_memories = [a_memory, b_memory, c_memory, s_memory]
    if independent_a_memory is not None:
        all_memories.append(independent_a_memory)
    assert all(item.schema_version == 2 for item in all_memories)
    assert len({item.id for item in all_memories}) == len(all_memories)
    memories = {"a": a_memory, "b": b_memory, "c": c_memory, "s": s_memory}
    if independent_a_memory is not None:
        memories["a_independent"] = independent_a_memory
    return (manager, trust,
            {"a": a_save, "b": b_save, "c": c_save, "s": s_save},
            memories)


def test_cold_resume_grandchild_verifies_ancestors_and_preserves_timeline(tmp_path):
    manager, trust, saves, memories = _multigeneration_memory_saves(tmp_path)
    reopened = SaveManager(manager.root, trust=trust)
    staged = reopened.stage_cold_resume(
        saves["c"].save_id, timeline_id=saves["c"].timeline_id,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    )
    assert staged.runtime.context.event_history.timeline_id == saves["c"].timeline_id
    resumed = ColdRuntimePublisher().activate(staged).current
    assert resumed.context.event_history.timeline_id == saves["c"].timeline_id
    assert resumed.write_fence.session_id != saves["c"].runtime_session_id
    assert resumed.cognition_context_provider(
        resumed.context.agent_registry.get(AGENT_ID)
    ).memory_store.get_memory(memories["c"].id) == memories["c"]
    assert resumed.context.event_history.get_event("event:ancestor-a") is not None
    assert resumed.context.event_history.get_event("event:ancestor-b") is not None
    assert resumed.context.event_history.get_event("event:ancestor-c") is not None
    assert resumed.context.event_history.get_event("event:ancestor-s") is None


def _ancestor_component_path(manager, saved, component):
    """Locate one published test blob without changing the signed catalog."""
    catalog = manager._load_catalog()
    resource_id = catalog["saves"][saved.save_id]["blob_refs"][component]
    path = manager.resources / f"{resource_id.removeprefix('sha256:')}.blob"
    assert path.is_file()
    return path


def _replace_saved_blob(manager, saved, component, content):
    """Install a controlled test blob and re-sign only its temporary catalog."""
    from cognitive_world.core.persistence import sha256_hex

    catalog = manager._load_catalog()
    body = dict(catalog)
    saves = dict(body["saves"])
    record = dict(saves[saved.save_id])
    refs = dict(record["blob_refs"])
    old_id = refs[component]
    new_id = f"sha256:{sha256_hex(content)}"
    new_path = manager._blob_path(new_id)
    if new_path.exists():
        assert new_path.read_bytes() == content
    else:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(content)
    refs[component] = new_id
    record["blob_refs"] = refs
    resource_ids = set(record["resource_ids"])
    if old_id not in refs.values():
        resource_ids.discard(old_id)
    resource_ids.add(new_id)
    record["resource_ids"] = sorted(resource_ids)
    if component == "bundle":
        record["bundle_resource_id"] = new_id
        record["bundle_sha256"] = new_id.removeprefix("sha256:")
        record["snapshot_id"] = new_id
    saves[saved.save_id] = record
    body["saves"] = saves

    checkpoints = dict(body["checkpoints"])
    checkpoint_id = record["bundle_resource_id"]
    checkpoint = dict(checkpoints[old_id if component == "bundle" else checkpoint_id])
    checkpoint_refs = dict(checkpoint["blob_refs"])
    checkpoint_refs[component] = new_id
    checkpoint["blob_refs"] = checkpoint_refs
    checkpoint_resources = set(checkpoint["resource_ids"])
    if old_id not in checkpoint_refs.values():
        checkpoint_resources.discard(old_id)
    checkpoint_resources.add(new_id)
    checkpoint["resource_ids"] = sorted(checkpoint_resources)
    checkpoints[checkpoint_id] = checkpoint
    body["checkpoints"] = checkpoints
    manager._write_catalog(body)
    return new_path


def _set_saved_fork_metadata(manager, saved, fork_bytes):
    """Keep a test save record aligned with its test-signed Fork resource."""
    from cognitive_world.core.timeline import TimelineForkManifest

    fork = TimelineForkManifest.from_bytes(fork_bytes)
    catalog = manager._load_catalog()
    body = dict(catalog)
    saves = dict(body["saves"])
    record = dict(saves[saved.save_id])
    record["parent_timeline_id"] = fork.parent_timeline_id
    record["fork_checkpoint_id"] = fork.fork_checkpoint_id
    saves[saved.save_id] = record
    body["saves"] = saves
    manager._write_catalog(body)


def _resign_fork_manifest(fork_bytes, trust, **changes):
    """Create a test-signed Fork record whose ancestry fields are inconsistent."""
    from dataclasses import replace
    from cognitive_world.core.timeline import TimelineForkManifest

    fork = TimelineForkManifest.from_bytes(fork_bytes)
    unsigned = replace(fork, **changes, signature=b"test-signature-pending")
    body = json.dumps(unsigned._body(), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    signature = trust.sign("cognitive-world/timeline-fork/v1", body)
    signed = replace(unsigned, signature=signature)
    assert trust.verify("cognitive-world/timeline-fork/v1", body, signature)
    return signed.to_bytes()


def _resign_world_checkpoint_with_invalid_local_event_signature(world_bytes, trust, event_id):
    """Keep the checkpoint envelope valid while invalidating one local Event proof."""
    import base64

    from cognitive_world.core.persistence import sha256_hex

    codec = PersistedValueCodec()
    envelope = json.loads(world_bytes.decode("utf-8"))
    body_bytes = base64.b64decode(envelope["body"], validate=True)
    body = codec.loads(body_bytes)
    records = body["event_history"]["local_records"]
    matched = False
    for record in records:
        event = codec.loads(base64.b64decode(record["event"], validate=True))
        if event.id == event_id:
            record["signature"] = base64.b64encode(b"invalid-event-signature").decode("ascii")
            matched = True
            break
    assert matched, f"expected local Event record {event_id!r} was not found"

    altered_body = codec.dumps(body)
    digest = sha256_hex(altered_body)
    signed = json.dumps({
        "schema": envelope["schema"], "version": envelope["version"],
        "timeline_id": envelope["timeline_id"],
        "simulation_tick": envelope["simulation_tick"], "body_sha256": digest,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = trust.sign("cognitive-world/world-state-checkpoint/v3", signed)
    envelope.update({
        "body": base64.b64encode(altered_body).decode("ascii"),
        "body_sha256": digest,
        "signature": base64.b64encode(signature).decode("ascii"),
    })
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resign_world_checkpoint_with_parent_checkpoint(
    world_bytes, trust, *, fork_manifest_bytes, checkpoint_manifest_bytes,
):
    """Rebind a child checkpoint's persisted fork descriptor to a test parent."""
    import base64

    from cognitive_world.core.persistence import sha256_hex

    codec = PersistedValueCodec()
    envelope = json.loads(world_bytes.decode("utf-8"))
    body = codec.loads(base64.b64decode(envelope["body"], validate=True))
    history = body["event_history"]
    history["fork_manifest"] = base64.b64encode(fork_manifest_bytes).decode("ascii")
    history["fork_checkpoint_manifest"] = base64.b64encode(
        checkpoint_manifest_bytes
    ).decode("ascii")
    body_bytes = codec.dumps(body)
    digest = sha256_hex(body_bytes)
    signed = json.dumps({
        "schema": envelope["schema"], "version": envelope["version"],
        "timeline_id": envelope["timeline_id"],
        "simulation_tick": envelope["simulation_tick"], "body_sha256": digest,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    envelope.update({
        "body": base64.b64encode(body_bytes).decode("ascii"),
        "body_sha256": digest,
        "signature": base64.b64encode(
            trust.sign("cognitive-world/world-state-checkpoint/v3", signed)
        ).decode("ascii"),
    })
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resign_world_checkpoint_without_local_event_record(world_bytes, trust, event_id):
    """Remove one local Event record, then keep the outer checkpoint validly signed."""
    import base64

    from cognitive_world.core.persistence import sha256_hex

    codec = PersistedValueCodec()
    envelope = json.loads(world_bytes.decode("utf-8"))
    body = codec.loads(base64.b64decode(envelope["body"], validate=True))
    records = body["event_history"]["local_records"]
    kept = []
    removed = False
    for record in records:
        event = codec.loads(base64.b64decode(record["event"], validate=True))
        if event.id == event_id:
            removed = True
        else:
            kept.append(record)
    assert removed, f"expected local Event record {event_id!r} was not found"
    assert kept, "test requires a later local record to expose the broken predecessor link"
    body["event_history"]["local_records"] = kept

    altered_body = codec.dumps(body)
    digest = sha256_hex(altered_body)
    signed = json.dumps({
        "schema": envelope["schema"], "version": envelope["version"],
        "timeline_id": envelope["timeline_id"],
        "simulation_tick": envelope["simulation_tick"], "body_sha256": digest,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    envelope.update({
        "body": base64.b64encode(altered_body).decode("ascii"),
        "body_sha256": digest,
        "signature": base64.b64encode(
            trust.sign("cognitive-world/world-state-checkpoint/v3", signed)
        ).decode("ascii"),
    })
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resign_bundle_for_world_checkpoint(bundle_bytes, world_bytes, trust):
    """Bind a test-signed Bundle manifest to a newly signed WorldState blob."""
    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest

    manifest = SnapshotBundleManifest.from_bytes(bundle_bytes)
    altered = replace(
        manifest, world_checkpoint_sha256=sha256_hex(world_bytes),
        signature=b"test-signature-pending",
    )
    body = json.dumps(altered._body(), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    signed = replace(
        altered,
        signature=trust.sign("cognitive-world/snapshot-bundle-manifest/v2", body),
    )
    assert signed.verify_signature(trust)
    return signed.to_bytes()


def _resign_cognitive_snapshot_with_replaced_memory(snapshot_bytes, trust, memory_id):
    from cognitive_world.cognition.snapshot import (
        CognitiveRecordSnapshot, CognitiveStateSnapshot, CognitiveStoreSnapshot,
        cognitive_snapshot_codec,
    )
    from cognitive_world.core.persistence import sha256_hex

    codec = cognitive_snapshot_codec()
    snapshot = CognitiveStateSnapshot.from_bytes(snapshot_bytes, trust=trust, codec=codec)
    stores = []
    replaced = False
    for store in snapshot.body.stores:
        if store.store_name != "memories":
            stores.append(store)
            continue
        records = []
        for record in store.records:
            if record.record_id == memory_id:
                memory = replace(record.value, content={"summary": "altered inherited memory"})
                record = CognitiveRecordSnapshot(
                    record.owner_id, record.record_id, memory, record.sources,
                )
                replaced = True
            records.append(record)
        frozen_records = tuple(records)
        unsigned = CognitiveStoreSnapshot(
            store.store_name, frozen_records, store.owner_ids, "sha256:pending",
        )
        state_version = "sha256:" + sha256_hex(codec.dumps(unsigned))
        stores.append(CognitiveStoreSnapshot(
            store.store_name, frozen_records, store.owner_ids, state_version,
        ))
    assert replaced, f"expected inherited Memory {memory_id!r} was not found"
    body = replace(snapshot.body, stores=tuple(stores))
    body_bytes = codec.dumps(body)
    signed = replace(
        snapshot, body=body, content_digest="sha256:" + sha256_hex(body_bytes),
        signature_hex=trust.sign("cognitive-world/cognitive-state-snapshot/v3", body_bytes).hex(),
    )
    return codec.dumps(signed)


def _resign_cognitive_snapshot_without_memory(snapshot_bytes, trust, memory_id):
    from cognitive_world.cognition.snapshot import (
        CognitiveStateSnapshot, CognitiveStoreSnapshot, cognitive_snapshot_codec,
    )
    from cognitive_world.core.persistence import sha256_hex

    codec = cognitive_snapshot_codec()
    snapshot = CognitiveStateSnapshot.from_bytes(snapshot_bytes, trust=trust, codec=codec)
    stores = []
    removed = False
    for store in snapshot.body.stores:
        if store.store_name != "memories":
            stores.append(store)
            continue
        records = tuple(item for item in store.records if item.record_id != memory_id)
        removed = len(records) != len(store.records)
        assert removed, f"expected inherited Memory {memory_id!r} was not found"
        owners = tuple(sorted({item.owner_id for item in records}))
        unsigned = CognitiveStoreSnapshot(
            store.store_name, records, owners, "sha256:pending",
        )
        stores.append(CognitiveStoreSnapshot(
            store.store_name, records, owners,
            "sha256:" + sha256_hex(codec.dumps(unsigned)),
        ))
    assert removed
    links = tuple(replace(
        link, memory_ids=tuple(item for item in link.memory_ids if item != memory_id),
    ) for link in snapshot.body.agent_links)
    body = replace(snapshot.body, stores=tuple(stores), agent_links=links)
    body_bytes = codec.dumps(body)
    signed = replace(
        snapshot, body=body, content_digest="sha256:" + sha256_hex(body_bytes),
        signature_hex=trust.sign("cognitive-world/cognitive-state-snapshot/v3", body_bytes).hex(),
    )
    return codec.dumps(signed)


def _resign_bundle_for_cognitive_snapshot(bundle_bytes, cognitive_bytes, trust):
    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest

    manifest = SnapshotBundleManifest.from_bytes(bundle_bytes)
    altered = replace(
        manifest, cognitive_snapshot_sha256=sha256_hex(cognitive_bytes),
        signature=b"test-signature-pending",
    )
    body = json.dumps(altered._body(), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    signed = replace(
        altered,
        signature=trust.sign("cognitive-world/snapshot-bundle-manifest/v2", body),
    )
    assert signed.verify_signature(trust)
    return signed.to_bytes()


def test_multigeneration_memory_ancestry_and_sibling_suffixes_restore(tmp_path):
    manager, trust, saves, memories = _multigeneration_memory_saves(tmp_path)
    expected = {
        "a": {"a"}, "b": {"a", "b"},
        "c": {"a", "b", "c"}, "s": {"a", "s"},
    }
    expected_events = {
        "a": {"event:ancestor-a"},
        "b": {"event:ancestor-a", "event:ancestor-b"},
        "c": {"event:ancestor-a", "event:ancestor-b", "event:ancestor-c"},
        "s": {"event:ancestor-a", "event:ancestor-s"},
    }
    for label, saved in saves.items():
        loaded = manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
        assert loaded.metadata.save_id == saved.save_id
        active, _, _ = _live_runtime(trust, timeline_id=saved.timeline_id)
        staged = manager.stage_restore(
            saved.save_id, timeline_id=saved.timeline_id, active_runtime=active,
            assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(),
            new_timeline_id=f"timeline:ancestor-check-{label}",
        )
        restored = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
        assert {event.id for event in restored.context.event_history.get_events()} == expected_events[label]
        store = restored.cognition_context_provider(
            restored.context.agent_registry.get(AGENT_ID)
        ).memory_store
        assert {item.id for item in store.get_all_memories()} == {
            memories[name].id for name in expected[label]
        }
        restored.memory_revision_lineage.validate_records(store.get_all_memories())
        for name in expected[label]:
            assert store.get_memory(memories[name].id) == memories[name]
        for name in {"a", "b", "c", "s"} - expected[label]:
            assert store.get_memory(memories[name].id) is None


@pytest.mark.parametrize("ancestor,component", [
    ("a", "bundle"), ("a", "cognition"),
    ("b", "bundle"), ("b", "cognition"), ("b", "fork"),
])
def test_missing_ancestor_blob_rejects_grandchild_load_and_stage(
    tmp_path, ancestor, component,
):
    manager, trust, saves, _ = _multigeneration_memory_saves(tmp_path)
    target = _ancestor_component_path(manager, saves[ancestor], component)
    assert f"sha256:{target.stem}" in saves["c"].resource_ids
    target.unlink()
    with pytest.raises(FileNotFoundError, match="missing resources"):
        manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    active, _, _ = _live_runtime(trust, timeline_id=saves["c"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    original_history = active.context.event_history
    original_generation = active.write_fence.restore_generation
    with pytest.raises(FileNotFoundError, match="missing resources"):
        manager.stage_restore(
            saves["c"].save_id, timeline_id=saves["c"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(),
            new_timeline_id="timeline:missing-ancestor-recovery",
        )
    assert slot.current is active
    assert active.context.event_history is original_history
    assert active.write_fence.restore_generation == original_generation
    assert not active.write_fence.frozen


@pytest.mark.parametrize("ancestor,component", [
    ("a", "bundle"), ("a", "cognition"),
    ("b", "bundle"), ("b", "cognition"), ("b", "fork"),
])
def test_corrupt_ancestor_blob_rejects_grandchild_load_and_stage(
    tmp_path, ancestor, component,
):
    manager, trust, saves, _ = _multigeneration_memory_saves(tmp_path)
    target = _ancestor_component_path(manager, saves[ancestor], component)
    assert f"sha256:{target.stem}" in saves["c"].resource_ids
    target.write_bytes(target.read_bytes() + b"\ncorrupted-ancestor-resource")
    with pytest.raises(PermissionError, match="resource content digest mismatch"):
        manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    active, _, _ = _live_runtime(trust, timeline_id=saves["c"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(PermissionError, match="resource content digest mismatch"):
        manager.stage_restore(
            saves["c"].save_id, timeline_id=saves["c"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(),
            new_timeline_id="timeline:corrupt-ancestor-recovery",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


def test_content_addressed_bundle_with_invalid_signature_rejects_load_and_stage(tmp_path):
    from dataclasses import replace
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest

    manager, trust, saves, _ = _multigeneration_memory_saves(tmp_path)
    original_path = _ancestor_component_path(manager, saves["b"], "bundle")
    manifest = SnapshotBundleManifest.from_bytes(original_path.read_bytes())
    invalid_bytes = replace(manifest, signature=b"\x00" * len(manifest.signature)).to_bytes()
    altered_path = _replace_saved_blob(manager, saves["b"], "bundle", invalid_bytes)
    assert altered_path.is_file()

    with pytest.raises(PermissionError, match="signature is invalid"):
        manager.load_verified(saves["b"].save_id, timeline_id=saves["b"].timeline_id)
    active, _, _ = _live_runtime(trust, timeline_id=saves["b"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(PermissionError, match="signature is invalid"):
        manager.stage_restore(
            saves["b"].save_id, timeline_id=saves["b"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:invalid-signed-bundle",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


def test_cross_sibling_fork_manifest_cannot_be_paired_with_branch_bundle(tmp_path):
    manager, trust, saves, _ = _multigeneration_memory_saves(tmp_path)
    sibling_fork = _ancestor_component_path(manager, saves["s"], "fork").read_bytes()
    _replace_saved_blob(manager, saves["b"], "fork", sibling_fork)

    with pytest.raises(PermissionError, match="fork manifest does not bind"):
        manager.load_verified(saves["b"].save_id, timeline_id=saves["b"].timeline_id)
    active, _, _ = _live_runtime(trust, timeline_id=saves["b"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(PermissionError, match="fork manifest does not bind"):
        manager.stage_restore(
            saves["b"].save_id, timeline_id=saves["b"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:cross-sibling-fork",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


def test_signed_fork_with_wrong_parent_checkpoint_is_rejected_and_recovery_remains_available(
    tmp_path,
):
    from cognitive_world.core.timeline import TimelineForkManifest

    manager, trust, saves, memories = _multigeneration_memory_saves(tmp_path)
    fork_path = _ancestor_component_path(manager, saves["c"], "fork")
    original_fork = fork_path.read_bytes()
    original = TimelineForkManifest.from_bytes(original_fork)
    assert original.fork_checkpoint_id == saves["b"].bundle_sha256
    assert original.parent_timeline_id == saves["b"].timeline_id
    wrong_parent_bytes = _resign_fork_manifest(
        original_fork, trust, fork_checkpoint_id=saves["a"].bundle_sha256,
    )
    signed_wrong_parent = TimelineForkManifest.from_bytes(wrong_parent_bytes)
    assert signed_wrong_parent.parent_timeline_id == original.parent_timeline_id
    assert signed_wrong_parent.fork_checkpoint_id == saves["a"].bundle_sha256
    assert signed_wrong_parent.fork_checkpoint_id != saves["b"].bundle_sha256
    assert trust.verify(
        "cognitive-world/timeline-fork/v1",
        json.dumps(signed_wrong_parent._body(), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode("utf-8"),
        signed_wrong_parent.signature,
    )
    _replace_saved_blob(manager, saves["c"], "fork", wrong_parent_bytes)

    # The invalid save is rejected before staging. The later healthy recovery
    # stages a new child from C itself, so its active parent must be C.
    active, _, _ = _live_runtime(trust, timeline_id=saves["c"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(
        PermissionError, match="resolved parent EventHistory does not match fork checkpoint",
    ):
        manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    with pytest.raises(
        PermissionError, match="resolved parent EventHistory does not match fork checkpoint",
    ):
        manager.stage_restore(
            saves["c"].save_id, timeline_id=saves["c"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:wrong-parent-c",
        )
    assert slot.current is active
    assert not active.write_fence.frozen
    assert manager.load_verified(saves["s"].save_id, timeline_id=saves["s"].timeline_id)

    _replace_saved_blob(manager, saves["c"], "fork", original_fork)
    assert manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    staged = manager.stage_restore(
        saves["c"].save_id, timeline_id=saves["c"].timeline_id,
        active_runtime=active, assembler=DoorRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="timeline:recovered-c",
    )
    assert staged.parent_timeline_id == active.context.event_history.timeline_id
    assert staged.parent_timeline_id == saves["c"].timeline_id
    recovered = RestoreCoordinator(slot).activate(staged)
    assert slot.current is recovered
    recovered_store = recovered.cognition_context_provider(
        recovered.context.agent_registry.get(AGENT_ID)
    ).memory_store
    assert {item.id for item in recovered_store.get_all_memories()} == {
        memories[name].id for name in ("a", "b", "c")
    }
    assert recovered_store.get_memory(memories["s"].id) is None

    sibling_active, _, _ = _live_runtime(
        trust, timeline_id=saves["s"].timeline_id,
    )
    sibling_slot = ActiveRuntimeSlot(sibling_active)
    sibling_staged = manager.stage_restore(
        saves["s"].save_id, timeline_id=saves["s"].timeline_id,
        active_runtime=sibling_active, assembler=DoorRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="timeline:recovered-sibling",
    )
    sibling = RestoreCoordinator(sibling_slot).activate(sibling_staged)
    assert sibling_slot.current is sibling
    assert {event.id for event in sibling.context.event_history.get_events()} == {
        "event:ancestor-a", "event:ancestor-s",
    }
    sibling_store = sibling.cognition_context_provider(
        sibling.context.agent_registry.get(AGENT_ID)
    ).memory_store
    assert {item.id for item in sibling_store.get_all_memories()} == {
        memories["a"].id, memories["s"].id,
    }
    assert sibling_store.get_memory(memories["b"].id) is None
    assert sibling_store.get_memory(memories["c"].id) is None


def test_signed_fork_with_wrong_inherited_event_head_is_rejected(tmp_path):
    manager, trust, saves, _ = _multigeneration_memory_saves(tmp_path)
    fork_path = _ancestor_component_path(manager, saves["c"], "fork")
    original_fork = fork_path.read_bytes()
    bad_head = "f" * 64
    assert bad_head != saves["b"].event_chain_head_sha256
    wrong_head_bytes = _resign_fork_manifest(
        original_fork, trust, inherited_event_chain_head_sha256=bad_head,
    )
    _replace_saved_blob(manager, saves["c"], "fork", wrong_head_bytes)

    active, _, _ = _live_runtime(
        trust, timeline_id=saves["c"].parent_timeline_id,
    )
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(
        PermissionError, match="resolved parent EventHistory does not match fork checkpoint",
    ):
        manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    with pytest.raises(
        PermissionError, match="resolved parent EventHistory does not match fork checkpoint",
    ):
        manager.stage_restore(
            saves["c"].save_id, timeline_id=saves["c"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:wrong-event-head-c",
        )
    assert slot.current is active
    assert not active.write_fence.frozen
    assert manager.load_verified(saves["s"].save_id, timeline_id=saves["s"].timeline_id)


def test_signed_ancestor_checkpoint_rejects_invalid_local_event_proof(tmp_path):
    import base64

    from cognitive_world.core.persistence import sha256_hex

    manager, trust, saves, _ = _multigeneration_memory_saves(tmp_path)
    world_path = _ancestor_component_path(manager, saves["b"], "world")
    bundle_path = _ancestor_component_path(manager, saves["b"], "bundle")
    original_world = world_path.read_bytes()
    original_bundle = bundle_path.read_bytes()

    invalid_world = _resign_world_checkpoint_with_invalid_local_event_signature(
        original_world, trust, "event:ancestor-b",
    )
    invalid_bundle = _resign_bundle_for_world_checkpoint(
        original_bundle, invalid_world, trust,
    )
    _replace_saved_blob(manager, saves["b"], "world", invalid_world)
    _replace_saved_blob(manager, saves["b"], "bundle", invalid_bundle)

    # The outer content address, WorldState signature, and Bundle signature all
    # remain valid; rejection must reach the EventHistory local-proof boundary.
    world_envelope = json.loads(invalid_world.decode("utf-8"))
    world_body = base64.b64decode(world_envelope["body"], validate=True)
    world_signed = json.dumps({
        "schema": world_envelope["schema"], "version": world_envelope["version"],
        "timeline_id": world_envelope["timeline_id"],
        "simulation_tick": world_envelope["simulation_tick"],
        "body_sha256": world_envelope["body_sha256"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert sha256_hex(world_body) == world_envelope["body_sha256"]
    assert trust.verify(
        "cognitive-world/world-state-checkpoint/v3", world_signed,
        base64.b64decode(world_envelope["signature"], validate=True),
    )
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
    manifest = SnapshotBundleManifest.from_bytes(invalid_bundle)
    assert manifest.world_checkpoint_sha256 == sha256_hex(invalid_world)
    assert manifest.verify_signature(trust)
    assert sha256_hex(invalid_world) == _ancestor_component_path(
        manager, saves["b"], "world",
    ).stem

    with pytest.raises(
        PermissionError, match="Event processing attestation is missing or invalid",
    ):
        manager.load_verified(saves["b"].save_id, timeline_id=saves["b"].timeline_id)

    active, _, _ = _live_runtime(trust, timeline_id=saves["b"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(
        PermissionError, match="Event processing attestation is missing or invalid",
    ):
        manager.stage_restore(
            saves["b"].save_id, timeline_id=saves["b"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:invalid-local-proof",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


def test_grandchild_load_rejects_invalid_intermediate_ancestor_event_proof(tmp_path):
    import base64

    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
    from cognitive_world.core.timeline import TimelineForkManifest

    manager, trust, saves, memories = _multigeneration_memory_saves(tmp_path)
    assert manager.load_verified(saves["a"].save_id, timeline_id=saves["a"].timeline_id)

    b_world_path = _ancestor_component_path(manager, saves["b"], "world")
    b_bundle_path = _ancestor_component_path(manager, saves["b"], "bundle")
    b_fork_path = _ancestor_component_path(manager, saves["b"], "fork")
    c_world_path = _ancestor_component_path(manager, saves["c"], "world")
    c_fork_path = _ancestor_component_path(manager, saves["c"], "fork")
    c_bundle_path = _ancestor_component_path(manager, saves["c"], "bundle")
    original_b_world = b_world_path.read_bytes()
    original_b_bundle = b_bundle_path.read_bytes()
    original_b_fork = b_fork_path.read_bytes()
    original_c_world = c_world_path.read_bytes()
    original_c_fork = c_fork_path.read_bytes()
    original_c_bundle = c_bundle_path.read_bytes()

    invalid_b_world = _resign_world_checkpoint_with_invalid_local_event_signature(
        original_b_world, trust, "event:ancestor-b",
    )
    invalid_b_bundle = _resign_bundle_for_world_checkpoint(
        original_b_bundle, invalid_b_world, trust,
    )
    faulty_b_checkpoint_id = sha256_hex(invalid_b_bundle)
    original_c_fork_manifest = TimelineForkManifest.from_bytes(original_c_fork)
    rebound_c_fork = _resign_fork_manifest(
        original_c_fork, trust, fork_checkpoint_id=faulty_b_checkpoint_id,
    )
    rebound_c_world = _resign_world_checkpoint_with_parent_checkpoint(
        original_c_world, trust, fork_manifest_bytes=rebound_c_fork,
        checkpoint_manifest_bytes=invalid_b_bundle,
    )
    rebound_c_bundle = _resign_bundle_for_world_checkpoint(
        original_c_bundle, rebound_c_world, trust,
    )

    # Install B first, then re-sign C's two persisted parent references and
    # outer components so C's content-addressed graph points at faulty B.
    _replace_saved_blob(manager, saves["b"], "world", invalid_b_world)
    _replace_saved_blob(manager, saves["b"], "bundle", invalid_b_bundle)
    _replace_saved_blob(manager, saves["c"], "world", rebound_c_world)
    _replace_saved_blob(manager, saves["c"], "fork", rebound_c_fork)
    _replace_saved_blob(manager, saves["c"], "bundle", rebound_c_bundle)
    _set_saved_fork_metadata(manager, saves["c"], rebound_c_fork)

    # A remains valid. B's WorldState and Bundle envelopes are validly signed,
    # while the selected local Event attestation is independently invalid.
    assert manager.load_verified(saves["a"].save_id, timeline_id=saves["a"].timeline_id)
    b_world_envelope = json.loads(invalid_b_world.decode("utf-8"))
    b_world_signed = json.dumps({
        "schema": b_world_envelope["schema"], "version": b_world_envelope["version"],
        "timeline_id": b_world_envelope["timeline_id"],
        "simulation_tick": b_world_envelope["simulation_tick"],
        "body_sha256": b_world_envelope["body_sha256"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    b_world_body = base64.b64decode(b_world_envelope["body"], validate=True)
    assert sha256_hex(b_world_body) == b_world_envelope["body_sha256"]
    assert trust.verify(
        "cognitive-world/world-state-checkpoint/v3", b_world_signed,
        base64.b64decode(b_world_envelope["signature"], validate=True),
    )
    b_manifest = SnapshotBundleManifest.from_bytes(invalid_b_bundle)
    assert b_manifest.verify_signature(trust)
    assert b_manifest.world_checkpoint_sha256 == sha256_hex(invalid_b_world)
    b_fork_manifest = TimelineForkManifest.from_bytes(original_b_fork)
    assert b_fork_manifest.parent_timeline_id == saves["a"].timeline_id
    assert b_fork_manifest.fork_checkpoint_id == saves["a"].bundle_sha256
    assert trust.verify(
        "cognitive-world/timeline-fork/v1",
        json.dumps(b_fork_manifest._body(), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode("utf-8"),
        b_fork_manifest.signature,
    )
    codec = PersistedValueCodec()
    b_state = codec.loads(b_world_body)
    invalid_record = next(
        record for record in b_state["event_history"]["local_records"]
        if codec.loads(base64.b64decode(record["event"], validate=True)).id
        == "event:ancestor-b"
    )
    assert not trust.verify(
        "cognitive-world/event-processing/v2",
        base64.b64decode(invalid_record["attestation"], validate=True),
        base64.b64decode(invalid_record["signature"], validate=True),
    )

    # Both C's signed Fork record and embedded checkpoint bytes resolve to the
    # new B Bundle content address; the old healthy B ID is not being followed.
    c_fork_manifest = TimelineForkManifest.from_bytes(rebound_c_fork)
    assert c_fork_manifest.parent_timeline_id == saves["b"].timeline_id
    assert c_fork_manifest.fork_checkpoint_id == faulty_b_checkpoint_id
    assert c_fork_manifest.fork_checkpoint_id != original_c_fork_manifest.fork_checkpoint_id
    assert trust.verify(
        "cognitive-world/timeline-fork/v1",
        json.dumps(c_fork_manifest._body(), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode("utf-8"),
        c_fork_manifest.signature,
    )
    c_state = PersistedValueCodec().loads(
        base64.b64decode(json.loads(rebound_c_world.decode("utf-8"))["body"], validate=True)
    )
    embedded_history = c_state["event_history"]
    assert base64.b64decode(embedded_history["fork_manifest"], validate=True) == rebound_c_fork
    assert base64.b64decode(
        embedded_history["fork_checkpoint_manifest"], validate=True
    ) == invalid_b_bundle
    c_world_envelope = json.loads(rebound_c_world.decode("utf-8"))
    c_world_signed = json.dumps({
        "schema": c_world_envelope["schema"], "version": c_world_envelope["version"],
        "timeline_id": c_world_envelope["timeline_id"],
        "simulation_tick": c_world_envelope["simulation_tick"],
        "body_sha256": c_world_envelope["body_sha256"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert trust.verify(
        "cognitive-world/world-state-checkpoint/v3", c_world_signed,
        base64.b64decode(c_world_envelope["signature"], validate=True),
    )
    c_manifest = SnapshotBundleManifest.from_bytes(rebound_c_bundle)
    assert c_manifest.verify_signature(trust)
    assert c_manifest.world_checkpoint_sha256 == sha256_hex(rebound_c_world)
    c_record = manager._load_catalog()["saves"][saves["c"].save_id]
    assert c_record["fork_checkpoint_id"] == faulty_b_checkpoint_id
    assert manager._read_blob(f"sha256:{faulty_b_checkpoint_id}") == invalid_b_bundle
    assert manager._load_catalog()["checkpoints"][
        f"sha256:{faulty_b_checkpoint_id}"
    ]["blob_refs"]["world"] == f"sha256:{sha256_hex(invalid_b_world)}"

    active, _, _ = _live_runtime(trust, timeline_id=saves["c"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    original_history = active.context.event_history
    with pytest.raises(
        PermissionError, match="Event processing attestation is missing or invalid",
    ):
        manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    with pytest.raises(
        PermissionError, match="Event processing attestation is missing or invalid",
    ):
        manager.stage_restore(
            saves["c"].save_id, timeline_id=saves["c"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:bad-grandchild",
        )
    assert slot.current is active
    assert active.context.event_history is original_history
    assert not active.write_fence.frozen

    # The healthy sibling remains independently loadable and restorable.
    assert manager.load_verified(saves["s"].save_id, timeline_id=saves["s"].timeline_id)
    sibling_active, _, _ = _live_runtime(trust, timeline_id=saves["s"].timeline_id)
    sibling_slot = ActiveRuntimeSlot(sibling_active)
    sibling_staged = manager.stage_restore(
        saves["s"].save_id, timeline_id=saves["s"].timeline_id,
        active_runtime=sibling_active, assembler=DoorRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="timeline:healthy-sibling",
    )
    sibling = RestoreCoordinator(sibling_slot).activate(sibling_staged)
    sibling_store = sibling.cognition_context_provider(
        sibling.context.agent_registry.get(AGENT_ID)
    ).memory_store
    assert {event.id for event in sibling.context.event_history.get_events()} == {
        "event:ancestor-a", "event:ancestor-s",
    }
    assert {item.id for item in sibling_store.get_all_memories()} == {
        memories["a"].id, memories["s"].id,
    }
    assert sibling_store.get_memory(memories["b"].id) is None
    assert sibling_store.get_memory(memories["c"].id) is None

    # Restore only the original test resources, then prove the healthy C chain
    # remains loadable and can be activated through the normal coordinator.
    _replace_saved_blob(manager, saves["b"], "world", original_b_world)
    _replace_saved_blob(manager, saves["b"], "bundle", original_b_bundle)
    _replace_saved_blob(manager, saves["c"], "world", original_c_world)
    _replace_saved_blob(manager, saves["c"], "fork", original_c_fork)
    _replace_saved_blob(manager, saves["c"], "bundle", original_c_bundle)
    _set_saved_fork_metadata(manager, saves["c"], original_c_fork)
    assert manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    healthy_staged = manager.stage_restore(
        saves["c"].save_id, timeline_id=saves["c"].timeline_id,
        active_runtime=active, assembler=DoorRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="timeline:healthy-grandchild",
    )
    recovered = RestoreCoordinator(slot).activate(healthy_staged)
    assert slot.current is recovered
    recovered_store = recovered.cognition_context_provider(
        recovered.context.agent_registry.get(AGENT_ID)
    ).memory_store
    assert {event.id for event in recovered.context.event_history.get_events()} == {
        "event:ancestor-a", "event:ancestor-b", "event:ancestor-c",
    }
    assert {item.id for item in recovered_store.get_all_memories()} == {
        memories["a"].id, memories["b"].id, memories["c"].id,
    }
    assert recovered_store.get_memory(memories["s"].id) is None


def test_signed_ancestor_checkpoint_rejects_omitted_local_event_record(tmp_path):
    import base64

    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest

    manager, trust, saves, _ = _multigeneration_memory_saves(
        tmp_path, include_second_b_event=True,
    )
    original_world = _ancestor_component_path(manager, saves["b"], "world").read_bytes()
    original_bundle = _ancestor_component_path(manager, saves["b"], "bundle").read_bytes()
    missing_record_world = _resign_world_checkpoint_without_local_event_record(
        original_world, trust, "event:ancestor-b",
    )
    signed_bundle = _resign_bundle_for_world_checkpoint(
        original_bundle, missing_record_world, trust,
    )
    _replace_saved_blob(manager, saves["b"], "world", missing_record_world)
    _replace_saved_blob(manager, saves["b"], "bundle", signed_bundle)

    envelope = json.loads(missing_record_world.decode("utf-8"))
    body_bytes = base64.b64decode(envelope["body"], validate=True)
    signed_body = json.dumps({
        "schema": envelope["schema"], "version": envelope["version"],
        "timeline_id": envelope["timeline_id"],
        "simulation_tick": envelope["simulation_tick"],
        "body_sha256": envelope["body_sha256"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert sha256_hex(body_bytes) == envelope["body_sha256"]
    assert trust.verify(
        "cognitive-world/world-state-checkpoint/v3", signed_body,
        base64.b64decode(envelope["signature"], validate=True),
    )
    manifest = SnapshotBundleManifest.from_bytes(signed_bundle)
    assert manifest.world_checkpoint_sha256 == sha256_hex(missing_record_world)
    assert manifest.verify_signature(trust)

    expected_error = "Event attestation chain or schema is invalid"
    with pytest.raises(ValueError, match=expected_error):
        manager.load_verified(saves["b"].save_id, timeline_id=saves["b"].timeline_id)
    active, _, _ = _live_runtime(trust, timeline_id=saves["b"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(ValueError, match=expected_error):
        manager.stage_restore(
            saves["b"].save_id, timeline_id=saves["b"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:missing-local-event",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


def test_signed_checkpoint_rejects_changed_inherited_memory_on_load_and_stage(tmp_path):
    from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, cognitive_snapshot_codec
    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest

    manager, trust, saves, memories = _multigeneration_memory_saves(tmp_path)
    cognition_path = _ancestor_component_path(manager, saves["b"], "cognition")
    bundle_path = _ancestor_component_path(manager, saves["b"], "bundle")
    original_cognition = cognition_path.read_bytes()
    original_bundle = bundle_path.read_bytes()

    invalid_cognition = _resign_cognitive_snapshot_with_replaced_memory(
        original_cognition, trust, memories["a"].id,
    )
    invalid_bundle = _resign_bundle_for_cognitive_snapshot(
        original_bundle, invalid_cognition, trust,
    )
    _replace_saved_blob(manager, saves["b"], "cognition", invalid_cognition)
    _replace_saved_blob(manager, saves["b"], "bundle", invalid_bundle)

    codec = cognitive_snapshot_codec()
    parsed_snapshot = CognitiveStateSnapshot.from_bytes(
        invalid_cognition, trust=trust, codec=codec,
    )
    assert parsed_snapshot.signature_hex is not None
    manifest = SnapshotBundleManifest.from_bytes(invalid_bundle)
    assert manifest.cognitive_snapshot_sha256 == sha256_hex(invalid_cognition)
    assert manifest.verify_signature(trust)

    expected_error = "branch changed or omitted an inherited checkpoint Memory"
    with pytest.raises(PermissionError, match=expected_error):
        manager.load_verified(saves["b"].save_id, timeline_id=saves["b"].timeline_id)

    active, _, _ = _live_runtime(trust, timeline_id=saves["b"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(PermissionError, match=expected_error):
        manager.stage_restore(
            saves["b"].save_id, timeline_id=saves["b"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:altered-ancestor-memory",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


def test_signed_grandchild_rejects_omitted_independent_ancestor_memory(tmp_path):
    from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, cognitive_snapshot_codec
    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest

    manager, trust, saves, memories = _multigeneration_memory_saves(
        tmp_path, include_independent_ancestor_memory=True,
    )
    cognition_bytes = _ancestor_component_path(manager, saves["c"], "cognition").read_bytes()
    bundle_bytes = _ancestor_component_path(manager, saves["c"], "bundle").read_bytes()
    omitted_id = memories["a_independent"].id
    omitted_cognition = _resign_cognitive_snapshot_without_memory(
        cognition_bytes, trust, omitted_id,
    )
    signed_bundle = _resign_bundle_for_cognitive_snapshot(bundle_bytes, omitted_cognition, trust)
    _replace_saved_blob(manager, saves["c"], "cognition", omitted_cognition)
    _replace_saved_blob(manager, saves["c"], "bundle", signed_bundle)

    snapshot = CognitiveStateSnapshot.from_bytes(
        omitted_cognition, trust=trust, codec=cognitive_snapshot_codec(),
    )
    assert snapshot.signature_hex is not None
    manifest = SnapshotBundleManifest.from_bytes(signed_bundle)
    assert manifest.cognitive_snapshot_sha256 == sha256_hex(omitted_cognition)
    assert manifest.verify_signature(trust)

    expected_error = "branch changed or omitted an inherited checkpoint Memory"
    with pytest.raises(PermissionError, match=expected_error):
        manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    active, _, _ = _live_runtime(trust, timeline_id=saves["c"].timeline_id)
    slot = ActiveRuntimeSlot(active)
    with pytest.raises(PermissionError, match=expected_error):
        manager.stage_restore(
            saves["c"].save_id, timeline_id=saves["c"].timeline_id,
            active_runtime=active, assembler=DoorRuntimeAssembler(trust),
            dependencies=_dependency_manifest(), new_timeline_id="timeline:omitted-ancestor-memory",
        )
    assert slot.current is active
    assert not active.write_fence.frozen


@pytest.mark.parametrize("delete_order", [("b", "s"), ("s", "b")])
def test_shared_ancestor_survives_parent_and_sibling_slot_deletion_orders(
    tmp_path, delete_order,
):
    manager, trust, saves, memories = _multigeneration_memory_saves(tmp_path)
    manager.delete_manual_save(saves["a"].save_id)
    manager.collect_garbage()
    assert manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
    assert manager.load_verified(saves["s"].save_id, timeline_id=saves["s"].timeline_id)
    assert all(manager._blob_path(item).is_file() for item in saves["c"].resource_ids)

    for index, label in enumerate(delete_order):
        manager.delete_manual_save(saves[label].save_id)
        manager.collect_garbage()
        remaining = {"b", "s"} - set(delete_order[:index + 1])
        for branch in remaining:
            assert manager.load_verified(
                saves[branch].save_id, timeline_id=saves[branch].timeline_id,
            )
        assert manager.load_verified(saves["c"].save_id, timeline_id=saves["c"].timeline_id)
        assert all(manager._blob_path(item).is_file() for item in saves["c"].resource_ids)
        assert manager.verify_consistency()

    active, _, _ = _live_runtime(trust, timeline_id=saves["c"].timeline_id)
    staged = manager.stage_restore(
        saves["c"].save_id, timeline_id=saves["c"].timeline_id,
        active_runtime=active, assembler=DoorRuntimeAssembler(trust),
        dependencies=_dependency_manifest(),
        new_timeline_id="timeline:surviving-grandchild",
    )
    restored = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
    store = restored.cognition_context_provider(
        restored.context.agent_registry.get(AGENT_ID)
    ).memory_store
    assert {item.id for item in store.get_all_memories()} == {
        memories[name].id for name in ("a", "b", "c")
    }
    assert store.get_memory(memories["s"].id) is None
