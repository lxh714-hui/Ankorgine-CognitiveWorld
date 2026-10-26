"""Explicit state commitments use the owner's consumed evidence, not another Attempt."""
import pytest
from test_goal_completion import make_room, objective, results
from cognitive_world.cognition.goal_completion import GoalCompletionCondition, COMPLETION_KEY
from cognitive_world.cognition.goal_creation import GoalCreationProposal
from cognitive_world.cognition.validation import CognitiveUpdateValidator
from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
from cognitive_world.agent.runtime_agent import RuntimeAgent


def add_witness_goals(scene, owner=None, *, subject=None, predicate="door_open"):
    rt = scene.runtime
    owner = owner or scene.definition.speaker
    agent = rt.context.agent_registry.get(owner)
    goals = []
    with rt.write_fence.operation():
        for kind in ("state", "actor_action"):
            target = subject or scene.definition.door
            condition = GoalCompletionCondition("object:" + target,
                "environment_state", predicate, target, True,
                version=2, completion_kind=kind)
            proposal = GoalCreationProposal(owner, "witness-" + kind, "Explicit commitment", .5,
                ["room-initial-light"], {COMPLETION_KEY: condition.as_value()})
            validation = CognitiveUpdateValidator().validate(proposal,
                {"agent_id": owner, "authorized_source_refs": ("room-initial-light",)})
            assert validation.accepted
            CognitiveUpdateApplier(scene.cognition.belief_store, scene.cognition.goal_store,
                scene.cognition.self_model_store, write_fence=rt.write_fence).apply(proposal, validation)
            goals.append(proposal.goal_id)
        rt.context.agent_registry.register(RuntimeAgent(agent.agent_id, agent.character_id, [*agent.goal_ids, *goals], agent.metadata))
    return owner, goals


def consume(scene, owner):
    rt = scene.runtime
    actor = rt.context.agent_registry.get(owner)
    with rt.write_fence.operation():
        return rt.agent_action_loop.agent_turn.prepare_decision_context(actor,
            rt.cognition_context_provider(actor), simulation_tick=rt.context.clock.capture())


def test_other_actor_state_completion_requires_own_consumption_and_preserves_actor_goal():
    scene = make_room()
    owner, (state_id, action_id) = add_witness_goals(scene)
    scene.advance(speak=True)
    action, = scene.advance()
    assert action.event_committed and action.execution.resolution.success
    store = scene.cognition.goal_store
    assert store.get_owned(owner, state_id).status == "active"
    own_memories = tuple(m for m in scene.memory.get_memories_by_owner(owner))
    consume(scene, owner)
    goal = store.get_owned(owner, state_id)
    assert goal.status == "completed" and action.execution.event.id in goal.source_refs
    assert store.get_owned(owner, action_id).status == "active"
    assert tuple(scene.memory.get_memories_by_owner(owner)) == own_memories
    consume(scene, owner)
    assert store.get_owned(owner, state_id) == goal and len(results(scene)) == 1


def test_state_goal_does_not_complete_from_closed_state_or_governance_refusal(monkeypatch):
    from cognitive_world.cognition.validation import ValidationResult
    scene = make_room()
    owner, (state_id, _) = add_witness_goals(scene)
    consume(scene, owner)
    assert scene.cognition.goal_store.get_owned(owner, state_id).status == "active"
    scene.advance(speak=True)
    action, = scene.advance()
    assert action.event_committed
    monkeypatch.setattr(scene.goal_completion.validator, "validate",
        lambda *args: ValidationResult(False, "controlled refusal"))
    consume(scene, owner)
    assert scene.cognition.goal_store.get_owned(owner, state_id).status == "active"


def test_legacy_condition_encoding_is_unchanged_and_unknown_semantics_fail_closed():
    legacy = GoalCompletionCondition("object:door", "environment_state", "door_open", "door", True)
    assert set(legacy.as_value()) == {"version", "target_ref", "fact_type", "predicate", "subject_ref", "expected_value"}
    assert GoalCompletionCondition.from_value(legacy.as_value()) == legacy
    with pytest.raises(ValueError):
        GoalCompletionCondition.from_value({**legacy.as_value(), "version": 2, "completion_kind": "infer_from_text"})


