"""Goal completion through a committed own result and actual owner L1."""
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.examples.social_room import SocialRoom, RoomDefinition, RoomCandidates, SocialRoomAssembler, dependency_manifest
from dataclasses import replace
import pytest
from cognitive_world.cognition.goal_completion import GoalCompletionCondition, COMPLETION_KEY
from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher


def make_room(**changes):
    return SocialRoom(trust=HmacPersistenceTrust(b"goal-completion-test-trust-material"),
                      definition=replace(RoomDefinition(), **changes))


def objective(scene):
    return next(g for g in scene.cognition.goal_store.get(scene.definition.receiver)
                if g.goal_id.startswith("evidence-goal:"))


def test_consumed_success_completes_goal_and_next_decision_does_not_repeat_action():
    scene = make_room()
    scene.advance(speak=True)
    goal = objective(scene)
    initial_goals = {g.goal_id: g for g in scene.cognition.goal_store.get_all()
                     if g.goal_id != goal.goal_id}
    action, = scene.advance()
    assert action.failure_type is None and action.event_committed
    assert action.execution.resolution.success
    assert scene.runtime.context.world_state.environment[scene.definition.door].is_open
    assert objective(scene).status == "active"  # delivery is not L1 consumption
    next_turn, = scene.advance()
    assert next_turn.failure_type is None
    completed = scene.cognition.goal_store.get_owned(goal.owner_id, goal.goal_id)
    assert completed.status == "completed"
    assert completed.priority == goal.priority and completed.description == goal.description
    assert next_turn.execution.proposal.action_type == "Wait"
    assert next_turn.execution.event is None
    assert {g.goal_id: g for g in scene.cognition.goal_store.get_all()
            if g.goal_id != goal.goal_id} == initial_goals


def review(scene, event_id):
    rt = scene.runtime
    actor = rt.context.agent_registry.get(scene.definition.receiver)
    context = rt.cognition_context_provider(actor)
    with rt.write_fence.operation():
        return scene.goal_completion.review(context, rt.agent_action_loop.agent_turn.cognitive_runtime,
            goal_id=objective(scene).goal_id, event_id=event_id)



def consume_result(scene):
    rt = scene.runtime
    actor = rt.context.agent_registry.get(scene.definition.receiver)
    with rt.write_fence.operation():
        return rt.agent_action_loop.agent_turn.prepare_decision_context(
            actor, rt.cognition_context_provider(actor), simulation_tick=rt.context.clock.capture())


def results(scene):
    return tuple(e for e in scene.runtime.context.event_history.get_events()
                 if e.has_trusted_source("resolution"))


def test_successful_action_does_not_complete_an_unsatisfied_condition():
    d = RoomDefinition()
    scene = make_room(goal_completion=GoalCompletionCondition(
        "object:" + d.door, "environment_state", "door_open", d.door, False))
    scene.advance(speak=True)
    action, = scene.advance()
    assert action.event_committed and action.execution.resolution.success
    consume_result(scene)
    assert objective(scene).status == "active"
    assert review(scene, action.execution.event.id).status == "success_condition_unmet"
    assert len(results(scene)) == 1


def test_formal_result_is_required_and_delivery_alone_does_not_complete():
    scene = make_room()
    scene.advance(speak=True)
    rt = scene.runtime
    actor = rt.context.agent_registry.get(scene.definition.receiver)
    with rt.write_fence.operation():
        execution = rt.agent_action_loop.run_turn_with_result(actor,
            rt.cognition_context_provider(actor), rt.agent_decision,
            simulation_tick=rt.context.clock.capture())
        assert execution.resolution.success and execution.event is not None
        assert review(scene, execution.event.id).status == "uncommitted"
        assert objective(scene).status == "active"
        scene.processor.dispatch_with_evidence(execution.event)
    assert review(scene, execution.event.id).status == "awaiting_consumption"
    assert objective(scene).status == "active"
    scene.advance()
    assert objective(scene).status == "completed"
    assert len(results(scene)) == 1


