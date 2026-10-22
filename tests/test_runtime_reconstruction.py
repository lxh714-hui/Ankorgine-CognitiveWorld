from __future__ import annotations

from dataclasses import replace

import pytest
import json

from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.belief_update import BeliefChange, BeliefUpdateProposal
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.goal_update import GoalChange, GoalUpdateProposal
from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
from cognitive_world.cognition.validation import CognitiveUpdateValidator
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.personality import Personality
from cognitive_world.cognition.snapshot import (
    CognitiveAgentManifestEntry, CognitiveStateSnapshot,
)
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
from cognitive_world.core.timeline import TimelineForkManifest
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.evidence_review import DeterministicLocalEvidenceReviewProvider
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event.handler import EventHandler
from cognitive_world.core.update import WorldUpdate
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.reconstruction import (
    DependencyStrategy, IsolatedRuntimeReconstructionFactory,
    RuntimeDependencyManifest, RuntimeDependencyResolution,
    RuntimeReconstructionError,
)
from cognitive_world.runtime.recovery import (
    ActiveRuntimeSlot, RestoreCoordinator, RestoreState, RuntimeRestoreError,
)
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.safety.governance import UniversalSafetyGovernance
from _trusted_event_support import make_system_event


class FakeTrust:
    def sign(self, purpose, payload):
        import hashlib, hmac
        return hmac.new(b"isolated-runtime-test-key-material", purpose.encode() + b"\0" + payload,
                        hashlib.sha256).digest()

    def verify(self, purpose, payload, signature):
        import hmac
        return hmac.compare_digest(self.sign(purpose, payload), signature)


def _dependency_manifest(*, omit: str | None = None):
    policies = {
        "agent_character_catalog": DependencyStrategy.HOST,
        "agent_runtime_metadata": DependencyStrategy.HOST,
        "agent_scheduler_state": DependencyStrategy.HOST,
        "event_scheduler_state": DependencyStrategy.HOST,
        "event_handler_registry": DependencyStrategy.HOST,
        "agent_decision_policy": DependencyStrategy.HOST,
        "agent_action_loop_policy": DependencyStrategy.HOST,
        "cognition_context_provider": DependencyStrategy.HOST,
        "safety_policy": DependencyStrategy.HOST,
        "observation_policy": DependencyStrategy.HOST,
        "provider_policy": DependencyStrategy.DISABLED,
        "conflict_scheduler_policy": DependencyStrategy.REBUILT,
        "event_tree_policy": DependencyStrategy.REBUILT,
        "content_expansion_policy": DependencyStrategy.DISABLED,
        "player_session_policy": DependencyStrategy.DISABLED,
    }
    return RuntimeDependencyManifest(tuple(
        RuntimeDependencyResolution(role, strategy, f"test-host:{role}")
        for role, strategy in policies.items() if role != omit
    ))


def _signed_inputs(*, shared_goal: bool = False):
    trust = FakeTrust()
    cognition = CognitionContainer()
    cognition.add_personality(Personality("agent-a", traits={"steady": True}))
    if shared_goal:
        cognition.add_personality(Personality("agent-b", traits={"steady": False}))
        cognition.add_goal(Goal("shared-goal", "agent-a", "A private aim", 0.2, "active"))
        cognition.add_goal(Goal("shared-goal", "agent-b", "B private aim", 0.6, "active"))
    memories = MemoryStore()
    roster = (CognitiveAgentManifestEntry("agent-a", "character-a"),)
    if shared_goal:
        roster += (CognitiveAgentManifestEntry("agent-b", "character-b"),)
    character = Character("character-a", "agent-a", "agent-a")
    characters = {"agent-a": character}
    if shared_goal:
        characters["agent-a"] = Character("character-a", "agent-a", "agent-a", goal_ids=["shared-goal"])
        characters["agent-b"] = Character("character-b", "agent-b", "agent-b", goal_ids=["shared-goal"])
    cognition_contexts = tuple(CognitionContext.from_character(
        item, cognition, memories,
    ) for item in characters.values())
    fence = RuntimeWriteFence("source-session")
    for cognition_context in cognition_contexts:
        cognition_context.bind_write_fence(fence)
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a", "character-a",
                                   goal_ids=["shared-goal"] if shared_goal else []))
    if shared_goal:
        registry.register(RuntimeAgent("agent-b", "character-b", goal_ids=["shared-goal"]))
    parent_history = EventHistory(timeline_id="timeline-parent")
    world = WorldState()
    source_runtime = SimulationRuntime(RuntimeContext(
        SimulationClock(4), world, parent_history, agent_registry=registry,
    ), write_fence=fence)
    source_runtime.cognition_context_provider = lambda agent: CognitionContext.from_character(
        characters[agent.agent_id], cognition, memories,
    )
    with fence.operation():
        cognitive_snapshot = CognitiveStateSnapshot.capture(
            cognition=cognition, memory_store=memories, runtime=source_runtime,
            agent_contexts=cognition_contexts, timeline_id="timeline-parent", trust=trust,
        )
    checkpoint = world.export_persisted_snapshot(
        event_history=parent_history, simulation_tick=4,
        trust=trust, timeline_id="timeline-parent",
    )
    manifest = SnapshotBundleManifest.create(
        world_checkpoint=checkpoint, cognitive_snapshot=cognitive_snapshot,
        expected_agents=roster, trust=trust,
    )
    bundle = manifest.verify_and_stage(
        world_checkpoint=checkpoint, cognitive_snapshot=cognitive_snapshot.to_bytes(),
        expected_agents=roster, trust=trust,
    )
    fork = TimelineForkManifest.create_from_checkpoint(
        checkpoint_manifest=manifest, verified_bundle=bundle,
        trust=trust, timeline_id="timeline-child",
    )
    return trust, checkpoint, cognitive_snapshot.to_bytes(), roster, manifest, fork, source_runtime


