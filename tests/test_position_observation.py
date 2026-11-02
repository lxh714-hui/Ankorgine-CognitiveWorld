"""Distance gates select detail; actual movement and authorization remain separate."""
import json
from pathlib import Path
import pytest
from test_json_objects_lod import install
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory
from cognitive_world.observation.store import ObservationStore
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext, PlayerMode, PlayerSessionBinding
from cognitive_world.presentation import PresentationPipeline, InMemoryChatOutputGateway

FIXTURE = Path(__file__).resolve().parents[1] / "examples/data/position_observation.json"

def document():
    return json.loads(FIXTURE.read_text())

class Scene:
    def __init__(self, data=None):
        self.world, self.cognition, self.agents, self.instance = install(data or document())
        for location in self.instance.locations:
            self.world.load_environment_data(location.instance_id, {"light_on": True})
        self.history = EventHistory(timeline_id="position-parent")
        self.clock, self.store = SimulationClock(), ObservationStore()
        self.trust = HmacPersistenceTrust(b"position-observation-test-trust-material")
        self.processor = EventProcessor(world_state=self.world, event_history=self.history,
            simulation_clock=self.clock, agent_registry=self.agents, observation_store=self.store,
            persistence_trust=self.trust)
        self.target = "world:one:object:tool"

    def observe(self, who="worker", precision="detail"):
        owner = "world:one:agent:" + who
        event = SystemEventFactory().create(event_id=f"view:{self.history.timeline_id}:{len(self.history.get_events())}",
            event_type="object_observed", timestamp="", simulation_tick=self.clock.current_time,
            participants=[owner], changes=[{"entity_id":self.target,"observer_id":owner,"precision":precision}])
        self.processor.dispatch_with_evidence(event)
        context = RuntimeContext(self.clock, self.world, self.history, agent_registry=self.agents,
            observation_store=self.store, player_session=PlayerSessionBinding("session:"+who, "player:"+who,
                PlayerMode.ROLEPLAY, controlled_agent_id=owner))
        batch = PresentationPipeline.for_runtime(context, InMemoryChatOutputGateway(context)).publish_event(event.id)
        return tuple(m.content for m in batch.messages), event

    def move(self):
        from cognitive_world.decision import ActionPipeline, ActionProposal
        from cognitive_world.resolution.action_flow import ActionResolutionFlow
        from cognitive_world.resolution.causal import MethodBasedResolutionEngine
        owner = "world:one:agent:worker"
        target = "world:one:mechanism:far/route"
        attempt = ActionPipeline().create_attempt(ActionProposal("approach",owner,"Walk",[target],
            {"method":"walk through the passage"}))
        result,event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=self.world),
            world_state=self.world,event_history=self.history).execute_with_result(attempt,
                simulation_tick=self.clock.capture())
        assert result.success and event is not None
        self.processor.dispatch_with_evidence(event)
        return event


def test_actual_passage_movement_changes_precision_not_object_facts():
    scene = Scene()
    entity = scene.world.get_entity(scene.target)
    position = scene.world.locations[scene.target]
    environment = scene.world.environment
    far, before = scene.observe()
    assert far == ("你看到一个小物体。",)
    movement = scene.move()
    assert scene.world.locations["world:one:agent:worker"] == "world:one:location:near"
    assert any(f.predicate=="actor_arrived" for f in scene.history.get_processing_evidence(movement.id).observable_facts)
    near, after = scene.observe()
    assert near == ("细看可见物体边缘的凹齿。",)
    assert scene.world.get_entity(scene.target) == entity
    assert scene.world.locations[scene.target] == position
    assert scene.world.environment == environment
    assert scene.history.get_event(before.id) is not None and before.id != after.id


def test_nearby_other_owner_does_not_inherit_detail_permission():
    scene=Scene()
    far,_=scene.observe("worker")
    denied,_=scene.observe("other")
    assert far==denied==("你看到一个小物体。",)
    scene.move()
    allowed,event=scene.observe("worker")
    assert allowed != denied
    assert all(o.content.predicate != "object_detail" for o in scene.store.get_by_observer("world:one:agent:other"))
    assert any(o.source_event_id == event.id for o in scene.store.get_by_observer("world:one:agent:worker"))