def test_duplicate_review_does_not_reapply_goal_update_or_repeat_action(monkeypatch):
    scene = make_room()
    scene.advance(speak=True)
    action, = scene.advance()
    scene.advance()
    goal = objective(scene)
    before = (scene.memory.get_all_memories(), tuple(scene.runtime.context.event_history.get_events()))
    def forbidden(*args, **kwargs):
        pytest.fail("duplicate result must not update GoalStore")
    monkeypatch.setattr(scene.cognition.goal_store, "update", forbidden)
    for _ in range(2):
        assert review(scene, action.execution.event.id).status == "already_completed"
        turn, = scene.advance()
        assert turn.failure_type is None and turn.execution.proposal.action_type == "Wait"
    assert objective(scene) == goal
    current = {m.id: m for m in scene.memory.get_all_memories()}
    assert all(current[m.id] == m for m in before[0])
    assert tuple(scene.runtime.context.event_history.get_events()) == before[1]
    assert len(results(scene)) == 1


def test_governance_rejection_preserves_goal(monkeypatch):
    from cognitive_world.cognition.validation import ValidationResult
    scene = make_room()
    scene.advance(speak=True)
    action, = scene.advance()
    before = objective(scene)
    monkeypatch.setattr(scene.goal_completion.validator, "validate",
                        lambda *args: ValidationResult(False, "injected governance refusal"))
    consume_result(scene)
    assert objective(scene) == before
    assert review(scene, action.execution.event.id).status == "governance_rejected"
    assert len(results(scene)) == 1


def test_committed_failure_does_not_complete_goal():
    # Bare object addresses remain a supported production input. This fixture
    # uses that path without faking Resolution, processing or historical evidence.
    d = RoomDefinition()
    scene = make_room(key_available=False, goal_completion=GoalCompletionCondition(
        d.door, "environment_state", "door_open", d.door, True))
    class BareAddresses(RoomCandidates):
        def generate(self, situation):
            return tuple(replace(c, target=d.door) if c.target else c
                         for c in super().generate(situation))
    scene.runtime.agent_decision.candidate_policy = BareAddresses(scene.definition)
    scene.advance(speak=True)
    action, = scene.advance()
    assert action.failure_type is None and action.event_committed
    assert not action.execution.resolution.success
    before = objective(scene)
    assert review(scene, action.execution.event.id).status == "action_failed"
    assert objective(scene) == before and before.status == "active"
    assert not scene.runtime.context.world_state.environment[d.door].is_open
    assert len(results(scene)) == 1


