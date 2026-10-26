"""Observation disclosure and authoritative reach are independent data policies."""
import json
import pytest
from test_position_observation import Scene, document as position_document
from cognitive_world.decision import ActionPipeline, ActionProposal
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine


def document(*, reach=1, detail=10, authorize=True):
    data = position_document()
    data["schema_version"] = 4
    for location in data["locations"]:
        for mechanism in location["mechanisms"]:
            mechanism.update(interaction_policy=None, appearance_ref=None)
    data["locations"][2]["mechanisms"].append(dict(local_id="door",kind="door",
        destination_key=None,initially_open=False,initially_locked=False,operable=True,key_ref=None,
        interaction_policy={"version":1,"maximum_distance_m":reach},appearance_ref="keytool"))
    data["objects"][0]["observation_policy"]["detail_distance_m"] = detail
    data["objects"][0]["observation_policy"]["detail_observers"] = ["worker"] if authorize else []
    return data


def scene_for(**settings):
    scene = Scene(document(**settings))
    scene.target = "world:one:mechanism:target/door"
    return scene


def attempt_open(scene):
    attempt = ActionPipeline().create_attempt(ActionProposal("open:"+str(len(scene.history.get_events())),
        "world:one:agent:worker","Open",["object:"+scene.target],{"method":"push open the door"}))
    result,event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=scene.world),
        world_state=scene.world,event_history=scene.history).execute_with_result(attempt,
            simulation_tick=scene.clock.capture())
    assert event is not None
    scene.processor.dispatch_with_evidence(event)
    return result,event


@pytest.mark.parametrize("reach,detail,authorized,expected_text,success",[
    (9,2,True,"你看到一个小物体。",True),
    (1,10,True,"细看可见物体边缘的凹齿。",False),
    (9,10,False,"你看到一个小物体。",True),
    (1,2,True,"你看到一个小物体。",False),
])
def test_independent_observation_interaction_matrix(reach,detail,authorized,expected_text,success):
    scene = scene_for(reach=reach,detail=detail,authorize=authorized)
    before = scene.world.get_entity(scene.target)
    assert scene.observe()[0] == (expected_text,)
    result,event = attempt_open(scene)
    assert result.success is success
    assert scene.world.environment[scene.target].is_open is success
    assert scene.world.get_entity(scene.target) == before
    evidence = scene.history.get_processing_evidence(event.id)
    failures = [f for f in evidence.observable_facts if f.predicate == "interaction_out_of_reach"]
    assert bool(failures) is (not success)
    if not success:
        owner = "world:one:agent:worker"
        assert any(o.content == failures[0] for o in scene.store.get_by_observer(owner))
        assert not any(o.source_event_id == event.id for o in scene.store.get_by_observer("world:one:agent:other"))
        assert event.metadata["confirmed_attempt_failure"]["verified_conditions"] == ("interaction_out_of_reach",)


@pytest.mark.parametrize("value",[-1,True,float("nan"),float("inf")])
def test_invalid_reach_configuration_fails_closed(value):
    with pytest.raises((ValueError,TypeError)):
        Scene(document(reach=value))


def test_policy_codec_is_closed_versioned_and_symmetric():
    from cognitive_world.core.interaction_range import InteractionRangePolicy
    from cognitive_world.core.persistence import PersistedValueCodec
    codec = PersistedValueCodec()
    policy = InteractionRangePolicy(1,2)
    assert codec.loads(codec.dumps(policy)) == policy
    raw = json.loads(codec.dumps(policy));raw["fields"]["version"] = 2
    with pytest.raises(ValueError): codec.loads(json.dumps(raw).encode())


