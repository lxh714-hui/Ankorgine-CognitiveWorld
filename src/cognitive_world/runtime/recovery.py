from __future__ import annotations

from dataclasses import dataclass
import base64
import json
from enum import Enum
from threading import RLock
from typing import Callable
from weakref import ref

from cognitive_world.cognition.snapshot import (
    CognitiveStateSnapshot, verify_restored_stores_match_snapshot,
)
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.runtime.reconstruction import (
    IsolatedRuntimeReconstructionFactory,
    StagedRuntime,
    _STAGED_RUNTIME_SEAL,
)
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime.write_fence import _RESTORE_COORDINATOR_AUTHORITY


_ACTIVE_OWNERS_LOCK = RLock()
_ACTIVE_RUNTIME_OWNERS: dict[int, tuple[object, object]] = {}


def _claim_active_slot(slot: object, runtime: SimulationRuntime) -> None:
    runtime_key = id(runtime)
    with _ACTIVE_OWNERS_LOCK:
        runtime_entry = _ACTIVE_RUNTIME_OWNERS.get(runtime_key)
        if (runtime_entry is not None and runtime_entry[0]() is runtime
                and runtime_entry[1]() is not None):
            raise RuntimeError("Runtime is already owned by another ActiveRuntimeSlot")
        slot_ref = ref(slot)
        _ACTIVE_RUNTIME_OWNERS[runtime_key] = (ref(runtime), slot_ref)


def _replace_active_slot(slot: object, old: SimulationRuntime, new: SimulationRuntime) -> None:
    with _ACTIVE_OWNERS_LOCK:
        existing_runtime = _ACTIVE_RUNTIME_OWNERS.get(id(new))
        if existing_runtime is not None and existing_runtime[0]() is new:
            if existing_runtime[1]() is not slot:
                raise RuntimeError("replacement Runtime is already owned by another active slot")
        old_runtime = _ACTIVE_RUNTIME_OWNERS.get(id(old))
        if old_runtime is not None and old_runtime[1]() is slot:
            del _ACTIVE_RUNTIME_OWNERS[id(old)]
        slot_ref = ref(slot)
        _ACTIVE_RUNTIME_OWNERS[id(new)] = (ref(new), slot_ref)


class RestoreState(str, Enum):
    ACTIVE = "ACTIVE"
    PREPARING = "PREPARING"
    FROZEN = "FROZEN"
    PUBLISHING = "PUBLISHING"
    ACTIVE_NEW = "ACTIVE_NEW"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class RuntimeRestoreError(RuntimeError):
    def __init__(self, stage: RestoreState, reason: str) -> None:
        super().__init__(f"Runtime restore failed during {stage.value}: {reason}")
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class RuntimePublication:
    runtime: SimulationRuntime
    state: RestoreState
    publication_generation: int


class ActiveRuntimeSlot:
    """The sole synchronized active Runtime reference for one host session."""

    def __init__(self, runtime: SimulationRuntime) -> None:
        if type(runtime) is not SimulationRuntime:
            raise TypeError("active slot requires canonical SimulationRuntime")
        if runtime.write_fence.frozen or runtime.write_fence.staged_only or runtime.write_fence.retired:
            raise ValueError("initial Runtime must be active and writable")
        self._runtime = runtime
        self._state = RestoreState.ACTIVE
        self._publication_generation = 0
        self._lock = RLock()
        self._coordinator = None
        _claim_active_slot(self, runtime)

    def snapshot(self) -> RuntimePublication:
        with self._lock:
            return RuntimePublication(self._runtime, self._state, self._publication_generation)

    @property
    def current(self) -> SimulationRuntime:
        return self.snapshot().runtime

    @property
    def state(self) -> RestoreState:
        return self.snapshot().state

    def _bind_coordinator(self, coordinator: "RestoreCoordinator") -> None:
        with self._lock:
            current = None if self._coordinator is None else self._coordinator()
            if current is not None and current is not coordinator:
                raise RuntimeError("ActiveRuntimeSlot already has a RestoreCoordinator")
            self._coordinator = ref(coordinator)

    def _set_state(self, coordinator: "RestoreCoordinator", state: RestoreState) -> None:
        with self._lock:
            if self._coordinator is None or self._coordinator() is not coordinator:
                raise PermissionError("only the bound RestoreCoordinator may change slot state")
            self._state = state

    def _publish(
        self, coordinator: "RestoreCoordinator", expected: SimulationRuntime,
        replacement: SimulationRuntime,
    ) -> None:
        with self._lock:
            if self._coordinator is None or self._coordinator() is not coordinator:
                raise PermissionError("only the bound RestoreCoordinator may publish a Runtime")
            if self._runtime is not expected or self._state is not RestoreState.PUBLISHING:
                raise RuntimeError("active Runtime slot changed during publication")
            if (replacement.write_fence.frozen or replacement.write_fence.staged_only
                    or not replacement.running):
                raise RuntimeError("replacement Runtime is not activated")
            if not expected.write_fence.frozen:
                raise RuntimeError("old Runtime must be frozen before publication")
            _replace_active_slot(self, expected, replacement)
            self._runtime = replacement
            self._publication_generation += 1
            self._state = RestoreState.ACTIVE_NEW