class ActivationTestHandler(EventHandler):
    def handle(self, event):
        return WorldUpdate("facts", "update", {})


class LocalRuntimeAssembler:
    def __init__(self, trust, *, bad_roster=False, bad_context=False, strict=True,
                 active_alias_runtime=None):
        self.trust = trust
        self.bad_roster = bad_roster
        self.bad_context = bad_context
        self.strict = strict
        self.active_alias_runtime = active_alias_runtime

    def assemble(self, inputs):
        governance = UniversalSafetyGovernance()
        registry = (self.active_alias_runtime.context.agent_registry
                    if self.active_alias_runtime is not None else AgentRegistry())
        if self.active_alias_runtime is None:
            for entry in inputs.expected_agents:
                registry.register(RuntimeAgent(
                    entry.agent_id if not self.bad_roster else "other-agent",
                    entry.character_id,
                    goal_ids=list(next(
                        link.goal_ids for link in inputs.agent_links if link.agent_id == entry.agent_id
                    )),
                ))
        observation_store = ObservationStore()
        context = RuntimeContext(
            inputs.clock, inputs.world_state, inputs.event_history,
            scheduler=EventScheduler(), agent_scheduler=AgentScheduler(),
            agent_registry=registry, observation_store=observation_store,
            safety_governance=governance,
        )
        processor = EventProcessor(
            event_history=inputs.event_history, world_state=inputs.world_state,
            simulation_clock=inputs.clock, agent_registry=registry,
            observation_store=observation_store, persistence_trust=self.trust,
            persistence_codec=PersistedValueCodec(), write_fence=inputs.write_fence,
        )
        processor.register_handler("activation_test", ActivationTestHandler())
        loop = AgentActionLoop(
            agent_turn=AgentTurn(write_fence=inputs.write_fence),
            action_resolution_flow=ActionResolutionFlow(
                world_state=inputs.world_state, event_history=inputs.event_history,
                safety_governance=governance,
            ),
            safety_governance=governance, write_fence=inputs.write_fence,
        )
        links = {item.agent_id: item for item in inputs.agent_links}

        def cognition_provider(agent):
            link = links[agent.agent_id]
            character = Character(
                "wrong-character" if self.bad_context else link.character_id,
                link.agent_id, link.personality_id or "",
                list(link.memory_ids), list(link.belief_ids), link.emotion_id or "",
                goal_ids=list(link.goal_ids),
            )
            return CognitionContext.from_character(
                character, inputs.cognition, inputs.memory_store,
                observation_store=observation_store,
            )

        return SimulationRuntime(
            context, write_fence=inputs.write_fence,
            behavior_feedback=inputs.behavior_feedback,
            behavior_feedback_status=inputs.behavior_feedback_status,
            event_processor=processor, agent_action_loop=loop,
            cognition_context_provider=cognition_provider,
            agent_decision=AgentDecision(),
            evidence_review_provider=DeterministicLocalEvidenceReviewProvider(),
            conflict_opportunity_scheduler=ConflictOpportunityScheduler(),
            cognitive_review_provider=None, self_model_review_provider=None,
            allow_environment_provider_discovery=False,
            strict_dependency_binding=self.strict,
        )