def test_stale_failure_cannot_commit_after_authoritative_movement():
    scene = scene_for()
    attempt = ActionPipeline().create_attempt(ActionProposal("stale-open", "world:one:agent:worker",
        "Open", ["object:"+scene.target], {"method":"push open the door"}))
    result,event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=scene.world),
        world_state=scene.world,event_history=scene.history).execute_with_result(attempt,
            simulation_tick=scene.clock.capture())
    assert result.success is False and event is not None
    movement = scene.move()
    before = tuple(scene.history.get_events())
    with pytest.raises(PermissionError, match="reach failure"):
        scene.processor.dispatch_with_evidence(event)
    assert tuple(scene.history.get_events()) == before
    assert scene.history.get_event(movement.id) is not None
    assert not scene.world.environment[scene.target].is_open
    assert not scene.history.requires_recovery()


@pytest.mark.parametrize("change",["missing", "different_frame"])
def test_unknown_geometry_is_not_an_authoritative_reach_failure(change):
    data = document()
    data["locations"][0]["observation_zone"] = (None if change == "missing" else
        {"version":1,"frame_id":"far","offset_m":8})
    scene = Scene(data);scene.target = "world:one:mechanism:target/door"
    attempt = ActionPipeline().create_attempt(ActionProposal("unknown", "world:one:agent:worker",
        "Open",["object:"+scene.target],{"method":"push open the door"}))
    result,event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=scene.world),
        world_state=scene.world,event_history=scene.history).execute_with_result(attempt,
            simulation_tick=scene.clock.capture())
    assert not result.success and event is None
    assert not scene.world.environment[scene.target].is_open and not scene.history.get_events()


@pytest.mark.parametrize("change",["future", "field", "appearance", "recipient", "passage"])
def test_v4_unknown_or_unresolved_configuration_fails_closed(change):
    data = document();mechanism=data["locations"][2]["mechanisms"][0]
    if change == "future": mechanism["interaction_policy"]["version"]=2
    elif change == "field": mechanism["interaction_policy"]["script"]="never execute"
    elif change == "appearance": mechanism["appearance_ref"]="missing"
    elif change == "recipient": data["objects"][0]["observation_policy"]["detail_observers"]=["missing"]
    else: data["locations"][0]["mechanisms"][0]["interaction_policy"]={"version":1,"maximum_distance_m":1}
    with pytest.raises((ValueError,TypeError)): Scene(data)


def test_new_result_is_actually_consumable_but_not_a_v1_feedback_snapshot_record():
    from types import SimpleNamespace
    from cognitive_world.cognition.runtime import CognitiveRuntime
    from cognitive_world.decision.behavior_feedback import BehaviorFeedback
    from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
    scene = scene_for();result,event = attempt_open(scene)
    assert not result.success
    owner = "world:one:agent:worker"
    observation, = (o for o in scene.store.get_by_observer(owner) if o.source_event_id == event.id)
    runtime = CognitiveRuntime()
    runtime._bind_observation_history(scene.history,codec=scene.processor.persistence_codec,trust=scene.trust)
    state = runtime.process(owner,[observation])
    assert state.percept_ids == ["percept:"+observation.observation_id]
    assert runtime.has_consumed_observation(owner,observation,source_event_id=event.id)
    # Demonstrate the precise compatibility boundary, not a production workaround.
    feedback = BehaviorFeedback()
    source = event.metadata["confirmed_attempt_failure"]
    fact = SimpleNamespace(percept_id=state.percept_ids[0],source_event_id=event.id,
        predicate=observation.content.predicate,value="True")
    assert feedback.record_failure(owner_id=owner,action_type=source["action_type"],
        target=source["target_refs"][0],method=source["method"],facts=(fact,),
        source_refs=(fact.percept_id,),event_id=event.id,tick=scene.clock.current_time)
    with pytest.raises(PermissionError,match="locked-door"):
        BehaviorFeedbackSnapshot.capture(feedback=feedback,event_history=scene.history,
            timeline_id=scene.history.timeline_id,simulation_tick=scene.clock.current_time,
            session_id="scope",restore_generation=0,agent_ids=(owner,))


