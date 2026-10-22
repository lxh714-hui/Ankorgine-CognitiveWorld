"""Fail-closed construction of an isolated, staged SimulationRuntime.

Snapshot data restores canonical state only. Host-owned executable policy and
pending runtime work must be explicitly reconstructed by the host; this module
never clones a live Runtime or activates the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol
from uuid import uuid4

from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition.snapshot import CognitiveAgentManifestEntry
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
from cognitive_world.core.persistence import PersistenceTrust, PersistedValueCodec
from cognitive_world.core.snapshot_bundle import (
    SnapshotBundleManifest, VerifiedSnapshotBundle, _require_verified_snapshot_bundle,
)
from cognitive_world.core.timeline import TimelineForkManifest
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.write_fence import (
    RuntimeWriteFence, _RESTORE_COORDINATOR_AUTHORITY,
)
from cognitive_world.safety.governance import UniversalSafetyGovernance


class DependencyStrategy(str, Enum):
    """How one Runtime dependency is supplied for reconstruction."""

    SNAPSHOT = "verified_snapshot"
    REBUILT = "rebuilt_from_verified_state_or_code"
    HOST = "explicit_host_reinjection"
    DISABLED = "explicitly_disabled"
    UNSUPPORTED = "unsupported"


_DEPENDENCY_ROLES = frozenset({
    "agent_character_catalog", "agent_runtime_metadata", "agent_scheduler_state",
    "event_scheduler_state", "event_handler_registry", "agent_decision_policy",
    "agent_action_loop_policy", "cognition_context_provider", "safety_policy",
    "observation_policy", "provider_policy", "conflict_scheduler_policy",
    "event_tree_policy", "content_expansion_policy", "player_session_policy",
})
_DISABLABLE_ROLES = frozenset({
    "provider_policy", "content_expansion_policy", "player_session_policy",
})


@dataclass(frozen=True)
class RuntimeDependencyResolution:
    role: str
    strategy: DependencyStrategy
    source: str

    def __post_init__(self) -> None:
        if self.role not in _DEPENDENCY_ROLES:
            raise ValueError("unknown Runtime reconstruction dependency role")
        if not isinstance(self.strategy, DependencyStrategy):
            raise TypeError("dependency strategy must be typed")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("dependency resolution requires an auditable source")


@dataclass(frozen=True)
class RuntimeDependencyManifest:
    """Host declaration of where non-snapshot Runtime dependencies come from.

    This is an assembly contract, not a signature or proof that a host source
    is trustworthy. The host supplying it remains part of the trust boundary.
    """

    resolutions: tuple[RuntimeDependencyResolution, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.resolutions, tuple) or any(
            type(item) is not RuntimeDependencyResolution for item in self.resolutions
        ):
            raise TypeError("Runtime dependency resolutions must be a typed tuple")
        roles = tuple(item.role for item in self.resolutions)
        if len(roles) != len(set(roles)) or set(roles) != _DEPENDENCY_ROLES:
            raise ValueError("Runtime dependency manifest must resolve every required role exactly once")
        for item in self.resolutions:
            if item.strategy is DependencyStrategy.UNSUPPORTED:
                raise RuntimeError(f"required Runtime dependency is unsupported: {item.role}")
            if item.strategy is DependencyStrategy.DISABLED and item.role not in _DISABLABLE_ROLES:
                raise RuntimeError(f"required Runtime dependency cannot be disabled: {item.role}")
        selected = {item.role: item.strategy for item in self.resolutions}
        host_roles = {
            "agent_character_catalog", "agent_runtime_metadata", "agent_scheduler_state",
            "event_scheduler_state", "event_handler_registry", "agent_decision_policy",
            "agent_action_loop_policy", "cognition_context_provider", "safety_policy",
            "observation_policy",
        }
        if any(selected[role] is not DependencyStrategy.HOST for role in host_roles):
            raise ValueError("runtime-specific definitions and policies require explicit host reinjection")
        if selected["event_tree_policy"] is not DependencyStrategy.REBUILT:
            raise ValueError("Event Tree diagnostics must be rebuilt from the current implementation")
        if selected["conflict_scheduler_policy"] not in {
            DependencyStrategy.HOST, DependencyStrategy.REBUILT,
        }:
            raise ValueError("Conflict & Opportunity Scheduler must be explicitly rebuilt or reinjected")
        if selected["provider_policy"] not in {
            DependencyStrategy.HOST, DependencyStrategy.DISABLED,
        } or selected["content_expansion_policy"] not in {
            DependencyStrategy.HOST, DependencyStrategy.DISABLED,
        } or selected["player_session_policy"] not in {
            DependencyStrategy.HOST, DependencyStrategy.DISABLED,
        }:
            raise ValueError("optional services must be explicitly configured or disabled")

    def strategy_for(self, role: str) -> DependencyStrategy:
        return next(item.strategy for item in self.resolutions if item.role == role)


@dataclass(frozen=True)
class RuntimeAssemblyInputs:
    world_state: object
    event_history: EventHistory
    cognition: object
    memory_store: object
    expected_agents: tuple[CognitiveAgentManifestEntry, ...]
    agent_links: tuple[object, ...]
    clock: SimulationClock
    write_fence: RuntimeWriteFence
    timeline_id: str
    parent_timeline_id: str | None
    fork_checkpoint_id: str | None
    simulation_tick: int
    dependencies: RuntimeDependencyManifest
    behavior_feedback: object
    behavior_feedback_status: str
    memory_revision_lineage: MemoryRevisionLineage


class RuntimeAssembler(Protocol):
    """Trusted host adapter which creates fresh executable Runtime components."""

    def assemble(self, inputs: RuntimeAssemblyInputs) -> SimulationRuntime:
        """Return a new Runtime whose dependencies reference only ``inputs``."""
        ...


_STAGED_RUNTIME_SEAL = object()


@dataclass(frozen=True)
class StagedRuntime:
    runtime: SimulationRuntime
    timeline_id: str
    parent_timeline_id: str
    fork_checkpoint_id: str
    simulation_tick: int
    restore_generation: int
    dependencies: RuntimeDependencyManifest
    status: str = "staged_not_active"
    _inputs: RuntimeAssemblyInputs | None = field(default=None, repr=False, compare=False)
    _trust: PersistenceTrust | None = field(default=None, repr=False, compare=False)
    _codec: PersistedValueCodec | None = field(default=None, repr=False, compare=False)
    _seal: object | None = field(default=None, repr=False, compare=False)
    _checkpoint_manifest: SnapshotBundleManifest | None = field(default=None, repr=False, compare=False)
    _fork_manifest: TimelineForkManifest | None = field(default=None, repr=False, compare=False)
    _world_checkpoint: bytes | None = field(default=None, repr=False, compare=False)
    _cognitive_snapshot: bytes | None = field(default=None, repr=False, compare=False)
    _behavior_feedback_snapshot: bytes | None = field(default=None, repr=False, compare=False)
    _expected_agents: tuple[CognitiveAgentManifestEntry, ...] | None = field(default=None, repr=False, compare=False)
    _event_history_resolver: object | None = field(default=None, repr=False, compare=False)
    _checkpoint_memory_revision_lineage: MemoryRevisionLineage | None = field(
        default=None, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        if self.status != "staged_not_active":
            raise ValueError("reconstruction cannot produce an active Runtime")
        if (self.runtime.running or not self.runtime.write_fence.frozen
                or not self.runtime.write_fence.staged_only):
            raise ValueError("staged Runtime must be stopped and write-frozen")
        if self.runtime.write_fence.restore_generation != self.restore_generation:
            raise ValueError("staged Runtime generation does not match its fence")


class RuntimeReconstructionError(RuntimeError):
    """A reconstruction stage failed without publishing or activating state."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"Runtime reconstruction failed at {stage}: {reason}")
        self.stage = stage
        self.reason = reason