def _stage(*, active_runtime, trust, checkpoint, cognition_bytes, roster, manifest, fork,
           dependencies=None, assembler=None):
    return IsolatedRuntimeReconstructionFactory.stage(
        active_runtime=active_runtime,
        checkpoint_manifest=manifest, world_checkpoint=checkpoint,
        cognitive_snapshot=cognition_bytes, expected_agents=roster,
        fork_manifest=fork, trust=trust,
        assembler=assembler or LocalRuntimeAssembler(trust),
        dependencies=dependencies or _dependency_manifest(),
    )


def test_verified_bundle_is_reassembled_as_frozen_staged_runtime():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint, cognition_bytes=cognition,
                    roster=roster, manifest=manifest, fork=fork)

    runtime = staged.runtime
    assert staged.status == "staged_not_active"
    assert not runtime.running and runtime.write_fence.frozen
    assert runtime.context.clock.current_time == 4
    assert runtime.context.event_history.timeline_id == "timeline-child"
    assert runtime.context.world_state is not source.context.world_state
    assert runtime.context.event_history is not source.context.event_history
    assert runtime.write_fence is not source.write_fence
    assert runtime.context.agent_registry is not source.context.agent_registry
    assert runtime.event_processor.world_state is runtime.context.world_state
    assert runtime.event_processor.event_history is runtime.context.event_history
    assert runtime.event_processor.write_fence is runtime.write_fence
    assert runtime.agent_action_loop.write_fence is runtime.write_fence
    assert runtime.allow_environment_provider_discovery is False
    with pytest.raises(PermissionError):
        runtime.step()
    with pytest.raises(PermissionError, match="cannot be activated"):
        runtime.unfreeze_writes()
    child_events_before = runtime.context.event_history.get_events()
    with source.write_fence.operation():
        late_event = make_system_event(event_id="late-parent-result")
        with pytest.raises(PermissionError):
            runtime.event_processor.dispatch(late_event)
    assert runtime.context.event_history.get_events() == child_events_before


def test_missing_host_dependency_fails_before_runtime_assembly():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    with pytest.raises(ValueError, match="resolve every required role"):
        _dependency_manifest(omit="event_scheduler_state")
    # A valid declaration but no assembler remains a required explicit boundary.
    with pytest.raises(TypeError, match="RuntimeAssembler"):
        IsolatedRuntimeReconstructionFactory.stage(
            active_runtime=source,
            checkpoint_manifest=manifest, world_checkpoint=checkpoint,
            cognitive_snapshot=cognition, expected_agents=roster,
            fork_manifest=fork, trust=trust, assembler=None,
            dependencies=_dependency_manifest(),
        )


def test_timeline_or_checkpoint_mismatch_is_rejected_without_active_mutation():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    altered = replace(fork, parent_timeline_id="different-parent")
    before = source.snapshot()
    with pytest.raises(RuntimeReconstructionError) as error:
        _stage(active_runtime=source, trust=trust, checkpoint=checkpoint, cognition_bytes=cognition,
               roster=roster, manifest=manifest, fork=altered)
    assert error.value.stage == "timeline_lineage"
    assert source.snapshot() == before
    assert source.context.event_history.timeline_id == "timeline-parent"


def test_wrong_reconstructed_agent_registry_is_rejected_without_publication():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    before_world = source.context.world_state
    with pytest.raises(RuntimeReconstructionError) as error:
        _stage(active_runtime=source, trust=trust, checkpoint=checkpoint, cognition_bytes=cognition,
               roster=roster, manifest=manifest, fork=fork,
               assembler=LocalRuntimeAssembler(trust, bad_roster=True))
    assert error.value.stage == "runtime_assembly"
    assert source.context.world_state is before_world
    assert source.context.agent_registry.get("agent-a") is not None


def test_independent_agent_manifest_mismatch_is_rejected():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    with pytest.raises(RuntimeReconstructionError) as error:
        _stage(active_runtime=source, trust=trust, checkpoint=checkpoint, cognition_bytes=cognition,
               roster=(CognitiveAgentManifestEntry("agent-other", "character-other"),),
               manifest=manifest, fork=fork)
    assert error.value.stage == "bundle_verification"