def test_signed_restore_preserves_reach_policy_event_identity_and_independent_observation(tmp_path,monkeypatch):
    from cognitive_world.agent import AgentActionLoop,Character,CognitionContext
    from cognitive_world.cognition.memory_store import MemoryStore
    from cognitive_world.runtime.context import RuntimeContext
    from cognitive_world.runtime.runtime import SimulationRuntime
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot,RestoreCoordinator
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from test_runtime_content_commit_boundary import _signed_runtime
    from test_runtime_reconstruction import _dependency_manifest
    scene=scene_for();original_view=scene.observe()[0];result,event=attempt_open(scene)
    assert not result.success
    memory=MemoryStore()
    context=RuntimeContext(scene.clock,scene.world,scene.history,agent_registry=scene.agents,
        observation_store=scene.store)
    def provide(agent):
        return CognitionContext.from_character(Character(agent.character_id,agent.agent_id,agent.agent_id,
            goal_ids=list(agent.goal_ids)),scene.cognition,memory,observation_store=scene.store)
    runtime=SimulationRuntime(context,event_processor=scene.processor,agent_action_loop=AgentActionLoop(),
        cognition_context_provider=provide,allow_environment_provider_discovery=False)
    scene.cognition.bind_write_fence(runtime.write_fence);memory.bind_write_fence(runtime.write_fence)
    owner="world:one:agent:worker"
    actor=scene.agents.get(owner)
    turn=runtime.agent_action_loop.agent_turn
    with runtime.write_fence.operation():
        turn.prepare_decision_context(actor,provide(actor),simulation_tick=scene.clock.capture())
    observed,=(o for o in scene.store.get_by_observer(owner) if o.source_event_id==event.id)
    assert turn.cognitive_runtime.has_consumed_observation(owner,observed,source_event_id=event.id)
    assert "percept:"+observed.observation_id in turn.cognitive_runtime.working_memory_store.get(owner).percept_ids
    assert memory.get_all_memories()==()
    assert runtime.behavior_feedback.history==[]
    manager=SaveManager(tmp_path/"range",trust=scene.trust,codec=scenario_snapshot_codec())
    saved=manager.create_manual_save(runtime=runtime,cognition=scene.cognition,memory_store=memory,
        agent_contexts=tuple(provide(a) for a in scene.agents.all_agents()))
    recorded=scene.history.get_persistence_record(event.id).to_json_record()
    original=scene.world.get_entity(scene.target)
    class Assembler:
        def assemble(self,inputs):
            return _signed_runtime(scene.trust,inputs)[0]
    def forbidden(*args,**kwargs):
        pytest.fail("restore must not re-sign inherited results")
    with monkeypatch.context() as guard:
        guard.setattr("cognitive_world.event.processor.make_persisted_event_record",forbidden)
        child=RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(manager.stage_restore(saved.save_id,
            timeline_id=saved.timeline_id,active_runtime=runtime,assembler=Assembler(),
            dependencies=_dependency_manifest(),new_timeline_id="range-child"))
    assert child.context.event_history.get_persistence_record(event.id).to_json_record()==recorded
    assert child.context.world_state.get_entity(scene.target)==original
    restored=Scene.__new__(Scene)
    restored.world=child.context.world_state;restored.history=child.context.event_history
    restored.processor=child.event_processor;restored.agents=child.context.agent_registry
    restored.clock=child.context.clock;restored.store=child.context.observation_store;restored.target=scene.target
    assert restored.observe()[0]==original_view
    # Old out-of-reach evidence stays historical; movement changes the next
    # assessment rather than upgrading that old result or repeating its Attempt.
    with child.write_fence.operation():
        movement=restored.move()
        result,opened=attempt_open(restored)
    assert result.success and restored.world.environment[restored.target].is_open
    assert restored.history.get_event(event.id).changes[0]["success"] is False
    assert len([e for e in restored.history.get_events() if e.id==event.id])==1
    assert not scene.world.environment[scene.target].is_open
    assert scene.history.get_event(opened.id) is None and scene.history.get_event(movement.id) is None