class IsolatedRuntimeReconstructionFactory:
    """Reverify a signed checkpoint and stage a separately assembled Runtime."""

    @staticmethod
    def stage(
        *, active_runtime: SimulationRuntime,
        checkpoint_manifest: SnapshotBundleManifest,
        world_checkpoint: bytes,
        cognitive_snapshot: bytes,
        behavior_feedback_snapshot: bytes | None = None,
        expected_agents: tuple[CognitiveAgentManifestEntry, ...],
        fork_manifest: TimelineForkManifest,
        trust: PersistenceTrust,
        assembler: RuntimeAssembler,
        dependencies: RuntimeDependencyManifest,
        event_history_resolver: object | None = None,
        memory_revision_lineage: MemoryRevisionLineage | None = None,
        codec: PersistedValueCodec | None = None,
    ) -> StagedRuntime:
        """Build an isolated child Runtime; never changes a live Runtime.

        Raw signed component bytes are reverified here so a caller cannot
        mutate an already-staged mutable ``VerifiedSnapshotBundle`` and then
        ask this factory to trust it.
        """
        if type(active_runtime) is not SimulationRuntime:
            raise TypeError("reconstruction requires the current canonical active Runtime for alias checks")
        if type(checkpoint_manifest) is not SnapshotBundleManifest:
            raise TypeError("reconstruction requires a signed SnapshotBundleManifest")
        if type(fork_manifest) is not TimelineForkManifest:
            raise TypeError("reconstruction requires a signed TimelineForkManifest")
        if not isinstance(dependencies, RuntimeDependencyManifest):
            raise TypeError("reconstruction requires an explicit Runtime dependency manifest")
        if not callable(getattr(assembler, "assemble", None)):
            raise TypeError("reconstruction requires an explicit RuntimeAssembler")
        codec = codec or PersistedValueCodec()
        try:
            bundle = checkpoint_manifest.verify_and_stage(
                world_checkpoint=world_checkpoint,
                cognitive_snapshot=cognitive_snapshot,
                expected_agents=expected_agents,
                trust=trust,
                event_history_resolver=event_history_resolver,
                behavior_feedback_snapshot=behavior_feedback_snapshot,
                memory_revision_lineage=memory_revision_lineage,
                codec=codec,
            )
            if type(bundle) is not VerifiedSnapshotBundle:
                raise TypeError("bundle verifier returned an unsupported staging object")
            _require_verified_snapshot_bundle(bundle)
        except Exception as error:
            raise RuntimeReconstructionError(
                "bundle_verification", f"{type(error).__name__}: {error}"
            ) from error

        try:
            fork_manifest.verify_against_checkpoint(
                checkpoint_manifest, verified_bundle=bundle, trust=trust,
            )
            if fork_manifest.timeline_id == fork_manifest.parent_timeline_id:
                raise PermissionError("child Runtime requires an independent Timeline ID")
            child_history = EventHistory.fork_from_checkpoint(
                bundle.event_history,
                fork_manifest=fork_manifest,
                checkpoint_manifest=checkpoint_manifest,
                verified_bundle=bundle,
                trust=trust,
                codec=codec,
            )
            child_history.verify_persisted_lineage(codec=codec, trust=trust)
            if (child_history.timeline_id != fork_manifest.timeline_id
                    or child_history.last_persistence_record_digest()
                    != fork_manifest.inherited_event_chain_head_sha256
                    or child_history.export_local_persisted_records()):
                raise PermissionError("new branch history is not anchored at the verified checkpoint")
            revision_lineage = MemoryRevisionLineage.fork_from_verified_bundle(
                verified_bundle=bundle, checkpoint_manifest=checkpoint_manifest,
                timeline_id=fork_manifest.timeline_id, fork_manifest=fork_manifest,
                trust=trust,
            )
            checkpoint_revision_lineage = memory_revision_lineage or bundle.memory_revision_lineage
        except Exception as error:
            raise RuntimeReconstructionError(
                "timeline_lineage", f"{type(error).__name__}: {error}"
            ) from error

        fence = RuntimeWriteFence(session_id=str(uuid4()))
        fence.seal_staged_only()
        clock = SimulationClock(bundle.simulation_tick)
        branch_memory_store = MemoryStore.from_isolated_snapshot(
            bundle.cognition.memory_store.get_all_memories(),
            revision_lineage=revision_lineage,
        )
        revision_lineage.validate_records(branch_memory_store.get_all_memories())
        inputs = RuntimeAssemblyInputs(
            bundle.world_state, child_history, bundle.cognition.cognition,
            branch_memory_store, bundle.cognition.expected_agents,
            bundle.cognition.agent_links, clock, fence, fork_manifest.timeline_id,
            fork_manifest.parent_timeline_id, fork_manifest.fork_checkpoint_id,
            bundle.simulation_tick, dependencies,
            bundle.behavior_feedback, bundle.behavior_feedback_status,
            revision_lineage,
        )
        try:
            runtime = assembler.assemble(inputs)
            if runtime.memory_revision_lineage is None:
                runtime.memory_revision_lineage = revision_lineage
            if runtime.memory_revision_lineage != revision_lineage:
                raise PermissionError("Runtime is bound to a different Memory revision view")
            IsolatedRuntimeReconstructionFactory._validate_assembly(runtime, inputs, trust)
            IsolatedRuntimeReconstructionFactory._validate_no_active_aliases(
                runtime, active_runtime, inputs,
            )
        except Exception as error:
            raise RuntimeReconstructionError(
                "runtime_assembly", f"{type(error).__name__}: {error}"
            ) from error
        return StagedRuntime(
            runtime=runtime, timeline_id=fork_manifest.timeline_id,
            parent_timeline_id=fork_manifest.parent_timeline_id,
            fork_checkpoint_id=fork_manifest.fork_checkpoint_id,
            simulation_tick=bundle.simulation_tick,
            restore_generation=fence.restore_generation, dependencies=dependencies,
            _inputs=inputs, _trust=trust, _codec=codec, _seal=_STAGED_RUNTIME_SEAL,
            _checkpoint_manifest=checkpoint_manifest, _fork_manifest=fork_manifest,
            _world_checkpoint=world_checkpoint, _cognitive_snapshot=cognitive_snapshot,
            _behavior_feedback_snapshot=behavior_feedback_snapshot,
            _expected_agents=expected_agents, _event_history_resolver=event_history_resolver,
            _checkpoint_memory_revision_lineage=checkpoint_revision_lineage,
        )

    @staticmethod
    def _validate_assembly(
        runtime: object, inputs: RuntimeAssemblyInputs, trust: PersistenceTrust,
        *, activating: bool = False,
    ) -> None:
        if type(runtime) is not SimulationRuntime:
            raise TypeError("assembler must return canonical SimulationRuntime")
        if not runtime.strict_dependency_binding:
            raise PermissionError("staged Runtime must use strict no-rebinding dependency validation")
        if runtime.memory_revision_lineage != inputs.memory_revision_lineage:
            raise PermissionError("Runtime is not bound to the verified Memory revision view")
        if type(runtime.memory_revision_lineage) is not MemoryRevisionLineage:
            raise PermissionError("Runtime has an invalid Memory revision view")
        runtime.memory_revision_lineage._require_issued()
        inputs.memory_revision_lineage._require_issued()
        if (runtime.behavior_feedback is not inputs.behavior_feedback
                or runtime.behavior_feedback_status != inputs.behavior_feedback_status):
            raise PermissionError("Runtime BehaviorFeedback is not bound to the verified staged component")
        if runtime.running is not activating:
            raise PermissionError("Runtime running state does not match the assembly phase")
        if runtime.write_fence is not inputs.write_fence:
            raise PermissionError("Runtime must use the reconstructed write fence")
        if activating:
            if runtime.write_fence.frozen or runtime.write_fence.staged_only:
                raise PermissionError("activating Runtime fence is not writable")
        elif not runtime.write_fence.frozen or not runtime.write_fence.staged_only:
            raise PermissionError("staged Runtime fence must remain sealed")
        if runtime.allow_environment_provider_discovery:
            raise PermissionError("staged Runtime cannot discover providers from ambient environment")
        context = runtime.context
        if (context.world_state is not inputs.world_state
                or context.event_history is not inputs.event_history
                or context.event_history.timeline_id != inputs.timeline_id
                or context.clock is not inputs.clock
                or context.clock.current_time != inputs.simulation_tick):
            raise PermissionError("Runtime context is not bound to the staged checkpoint")
        if (type(context.agent_registry) is not AgentRegistry
                or type(context.agent_scheduler) is not AgentScheduler
                or type(context.scheduler) is not EventScheduler
                or type(context.observation_store) is not ObservationStore
                or type(context.safety_governance) is not UniversalSafetyGovernance):
            raise TypeError("Runtime assembly omitted a required canonical context dependency")
        if (inputs.dependencies.strategy_for("player_session_policy") is DependencyStrategy.DISABLED
                and context.player_session is not None):
            raise PermissionError("PlayerSession was supplied although its policy is disabled")
        if (inputs.dependencies.strategy_for("player_session_policy") is DependencyStrategy.HOST
                and context.player_session is None):
            raise PermissionError("host-declared PlayerSession policy was not supplied")
        expected = tuple(sorted((item.agent_id, item.character_id) for item in inputs.expected_agents))
        actual_agents = context.agent_registry.all_agents()
        actual = tuple(sorted((item.agent_id, item.character_id) for item in actual_agents))
        if actual != expected:
            raise PermissionError("staged AgentRegistry does not match the verified manifest")
        goal_links = {item.agent_id: tuple(sorted(item.goal_ids)) for item in inputs.agent_links}
        if any(tuple(sorted(agent.get_goals())) != goal_links.get(agent.agent_id, ())
               for agent in actual_agents):
            raise PermissionError("RuntimeAgent Goal links do not match the verified cognition manifest")
        processor = runtime.event_processor
        if type(processor) is not EventProcessor:
            raise TypeError("staged Runtime requires the canonical EventProcessor")
        if (processor.world_state is not inputs.world_state
                or processor.event_history is not inputs.event_history
                or processor.simulation_clock is not inputs.clock
                or processor.agent_registry is not context.agent_registry
                or processor.observation_store is not context.observation_store
                or processor.write_fence is not inputs.write_fence
                or processor.persistence_trust is not trust):
            raise PermissionError("EventProcessor references a different Runtime state or trust root")
        loop = runtime.agent_action_loop
        if type(loop) is not AgentActionLoop or loop.write_fence is not inputs.write_fence:
            raise TypeError("staged Runtime requires a newly bound canonical AgentActionLoop")
        from cognitive_world.agent.turn import AgentTurn
        from cognitive_world.decision.action_pipeline import ActionPipeline
        from cognitive_world.decision.agent_decision import AgentDecision
        from cognitive_world.resolution.action_flow import ActionResolutionFlow
        if (type(loop.agent_turn) is not AgentTurn
                or loop.agent_turn.write_fence is not inputs.write_fence
                or type(loop.action_pipeline) is not ActionPipeline
                or type(loop.action_resolution_flow) is not ActionResolutionFlow):
            raise TypeError("staged Runtime requires canonical AgentTurn, ActionPipeline and Resolution flow")
        from cognitive_world.cognition.l1_consumption_proof import L1ConsumptionIssuer
        issuer = loop.agent_turn.l1_consumption_issuer
        if (type(issuer) is not L1ConsumptionIssuer
                or issuer.history is not inputs.event_history
                or issuer.clock is not inputs.clock
                or issuer.trust is not trust
                or issuer.fence is not inputs.write_fence):
            raise PermissionError("staged L1 proof issuer is not bound to reconstructed authorities")
        if (loop.safety_governance is not context.safety_governance
                or loop.action_pipeline.safety_governance is not context.safety_governance
                or loop.action_resolution_flow.world_state is not inputs.world_state
                or loop.action_resolution_flow.event_history is not inputs.event_history
                or loop.action_resolution_flow.safety_governance is not context.safety_governance
                or loop.action_resolution_flow.event_factory.safety_governance is not context.safety_governance):
            raise PermissionError("ActionLoop references a different staged authority")
        if type(runtime.agent_decision) is not AgentDecision:
            raise TypeError("staged Runtime requires canonical AgentDecision")
        if runtime.evidence_review_provider is None:
            raise PermissionError("staged Runtime requires an explicit evidence review provider")
        if inputs.dependencies.strategy_for("provider_policy") is DependencyStrategy.DISABLED:
            if (runtime.cognitive_review_provider is not None
                    or runtime.self_model_review_provider is not None):
                raise PermissionError("provider was supplied although model provider policy is disabled")
        elif (runtime.cognitive_review_provider is None
              and runtime.self_model_review_provider is None):
            raise PermissionError("host-declared model provider policy was not supplied")
        if inputs.dependencies.strategy_for("content_expansion_policy") is DependencyStrategy.DISABLED:
            if runtime.proactive_content_expansion is not None:
                raise PermissionError("content expansion is enabled contrary to its dependency manifest")
        elif runtime.proactive_content_expansion is None:
            raise PermissionError("host-declared content expansion policy was not supplied")
        provider = runtime.cognition_context_provider
        if not callable(provider):
            raise TypeError("staged Runtime requires an explicit cognition context provider")
        links = {item.agent_id: item for item in inputs.agent_links}
        def checked_provider(agent):
            cognition_context = provider(agent)
            link = links.get(agent.agent_id)
            if (type(cognition_context) is not CognitionContext or link is None
                    or cognition_context.owner_id != agent.agent_id
                    or cognition_context.character_id != agent.character_id
                    or cognition_context.cognition_container is not inputs.cognition
                    or cognition_context.memory_store is not inputs.memory_store
                    or cognition_context.observation_store is not context.observation_store
                    or cognition_context.metacognitive_feedback is not None
                    or (cognition_context.memory_retriever is not None
                        and getattr(cognition_context.memory_retriever, "store", None)
                        is not inputs.memory_store)):
                raise PermissionError("CognitionContext is not rebuilt from staged owner stores")
            expected_memory_ids: list[str] = []
            for memory_id in link.memory_ids:
                memory = inputs.memory_store.get_memory(memory_id)
                if memory is None or memory.owner_id != link.agent_id:
                    raise PermissionError("verified Memory link is missing or belongs to another owner")
                if MemoryStore.is_semantically_retrievable(memory):
                    expected_memory_ids.append(memory_id)
            if (tuple(sorted(item.id for item in cognition_context.get_beliefs()))
                    != tuple(sorted(link.belief_ids))
                    or tuple(sorted(item.goal_id for item in cognition_context.get_goals()))
                    != tuple(sorted(link.goal_ids))
                    or tuple(sorted(item.id for item in cognition_context.get_memories()))
                    != tuple(sorted(expected_memory_ids))):
                raise PermissionError("CognitionContext record links do not match the verified snapshot")
            self_model = cognition_context.get_self_model()
            if (self_model is not None) != link.has_self_model:
                raise PermissionError("CognitionContext SelfModel link does not match the verified snapshot")
            personality = cognition_context.get_personality()
            if (None if personality is None else personality.id) != link.personality_id:
                raise PermissionError("CognitionContext Personality link does not match the verified snapshot")
            emotion = cognition_context.get_emotion()
            if (None if emotion is None else emotion.id) != link.emotion_id:
                raise PermissionError("CognitionContext Emotion link does not match the verified snapshot")
            cognition_context.bind_write_fence(inputs.write_fence)
            if (inputs.cognition.write_fence is not inputs.write_fence
                    or inputs.memory_store.write_fence is not inputs.write_fence):
                raise PermissionError("canonical cognition and Memory Stores are not bound to the staged fence")
            return cognition_context
        runtime.cognition_context_provider = checked_provider
        for agent in actual_agents:
            checked_provider(agent)

    @staticmethod
    def _validate_no_active_aliases(
        staged: SimulationRuntime, active: SimulationRuntime,
        inputs: RuntimeAssemblyInputs,
    ) -> None:
        """Reject reused mutable Runtime authorities and cognition Stores."""
        def identities(runtime: SimulationRuntime) -> set[int]:
            context = runtime.context
            values = [
                context, context.clock, context.world_state, context.event_history,
                context.scheduler, context.agent_scheduler, context.agent_registry,
                context.observation_store, context.safety_governance, runtime.write_fence,
                runtime.event_processor, runtime.agent_action_loop, runtime.agent_decision,
                runtime.evidence_review_provider, runtime.conflict_opportunity_scheduler,
                runtime.proactive_content_expansion, runtime.cognitive_review_provider,
                runtime.self_model_review_provider,
            ]
            loop = runtime.agent_action_loop
            if loop is not None:
                flow = getattr(loop, "action_resolution_flow", None)
                turn = getattr(loop, "agent_turn", None)
                values.extend((
                    turn, getattr(loop, "action_pipeline", None), flow,
                    getattr(turn, "cognitive_runtime", None),
                    getattr(flow, "resolution_engine", None),
                    getattr(flow, "event_factory", None),
                ))
            processor = runtime.event_processor
            handlers = getattr(processor, "_handlers", None)
            if isinstance(handlers, dict):
                values.extend((handlers, *handlers.values()))
            return {id(value) for value in values if value is not None}

        if identities(staged) & identities(active):
            raise PermissionError("staged Runtime aliases a mutable active Runtime dependency")

        active_provider = active.cognition_context_provider
        active_registry = active.context.agent_registry
        if callable(active_provider) and isinstance(active_registry, AgentRegistry):
            for entry in inputs.expected_agents:
                agent = active_registry.get(entry.agent_id)
                if agent is None:
                    continue
                old_context = active_provider(agent)
                if (getattr(old_context, "cognition_container", None) is inputs.cognition
                        or getattr(old_context, "memory_store", None) is inputs.memory_store):
                    raise PermissionError("staged canonical cognition aliases an active Agent Store")