def test_signed_bundle_tick_mismatch_is_rejected():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    altered = replace(manifest, simulation_tick=5, signature=b"placeholder")
    payload = json.dumps(altered._body(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    altered = replace(altered, signature=trust.sign(
        "cognitive-world/snapshot-bundle-manifest/v1", payload,
    ))
    with pytest.raises(RuntimeReconstructionError) as error:
        _stage(active_runtime=source, trust=trust, checkpoint=checkpoint, cognition_bytes=cognition,
               roster=roster, manifest=altered, fork=fork)
    assert error.value.stage == "bundle_verification"


def test_wrong_cognition_context_mapping_and_non_strict_assembly_are_rejected():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    for assembler in (
        LocalRuntimeAssembler(trust, bad_context=True),
        LocalRuntimeAssembler(trust, strict=False),
    ):
        with pytest.raises(RuntimeReconstructionError) as error:
            _stage(active_runtime=source, trust=trust, checkpoint=checkpoint, cognition_bytes=cognition,
                   roster=roster, manifest=manifest, fork=fork, assembler=assembler)
        assert error.value.stage == "runtime_assembly"


def test_active_registry_alias_is_rejected_even_when_manifest_matches():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    with pytest.raises(RuntimeReconstructionError) as error:
        _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
               cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork,
               assembler=LocalRuntimeAssembler(trust, active_alias_runtime=source))
    assert error.value.stage == "runtime_assembly"
    assert "aliases" in error.value.reason



def test_restore_coordinator_freezes_retires_and_atomically_activates_staged_runtime():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(slot)
    old_generation = source.write_fence.restore_generation
    old_session = source.write_fence.session_id
    staged_session = staged.runtime.write_fence.session_id
    from contextvars import copy_context
    source_agent = source.context.agent_registry.get("agent-a")
    source_cognition_context = source.cognition_context_provider(source_agent)
    with source.write_fence.operation():
        late_event = make_system_event(event_id="late-before-runtime-activation")
        late_context = copy_context()
    old_world = source.context.world_state

    activated = coordinator.activate(staged)

    assert activated is staged.runtime
    assert slot.current is activated
    assert coordinator.state is RestoreState.ACTIVE_NEW
    assert slot.state is RestoreState.ACTIVE_NEW
    assert slot.snapshot().publication_generation == 1
    assert activated.running and not activated.write_fence.frozen
    assert activated.write_fence.session_id != old_session
    assert activated.write_fence.session_id != staged_session
    assert activated.write_fence.restore_generation == staged.restore_generation + 1
    assert source.write_fence.retired and source.write_fence.frozen
    assert source.write_fence.restore_generation > old_generation
    with pytest.raises(PermissionError):
        source.unfreeze_writes()
    with pytest.raises(PermissionError):
        source.write_fence.capture()
    with pytest.raises(RuntimeError, match="not frozen"):
        activated.write_fence.unfreeze()
    with pytest.raises(PermissionError):
        activated.event_processor.dispatch(late_event)
    with pytest.raises(PermissionError):
        late_context.run(source_cognition_context.cognition_container.add_belief,
                         Belief("late-belief", "agent-a", "stale result"))
    assert source_cognition_context.get_beliefs() == ()
    assert old_world is not activated.context.world_state
    with activated.write_fence.operation() as new_permit:
        assert new_permit.session_id == activated.write_fence.session_id
        assert new_permit.restore_generation == staged.restore_generation + 1


def test_restored_runtime_keeps_same_goal_id_owner_scoped_in_agent_turn():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs(
        shared_goal=True,
    )
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    activated = RestoreCoordinator(ActiveRuntimeSlot(source)).activate(staged)
    goals = activated.cognition_context_provider(
        activated.context.agent_registry.get("agent-b")
    ).cognition_container.goal_store
    a_before = goals.get_owned("agent-a", "shared-goal")
    with activated.write_fence.operation():
        proposal = GoalUpdateProposal(
            "agent-b", "shared-goal",
            GoalChange("progress", "active", "completed", 0.6, 0.8,
                       "observed", ["obs-b"]), ["obs-b"],
        )
        validation = CognitiveUpdateValidator().validate(
            proposal, {"agent_id": "agent-b", "authorized_source_refs": ("obs-b",)},
        )
        result = CognitiveUpdateApplier(
            activated.cognition_context_provider(
                activated.context.agent_registry.get("agent-b")
            ).cognition_container.belief_store, goals,
        ).apply(proposal, validation)
    assert result == goals.get_owned("agent-b", "shared-goal")
    assert result.description == "B private aim"
    assert goals.get_owned("agent-a", "shared-goal") == a_before
    for owner, expected in (("agent-a", "A private aim"), ("agent-b", "B private aim")):
        agent = activated.context.agent_registry.get(owner)
        context = activated.cognition_context_provider(agent)
        decision, _ = activated.agent_action_loop.agent_turn.prepare_decision_context(
            agent, context,
        )
        assert decision.goals[0].owner_id == owner
        assert decision.goals[0].description == expected


def test_recovery_required_runtime_stays_closed_until_verified_runtime_activation():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)

    class FailingTrust(FakeTrust):
        def sign(self, purpose, payload):
            raise OSError("event attestation unavailable")

    class ChangingHandler(EventHandler):
        def handle(self, event):
            return WorldUpdate("facts", "update", {"faulted-world": True})

    processor = EventProcessor(
        event_history=source.context.event_history,
        world_state=source.context.world_state,
        simulation_clock=source.context.clock,
        persistence_trust=FailingTrust(),
        write_fence=source.write_fence,
    )
    processor.register_handler("activation_test", ChangingHandler())
    old_event = make_system_event(event_id="fault-before-recovery", event_type="activation_test")
    with source.write_fence.operation():
        with pytest.raises(OSError, match="event attestation unavailable"):
            processor.dispatch_with_evidence(old_event)
    assert source.context.world_state.facts["faulted-world"] is True
    assert source.context.event_history.requires_recovery()
    assert source.write_fence.recovery_required
    with pytest.raises(PermissionError):
        processor.dispatch_with_evidence(make_system_event(
            event_id="other-event-before-recovery", event_type="activation_test"))

    activated = RestoreCoordinator(slot).activate(staged)
    assert activated is staged.runtime
    assert not activated.context.event_history.requires_recovery()
    assert "faulted-world" not in activated.context.world_state.facts
    assert source.write_fence.retired and source.write_fence.recovery_required
    with pytest.raises(PermissionError):
        processor.dispatch_with_evidence(make_system_event(
            event_id="late-old-event", event_type="activation_test"))
    new_event = make_system_event(event_id="new-runtime-event", event_type="activation_test")
    with activated.write_fence.operation():
        activated.event_processor.dispatch_with_evidence(new_event)
    assert activated.context.event_history.get_events() == (new_event,)
    assert source.context.event_history.get_events() == ()