def test_completed_goal_survives_restore_and_isolated_sibling_forks(tmp_path, monkeypatch):
    scene = make_room()
    scene.advance(speak=True)
    action, = scene.advance()
    scene.advance()
    goal = objective(scene)
    manager = SaveManager(tmp_path / "saves", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    def forbidden(*args, **kwargs):
        pytest.fail("restore must not re-sign ancestor evidence")
    def fork(active, name):
        # Host content changes cannot rewrite a saved Goal completion condition.
        altered = replace(scene.definition, goal_completion=GoalCompletionCondition(
            "object:" + scene.definition.door, "environment_state", "door_open", scene.definition.door, False))
        assembler = SocialRoomAssembler(trust=scene.trust, definition=altered)
        with monkeypatch.context() as guard:
            guard.setattr("cognitive_world.event.processor.make_persisted_event_record", forbidden)
            guard.setattr("cognitive_world.cognition.l1_consumption_proof.L1ConsumptionIssuer.issue_after_l1", forbidden)
            staged = manager.stage_restore(saved.save_id, timeline_id=saved.timeline_id,
                active_runtime=active, assembler=assembler, dependencies=dependency_manifest(),
                new_timeline_id=name)
            runtime = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
        return runtime, assembler.scene
    child, restored = fork(scene.runtime, "completed-child")
    assert objective(restored) == goal
    with child.write_fence.operation():
        restored.observe_door()
    turns = restored.advance()
    assert all(t.failure_type is None and t.execution.proposal.action_type == "Wait" for t in turns)
    assert objective(restored) == goal
    assert [e.id for e in results(restored)] == [action.execution.event.id]
    assembler = SocialRoomAssembler(trust=scene.trust)
    parent = ColdRuntimePublisher().activate(manager.stage_cold_resume(
        saved.save_id, timeline_id=saved.timeline_id, assembler=assembler,
        dependencies=dependency_manifest())).current
    sibling, other = fork(parent, "completed-sibling")
    assert objective(other) == goal
    with sibling.write_fence.operation():
        other.observe_door()
    assert all(t.failure_type is None and t.execution.proposal.action_type == "Wait" for t in other.advance())
    assert objective(other) == goal
    child_only = set(e.id for e in child.context.event_history.get_events()) - set(e.id for e in parent.context.event_history.get_events())
    assert child_only and all(sibling.context.event_history.get_event(e) is None for e in child_only)


def test_uncertain_goal_write_freezes_checkpoint_without_replaying_world_action(tmp_path, monkeypatch):
    scene = make_room()
    scene.advance(speak=True)
    action, = scene.advance()
    commit = scene.cognition.goal_store.update
    def committed_then_error(*args, **kwargs):
        commit(*args, **kwargs)
        raise OSError("injected uncertain cognitive commit")
    monkeypatch.setattr(scene.cognition.goal_store, "update", committed_then_error)
    with pytest.raises(OSError):
        consume_result(scene)
    assert scene.runtime.write_fence.recovery_required
    assert objective(scene).status == "completed"
    assert [e.id for e in results(scene)] == [action.execution.event.id]
    manager = SaveManager(tmp_path / "uncertain", trust=scene.trust, codec=cognitive_snapshot_codec())
    with pytest.raises(PermissionError):
        scene.save(manager)


def test_completion_definition_is_immutable_after_creation():
    from cognitive_world.cognition.goal_update import GoalUpdater
    from cognitive_world.cognition.validation import CognitiveUpdateValidator
    from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
    scene = make_room()
    scene.advance(speak=True)
    goal = objective(scene)
    with scene.runtime.write_fence.operation():
        proposal = GoalUpdater().propose_update(goal, {
            "metadata": {COMPLETION_KEY: {**goal.metadata[COMPLETION_KEY], "expected_value": False}},
            "source_refs": goal.source_refs})
        validation = CognitiveUpdateValidator().validate(proposal, {
            "agent_id": goal.owner_id, "authorized_source_refs": goal.source_refs})
        assert validation.accepted  # mutation boundary must still reject definition replacement
        with pytest.raises(ValueError, match="cannot change the Goal completion condition"):
            CognitiveUpdateApplier(scene.cognition.belief_store, scene.cognition.goal_store,
                write_fence=scene.runtime.write_fence).apply(proposal, validation)
    assert objective(scene) == goal


@pytest.mark.parametrize("payload", [
    {}, {"version": 2},
    {**GoalCompletionCondition("object:door", "environment_state", "door_open", "door", True).as_value(), "script": "forbidden"},
    {**GoalCompletionCondition("object:door", "environment_state", "door_open", "door", True).as_value(), "expected_value": float("nan")},
])
def test_unknown_or_malformed_conditions_are_rejected_by_creation_governance(payload):
    from cognitive_world.cognition.goal_creation import GoalCreationProposal
    from cognitive_world.cognition.validation import CognitiveUpdateValidator
    proposal = GoalCreationProposal("owner", "goal", "Try an explicit action", .5,
        ["evidence"], {COMPLETION_KEY: payload})
    validation = CognitiveUpdateValidator().validate(proposal, {
        "agent_id": "owner", "authorized_source_refs": ("evidence",)})
    assert not validation.accepted


def test_qualified_address_failure_is_uncommitted_and_never_completes_goal():
    scene = make_room(key_available=False)
    scene.advance(speak=True)
    before = objective(scene)
    action, = scene.advance()
    # Existing B1 failure validation compares a qualified target to a raw slot ID.
    # Record this limitation instead of treating Resolution's failure as a commit.
    assert action.failure_type == "PermissionError" and not action.event_committed
    assert action.execution.resolution.success is False
    assert review(scene, action.execution.event.id).status == "uncommitted"
    assert objective(scene) == before
    assert not results(scene)


def test_existing_goal_without_condition_is_not_inferred_from_its_text(monkeypatch):
    scene = make_room()
    propose = scene.social.policy.propose_goals
    monkeypatch.setattr(scene.social.policy, "propose_goals",
        lambda experiences: tuple(replace(d, completion_condition=None) for d in propose(experiences)))
    scene.advance(speak=True)
    before = objective(scene)
    assert COMPLETION_KEY not in before.metadata
    action, = scene.advance()
    assert action.event_committed and action.execution.resolution.success
    consume_result(scene)
    assert review(scene, action.execution.event.id).status == "not_configured"
    assert objective(scene) == before


def test_child_completion_does_not_complete_active_parent_or_sibling(tmp_path):
    scene = make_room()
    scene.advance(speak=True)
    original = objective(scene)
    manager = SaveManager(tmp_path / "branches", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    assembler = SocialRoomAssembler(trust=scene.trust)
    child = RestoreCoordinator(ActiveRuntimeSlot(scene.runtime)).activate(manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=scene.runtime,
        assembler=assembler, dependencies=dependency_manifest(), new_timeline_id="goal-child"))
    restored = assembler.scene
    with child.write_fence.operation():
        restored.observe_door()
    action, = restored.advance()
    assert action.event_committed and action.execution.resolution.success
    turn, = restored.advance()
    assert turn.failure_type is None
    assert objective(restored).status == "completed"
    assert objective(scene) == original and original.status == "active"
    parent_assembler = SocialRoomAssembler(trust=scene.trust)
    parent = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
        timeline_id=saved.timeline_id, assembler=parent_assembler, dependencies=dependency_manifest())).current
    sibling_assembler = SocialRoomAssembler(trust=scene.trust)
    sibling = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=parent,
        assembler=sibling_assembler, dependencies=dependency_manifest(), new_timeline_id="goal-sibling"))
    assert objective(sibling_assembler.scene) == original
    assert sibling.context.event_history.get_event(action.execution.event.id) is None
    assert not sibling.context.world_state.environment[scene.definition.door].is_open