def test_configured_threshold_controls_precision_without_engine_branches():
    d=document();d["objects"][0]["observation_policy"]["detail_distance_m"]=.5
    scene=Scene(d);scene.move()
    assert scene.observe()[0]==("你看到一个小物体。",)


def test_two_authorized_observers_at_different_positions_receive_different_evidence():
    d=document();d["objects"][0]["observation_policy"]["detail_observers"]=["worker","other"]
    scene=Scene(d)
    assert scene.observe("worker")[0] == ("你看到一个小物体。",)
    assert scene.observe("other")[0] == ("细看可见物体边缘的凹齿。",)
    owners={o.observer_id for o in scene.store.all()}
    assert owners == {"world:one:agent:worker","world:one:agent:other"}


@pytest.mark.parametrize("missing", ["zone", "domain", "light", "visible", "detail_permission", "range"])
def test_missing_conditions_cannot_be_replaced_by_a_detail_request(missing):
    d=document()
    if missing == "zone": d["locations"][0]["observation_zone"]=None
    elif missing == "domain": d["locations"][0]["observation_zone"]["frame_id"]="far"
    elif missing == "visible": d["objects"][0]["appearance"]["visible"]=False
    elif missing == "detail_permission": d["objects"][0]["appearance"]["detail_visible"]=False
    elif missing == "range": d["objects"][0]["observation_policy"]["coarse_distance_m"]=7
    scene=Scene(d)
    if missing == "light":
        scene.world.load_environment_data("world:one:location:far", {"light_on":False})
    result,_=scene.observe()
    assert result == (("你看到一个小物体。",) if missing=="detail_permission" else ())


@pytest.mark.parametrize("invalid", ["negative", "reversed", "nan", "bool", "future", "unknown", "recipient", "frame"])
def test_closed_position_configuration_rejects_unsupported_data(invalid):
    d=document();p=d["objects"][0]["observation_policy"]
    if invalid=="negative": p["detail_distance_m"]=-1
    elif invalid=="reversed": p["detail_distance_m"]=11
    elif invalid=="nan": p["coarse_distance_m"]=float("nan")
    elif invalid=="bool": d["locations"][0]["observation_zone"]["offset_m"]=True
    elif invalid=="future": p["version"]=2
    elif invalid=="unknown": p["script"]="not allowed"
    elif invalid=="recipient": p["detail_observers"]=["unplaced"]
    elif invalid=="frame": d["locations"][0]["observation_zone"]["frame_id"]="missing"
    with pytest.raises((ValueError,TypeError,PermissionError)): Scene(d)


def test_old_far_observation_does_not_upgrade_or_reexecute_after_movement():
    scene=Scene();far,event=scene.observe();scene.move()
    count=len(scene.history.get_events());observations=scene.store.all()
    owner="world:one:agent:worker"
    context=RuntimeContext(scene.clock,scene.world,scene.history,agent_registry=scene.agents,
        observation_store=scene.store,player_session=PlayerSessionBinding("retry","player",PlayerMode.ROLEPLAY,
            controlled_agent_id=owner))
    pipeline=PresentationPipeline.for_runtime(context,InMemoryChatOutputGateway(context))
    for _ in range(2):
        assert tuple(m.content for m in pipeline.publish_event(event.id).messages)==far
    assert len(scene.history.get_events())==count and scene.store.all()==observations
    assert scene.observe()[0] != far


def test_range_records_are_versioned_closed_and_round_trip():
    from cognitive_world.core.persistence import PersistedValueCodec
    from cognitive_world.core.observation_range import ObservationZone, ObservationRangePolicy
    codec=PersistedValueCodec()
    for value in (ObservationZone(1,"frame",3),ObservationRangePolicy(1,10,2,("owner",))):
        assert codec.loads(codec.dumps(value))==value
        raw=json.loads(codec.dumps(value));raw["fields"]["version"]=2
        with pytest.raises(ValueError): codec.loads(json.dumps(raw).encode())