def test_old_cognition_validation_cannot_be_rebound_to_activated_runtime():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    with source.write_fence.operation():
        old = BeliefUpdateProposal(
            "agent-a", "belief-a",
            BeliefChange("replace", "old", "new", "observed", ["obs-a"]),
            ["obs-a"], 0.7,
        )
        old_validation = CognitiveUpdateValidator().validate(
            old, {"agent_id": "agent-a", "authorized_source_refs": ("obs-a",)},
        )
        old_goal = GoalUpdateProposal(
            "agent-a", "goal-a",
            GoalChange("update", "active", "completed", 0.4, 0.6,
                       "observed", ["obs-a"]),
            ["obs-a"],
        )
        old_goal_validation = CognitiveUpdateValidator().validate(
            old_goal, {"agent_id": "agent-a", "authorized_source_refs": ("obs-a",)},
        )
    activated = RestoreCoordinator(slot).activate(staged)
    agent = activated.context.agent_registry.get("agent-a")
    context = activated.cognition_context_provider(agent)
    with activated.write_fence.operation() as fresh:
        context.cognition_container.add_belief(
            Belief("belief-a", "agent-a", "old", ["obs-a"], 0.5)
        )
        context.cognition_container.add_goal(
            Goal("goal-a", "agent-a", "go", 0.4, "active")
        )
        applier = CognitiveUpdateApplier(
            context.cognition_container.belief_store,
            context.cognition_container.goal_store,
            write_fence=activated.write_fence,
        )
        with pytest.raises(PermissionError, match="rebind"):
            replace(old, runtime_write_permit=fresh)
        with pytest.raises(PermissionError, match="rebind"):
            replace(old_goal, runtime_write_permit=fresh)
        old.runtime_write_permit = fresh
        old_goal.runtime_write_permit = fresh
        with pytest.raises(PermissionError):
            applier.apply(old, old_validation)
        with pytest.raises(PermissionError):
            applier.apply(old_goal, old_goal_validation)
    assert context.cognition_container.get_belief("belief-a").content == "old"
    assert context.cognition_container.get_goal("goal-a").status == "active"
    assert source.write_fence.retired
    assert activated.write_fence.restore_generation > 0


def test_restore_failure_before_publication_resumes_old_runtime_with_new_generation():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(
        slot, pre_publish_hook=lambda _: (_ for _ in ()).throw(RuntimeError("injected prepublish failure")),
    )
    old_permit = None
    from contextvars import copy_context
    with source.write_fence.operation() as old_permit:
        late_context = copy_context()
    generation = source.write_fence.restore_generation

    with pytest.raises(RuntimeRestoreError) as error:
        coordinator.activate(staged)

    assert error.value.stage is RestoreState.FROZEN
    assert slot.current is source
    assert coordinator.state is RestoreState.ACTIVE
    assert not source.write_fence.frozen and not source.write_fence.retired
    assert source.write_fence.restore_generation == generation + 1
    assert not source.running
    source.step()
    assert source.context.clock.current_time == 5
    with pytest.raises(PermissionError):
        late_context.run(lambda: _commit_without_mutation(source.write_fence))
    with pytest.raises(PermissionError):
        staged.runtime.write_fence.capture()


