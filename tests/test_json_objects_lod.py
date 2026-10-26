"""JSON objects use installed physics and evidence-bound appearance projection."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from cognitive_world.content.llm import parse_generation_proposal
from cognitive_world.content.pipeline import ContentRegistry, ContentValidator, ContentInstantiator
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.core.world_state import WorldState
from cognitive_world.safety.governance import UniversalSafetyGovernance

FIXTURE = Path(__file__).resolve().parents[1] / "examples/data/json_objects.json"

def document():
    return json.loads(FIXTURE.read_text())

def install(data=None):
    registry = ContentRegistry(ContentValidator(UniversalSafetyGovernance()))
    registry.register(parse_generation_proposal(json.dumps(data or document())))
    world, cognition, agents = WorldState(), CognitionContainer(), AgentRegistry()
    instance = ContentInstantiator(registry).instantiate("visit", "one", "world",
        world=world, cognition=cognition, agents=agents)
    return world, cognition, agents, instance

def test_json_objects_have_resolved_identity_owner_and_mechanism_reference():
    world, _, _, instance = install()
    actor = instance.characters[0].agent_id
    tool = world.get_entity("world:one:object:tool")
    assert tool.type == "tool" and tool.owner_id == actor
    assert world.locations[tool.id] == actor
    assert world.environment[instance.locations[0].mechanism_ids[0]].key_id == tool.id


def observe(data=None, precision="coarse", lit=True, sequential=False):
    from cognitive_world.core.persistence import HmacPersistenceTrust
    from cognitive_world.event import EventProcessor, EventHistory, SystemEventFactory
    from cognitive_world.observation.store import ObservationStore
    from cognitive_world.runtime.clock import SimulationClock
    from cognitive_world.runtime.context import RuntimeContext, PlayerSessionBinding, PlayerMode
    from cognitive_world.presentation import PresentationPipeline, InMemoryChatOutputGateway
    world, cognition, agents, instance = install(data)
    actor = instance.characters[0].agent_id
    world.load_environment_data(instance.entry_location_id, {"light_on": lit})
    history, store, clock = EventHistory(timeline_id="object-tests"), ObservationStore(), SimulationClock()
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=agents, observation_store=store,
        persistence_trust=HmacPersistenceTrust(b"json-object-test-trust-material-32"))
    event = SystemEventFactory().create(event_id="inspect", event_type="object_observed",
        timestamp="", simulation_tick=0, participants=[actor],
        changes=[{"entity_id":"world:one:object:tool", "observer_id":actor,"precision":precision}])
    processor.dispatch_with_evidence(event)
    context = RuntimeContext(clock, world, history, agent_registry=agents, observation_store=store,
        player_session=PlayerSessionBinding("session", "player", PlayerMode.ROLEPLAY, controlled_agent_id=actor))
    batch = PresentationPipeline.for_runtime(context, InMemoryChatOutputGateway(context)).publish_event(event.id)
    if sequential:
        before = (world.entities, world.locations, world.environment)
        second = SystemEventFactory().create(event_id="inspect-detail", event_type="object_observed",
            timestamp="", simulation_tick=0, participants=[actor],
            changes=[{"entity_id":"world:one:object:tool", "observer_id":actor,"precision":"detail"}])
        processor.dispatch_with_evidence(second)
        detailed = PresentationPipeline.for_runtime(context, InMemoryChatOutputGateway(context)).publish_event(second.id)
        assert (world.entities, world.locations, world.environment) == before
        return batch, detailed, store, actor
    return batch, store, history, actor


def test_same_json_entity_has_distinct_authorized_coarse_and_detail_messages():
    coarse, detail, store, owner = observe(sequential=True)
    assert len(coarse.messages) == len(detail.messages) == 1
    assert coarse.messages[0].content != detail.messages[0].content
    observations = store.get_by_observer(owner)
    assert len(observations) == 2
    assert observations[0].content.subject_ref == observations[1].content.subject_ref
    assert observations[0].source_event_id != observations[1].source_event_id
    assert {o.content.predicate for o in observations} == {"object_shape", "object_detail"}
    assert "world:" not in detail.messages[0].content
    assert "key" not in detail.messages[0].content.lower()


def test_detail_request_does_not_grant_missing_proximity_or_disclosure():
    data = document()
    data["scenarios"][0]["objects"][0][2] = "location:room"
    batch, _, _, _ = observe(data, precision="detail")
    coarse, _, _, _ = observe(data)
    assert batch.messages == coarse.messages  # retained coarse evidence, no invented reach
    data["objects"][0]["appearance"]["visible"] = False
    assert not observe(data, precision="detail")[0].messages
    assert not observe(lit=False, precision="detail")[0].messages


def act(data=None, tools=True):
    from cognitive_world.decision import ActionPipeline, ActionProposal
    from cognitive_world.resolution.action_flow import ActionResolutionFlow
    from cognitive_world.resolution.causal import MethodBasedResolutionEngine
    from cognitive_world.event import EventProcessor, EventHistory
    from cognitive_world.runtime.clock import SimulationClock
    from cognitive_world.core.persistence import HmacPersistenceTrust
    world, _, agents, instance = install(data)
    actor = instance.characters[0].agent_id
    target = instance.locations[0].mechanism_ids[0]
    history = EventHistory(timeline_id="physics-json")
    clock = SimulationClock()
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=agents, persistence_trust=HmacPersistenceTrust(b"json-object-test-trust-material-32"))
    attempt = ActionPipeline().create_attempt(ActionProposal("try", actor, "open", [target],
        {"method":"use key to unlock and open the door", "tools":["world:one:object:tool"] if tools else []}))
    resolution, event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world), world_state=world,
        event_history=history).execute_with_result(attempt, simulation_tick=clock.capture())
    assert event is not None
    processor.dispatch_with_evidence(event)
    return world, history, resolution, processor


def test_only_json_ownership_and_placement_change_formal_physical_result():
    good, history, result, _ = act()
    assert result.success and good.environment["world:one:mechanism:room/door"].is_open
    assert len(history.get_events()) == 1
    other = document()
    other["scenarios"][0]["characters"].append(["other", "worker", "room"])
    other["scenarios"][0]["objects"][0][3] = "actor:other"
    bad, h, failure, _ = act(other)
    assert not failure.success and len(h.get_events()) == 1
    assert not bad.environment["world:one:mechanism:room/door"].is_open
    away = document()
    away["scenarios"][0]["objects"][0][2] = "location:room"
    assert not act(away)[2].success
    assert not act(tools=False)[2].success


@pytest.mark.parametrize("change", ["owner", "missing", "collision", "mechanism", "unknown", "version"])
def test_invalid_json_references_and_definitions_fail_closed(change):
    d = document()
    if change == "owner": d["scenarios"][0]["objects"][0][3] = "actor:missing"
    elif change == "missing": d["scenarios"][0]["objects"] = []
    elif change == "collision": d["scenarios"][0]["objects"].append(d["scenarios"][0]["objects"][0])
    elif change == "mechanism": d["locations"][0]["mechanisms"][0]["kind"] = "invented"
    elif change == "unknown": d["objects"][0]["attributes"] = {"secret":"do not disclose"}
    elif change == "version": d["schema_version"] = 99
    with pytest.raises((ValueError, TypeError, PermissionError)): install(d)


def test_missing_sight_and_hidden_detail_cannot_be_requested_into_existence():
    d = document()
    d["characters"][0]["sensory_capabilities"] = []
    assert not observe(d, precision="detail")[0].messages
    d = document()
    d["objects"][0]["appearance"]["detail_visible"] = False
    assert observe(d, precision="detail")[0].messages == observe(d)[0].messages


def test_persisted_appearance_is_closed_versioned_and_round_trips():
    from cognitive_world.core.persistence import PersistedValueCodec
    from cognitive_world.core.object_appearance import ObjectAppearance
    codec = PersistedValueCodec()
    value = ObjectAppearance(1, "small", "notched", True, True)
    assert codec.loads(codec.dumps(value)) == value
    with pytest.raises(ValueError): ObjectAppearance(2, "small", "notched", True, True)
    from dataclasses import dataclass
    @dataclass
    class Unknown:
        value: int
    with pytest.raises(TypeError): codec.dumps(Unknown(1))


def test_real_runtime_installation_save_restore_and_fork_preserve_json_objects(tmp_path):
    from test_runtime_content_commit_boundary import _signed_runtime
    from test_runtime_reconstruction import _dependency_manifest
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from cognitive_world.event import SystemEventFactory
    runtime, cognition, memory, installer = _signed_runtime()
    proposal = parse_generation_proposal(json.dumps(document()))
    with runtime.write_fence.operation():
        instance = installer.install_proposal(proposal, template_id="visit", instance_id="one",
            world_id="world", source_id="json-file")
    world = runtime.context.world_state
    tool_id = "world:one:object:tool"
    actor = instance.characters[0].agent_id
    tool = world.get_entity(tool_id)
    assert tool.owner_id == actor and world.locations[tool_id] == actor
    installation_id = "runtime-content:world:one"
    from cognitive_world.core.world_state import WorldStateSlot
    slot = WorldStateSlot("entities", tool_id, ("owner_id",))
    origin = world.read_state_slot(slot, event_history=runtime.context.event_history)
    assert origin.source_event_id == installation_id and origin.origin_kind == "event"
    from cognitive_world.decision import ActionPipeline, ActionProposal
    from cognitive_world.resolution.action_flow import ActionResolutionFlow
    from cognitive_world.resolution.causal import MethodBasedResolutionEngine
    door_id = instance.locations[0].mechanism_ids[0]
    with runtime.write_fence.operation():
        attempt = ActionPipeline().create_attempt(ActionProposal("json-open", actor, "Try opening", [door_id],
            {"method":"use key to unlock and open the door", "tools":[tool_id]}))
        result, event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world), world_state=world,
            event_history=runtime.context.event_history).execute_with_result(attempt,
                simulation_tick=runtime.context.clock.capture())
        assert result.success and event is not None
        runtime.event_processor.dispatch_with_evidence(event)
    assert world.environment[door_id].is_open
    state_origin = world.read_state_slot(WorldStateSlot("environment", door_id, ("is_open",)),
        event_history=runtime.context.event_history)
    assert state_origin.source_event_id == event.id
    manager = SaveManager(tmp_path / "saves", trust=runtime.event_processor.persistence_trust,
                          codec=scenario_snapshot_codec())
    contexts = tuple(runtime.cognition_context_provider(a) for a in runtime.context.agent_registry.all_agents())
    saved = manager.create_manual_save(runtime=runtime, cognition=cognition, memory_store=memory,
                                      agent_contexts=contexts)
    class Assembler:
        def assemble(self, inputs):
            restored, _, _, install_service = _signed_runtime(runtime.event_processor.persistence_trust, inputs)
            install_service.registry.register(proposal)
            return restored
    before = [runtime.context.event_history.get_persistence_record(e.id).to_json_record()
              for e in runtime.context.event_history.get_events()]
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=runtime, assembler=Assembler(),
        dependencies=_dependency_manifest(), new_timeline_id="object-child"))
    assert child.context.world_state.get_entity(tool_id) == tool
    assert child.context.world_state.locations[tool_id] == actor
    assert child.context.world_state.read_state_slot(slot, event_history=child.context.event_history) == origin
    assert [child.context.event_history.get_persistence_record(e.id).to_json_record()
            for e in child.context.event_history.get_events()] == before
    assert child.context.world_state.environment[instance.locations[0].mechanism_ids[0]].key_id == tool_id

    assert child.context.world_state.environment[door_id].is_open
    assert child.context.world_state.read_state_slot(WorldStateSlot("environment", door_id, ("is_open",)),
        event_history=child.context.event_history) == state_origin


def test_observation_evidence_without_actual_delivery_is_not_presented(capsys):
    from cognitive_world.examples.json_objects import run
    from cognitive_world.observation.store import ObservationStore
    from cognitive_world.presentation import PresentationPipeline, InMemoryChatOutputGateway
    context = run(FIXTURE, "visit")
    output = capsys.readouterr().out
    assert "凹齿" in output and "Committed door result: True" in output
    assert len(context.event_history.get_events()) == 3
    context.observation_store = ObservationStore()
    pipeline = PresentationPipeline.for_runtime(context, InMemoryChatOutputGateway(context))
    assert pipeline.publish_event("view:tool:detail").messages == ()


def test_repeated_committed_result_does_not_reapply_physics():
    world, history, result, processor = act()
    event, = history.get_events()
    state = world.environment
    record = history.get_persistence_record(event.id).to_json_record()
    processor.dispatch_with_evidence(event)
    assert len(history.get_events()) == 1
    assert world.environment == state
    assert history.get_persistence_record(event.id).to_json_record() == record


def test_runtime_identity_collision_rejects_before_mutation():
    from cognitive_world.core.entity import Entity
    registry = ContentRegistry(ContentValidator(UniversalSafetyGovernance()))
    registry.register(parse_generation_proposal(json.dumps(document())))
    world, cognition, agents = WorldState(), CognitionContainer(), AgentRegistry()
    original = Entity("world:one:object:tool", "object")
    world.load_entity(original)
    with pytest.raises(ValueError):
        ContentInstantiator(registry).instantiate("visit", "one", "world", world=world,
            cognition=cognition, agents=agents)
    assert world.entities == {original.id: original}
    assert agents.all_agents() == ()


def test_future_and_unknown_persisted_records_reject():
    from cognitive_world.core.object_appearance import ObjectAppearance
    from cognitive_world.core.persistence import PersistedValueCodec
    codec = PersistedValueCodec()
    data = json.loads(codec.dumps(ObjectAppearance(1, "small", "notched", True, True)))
    data["fields"]["version"] = 2
    with pytest.raises(ValueError): codec.loads(json.dumps(data).encode())
    with pytest.raises(ValueError): codec.loads(b'{"$record":"unregistered:type","fields":{}}')


def test_json_renaming_does_not_require_a_new_python_world_constructor(tmp_path, capsys):
    from cognitive_world.examples.json_objects import run
    d = document()
    d["objects"][0]["template_id"] = "another-tool-template"
    d["scenarios"][0]["objects"][0][:2] = ["device", "another-tool-template"]
    d["locations"][0]["mechanisms"][0]["local_id"] = "hatch"
    d["locations"][0]["mechanisms"][0]["key_ref"] = "device"
    path = tmp_path / "variant.json"
    path.write_text(json.dumps(d))
    context = run(path, "visit")
    assert context.world_state.environment["local:demo:mechanism:room/hatch"].is_open
    assert context.world_state.get_entity("local:demo:object:device").owner_id == "local:demo:agent:worker"
    assert "Committed door result: True" in capsys.readouterr().out


def test_wrong_owner_cannot_gain_detail_even_at_the_same_position():
    d = document()
    d["scenarios"][0]["characters"].append(["other", "worker", "room"])
    d["scenarios"][0]["objects"][0][3] = "actor:other"
    coarse, _, _, _ = observe(d)
    detail, _, _, _ = observe(d, precision="detail")
    assert coarse.messages == detail.messages