def test_state_completion_survives_restore_without_crossing_sibling_or_resigning_ancestors(tmp_path,monkeypatch):
    from cognitive_world.examples.social_room import SocialRoomAssembler, dependency_manifest
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    scene = make_room()
    owner,(state_id,action_id) = add_witness_goals(scene)
    scene.advance(speak=True)
    manager = SaveManager(tmp_path/"branches",trust=scene.trust,codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    original = scene.cognition.goal_store.get_owned(owner,state_id)
    assembler = SocialRoomAssembler(trust=scene.trust)
    def forbidden(*args,**kwargs):
        pytest.fail("restoring inherited evidence must not re-sign it")
    with monkeypatch.context() as guard:
        guard.setattr("cognitive_world.event.processor.make_persisted_event_record",forbidden)
        child = RestoreCoordinator(ActiveRuntimeSlot(scene.runtime)).activate(manager.stage_restore(
            saved.save_id,timeline_id=saved.timeline_id,active_runtime=scene.runtime,
            assembler=assembler,dependencies=dependency_manifest(),new_timeline_id="state-child"))
    restored = assembler.scene
    with child.write_fence.operation(): restored.observe_door()
    action, = restored.advance()
    assert action.event_committed and action.execution.resolution.success
    consume(restored,owner)
    completed = restored.cognition.goal_store.get_owned(owner,state_id)
    assert completed.status == "completed"
    assert restored.cognition.goal_store.get_owned(owner,action_id).status == "active"
    assert scene.cognition.goal_store.get_owned(owner,state_id) == original
    cold = SocialRoomAssembler(trust=scene.trust)
    parent = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
        timeline_id=saved.timeline_id,assembler=cold,dependencies=dependency_manifest())).current
    sibling_assembler = SocialRoomAssembler(trust=scene.trust)
    sibling = RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(manager.stage_restore(saved.save_id,
        timeline_id=saved.timeline_id,active_runtime=parent,assembler=sibling_assembler,
        dependencies=dependency_manifest(),new_timeline_id="state-sibling"))
    assert sibling.context.event_history.get_event(action.execution.event.id) is None
    assert sibling_assembler.scene.cognition.goal_store.get_owned(owner,state_id) == original
    checkpoint = restored.save(manager)
    resumed = SocialRoomAssembler(trust=scene.trust)
    with monkeypatch.context() as guard:
        guard.setattr("cognitive_world.event.processor.make_persisted_event_record",forbidden)
        ColdRuntimePublisher().activate(manager.stage_cold_resume(checkpoint.save_id,
            timeline_id=checkpoint.timeline_id,assembler=resumed,dependencies=dependency_manifest()))
    assert resumed.scene.cognition.goal_store.get_owned(owner,state_id) == completed
    assert resumed.scene.cognition.goal_store.get_owned(owner,action_id).status == "active"


def test_unobserved_state_never_completes_even_after_other_actor_success():
    from cognitive_world.examples.social_room import RecipientDefinition
    scene = make_room(additional_receivers=(RecipientDefinition("blind-witness",False,can_see=False),))
    owner,(state_id,_) = add_witness_goals(scene,"blind-witness")
    scene.advance(speak=True)
    action, = scene.advance()
    assert action.event_committed and action.execution.resolution.success
    assert not any(o.source_event_id==action.execution.event.id
        for o in scene.runtime.context.observation_store.get_by_observer(owner))
    consume(scene,owner)
    assert scene.cognition.goal_store.get_owned(owner,state_id).status=="active"


def test_state_goal_rejects_a_result_not_yet_in_formal_history():
    scene = make_room();owner,(state_id,_) = add_witness_goals(scene)
    scene.advance(speak=True)
    rt=scene.runtime
    actor=rt.context.agent_registry.get(scene.definition.receiver)
    witness=rt.context.agent_registry.get(owner)
    with rt.write_fence.operation():
        execution=rt.agent_action_loop.run_turn_with_result(actor,rt.cognition_context_provider(actor),
            rt.agent_decision,simulation_tick=rt.context.clock.capture())
        assert execution.resolution.success
        result=scene.goal_completion.review(rt.cognition_context_provider(witness),
            rt.agent_action_loop.agent_turn.cognitive_runtime,goal_id=state_id,event_id=execution.event.id)
    assert result.status=="uncommitted"
    assert scene.cognition.goal_store.get_owned(owner,state_id).status=="active"


def test_old_true_observation_cannot_complete_state_goal_after_a_newer_formal_change():
    from cognitive_world.event import SystemEventFactory
    scene = make_room()
    owner,(state_id,_) = add_witness_goals(scene,subject=scene.definition.room,predicate="room_light_on")
    rt=scene.runtime
    with rt.write_fence.operation():
        scene.processor.dispatch_with_evidence(SystemEventFactory().create(event_id="light-now-off",
            event_type="room_light_changed",timestamp="0",simulation_tick=rt.context.clock.current_time,
            changes=[{"room_id":scene.definition.room,"from_light_on":True,"to_light_on":False}]))
    # The source Event and old observation are perfectly valid historical inputs.
    # Actual L1 may consume them, but their condition is no longer current.
    consume(scene,owner)
    assert scene.cognition.goal_store.get_owned(owner,state_id).status=="active"
    actor=rt.context.agent_registry.get(owner)
    with rt.write_fence.operation():
        result=scene.goal_completion.review(rt.cognition_context_provider(actor),
            rt.agent_action_loop.agent_turn.cognitive_runtime,goal_id=state_id,event_id="room-initial-light")
    assert result.status=="superseded_state_evidence"
    assert rt.context.world_state.environment[scene.definition.room]["light_on"] is False