def test_arch004_pre_publish_hook_cannot_change_staged_clock():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(
        slot, pre_publish_hook=lambda candidate: candidate.runtime.context.clock.tick(),
    )

    with pytest.raises(RuntimeRestoreError):
        coordinator.activate(staged)

    assert slot.current is source
    assert slot.snapshot().publication_generation == 0
    assert staged.runtime.context.clock.current_time == 5
    assert staged.runtime.write_fence.frozen


def test_arch004_post_freeze_validation_failure_keeps_old_writer_closed():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    original_stop = source.stop

    def stop_and_change_staged_clock():
        original_stop()
        staged.runtime.context.clock.tick()

    source.stop = stop_and_change_staged_clock
    coordinator = RestoreCoordinator(slot)
    with pytest.raises(RuntimeRestoreError) as failure:
        coordinator.activate(staged)
    assert failure.value.stage is RestoreState.FROZEN
    assert slot.current is source and slot.state is RestoreState.RECOVERY_REQUIRED
    assert source.write_fence.frozen and staged.runtime.write_fence.frozen
    with pytest.raises(PermissionError):
        source.write_fence.capture()


@pytest.mark.parametrize("change", (
    "clock", "timeline", "world", "history", "cognition", "owner",
    "dependency", "registry",
))
def test_arch004_final_publication_rejects_changed_staged_state(change):
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    old_generation = source.write_fence.restore_generation

    def change_after_initial_validation(candidate):
        runtime = candidate.runtime
        if change == "clock":
            runtime.context.clock.tick()
        elif change == "timeline":
            runtime.context.event_history.timeline_id = "different-timeline"
        elif change == "world":
            runtime.context.world_state.load_fact("late-world-fact", True)
        elif change == "history":
            runtime.context.event_history.fork_manifest_bytes = b"invalid-lineage"
        elif change == "cognition":
            # A host callback holding a mutable Store reference can bypass
            # public final-write APIs; publication must still detect it.
            candidate._inputs.cognition.personality_store._personalities[
                "agent-a"
            ].traits["steady"] = False
        elif change == "owner":
            candidate._inputs.cognition.personality_store._personalities[
                "agent-a"
            ].owner_id = "different-agent"
        elif change == "dependency":
            runtime.agent_action_loop.safety_governance = UniversalSafetyGovernance()
        elif change == "registry":
            runtime.context.agent_registry.register(RuntimeAgent("extra", "extra-character"))

    coordinator = RestoreCoordinator(slot, pre_publish_hook=change_after_initial_validation)
    with pytest.raises(RuntimeRestoreError) as failure:
        coordinator.activate(staged)

    assert failure.value.stage is RestoreState.PUBLISHING
    assert coordinator.state is RestoreState.RECOVERY_REQUIRED
    assert slot.current is source and slot.snapshot().publication_generation == 0
    assert source.context.clock.current_time == 4
    assert source.context.event_history.get_events() == ()
    assert "late-world-fact" not in source.context.world_state.facts
    assert source.write_fence.frozen and not source.write_fence.retired
    assert source.write_fence.restore_generation == old_generation + 1
    assert staged.runtime.write_fence.frozen and staged.runtime.write_fence.staged_only
    with pytest.raises(PermissionError):
        source.write_fence.capture()
    with pytest.raises(PermissionError):
        staged.runtime.write_fence.capture()


def test_arch004_start_hook_mutation_is_rechecked_before_publication():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    original_start = staged.runtime.start

    def start_with_mutation():
        original_start()
        staged.runtime.context.clock.tick()

    staged.runtime.start = start_with_mutation
    coordinator = RestoreCoordinator(slot)
    with pytest.raises(RuntimeRestoreError) as failure:
        coordinator.activate(staged)
    assert failure.value.stage is RestoreState.PUBLISHING
    assert slot.current is source and slot.state is RestoreState.RECOVERY_REQUIRED
    assert source.write_fence.frozen and staged.runtime.write_fence.frozen
    assert not staged.runtime.running


def test_arch004_mutation_during_retirement_is_rechecked_at_pointer_swap():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    original_retire = source.write_fence._retire_after_recovery

    def retire_then_change_clock(authority):
        original_retire(authority)
        staged.runtime.context.clock.tick()

    source.write_fence._retire_after_recovery = retire_then_change_clock
    coordinator = RestoreCoordinator(slot)
    with pytest.raises(RuntimeRestoreError) as failure:
        coordinator.activate(staged)
    assert failure.value.stage is RestoreState.PUBLISHING
    assert slot.current is source and slot.state is RestoreState.RECOVERY_REQUIRED
    assert source.write_fence.retired and source.write_fence.frozen
    assert staged.runtime.write_fence.frozen and staged.runtime.write_fence.staged_only
    assert not staged.runtime.running


