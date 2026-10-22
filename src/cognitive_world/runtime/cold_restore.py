"""Verified, parentless resumption of an existing saved Timeline.

The fork reconstruction path remains separate: this entry resumes the exact
signed Timeline rather than creating a child or fabricating an active parent.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
from threading import RLock
from uuid import uuid4

from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.snapshot import (
    CognitiveStateSnapshot, verify_restored_stores_match_snapshot,
)
from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust
from cognitive_world.core.snapshot_bundle import (
    SnapshotBundleManifest, _require_verified_snapshot_bundle,
)
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime.reconstruction import (
    IsolatedRuntimeReconstructionFactory, RuntimeAssembler,
    RuntimeAssemblyInputs, RuntimeDependencyManifest,
)
from cognitive_world.runtime.recovery import ActiveRuntimeSlot
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.write_fence import RuntimeWriteFence, _RESTORE_COORDINATOR_AUTHORITY


_COLD_STAGE_SEAL = object()


@dataclass(frozen=True)
class ColdStagedRuntime:
    runtime: SimulationRuntime
    inputs: RuntimeAssemblyInputs
    manifest: SnapshotBundleManifest
    world_checkpoint: bytes
    cognitive_snapshot: bytes
    behavior_feedback_snapshot: bytes | None
    expected_agents: tuple[object, ...]
    trust: PersistenceTrust = field(repr=False, compare=False)
    codec: PersistedValueCodec = field(repr=False, compare=False)
    event_history_resolver: object | None = field(repr=False, compare=False)
    memory_revision_lineage: object = field(repr=False, compare=False)
    restore_generation: int = 0
    _seal: object = field(default=None, repr=False, compare=False)


class ColdRuntimeFactory:
    """Reverify signed resources and assemble an unpublished original Timeline."""

    @staticmethod
    def stage(*, saved: object, trust: PersistenceTrust, codec: PersistedValueCodec,
              assembler: RuntimeAssembler, dependencies: RuntimeDependencyManifest,
              event_history_resolver: object | None) -> ColdStagedRuntime:
        from cognitive_world.runtime.save_manager import VerifiedSave
        from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
        from cognitive_world.runtime.clock import SimulationClock

        if type(saved) is not VerifiedSave or type(codec) is not PersistedValueCodec:
            raise TypeError("cold resume requires a verified save and explicit canonical codec")
        if not isinstance(dependencies, RuntimeDependencyManifest):
            raise TypeError("cold resume requires explicit host dependencies")
        if not callable(getattr(assembler, "assemble", None)):
            raise TypeError("cold resume requires a host Runtime assembler")
        bundle = saved.bundle_manifest.verify_and_stage(
            world_checkpoint=saved.world_checkpoint,
            cognitive_snapshot=saved.cognitive_snapshot,
            expected_agents=saved.expected_agents, trust=trust, codec=codec,
            event_history_resolver=event_history_resolver,
            behavior_feedback_snapshot=saved.behavior_feedback_snapshot,
            memory_revision_lineage=saved.memory_revision_lineage,
        )
        _require_verified_snapshot_bundle(bundle)
        history = bundle.event_history
        if type(history) is not EventHistory or history.timeline_id != saved.metadata.timeline_id:
            raise PermissionError("saved EventHistory does not belong to the requested Timeline")
        history.verify_persisted_lineage(codec=codec, trust=trust,
                                         parent_history_resolver=event_history_resolver)
        lineage = saved.memory_revision_lineage
        if type(lineage) is not MemoryRevisionLineage or lineage.timeline_id != history.timeline_id:
            raise PermissionError("saved Memory revision lineage is not bound to the Timeline")
        lineage._require_issued()
        fence = RuntimeWriteFence(session_id=str(uuid4()))
        fence.seal_staged_only()
        memory = MemoryStore.from_isolated_snapshot(
            bundle.cognition.memory_store.get_all_memories(), revision_lineage=lineage,
        )
        lineage.validate_records(memory.get_all_memories())
        fork = saved.fork_manifest
        inputs = RuntimeAssemblyInputs(
            bundle.world_state, history, bundle.cognition.cognition, memory,
            bundle.cognition.expected_agents, bundle.cognition.agent_links,
            SimulationClock(bundle.simulation_tick), fence, history.timeline_id,
            None if fork is None else fork.parent_timeline_id,
            None if fork is None else fork.fork_checkpoint_id,
            bundle.simulation_tick, dependencies, bundle.behavior_feedback,
            bundle.behavior_feedback_status, lineage,
        )
        runtime = assembler.assemble(inputs)
        if runtime.memory_revision_lineage is None:
            runtime.memory_revision_lineage = lineage
        IsolatedRuntimeReconstructionFactory._validate_assembly(runtime, inputs, trust)
        stage = ColdStagedRuntime(
            runtime, inputs, saved.bundle_manifest, saved.world_checkpoint,
            saved.cognitive_snapshot, saved.behavior_feedback_snapshot,
            saved.expected_agents, trust, codec, event_history_resolver, lineage,
            fence.restore_generation, _COLD_STAGE_SEAL,
        )
        ColdRuntimeFactory.validate(stage, activated=False)
        return stage

    @staticmethod
    def validate(stage: ColdStagedRuntime, *, activated: bool) -> None:
        if type(stage) is not ColdStagedRuntime or stage._seal is not _COLD_STAGE_SEAL:
            raise PermissionError("cold staged Runtime was not issued by its verifier")
        runtime, inputs = stage.runtime, stage.inputs
        if (runtime.write_fence is not inputs.write_fence
                or runtime.write_fence.frozen is activated
                or runtime.write_fence.staged_only is activated
                or runtime.running is not activated
                or runtime.write_fence.restore_generation != stage.restore_generation + int(activated)):
            raise PermissionError("cold staged Runtime activation state changed")
        bundle = stage.manifest.verify_and_stage(
            world_checkpoint=stage.world_checkpoint,
            cognitive_snapshot=stage.cognitive_snapshot,
            expected_agents=stage.expected_agents, trust=stage.trust,
            codec=stage.codec,
            event_history_resolver=stage.event_history_resolver,
            behavior_feedback_snapshot=stage.behavior_feedback_snapshot,
            memory_revision_lineage=stage.memory_revision_lineage,
        )
        _require_verified_snapshot_bundle(bundle)
        IsolatedRuntimeReconstructionFactory._validate_assembly(
            runtime, inputs, stage.trust, activating=activated,
        )
        actual_history = runtime.context.event_history
        actual_history.verify_persisted_lineage(
            codec=stage.codec, trust=stage.trust,
            parent_history_resolver=stage.event_history_resolver,
        )
        if (stage.codec.dumps(actual_history.export_persisted_state())
                != stage.codec.dumps(bundle.event_history.export_persisted_state())):
            raise PermissionError("cold staged EventHistory differs from the signed save")
        snapshot = CognitiveStateSnapshot.from_bytes(
            stage.cognitive_snapshot, trust=stage.trust, codec=stage.codec,
        )
        verify_restored_stores_match_snapshot(
            snapshot, cognition=inputs.cognition, memory_store=inputs.memory_store,
            event_history=actual_history, write_fence=runtime.write_fence,
            codec=stage.codec, trust=stage.trust,
            memory_revision_lineage=stage.memory_revision_lineage,
            snapshot_event_history=bundle.event_history,
        )
        current = runtime.context.world_state.export_persisted_snapshot(
            event_history=actual_history, simulation_tick=inputs.simulation_tick,
            timeline_id=inputs.timeline_id, trust=stage.trust, codec=stage.codec,
        )
        current_envelope = json.loads(current.decode("utf-8"))
        expected_envelope = json.loads(stage.world_checkpoint.decode("utf-8"))
        current_envelope.pop("signature", None)
        expected_envelope.pop("signature", None)
        if activated:
            current_body = stage.codec.loads(base64.b64decode(current_envelope.pop("body"), validate=True))
            expected_body = stage.codec.loads(base64.b64decode(expected_envelope.pop("body"), validate=True))
            current_envelope.pop("body_sha256")
            expected_envelope.pop("body_sha256")
            if current_body.get("initialization_sealed") is not True:
                raise PermissionError("activated WorldState is not sealed")
            current_body["initialization_sealed"] = expected_body["initialization_sealed"]
            if stage.codec.dumps(current_body) != stage.codec.dumps(expected_body):
                raise PermissionError("cold staged WorldState differs from the signed save")
        if current_envelope != expected_envelope:
            raise PermissionError("cold staged WorldState envelope differs from the signed save")
        if (runtime.context.clock.current_time != inputs.simulation_tick
                or actual_history.timeline_id != stage.manifest.timeline_id
                or runtime.behavior_feedback != bundle.behavior_feedback
                or runtime.behavior_feedback_status != bundle.behavior_feedback_status):
            raise PermissionError("cold staged Timeline, clock or feedback changed")


class ColdRuntimePublisher:
    """Publish a first Runtime only after a final locked signed-state check."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._published = False

    def activate(self, stage: ColdStagedRuntime) -> ActiveRuntimeSlot:
        with self._lock:
            if self._published:
                raise RuntimeError("cold publisher has already published a Runtime")
            ColdRuntimeFactory.validate(stage, activated=False)
            slot = None

            def publish() -> None:
                nonlocal slot
                stage.runtime.start()
                ColdRuntimeFactory.validate(stage, activated=True)
                slot = ActiveRuntimeSlot(stage.runtime)

            try:
                with stage.runtime.context.agent_registry.snapshot_scope():
                    stage.runtime.write_fence._activate_staged_and_publish(
                        _RESTORE_COORDINATOR_AUTHORITY, publish,
                        validate=lambda: ColdRuntimeFactory.validate(stage, activated=False),
                    )
            except BaseException:
                stage.runtime.stop()
                raise
            if slot is None:
                raise RuntimeError("cold Runtime publication did not yield an active slot")
            self._published = True
            return slot