def test_restore_retains_positions_permissions_history_and_can_observe_again(tmp_path,monkeypatch):
    from cognitive_world.agent import AgentActionLoop,Character,CognitionContext
    from cognitive_world.cognition.memory_store import MemoryStore
    from cognitive_world.runtime.runtime import SimulationRuntime
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot,RestoreCoordinator
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from test_runtime_content_commit_boundary import _signed_runtime
    from test_runtime_reconstruction import _dependency_manifest
    scene=Scene();scene.observe();scene.move();near,event=scene.observe()
    memory=MemoryStore()
    context=RuntimeContext(scene.clock,scene.world,scene.history,agent_registry=scene.agents,observation_store=scene.store)
    def provide(agent):
        return CognitionContext.from_character(Character(agent.character_id,agent.agent_id,agent.agent_id,
            goal_ids=list(agent.goal_ids)),scene.cognition,memory,observation_store=scene.store)
    runtime=SimulationRuntime(context,event_processor=scene.processor,agent_action_loop=AgentActionLoop(),
        cognition_context_provider=provide,allow_environment_provider_discovery=False)
    scene.cognition.bind_write_fence(runtime.write_fence);memory.bind_write_fence(runtime.write_fence)
    manager=SaveManager(tmp_path/"saves",trust=scene.trust,codec=scenario_snapshot_codec())
    saved=manager.create_manual_save(runtime=runtime,cognition=scene.cognition,memory_store=memory,
        agent_contexts=tuple(provide(a) for a in scene.agents.all_agents()))
    prior=[scene.history.get_persistence_record(e.id).to_json_record() for e in scene.history.get_events()]
    entity=scene.world.get_entity(scene.target)
    class Assembler:
        def assemble(self,inputs):
            rt,_,_,_=_signed_runtime(scene.trust,inputs)
            return rt
    def forbidden(*args,**kwargs):
        pytest.fail("restore must not reissue ancestor Event attestations")
    with monkeypatch.context() as guard:
        guard.setattr("cognitive_world.event.processor.make_persisted_event_record",forbidden)
        child=RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(manager.stage_restore(saved.save_id,
            timeline_id=saved.timeline_id,active_runtime=runtime,assembler=Assembler(),
            dependencies=_dependency_manifest(),new_timeline_id="position-child"))
    assert child.context.world_state.get_entity(scene.target)==entity
    assert [child.context.event_history.get_persistence_record(e.id).to_json_record()
            for e in child.context.event_history.get_events()]==prior
    # This wrapper points only to the verified restored production authorities.
    restored=Scene.__new__(Scene)
    restored.world=child.context.world_state;restored.agents=child.context.agent_registry
    restored.history=child.context.event_history;restored.clock=child.context.clock
    restored.store=child.context.observation_store;restored.processor=child.event_processor
    restored.target=scene.target
    assert restored.store.all()==()
    assert restored.observe()[0]==near
    assert restored.observe("other")[0]==("你看到一个小物体。",)
    assert len(scene.history.get_events())==len(prior)


def test_runnable_json_host_approaches_via_committed_passage_then_observes(capsys):
    from cognitive_world.examples.json_objects import run
    context=run(FIXTURE,"visit",approach=True)
    output=capsys.readouterr().out
    assert "你看到一个小物体。" in output and "凹齿" in output
    assert "local:" not in output and "offset" not in output
    assert context.world_state.locations["local:demo:agent:worker"]=="local:demo:location:near"
    arrivals=[f for event in context.event_history.get_events()
              for f in context.event_history.get_processing_evidence(event.id).observable_facts
              if f.predicate=="actor_arrived"]
    assert len(arrivals)==1
    assert context.world_state.get_entity("local:demo:object:tool").owner_id is None