def test_arch004_pre_publish_hook_cannot_commit_through_frozen_writers():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    old_processor = EventProcessor(
        event_history=source.context.event_history,
        world_state=source.context.world_state,
        simulation_clock=source.context.clock,
        write_fence=source.write_fence,
    )
    old_processor.register_handler("activation_test", ActivationTestHandler())

    def blocked_writes(candidate):
        with pytest.raises(PermissionError):
            source.write_fence.capture()
        with pytest.raises(PermissionError):
            candidate.runtime.write_fence.capture()
        with pytest.raises(PermissionError):
            old_processor.dispatch_with_evidence(make_system_event(
                event_id="old-event-during-restore", event_type="activation_test",
            ))
        with pytest.raises(PermissionError):
            candidate.runtime.event_processor.dispatch_with_evidence(make_system_event(
                event_id="staged-event-during-restore", event_type="activation_test",
            ))

    activated = RestoreCoordinator(slot, pre_publish_hook=blocked_writes).activate(staged)
    assert slot.current is activated
    assert source.context.event_history.get_events() == ()
    assert activated.context.event_history.get_events() == ()
    assert source.write_fence.retired


def _commit_without_mutation(fence):
    with fence.commit_scope():
        pass


def test_freeze_waits_for_inflight_commit_before_publication():
    from threading import Event, Thread

    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(slot)
    entered = Event()
    freeze_requested = Event()
    release = Event()
    finished = Event()
    outcomes = []

    def hold_commit():
        with source.write_fence.operation():
            with source.write_fence.commit_scope():
                entered.set()
                assert release.wait(5)

    def restore():
        try:
            outcomes.append(coordinator.activate(staged))
        except Exception as error:  # surfaced in the main thread below
            outcomes.append(error)
        finally:
            finished.set()

    original_freeze = source.write_fence._freeze_for_recovery
    def tracked_freeze(authority):
        freeze_requested.set()
        return original_freeze(authority)
    source.write_fence._freeze_for_recovery = tracked_freeze
    writer = Thread(target=hold_commit)
    writer.start()
    assert entered.wait(5)
    restorer = Thread(target=restore)
    restorer.start()
    assert freeze_requested.wait(5)
    assert not finished.is_set()
    release.set()
    writer.join(5)
    restorer.join(5)
    assert not writer.is_alive() and not restorer.is_alive()
    assert finished.is_set()
    assert len(outcomes) == 1 and outcomes[0] is staged.runtime
    assert slot.current is staged.runtime
    assert source.write_fence.retired