class RestoreCoordinator:
    """Serializes freeze, validation and the only active Runtime publication."""

    def __init__(
        self, slot: ActiveRuntimeSlot,
        *, pre_publish_hook: Callable[[StagedRuntime], None] | None = None,
    ) -> None:
        if type(slot) is not ActiveRuntimeSlot:
            raise TypeError("RestoreCoordinator requires ActiveRuntimeSlot")
        if pre_publish_hook is not None and not callable(pre_publish_hook):
            raise TypeError("pre_publish_hook must be callable")
        self.slot = slot
        self.pre_publish_hook = pre_publish_hook
        self._lock = RLock()
        self._state = slot.state
        self._last_failure: RuntimeRestoreError | None = None
        slot._bind_coordinator(self)

    @property
    def state(self) -> RestoreState:
        with self._lock:
            return self._state

    @property
    def last_failure(self) -> RuntimeRestoreError | None:
        with self._lock:
            return self._last_failure

    def activate(self, staged: StagedRuntime) -> SimulationRuntime:
        """Validate, freeze, and atomically publish one staged Runtime.

        A previous Runtime is resumed only when publication has not happened;
        its old generation is never restored. Any uncertain post-freeze failure
        leaves the slot frozen in RECOVERY_REQUIRED rather than allowing two writers.
        """
        with self._lock:
            if self._state is RestoreState.RECOVERY_REQUIRED:
                raise RuntimeRestoreError(self._state, "manual recovery is required")
            old = self.slot.current
            if self._state not in (RestoreState.ACTIVE, RestoreState.ACTIVE_NEW):
                raise RuntimeRestoreError(self._state, "another restore is already in progress")
            prior_state = self._state
            old_was_running = old.running
            self._state = RestoreState.PREPARING
            self.slot._set_state(self, RestoreState.PREPARING)
            try:
                self._validate_staged(staged, old)
            except Exception as error:
                self._restore_stable_state(prior_state)
                failure = RuntimeRestoreError(RestoreState.PREPARING, f"{type(error).__name__}: {error}")
                self._last_failure = failure
                raise failure from error

            if staged.parent_timeline_id != old.context.event_history.timeline_id:
                self._restore_stable_state(prior_state)
                failure = RuntimeRestoreError(
                    RestoreState.PREPARING, "staged child does not descend from the active Timeline",
                )
                self._last_failure = failure
                raise failure

            try:
                old.write_fence._freeze_for_recovery(_RESTORE_COORDINATOR_AUTHORITY)
                old.stop()
                self._state = RestoreState.FROZEN
                self.slot._set_state(self, RestoreState.FROZEN)
            except Exception as error:
                if not old.write_fence.frozen:
                    self._restore_stable_state(prior_state)
                else:
                    self._state = RestoreState.RECOVERY_REQUIRED
                    self.slot._set_state(self, RestoreState.RECOVERY_REQUIRED)
                failure = RuntimeRestoreError(RestoreState.FROZEN, f"{type(error).__name__}: {error}")
                self._last_failure = failure
                raise failure from error

            try:
                self._validate_staged(staged, old)
            except Exception as error:
                self._state = RestoreState.RECOVERY_REQUIRED
                self.slot._set_state(self, RestoreState.RECOVERY_REQUIRED)
                failure = RuntimeRestoreError(RestoreState.FROZEN, f"{type(error).__name__}: {error}")
                self._last_failure = failure
                raise failure from error
            try:
                if self.pre_publish_hook is not None:
                    self.pre_publish_hook(staged)
            except Exception as error:
                self._resume_old_or_require_recovery(old, prior_state, error, old_was_running)
                failure = RuntimeRestoreError(RestoreState.FROZEN, f"{type(error).__name__}: {error}")
                self._last_failure = failure
                raise failure from error

            self._state = RestoreState.PUBLISHING
            self.slot._set_state(self, RestoreState.PUBLISHING)
            published = False
            integrity_failure = False

            def validate_for_publication() -> None:
                nonlocal integrity_failure
                try:
                    self._validate_staged(staged, old)
                    if staged.parent_timeline_id != old.context.event_history.timeline_id:
                        raise PermissionError("staged parent Timeline changed")
                except Exception:
                    integrity_failure = True
                    raise

            def publish_atomically() -> None:
                nonlocal published, integrity_failure
                staged.runtime.start()
                # start() is an overridable lifecycle entry point. Recheck
                # actual state and references before retiring the old writer.
                try:
                    self._validate_staged(staged, old, activating=True)
                except Exception:
                    integrity_failure = True
                    raise
                old.write_fence._retire_after_recovery(_RESTORE_COORDINATOR_AUTHORITY)
                # Retirement is the last operation before the pointer swap.
                # Recheck once more so even a changed dependency during that
                # transition cannot be published as the validated instance.
                try:
                    self._validate_staged(staged, old, activating=True)
                except Exception:
                    integrity_failure = True
                    raise
                self.slot._publish(self, old, staged.runtime)
                published = True

            try:
                # Agent registration has its own lock and is not governed by
                # RuntimeWriteFence. Hold both across final validation/swap.
                with staged.runtime.context.agent_registry.snapshot_scope():
                    staged.runtime.write_fence._activate_staged_and_publish(
                        _RESTORE_COORDINATOR_AUTHORITY, publish_atomically,
                        validate=validate_for_publication,
                    )
            except Exception as error:
                staged.runtime.stop()
                if integrity_failure:
                    self._state = RestoreState.RECOVERY_REQUIRED
                    self.slot._set_state(self, RestoreState.RECOVERY_REQUIRED)
                elif published:
                    self._state = RestoreState.RECOVERY_REQUIRED
                    self.slot._set_state(self, RestoreState.RECOVERY_REQUIRED)
                elif old.write_fence.retired:
                    self._state = RestoreState.RECOVERY_REQUIRED
                    self.slot._set_state(self, RestoreState.RECOVERY_REQUIRED)
                else:
                    self._resume_old_or_require_recovery(old, prior_state, error, old_was_running)
                failure = RuntimeRestoreError(RestoreState.PUBLISHING, f"{type(error).__name__}: {error}")
                self._last_failure = failure
                raise failure from error

            self._state = RestoreState.ACTIVE_NEW
            self._last_failure = None
            return staged.runtime

    def _validate_staged(
        self, staged: StagedRuntime, active: SimulationRuntime,
        *, activating: bool = False,
    ) -> None:
        if type(staged) is not StagedRuntime or staged._seal is not _STAGED_RUNTIME_SEAL:
            raise PermissionError("StagedRuntime was not issued by the isolated reconstruction factory")
        if staged._inputs is None or staged._trust is None:
            raise PermissionError("staged Runtime has no retained validation context")
        if staged.runtime is active:
            raise PermissionError("staged Runtime is already active")
        if staged.runtime.write_fence.session_id == active.write_fence.session_id:
            raise PermissionError("staged Runtime must use a new RuntimeSession ID")
        expected_generation = staged.restore_generation + int(activating)
        if (staged.status != "staged_not_active"
                or staged.runtime.running is not activating
                or staged.runtime.write_fence.restore_generation != expected_generation
                or staged.runtime.write_fence.frozen is activating
                or staged.runtime.write_fence.staged_only is activating):
            raise PermissionError("staged Runtime state or generation changed")
        if activating and staged.parent_timeline_id != active.context.event_history.timeline_id:
            raise PermissionError("staged parent Timeline changed")
        if (staged._checkpoint_manifest is None or staged._fork_manifest is None
                or staged._world_checkpoint is None or staged._cognitive_snapshot is None
                or (staged._checkpoint_manifest.version >= 2
                    and staged._behavior_feedback_snapshot is None)
                or staged._expected_agents is None):
            raise PermissionError("staged Runtime is missing its signed reconstruction inputs")
        if staged._checkpoint_memory_revision_lineage is None:
            raise PermissionError("staged Runtime is missing verified checkpoint revision ancestry")
        codec = staged._codec or PersistedValueCodec()
        verified = staged._checkpoint_manifest.verify_and_stage(
            world_checkpoint=staged._world_checkpoint,
            cognitive_snapshot=staged._cognitive_snapshot,
            expected_agents=staged._expected_agents, trust=staged._trust,
            event_history_resolver=staged._event_history_resolver,
            behavior_feedback_snapshot=staged._behavior_feedback_snapshot,
            memory_revision_lineage=staged._checkpoint_memory_revision_lineage,
            codec=codec,
        )
        if (verified.behavior_feedback_status != staged.runtime.behavior_feedback_status
                or verified.behavior_feedback != staged.runtime.behavior_feedback):
            raise PermissionError("staged BehaviorFeedback differs from the verified snapshot component")
        staged._fork_manifest.verify_against_checkpoint(
            staged._checkpoint_manifest, verified_bundle=verified, trust=staged._trust,
        )
        IsolatedRuntimeReconstructionFactory._validate_assembly(
            staged.runtime, staged._inputs, staged._trust, activating=activating,
        )
        IsolatedRuntimeReconstructionFactory._validate_no_active_aliases(
            staged.runtime, active, staged._inputs,
        )
        actual_history = staged.runtime.context.event_history
        actual_lineage = actual_history.verify_persisted_lineage(
            codec=codec, trust=staged._trust,
        )
        expected_history = EventHistory.fork_from_checkpoint(
            verified.event_history, fork_manifest=staged._fork_manifest,
            checkpoint_manifest=staged._checkpoint_manifest, verified_bundle=verified,
            trust=staged._trust, codec=codec,
        )
        expected_lineage = expected_history.verify_persisted_lineage(
            codec=codec, trust=staged._trust,
        )
        if (codec.dumps(actual_history.export_persisted_state())
                != codec.dumps(expected_history.export_persisted_state())
                or codec.dumps(actual_lineage[2]) != codec.dumps(expected_lineage[2])):
            raise PermissionError("staged EventHistory differs from the verified fork lineage")
        cognitive_snapshot = CognitiveStateSnapshot.from_bytes(
            staged._cognitive_snapshot, trust=staged._trust,
        )
        verify_restored_stores_match_snapshot(
            cognitive_snapshot, cognition=staged._inputs.cognition,
            memory_store=staged._inputs.memory_store, event_history=actual_history,
            write_fence=staged.runtime.write_fence, trust=staged._trust,
            memory_revision_lineage=staged._checkpoint_memory_revision_lineage,
            snapshot_event_history=verified.event_history,
        )
        current_world = staged.runtime.context.world_state.export_persisted_snapshot(
            event_history=verified.event_history, simulation_tick=staged.simulation_tick,
            trust=staged._trust, timeline_id=staged.parent_timeline_id, codec=codec,
        )
        current_envelope = json.loads(current_world.decode("utf-8"))
        expected_envelope = json.loads(staged._world_checkpoint.decode("utf-8"))
        current_envelope.pop("signature", None)
        expected_envelope.pop("signature", None)
        if activating:
            # Runtime.start() legitimately seals WorldState initialization.
            # Compare the actual canonical body against the signed body with
            # only that expected lifecycle transition normalized.
            current_body = codec.loads(base64.b64decode(current_envelope.pop("body"), validate=True))
            expected_body = codec.loads(base64.b64decode(expected_envelope.pop("body"), validate=True))
            current_envelope.pop("body_sha256")
            expected_envelope.pop("body_sha256")
            if current_body.get("initialization_sealed") is not True:
                raise PermissionError("activated WorldState initialization is not sealed")
            current_body["initialization_sealed"] = expected_body["initialization_sealed"]
            if codec.dumps(current_body) != codec.dumps(expected_body):
                raise PermissionError("activated WorldState differs from the signed checkpoint")
        if current_envelope != expected_envelope:
            raise PermissionError("staged WorldState differs from the signed checkpoint")
        if (actual_history.timeline_id != staged.timeline_id
                or staged.runtime.context.clock.current_time != staged.simulation_tick
                or staged._inputs.timeline_id != staged.timeline_id
                or staged._inputs.parent_timeline_id != staged.parent_timeline_id
                or staged._inputs.fork_checkpoint_id != staged.fork_checkpoint_id
                or staged._fork_manifest.timeline_id != staged.timeline_id
                or staged._fork_manifest.parent_timeline_id != staged.parent_timeline_id
                or staged._fork_manifest.fork_checkpoint_id != staged.fork_checkpoint_id):
            raise PermissionError("staged Timeline, clock or fork checkpoint binding changed")
        if actual_history.export_local_persisted_records():
            raise PermissionError("staged Runtime contains an unexpected local event suffix")

    def _restore_stable_state(self, state: RestoreState) -> None:
        self._state = state
        self.slot._set_state(self, state)

    def _resume_old_or_require_recovery(
        self, old: SimulationRuntime, prior_state: RestoreState, cause: Exception,
        old_was_running: bool,
    ) -> None:
        try:
            old.write_fence._resume_after_failed_recovery(_RESTORE_COORDINATOR_AUTHORITY)
            if old_was_running:
                old.start()
            self._restore_stable_state(prior_state)
        except Exception as resume_error:
            old.stop()
            if not old.write_fence.frozen:
                try:
                    old.write_fence._freeze_for_recovery(_RESTORE_COORDINATOR_AUTHORITY)
                except Exception:
                    pass
            self._state = RestoreState.RECOVERY_REQUIRED
            self.slot._set_state(self, RestoreState.RECOVERY_REQUIRED)
            self._last_failure = RuntimeRestoreError(
                RestoreState.RECOVERY_REQUIRED,
                f"restore failed ({type(cause).__name__}); old Runtime could not safely resume ({type(resume_error).__name__})",
            )