def test_detail_event_cannot_be_presented_through_another_observer_view():
    from copy import deepcopy
    from cognitive_world.observation.generator import VisibilityPolicy
    from cognitive_world.presentation.perspective import PerspectiveResolver

    data = document()
    data["scenarios"][0]["characters"][0][2] = "near"
    scene = Scene(data)
    owner_a = "world:one:agent:worker"
    owner_b = "world:one:agent:other"
    near = "world:one:location:near"
    assert scene.world.locations[owner_a] == scene.world.locations[owner_b] == near
    policy = scene.world.get_entity(scene.target).attributes["observation_policy"]
    assert owner_a in policy.detail_observers and owner_b not in policy.detail_observers

    detail, event = scene.observe("worker", "detail")
    assert detail == ("细看可见物体边缘的凹齿。",)
    evidence = scene.history.get_processing_evidence(event.id)
    assert scene.history.get_event(event.id) == event
    assert evidence is not None and evidence.has_trusted_source(event)
    observation_a, = scene.store.get_by_observer(owner_a)
    assert observation_a.source_event_id == event.id
    assert observation_a.content.predicate == "object_detail"
    assert observation_a.has_trusted_provenance()
    assert VisibilityPolicy().allows(event, evidence, owner_a)
    assert not VisibilityPolicy().allows(event, evidence, owner_b)
    assert scene.store.get_by_observer(owner_b) == ()

    # B has the same proximity and sight, but its own detail request is only coarse.
    coarse, _ = scene.observe("other", "detail")
    assert coarse == ("你看到一个小物体。",)
    assert all(o.source_event_id != event.id for o in scene.store.get_by_observer(owner_b))
    before_world = deepcopy((dict(scene.world.entities), dict(scene.world.locations), dict(scene.world.environment)))
    before_history = scene.history.get_events()
    before_observations = scene.store.all()

    def pipeline_for(owner, label):
        context = RuntimeContext(scene.clock, scene.world, scene.history,
            agent_registry=scene.agents, observation_store=scene.store,
            player_session=PlayerSessionBinding("session:" + label, "player:" + label,
                PlayerMode.ROLEPLAY, controlled_agent_id=owner))
        perspective = PerspectiveResolver(context).resolve()
        assert perspective.observer_id == owner and perspective.has_trusted_resolution()
        return PresentationPipeline.for_runtime(context, InMemoryChatOutputGateway(context))

    assert pipeline_for(owner_b, "b").publish_event(event.id).messages == ()
    assert tuple(m.content for m in pipeline_for(owner_a, "a").publish_event(event.id).messages) == detail
    assert (dict(scene.world.entities), dict(scene.world.locations), dict(scene.world.environment)) == before_world
    assert scene.history.get_events() == before_history
    assert scene.store.all() == before_observations
    assert scene.history.get_processing_evidence(event.id) == evidence


@pytest.mark.parametrize("distance, expected_worker", [
    (2, "细看可见物体边缘的凹齿。"),
    (2.000001, "你看到一个小物体。"),
])
def test_detail_distance_boundary_preserves_authorization_and_world(distance, expected_worker):
    from copy import deepcopy

    data = document()
    for location in data["locations"][:2]:
        location["observation_zone"]["offset_m"] = distance
    scene = Scene(data)
    before = deepcopy((dict(scene.world.entities), dict(scene.world.locations),
                       dict(scene.world.environment)))
    worker, worker_event = scene.observe("worker")
    other, other_event = scene.observe("other")
    assert worker == (expected_worker,)
    assert other == ("你看到一个小物体。",)
    worker_facts = scene.history.get_processing_evidence(worker_event.id).observable_facts
    other_facts = scene.history.get_processing_evidence(other_event.id).observable_facts
    assert any(f.predicate == ("object_detail" if distance == 2 else "object_shape") for f in worker_facts)
    assert all(f.predicate != "object_detail" for f in other_facts)
    assert (dict(scene.world.entities), dict(scene.world.locations),
            dict(scene.world.environment)) == before


@pytest.mark.parametrize("distance, visible", [(10, True), (10.000001, False)])
def test_coarse_distance_boundary(distance, visible):
    from copy import deepcopy

    data = document()
    data["locations"][0]["observation_zone"]["offset_m"] = distance
    scene = Scene(data)
    before = deepcopy((dict(scene.world.entities), dict(scene.world.locations),
                       dict(scene.world.environment)))
    messages, event = scene.observe(precision="coarse")
    facts = scene.history.get_processing_evidence(event.id).observable_facts
    observations = [o for o in scene.store.get_by_observer("world:one:agent:worker")
                    if o.source_event_id == event.id]
    if visible:
        assert messages == ("你看到一个小物体。",)
        assert any(f.predicate == "object_shape" for f in facts)
        assert any(o.content.predicate == "object_shape" for o in observations)
    else:
        assert messages == ()
        assert not any(f.predicate in {"object_shape", "object_detail"} for f in facts)
        assert observations == []
    assert (dict(scene.world.entities), dict(scene.world.locations),
            dict(scene.world.environment)) == before