def test_concurrent_restore_requests_are_serialized_and_stage_is_one_shot():
    from threading import Barrier, Thread

    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(slot)
    barrier = Barrier(3)
    outcomes = []

    def activate():
        barrier.wait()
        try:
            outcomes.append(coordinator.activate(staged))
        except RuntimeRestoreError as error:
            outcomes.append(error)

    threads = [Thread(target=activate), Thread(target=activate)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(item is staged.runtime for item in outcomes) == 1
    assert sum(isinstance(item, RuntimeRestoreError) for item in outcomes) == 1
    assert slot.current is staged.runtime
    assert slot.snapshot().publication_generation == 1


def test_failure_at_publication_boundary_leaves_no_writable_runtime():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(slot)

    def fail_publish(*args, **kwargs):
        raise RuntimeError("injected publication failure")
    slot._publish = fail_publish

    with pytest.raises(RuntimeRestoreError) as error:
        coordinator.activate(staged)

    assert error.value.stage is RestoreState.PUBLISHING
    assert coordinator.state is RestoreState.RECOVERY_REQUIRED
    assert slot.state is RestoreState.RECOVERY_REQUIRED
    assert slot.current is source
    assert source.write_fence.retired and source.write_fence.frozen
    assert staged.runtime.write_fence.frozen and staged.runtime.write_fence.staged_only
    with pytest.raises(PermissionError):
        source.write_fence.capture()
    with pytest.raises(PermissionError):
        staged.runtime.write_fence.capture()


def test_staged_runtime_cannot_be_activated_without_the_coordinator_capability():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    with pytest.raises(PermissionError):
        staged.runtime.write_fence._activate_staged_and_publish(object(), lambda: None)
    assert staged.runtime.write_fence.frozen
    assert staged.runtime.write_fence.staged_only



def test_staged_start_failure_rolls_back_only_to_a_fresh_old_generation():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    slot = ActiveRuntimeSlot(source)
    coordinator = RestoreCoordinator(slot)
    generation = source.write_fence.restore_generation
    staged.runtime.start = lambda: (_ for _ in ()).throw(RuntimeError("injected start failure"))

    with pytest.raises(RuntimeRestoreError) as error:
        coordinator.activate(staged)

    assert error.value.stage is RestoreState.PUBLISHING
    assert slot.current is source
    assert coordinator.state is RestoreState.ACTIVE
    assert source.write_fence.restore_generation == generation + 1
    assert not source.write_fence.frozen and not source.write_fence.retired
    assert not staged.runtime.running
    assert staged.runtime.write_fence.frozen and staged.runtime.write_fence.staged_only
    source.step()
    assert source.context.clock.current_time == 5



def test_pre_freeze_validation_failure_leaves_active_runtime_untouched():
    trust, checkpoint, cognition, roster, manifest, fork, active = _signed_inputs()
    staged = _stage(active_runtime=active, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    staged = replace(staged, parent_timeline_id="unrelated-parent")
    slot = ActiveRuntimeSlot(active)
    coordinator = RestoreCoordinator(slot)
    generation = active.write_fence.restore_generation
    before = active.snapshot()

    with pytest.raises(RuntimeRestoreError, match="requires a Timeline ID"):
        coordinator.activate(staged)

    assert slot.current is active
    assert slot.state is RestoreState.ACTIVE
    assert coordinator.state is RestoreState.ACTIVE
    assert active.snapshot() == before
    assert active.write_fence.restore_generation == generation
    assert not active.write_fence.frozen and not active.write_fence.retired


def test_staged_validation_failure_before_freeze_does_not_publish():
    trust, checkpoint, cognition, roster, manifest, fork, active = _signed_inputs()
    staged = _stage(active_runtime=active, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    staged.runtime.context.clock.tick()
    slot = ActiveRuntimeSlot(active)
    coordinator = RestoreCoordinator(slot)
    generation = active.write_fence.restore_generation

    with pytest.raises(RuntimeRestoreError, match="checkpoint"):
        coordinator.activate(staged)

    assert slot.current is active
    assert slot.state is RestoreState.ACTIVE
    assert active.write_fence.restore_generation == generation
    assert not active.write_fence.frozen



def test_activated_child_appends_only_to_its_own_timeline_suffix():
    trust, checkpoint, cognition, roster, manifest, fork, source = _signed_inputs()
    staged = _stage(active_runtime=source, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    parent_history = source.context.event_history
    coordinator = RestoreCoordinator(ActiveRuntimeSlot(source))
    child = coordinator.activate(staged)
    event = make_system_event(event_id="child-only-event", event_type="activation_test")

    result = child.event_processor.process_with_evidence(event, child.context.world_state)

    assert result.source_event_id == event.id
    assert child.context.event_history.timeline_id == "timeline-child"
    assert [item.id for item in child.context.event_history.get_events()] == [event.id]
    assert len(child.context.event_history.export_local_persisted_records()) == 1
    assert parent_history.timeline_id == "timeline-parent"
    assert parent_history.get_events() == ()
    assert parent_history.export_local_persisted_records() == ()



def test_same_runtime_cannot_be_owned_by_two_active_slots():
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot

    trust, checkpoint, cognition, roster, manifest, fork, runtime = _signed_inputs()
    first = ActiveRuntimeSlot(runtime)
    with pytest.raises(RuntimeError, match="already owned"):
        ActiveRuntimeSlot(runtime)

    assert first.current is runtime


@pytest.mark.parametrize("tamper", ["world", "cognition", "signed_input"])
def test_activation_reverifies_staged_contents_before_freezing_active_runtime(tamper):
    trust, checkpoint, cognition, roster, manifest, fork, active = _signed_inputs()
    staged = _stage(active_runtime=active, trust=trust, checkpoint=checkpoint,
                    cognition_bytes=cognition, roster=roster, manifest=manifest, fork=fork)
    if tamper == "world":
        staged.runtime.context.world_state._facts["untrusted-record"] = "changed-after-stage"
    elif tamper == "cognition":
        staged._inputs.cognition.personality_store._personalities["agent-a"] = Personality(
            "agent-a", traits={"steady": False},
        )
    else:
        staged = replace(staged, _world_checkpoint=checkpoint + b"tampered")
    slot = ActiveRuntimeSlot(active)
    coordinator = RestoreCoordinator(slot)
    generation = active.write_fence.restore_generation
    before = active.snapshot()

    with pytest.raises(RuntimeRestoreError):
        coordinator.activate(staged)

    assert slot.current is active
    assert slot.state is RestoreState.ACTIVE
    assert active.snapshot() == before
    assert active.write_fence.restore_generation == generation
    assert not active.write_fence.frozen and not active.write_fence.retired