def test_same_owner_other_goal_with_identical_fact_condition_is_not_completed(monkeypatch):
    scene = make_room()
    propose = scene.social.policy.propose_goals
    def two_goals(experiences):
        drafts = propose(experiences)
        return (*drafts, *(replace(d, description="A different objective with the same fact condition") for d in drafts))
    monkeypatch.setattr(scene.social.policy, "propose_goals", two_goals)
    scene.advance(speak=True)
    goals = [g for g in scene.cognition.goal_store.get(scene.definition.receiver)
             if g.goal_id.startswith("evidence-goal:")]
    assert len(goals) == 2
    selected = next(g for g in goals if g.description == scene.definition.goal_description)
    other = next(g for g in goals if g.goal_id != selected.goal_id)
    action, = scene.advance()
    assert action.event_committed and action.execution.resolution.success
    consume_result(scene)
    assert scene.cognition.goal_store.get_owned(selected.owner_id, selected.goal_id).status == "completed"
    assert scene.cognition.goal_store.get_owned(other.owner_id, other.goal_id) == other
    rt = scene.runtime
    actor = rt.context.agent_registry.get(other.owner_id)
    with rt.write_fence.operation():
        result = scene.goal_completion.review(rt.cognition_context_provider(actor),
            rt.agent_action_loop.agent_turn.cognitive_runtime,
            goal_id=other.goal_id, event_id=action.execution.event.id)
    assert result.status == "unbound_goal"
