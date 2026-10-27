"""Real JSON installation, signed take commits, authorized results and L1."""

from copy import deepcopy
from dataclasses import replace
import pytest
from test_pluggable_physics import Host, document
from cognitive_world.decision import ActionPipeline, ActionProposal
from cognitive_world.resolution.action_flow import ActionResolutionFlow


def make_host(eligible=True, structure=None, owned_relation=True, item_key="panel"):
    data = document()
    scenario = data["scenarios"][0]
    scenario["physical_rules"] = []
    scenario["characters"].append(["watcher", "worker", "far"])
    scenario["objects"][0][3] = "actor:watcher"
    scenario["physical_relations"] = [
        {"source": "object:panel", "target": "actor:watcher", "kinds": ["owned_by"]},
        {"source": "object:panel", "target": "object:latch", "kinds": ["controls"]},
    ]
    if structure:
        scenario["physical_relations"].append(
            {"source": "object:panel", "target": "object:handle", "kinds": [structure]}
        )
    data["objects"][0]["physical_state"]["properties"][0]["value"] = eligible
    if not owned_relation:
        scenario["physical_relations"] = [
            r for r in scenario["physical_relations"] if "owned_by" not in r["kinds"]
        ]
    if item_key != "panel":
        scenario["objects"][0][0] = item_key
        for r in scenario["physical_relations"]:
            if r["source"] == "object:panel":
                r["source"] = "object:" + item_key
    # Add a second actual location through the existing strict JSON installation.
    data["locations"].append(dict(data["locations"][0], template_id="elsewhere"))
    scenario["locations"].append(["elsewhere", "elsewhere"])
    host = Host(data)
    host.panel = "physical:one:object:" + item_key
    from cognitive_world.items.take import TakePolicy

    host.runtime.event_processor.take_policy = TakePolicy(
        1, "open", "manual_manipulation"
    )
    return host


def prepare(h, actor=None, model=None):
    from cognitive_world.items.take import ItemTakeResolutionEngine

    rt = h.runtime
    attempt = ActionPipeline().create_attempt(
        ActionProposal(
            "take-proposal",
            actor or h.owner,
            "take",
            ["object:" + h.panel],
            {"method": "take the item", "item_operation": "take"},
        )
    )
    flow = ActionResolutionFlow(
        ItemTakeResolutionEngine(
            rt.context.world_state,
            rt.context.event_history,
            rt.context.agent_registry,
            rt.event_processor.take_policy,
            model,
        ),
        world_state=rt.context.world_state,
        event_history=rt.context.event_history,
    )
    return flow.execute_with_result(attempt, simulation_tick=rt.context.clock.capture())


def observations(h):
    return tuple(
        o
        for o in h.runtime.context.observation_store.all()
        if o.content.predicate == "item_taken"
    )


def consume(h):
    rt = h.runtime
    agent = rt.context.agent_registry.get(h.owner)
    with rt.write_fence.operation():
        return rt.agent_action_loop.agent_turn.prepare_decision_context(
            agent,
            rt.cognition_context_provider(agent),
            simulation_tick=rt.context.clock.capture(),
        )[1]


def test_take_is_joint_owner_preserving_private_and_consumed_once():
    h = make_host()
    rt = h.runtime
    w = rt.context.world_state
    before = (w.entities, w.relationships, w.get_location(h.owner))
    goals_before = deepcopy(h.cognition.goal_store.get_all())
    owner = w.get_entity(h.panel).owner_id
    with rt.write_fence.operation():
        result, event = prepare(h)
        assert (
            result.success
            and not observations(h)
            and w.get_location(h.panel) == w.get_location(h.owner)
        )
        evidence = rt.event_processor.dispatch_with_evidence(event)
        repeated = rt.event_processor.dispatch_with_evidence(event)
    assert repeated == evidence
    assert w.get_location(h.panel) == h.owner and w.get_location(h.owner) == before[2]
    assert w.relationships[(h.panel, h.owner)].kinds == ("held_by",)
    assert w.get_entity(h.panel).owner_id == owner and w.entities == before[0]
    for key, value in before[1].items():
        assert w.relationships[key] == value
    (observation,) = observations(h)
    assert (
        observation.observer_id == h.owner
        and observation.content.subject_ref == h.panel
    )
    assert observation.source_event_id == event.id and observation.content.value is True
    cognitive = rt.agent_action_loop.agent_turn.cognitive_runtime
    assert not cognitive.has_consumed_observation(
        h.owner, observation, source_event_id=event.id
    )
    state = consume(h)
    assert "percept:" + observation.observation_id in state.percept_ids
    assert cognitive.has_consumed_observation(
        h.owner, observation, source_event_id=event.id
    )
    receipt = cognitive._l1_consumption_receipts[(h.owner, observation.observation_id)]
    consume(h)
    assert (
        cognitive._l1_consumption_receipts[(h.owner, observation.observation_id)]
        == receipt
    )
    assert len(observations(h)) == 1
    assert not h.cognition.belief_store.get_all()
    assert h.cognition.goal_store.get_all() == goals_before


def test_competing_candidates_reject_second_without_false_history():
    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        a, first = prepare(h)
        b, second = prepare(h, actor="physical:one:agent:watcher")
        assert a.success and b.success
        rt.event_processor.dispatch_with_evidence(first)
        count = len(rt.context.event_history.get_events())
        with pytest.raises((PermissionError, ValueError)):
            rt.event_processor.dispatch_with_evidence(second)
    assert len(rt.context.event_history.get_events()) == count
    assert (
        not rt.context.event_history.requires_recovery()
        and not rt.write_fence.recovery_required
    )
    assert rt.context.world_state.get_location(h.panel) == h.owner


@pytest.mark.parametrize("structure", ["part_of", "attached_to"])
def test_structure_is_not_implicitly_detached(structure):
    h = make_host(structure=structure)
    with h.runtime.write_fence.operation():
        result, event = prepare(h)
    assert not result.success and event is None and not observations(h)


def test_unmet_precondition_and_second_independent_take_are_not_success():
    h = make_host(False)
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        assert result.confirmed and not result.success
        rt.event_processor.dispatch_with_evidence(event)
    assert (
        not observations(h) and rt.context.world_state.get_location(h.panel) != h.owner
    )
    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        rt.event_processor.dispatch_with_evidence(event)
        next_result, next_event = prepare(h)
        assert next_result.confirmed and not next_result.success
        rt.event_processor.dispatch_with_evidence(next_event)
    assert len(observations(h)) == 1


def test_provider_cannot_forge_an_effect():
    class Bad:
        def evaluate(self, *args):
            return "success"

    h = make_host()
    before = h.runtime.context.world_state.locations
    with h.runtime.write_fence.operation(), pytest.raises((PermissionError, TypeError)):
        prepare(h, model=Bad())
    assert h.runtime.context.world_state.locations == before and not observations(h)


def change(h, target, payload):
    """Controlled system fault/setup event; never insert history or evidence directly."""
    from cognitive_world.event import SystemEventFactory
    from cognitive_world.event.handler import EventHandler
    from cognitive_world.core.update import WorldUpdate

    class Change(EventHandler):
        def handle(self, event):
            return WorldUpdate(target, "update", payload)

    rt = h.runtime
    rt.event_processor.register_handler("take_test_change", Change())
    event = SystemEventFactory().create(
        event_id="change:" + str(len(rt.context.event_history.get_events())),
        event_type="take_test_change",
        timestamp="",
        simulation_tick=rt.context.clock.current_time,
    )
    rt.event_processor.dispatch_with_evidence(event)
    return event


@pytest.mark.parametrize(
    "kind", ["position", "eligibility", "owner", "relation", "structure"]
)
def test_relevant_changes_reject_pending_candidate_without_recovery(kind):
    from cognitive_world.core.physical import PhysicalRelation

    h = make_host(owned_relation=kind != "owner")
    rt = h.runtime
    w = rt.context.world_state
    with rt.write_fence.operation():
        result, pending = prepare(h)
        if kind == "position":
            change(h, "locations", {h.panel: "physical:one:location:elsewhere"})
        elif kind == "eligibility":
            entity = w.get_entity(h.panel)
            state = entity.state["physical"]
            entity = replace(
                entity,
                state={
                    "physical": replace(
                        state,
                        properties=tuple(
                            replace(v, value=False) for v in state.properties
                        ),
                    )
                },
            )
            change(h, "entities", {h.panel: entity})
        elif kind == "owner":
            change(
                h, "entities", {h.panel: replace(w.get_entity(h.panel), owner_id=None)}
            )
        elif kind == "relation":
            change(
                h,
                "relationships",
                {
                    (h.panel, h.owner): PhysicalRelation(
                        1, h.panel, h.owner, ("controls",)
                    )
                },
            )
        else:
            key = (h.panel, "physical:one:object:latch")
            change(
                h,
                "relationships",
                {key: PhysicalRelation(1, *key, ("controls", "attached_to"))},
            )
        before = (
            w.entities,
            w.locations,
            w.relationships,
            rt.context.event_history.get_events(),
        )
        with pytest.raises((PermissionError, ValueError)):
            rt.event_processor.dispatch_with_evidence(pending)
    assert (
        w.entities,
        w.locations,
        w.relationships,
        rt.context.event_history.get_events(),
    ) == before
    assert (
        not rt.context.event_history.requires_recovery()
        and not rt.write_fence.recovery_required
    )


def test_unrelated_change_and_arbitrary_identity_do_not_block_take():
    h = make_host(item_key="arbitrary-token")
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        change(h, "facts", {"unrelated": True})
        rt.event_processor.dispatch_with_evidence(event)
    assert rt.context.world_state.get_location(h.panel) == h.owner


@pytest.mark.parametrize(
    "actor", ["physical:one:object:latch", "physical:one:location:far", "missing"]
)
def test_invalid_holder_identity_cannot_prepare(actor):
    h = make_host()
    before = h.runtime.context.event_history.get_events()
    with h.runtime.write_fence.operation(), pytest.raises(PermissionError):
        prepare(h, actor=actor)
    assert h.runtime.context.event_history.get_events() == before


def test_registered_agent_alias_is_supported_but_object_role_is_not():
    h = make_host()
    rt = h.runtime
    w = rt.context.world_state
    with rt.write_fence.operation():
        change(h, "entities", {h.owner: replace(w.get_entity(h.owner), type="object")})
        with pytest.raises(PermissionError):
            prepare(h)
        change(h, "entities", {h.owner: replace(w.get_entity(h.owner), type="agent")})
        result, event = prepare(h)
        assert result.success
        rt.event_processor.dispatch_with_evidence(event)


def test_old_generation_cannot_commit():
    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        rt.write_fence.freeze_and_advance()
        rt.write_fence.unfreeze()
    with rt.write_fence.operation(), pytest.raises(PermissionError):
        rt.event_processor.dispatch_with_evidence(event)
    assert rt.context.event_history.get_event(event.id) is None and not observations(h)


def test_delivery_failure_is_pending_then_retries_without_reapplying(monkeypatch):
    h = make_host()
    rt = h.runtime
    store = rt.context.observation_store
    add = store.add
    apply = rt.context.world_state.apply_event
    applied = []

    def track(event, update):
        applied.append(event.id)
        return apply(event, update)

    def fail(observation):
        if observation.content.predicate == "item_taken":
            raise RuntimeError("injected delivery failure")
        return add(observation)

    monkeypatch.setattr(store, "add", fail)
    monkeypatch.setattr(rt.context.world_state, "apply_event", track)
    from cognitive_world.event.history import EventProcessingStatus

    with rt.write_fence.operation():
        result, event = prepare(h)
        with pytest.raises(RuntimeError, match="Observation delivery failed"):
            rt.event_processor.dispatch_with_evidence(event)
        assert rt.context.world_state.get_location(h.panel) == h.owner
        assert (
            rt.context.event_history.get_processing_status(event.id)
            is EventProcessingStatus.OBSERVATIONS_PENDING
        )
        monkeypatch.setattr(store, "add", add)
        rt.event_processor.dispatch_with_evidence(event)
    assert applied == [event.id] and len(observations(h)) == 1


def test_observation_authorization_history_and_historical_value():
    from cognitive_world.observation.generator import ObservationGenerator
    from cognitive_world.cognition.runtime import CognitiveRuntime

    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        rt.event_processor.dispatch_with_evidence(event)
    (observation,) = observations(h)
    evidence = rt.context.event_history.get_processing_evidence(event.id)
    assert (
        ObservationGenerator().generate_authorized(
            event,
            evidence,
            observer_id="physical:one:agent:watcher",
            event_history=rt.context.event_history,
        )
        == ()
    )
    unbound = CognitiveRuntime()
    state = unbound.process(h.owner, [observation])
    assert not state.percept_ids and not unbound._l1_consumption_receipts
    bad = replace(observation, observer_id="other")
    assert not unbound.process("other", [bad]).percept_ids
    with rt.write_fence.operation():
        change(h, "locations", {h.owner: "physical:one:location:elsewhere"})
    assert rt.context.observation_store.get(observation.observation_id) == observation
    assert ObservationGenerator().generate_authorized(
        event, evidence, observer_id=h.owner, event_history=rt.context.event_history
    )


def save(h, root):
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.content.persistence import scenario_snapshot_codec

    rt = h.runtime
    manager = SaveManager(root, trust=h.trust, codec=scenario_snapshot_codec())
    saved = manager.create_manual_save(
        runtime=rt,
        cognition=h.cognition,
        memory_store=h.memory,
        agent_contexts=tuple(
            rt.cognition_context_provider(a)
            for a in rt.context.agent_registry.all_agents()
        ),
    )
    return manager, saved


def test_signed_cold_restore_and_child_sibling_isolation(tmp_path, monkeypatch):
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    from test_runtime_reconstruction import _dependency_manifest
    from cognitive_world.items.take import TakePolicy
    import cognitive_world.event.processor as processing

    h = make_host()
    rt = h.runtime
    manager, before = save(h, tmp_path / "saves")
    with rt.write_fence.operation():
        result, event = prepare(h)
        rt.event_processor.dispatch_with_evidence(event)
    manager, after = save(h, tmp_path / "saves")
    committed_state = take_snapshot(h)[:3]
    original_actor_location = rt.context.world_state.get_location(h.owner)
    signed = rt.context.event_history.get_persistence_record(event.id).to_json_record()

    class Assembler:
        def assemble(self, inputs):
            self.host = Host(inputs=inputs, trust=h.trust)
            self.host.runtime.event_processor.take_policy = TakePolicy(
                1, "open", "manual_manipulation"
            )
            return self.host.runtime

    def forbid(*args, **kwargs):
        pytest.fail("historical records must not be re-signed")

    monkeypatch.setattr(processing, "make_persisted_event_record", forbid)
    cold = Assembler()
    slot = ColdRuntimePublisher().activate(
        manager.stage_cold_resume(
            after.save_id,
            timeline_id=after.timeline_id,
            assembler=cold,
            dependencies=_dependency_manifest(),
        )
    )
    cw = cold.host.runtime.context.world_state
    assert cw.get_location(h.panel) == h.owner
    assert (cw.entities, cw.locations, cw.relationships) == committed_state
    assert cw.relationships[(h.panel, h.owner)].kinds == ("held_by",)
    assert cw.get_entity(h.panel).owner_id == "physical:one:agent:watcher"
    assert cw.relationships[(h.panel, "physical:one:agent:watcher")].kinds == (
        "owned_by",
    )
    assert cw.get_location(h.owner) == original_actor_location
    assert cw.relationships[(h.panel, "physical:one:object:latch")].kinds == (
        "controls",
    )
    assert (
        cold.host.runtime.context.event_history.get_persistence_record(
            event.id
        ).to_json_record()
        == signed
    )
    from cognitive_world.observation.generator import ObservationGenerator

    ch = cold.host.runtime.context.event_history
    observed = ObservationGenerator().generate_authorized(
        ch.get_event(event.id),
        ch.get_processing_evidence(event.id),
        observer_id=h.owner,
        event_history=ch,
    )
    assert len(observed) == 1 and observed[0].content.value is True
    assert observed[0].source_event_id == event.id
    restored = cold.host.runtime
    count = len(ch.get_events())
    cognitive = restored.agent_action_loop.agent_turn.cognitive_runtime
    assert not cognitive.has_consumed_observation(
        h.owner, observed[0], source_event_id=event.id
    )
    with restored.write_fence.operation():
        restored.event_processor.dispatch_with_evidence(ch.get_event(event.id))
    (delivered,) = observations(cold.host)
    assert delivered.source_event_id == event.id
    consumed = consume(cold.host)
    assert "percept:" + delivered.observation_id in consumed.percept_ids
    assert cognitive.has_consumed_observation(
        h.owner, delivered, source_event_id=event.id
    )
    receipt = cognitive._l1_consumption_receipts[(h.owner, delivered.observation_id)]
    watcher = "physical:one:agent:watcher"
    previous = cognitive.working_memory_store.get(watcher)
    with restored.write_fence.operation():
        rejected = cognitive.process(watcher, [delivered])
    assert not rejected.percept_ids
    assert cognitive.working_memory_store.get(watcher) == previous
    assert (watcher, delivered.observation_id) not in cognitive._l1_consumption_receipts
    with restored.write_fence.operation():
        restored.event_processor.dispatch_with_evidence(ch.get_event(event.id))
    assert not consume(cold.host).percept_ids
    assert (
        cognitive._l1_consumption_receipts[(h.owner, delivered.observation_id)]
        == receipt
    )
    assert len(observations(cold.host)) == 1 and len(ch.get_events()) == count
    assert ch.get_persistence_record(event.id).to_json_record() == signed
    # New current evidence changes eligibility through a real system event.
    # The old historical success must remain about the original event.
    monkeypatch.undo()
    entity = cw.get_entity(h.panel)
    state = entity.state["physical"]
    revised = replace(
        entity,
        state={
            "physical": replace(
                state,
                properties=tuple(replace(v, value=False) for v in state.properties),
            )
        },
    )
    with restored.write_fence.operation():
        change(cold.host, "entities", {h.panel: revised})
    assert cw.get_entity(h.panel).state["physical"].get("open").value is False
    historical = ObservationGenerator().generate_authorized(
        ch.get_event(event.id),
        ch.get_processing_evidence(event.id),
        observer_id=h.owner,
        event_history=ch,
    )
    assert len(historical) == 1 and historical[0].content.value is True
    assert historical[0].source_event_id == event.id
    assert ch.get_persistence_record(event.id).to_json_record() == signed
    parent = Assembler()
    parent_slot = ColdRuntimePublisher().activate(
        manager.stage_cold_resume(
            before.save_id,
            timeline_id=before.timeline_id,
            assembler=parent,
            dependencies=_dependency_manifest(),
        )
    )
    child = Assembler()
    staged = manager.stage_restore(
        before.save_id,
        timeline_id=before.timeline_id,
        active_runtime=parent.host.runtime,
        assembler=child,
        dependencies=_dependency_manifest(),
        new_timeline_id="take-child",
    )
    active = RestoreCoordinator(parent_slot).activate(staged)
    monkeypatch.undo()
    with active.write_fence.operation():
        result, child_event = prepare(child.host)
        active.event_processor.dispatch_with_evidence(child_event)
    again = Assembler()
    other_slot = ColdRuntimePublisher().activate(
        manager.stage_cold_resume(
            before.save_id,
            timeline_id=before.timeline_id,
            assembler=again,
            dependencies=_dependency_manifest(),
        )
    )
    sibling = Assembler()
    staged = manager.stage_restore(
        before.save_id,
        timeline_id=before.timeline_id,
        active_runtime=again.host.runtime,
        assembler=sibling,
        dependencies=_dependency_manifest(),
        new_timeline_id="take-sibling",
    )
    RestoreCoordinator(other_slot).activate(staged)
    assert active.context.world_state.get_location(h.panel) == h.owner
    assert sibling.host.runtime.context.world_state.get_location(h.panel) != h.owner
    assert sibling.host.runtime.context.event_history.get_event(child_event.id) is None


def test_closed_transition_codec_unknown_version_and_type_fail_closed():
    import json
    from cognitive_world.core.persistence import PersistedValueCodec

    h = make_host()
    with h.runtime.write_fence.operation():
        result, event = prepare(h)
    t = event.changes[1]["transition"]
    codec = PersistedValueCodec()
    assert codec.loads(codec.dumps(t)) == t
    raw = json.loads(codec.dumps(t))
    raw["fields"]["version"] = 99
    with pytest.raises(ValueError):
        codec.loads(json.dumps(raw).encode())
    with pytest.raises(ValueError):
        codec.loads(b'{"$record":"unknown:Take","fields":{}}')


def test_uncertain_history_append_freezes_after_joint_world_publication(
    monkeypatch, tmp_path
):
    h = make_host()
    rt = h.runtime
    history = rt.context.event_history
    append = history.append

    def fail(*args, **kwargs):
        append(*args, **kwargs)
        raise RuntimeError("injected committed-but-error history write")

    monkeypatch.setattr(history, "append", fail)
    with rt.write_fence.operation():
        result, event = prepare(h)
        with pytest.raises(RuntimeError):
            rt.event_processor.dispatch_with_evidence(event)
    assert rt.context.world_state.get_location(h.panel) == h.owner
    assert rt.context.world_state.relationships[(h.panel, h.owner)].kinds == (
        "held_by",
    )
    assert history.get_event(event.id) is not None
    assert history.requires_recovery() and rt.write_fence.recovery_required
    assert not observations(h)
    with pytest.raises((PermissionError, RuntimeError)):
        save(h, tmp_path / "blocked")


def test_unrelated_history_cannot_authorize_consumption():
    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        rt.event_processor.dispatch_with_evidence(event)
    (original,) = observations(h)
    other = make_host()
    other.runtime.context.observation_store.add(original)
    state = consume(other)
    assert "percept:" + original.observation_id not in state.percept_ids
    assert (
        (h.owner, original.observation_id)
        not in other.runtime.agent_action_loop.agent_turn.cognitive_runtime._l1_consumption_receipts
    )


def test_joint_slot_origins_and_private_result_do_not_leak_to_presentation():
    from cognitive_world.core.world_state import WorldStateSlot
    from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding
    from cognitive_world.presentation import (
        PresentationPipeline,
        InMemoryChatOutputGateway,
    )

    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        rt.event_processor.dispatch_with_evidence(event)
    w = rt.context.world_state
    for slot in [
        WorldStateSlot("locations", h.panel),
        WorldStateSlot("relationships", (h.panel, h.owner), ("kinds",)),
    ]:
        read = w.read_state_slot(slot, event_history=rt.context.event_history)
        assert read.origin_kind == "event" and read.source_event_id == event.id
    rt.context.player_session = PlayerSessionBinding(
        "take-view", "player", PlayerMode.ROLEPLAY, controlled_agent_id=h.owner
    )
    gateway = InMemoryChatOutputGateway(rt.context)
    assert (
        not PresentationPipeline.for_runtime(rt.context, gateway)
        .publish_event(event.id)
        .messages
    )


def take_snapshot(h):
    w = h.runtime.context.world_state
    return (
        w.entities,
        w.locations,
        w.relationships,
        h.runtime.context.event_history.get_events(),
    )


def test_failed_take_policy_replacement_rejects_before_append():
    from cognitive_world.items.take import TakePolicy

    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        rt.event_processor.take_policy = TakePolicy(1, "open", "absent_capability")
        before = take_snapshot(h)
        result, old = prepare(h)
        assert result.confirmed and not result.success
        assert take_snapshot(h) == before
        rt.event_processor.take_policy = TakePolicy(1, "open", "manual_manipulation")
        assert take_snapshot(h) == before
        with pytest.raises(PermissionError):
            rt.event_processor.dispatch_with_evidence(old)
        assert take_snapshot(h) == before
        assert not rt.context.event_history.requires_recovery()
        assert not rt.write_fence.recovery_required
        fresh, event = prepare(h)
        assert fresh.confirmed and fresh.success and event.id != old.id
        rt.event_processor.dispatch_with_evidence(event)
    assert rt.context.world_state.get_location(h.panel) == h.owner


@pytest.mark.parametrize("structure", ["attached_to", "part_of"])
def test_failed_take_new_structure_rejects_before_append(structure):
    from cognitive_world.core.physical import PhysicalRelation

    h = make_host(False)
    rt = h.runtime
    with rt.write_fence.operation():
        result, old = prepare(h)
        assert result.confirmed and not result.success
        # Trusted system fixture changes one declared relation through the real
        # processor. It is not a product detach/attach feature or fake history.
        pair = (h.panel, h.target)
        change(h, "relationships", {pair: PhysicalRelation(1, *pair, (structure,))})
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            rt.event_processor.dispatch_with_evidence(old)
        assert take_snapshot(h) == before
        assert not rt.context.event_history.requires_recovery()
        assert not rt.write_fence.recovery_required
        fresh, event = prepare(h)
        assert not fresh.confirmed and event is None
        assert take_snapshot(h) == before


def test_failed_take_unchanged_context_allows_unrelated_event():
    h = make_host(False)
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        assert result.confirmed and not result.success
        change(h, "facts", {"unrelated-take-work": True})
        before = take_snapshot(h)
        rt.event_processor.dispatch_with_evidence(event)
        assert take_snapshot(h)[:3] == before[:3]
        assert len(rt.context.event_history.get_events()) == len(before[3]) + 1
        assert not observations(h)


@pytest.mark.parametrize("defect", ["item", "actor", "owner", "location", "prestate"])
def test_type_correct_provider_cannot_forge_transition(defect):
    from cognitive_world.core.physical import PhysicalRelation
    from cognitive_world.items.take import TakeModel, TakeOutcome

    h = make_host()

    class Bad:
        def evaluate(self, request, view, policy):
            original = TakeModel().evaluate(request, view, policy).transition
            if defect == "item":
                wrong = replace(
                    original,
                    item_id=h.target,
                    relation=replace(original.relation, source=h.target),
                )
            elif defect == "actor":
                other = "physical:one:agent:watcher"
                wrong = replace(
                    original,
                    actor_id=other,
                    relation=replace(original.relation, target=other),
                )
            elif defect == "owner":
                wrong = replace(original, expected_owner=None)
            elif defect == "location":
                wrong = replace(
                    original, expected_location="physical:one:location:elsewhere"
                )
            else:
                prior = PhysicalRelation(1, h.panel, h.owner, ("controls",))
                wrong = replace(
                    original,
                    expected_relation=prior,
                    relation=replace(prior, kinds=("controls", "held_by")),
                )
            wrong.__post_init__()  # Correct closed type and internally valid shape.
            return TakeOutcome("changed", wrong)

    rt = h.runtime
    with rt.write_fence.operation():
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            prepare(h, model=Bad())
        assert take_snapshot(h) == before and not observations(h)
        assert not rt.context.event_history.requires_recovery()
        assert not rt.write_fence.recovery_required
        result, event = prepare(h)
        assert result.success
        rt.event_processor.dispatch_with_evidence(event)
    assert rt.context.world_state.get_location(h.panel) == h.owner


@pytest.mark.parametrize("remove_policy", [False, True])
def test_failed_take_policy_content_binding_and_missing_policy(remove_policy):
    from cognitive_world.items.take import TakePolicy

    h = make_host(False)
    rt = h.runtime
    with rt.write_fence.operation():
        result, event = prepare(h)
        assert result.confirmed and not result.success
        rt.event_processor.take_policy = (
            None if remove_policy else TakePolicy(1, "open", "manual_manipulation")
        )
        before = take_snapshot(h)
        if remove_policy:
            with pytest.raises(PermissionError):
                rt.event_processor.dispatch_with_evidence(event)
            assert take_snapshot(h) == before
            assert not rt.context.event_history.requires_recovery()
            assert not rt.write_fence.recovery_required
        else:
            rt.event_processor.dispatch_with_evidence(event)
            assert take_snapshot(h)[:3] == before[:3]
            assert len(rt.context.event_history.get_events()) == len(before[3]) + 1


def test_failed_take_restored_value_with_new_source_is_stale():
    h = make_host(False)
    rt = h.runtime
    w = rt.context.world_state
    with rt.write_fence.operation():
        _, pending = prepare(h)
        for flag in (True, False):
            entity = w.get_entity(h.panel)
            state = entity.state["physical"]
            entity = replace(
                entity,
                state={
                    "physical": replace(
                        state,
                        properties=tuple(
                            replace(v, value=flag) for v in state.properties
                        ),
                    )
                },
            )
            change(h, "entities", {h.panel: entity})
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            rt.event_processor.dispatch_with_evidence(pending)
        assert take_snapshot(h) == before
        assert not rt.context.event_history.requires_recovery()
        assert not rt.write_fence.recovery_required
        fresh, event = prepare(h)
        assert fresh.confirmed and not fresh.success
        rt.event_processor.dispatch_with_evidence(event)


def test_adjudication_context_closed_codec_values():
    from cognitive_world.core.persistence import PersistedValueCodec
    from cognitive_world.items.take import TakeAdjudicationContext

    h = make_host(False)
    with h.runtime.write_fence.operation():
        _, event = prepare(h)
    record = event.metadata["take_adjudication_context"]
    codec = PersistedValueCodec()
    restored = codec.loads(codec.dumps(record))
    assert TakeAdjudicationContext.from_record(restored).record() == record
    for key, value in [
        ("version", 99),
        ("policy_fingerprint", "0" * 64),
        ("expected_no_holder", False),
        ("extra", "unsupported"),
    ]:
        malformed = deepcopy(record)
        malformed[key] = value
        with pytest.raises((ValueError, PermissionError)):
            TakeAdjudicationContext.from_record(malformed)


@pytest.mark.parametrize("original_success", [True, False], ids=["success", "failure"])
def test_live_take_missing_context_is_rejected(original_success):
    from cognitive_world.items.take import (
        ItemTakeResolutionEngine,
        TakeModel,
        TakePolicy,
    )

    h = make_host()
    rt = h.runtime
    w = rt.context.world_state

    class CountModel(TakeModel):
        calls = 0

        def evaluate(self, *args):
            self.calls += 1
            return super().evaluate(*args)

    model = CountModel()

    class MissingContext(ItemTakeResolutionEngine):
        adjudicated = None

        def _adjudicate(self, attempt):
            decision = super()._adjudicate(attempt)
            assert decision is not None and decision.success is original_success
            assert "take_adjudication_context" in decision.metadata
            self.adjudicated = decision.success
            metadata = dict(decision.metadata)
            metadata.pop("take_adjudication_context")
            if not original_success:
                # Real policy replacement, after the old failure was adjudicated.
                rt.event_processor.take_policy = TakePolicy(
                    1, "open", "manual_manipulation"
                )
            return replace(decision, metadata=metadata)

    with rt.write_fence.operation():
        if not original_success:
            rt.event_processor.take_policy = TakePolicy(1, "open", "absent_capability")
        engine = MissingContext(
            w,
            rt.context.event_history,
            rt.context.agent_registry,
            rt.event_processor.take_policy,
            model,
        )
        attempt = ActionPipeline().create_attempt(
            ActionProposal(
                "missing-context-test",
                h.owner,
                "take",
                ["object:" + h.panel],
                {"method": "take the item", "item_operation": "take"},
            )
        )
        flow = ActionResolutionFlow(
            engine, world_state=w, event_history=rt.context.event_history
        )
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            result, event = flow.execute_with_result(
                attempt, simulation_tick=rt.context.clock.capture()
            )
            # Before the repair this reaches real confirmation, EventFactory and
            # signed EventProcessor commit. No receipts or history are fabricated.
            assert result.confirmed and result.success is original_success
            rt.event_processor.dispatch_with_evidence(event)
        assert engine.adjudicated is original_success and model.calls == 1
        assert take_snapshot(h) == before and not observations(h)
        assert not rt.context.event_history.requires_recovery()
        assert not rt.write_fence.recovery_required
        fresh, event = prepare(h)
        assert fresh.confirmed and fresh.success
        rt.event_processor.dispatch_with_evidence(event)
        assert model.calls == 1
    assert w.get_location(h.panel) == h.owner and len(observations(h)) == 1


@pytest.mark.parametrize("defect", ["version", "unknown", "attempt", "policy", "tick"])
def test_live_take_context_must_bind_adjudication_before_event_creation(defect):
    from cognitive_world.event.factory import EventFactory
    from cognitive_world.items.take import (
        ItemTakeResolutionEngine,
        TakePolicy,
        policy_fingerprint,
    )

    h = make_host()
    rt = h.runtime

    class FaultyContext(ItemTakeResolutionEngine):
        def _adjudicate(self, attempt):
            decision = super()._adjudicate(attempt)
            metadata = deepcopy(decision.metadata)
            context = metadata["take_adjudication_context"]
            if defect == "version":
                context["version"] = 99
            elif defect == "unknown":
                context["unsupported"] = True
            elif defect == "attempt":
                snapshot = list(context["attempt_snapshot"])
                snapshot[0] = "another-attempt"
                context["attempt_snapshot"] = tuple(snapshot)
            elif defect == "policy":
                different = TakePolicy(1, "open", "different-capability")
                context["policy"] = different.record()
                context["policy_fingerprint"] = policy_fingerprint(different)
            else:
                context["tick"] += 1
            return replace(decision, metadata=metadata)

    class TrackingFactory(EventFactory):
        calls = 0

        def create_from_resolution(self, *args, **kwargs):
            self.calls += 1
            return super().create_from_resolution(*args, **kwargs)

    with rt.write_fence.operation():
        attempt = ActionPipeline().create_attempt(
            ActionProposal(
                "faulty-live-context",
                h.owner,
                "take",
                ["object:" + h.panel],
                {"method": "take the item", "item_operation": "take"},
            )
        )
        engine = FaultyContext(
            rt.context.world_state,
            rt.context.event_history,
            rt.context.agent_registry,
            rt.event_processor.take_policy,
        )
        factory = TrackingFactory()
        flow = ActionResolutionFlow(
            engine,
            event_factory=factory,
            world_state=rt.context.world_state,
            event_history=rt.context.event_history,
        )
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            flow.execute_with_result(
                attempt, simulation_tick=rt.context.clock.capture()
            )
        assert factory.calls == 0
        assert take_snapshot(h) == before and not observations(h)
        assert not rt.write_fence.recovery_required
        assert not rt.context.event_history.requires_recovery()


class GenericTakeHostPolicy:
    """Test host assembles the existing generic Resolution extension publicly."""

    @staticmethod
    def engine(h, *, omit_context=False, before_return=None, malformed=None):
        from cognitive_world.items.take import (
            TakeRequest,
            TakeModel,
            TakeAdjudicationContext,
            capture,
        )
        from cognitive_world.resolution.engine import (
            ResolutionEngine,
            ResolutionDecision,
        )

        class HostEngine(ResolutionEngine):
            simulation_time = None
            calls = 0

            def _adjudicate(self, attempt):
                self.calls += 1
                policy = self.policy
                request = TakeRequest(attempt.agent_id, h.panel)
                view, reads = capture(
                    h.runtime.context.world_state,
                    h.runtime.context.event_history,
                    h.runtime.context.agent_registry,
                    request,
                    policy,
                )
                outcome = TakeModel().evaluate(request, view, policy)
                context = TakeAdjudicationContext(
                    attempt._resolution_snapshot(),
                    policy,
                    reads,
                    view.related_relations,
                    not view.held,
                    self.simulation_time.tick,
                ).record()
                metadata = {
                    "simulation_tick": self.simulation_time.tick,
                    "take_adjudication_context": context,
                }
                if outcome.status == "changed":
                    effects = (
                        dict(
                            effect_type="item_take_v1",
                            transition=outcome.transition,
                            policy=policy.record(),
                            expected_no_holder=True,
                            reads=reads,
                            attempt_snapshot=attempt._resolution_snapshot(),
                            tick=self.simulation_time.tick,
                        ),
                    )
                    decision = ResolutionDecision(
                        True,
                        "item taken into physical custody",
                        metadata=metadata,
                        world_effects=effects,
                    )
                else:
                    metadata["physical_effect_provenance"] = [
                        {"state_slot_reads": reads[i : i + 32]}
                        for i in range(0, len(reads), 32)
                    ]
                    decision = ResolutionDecision(
                        False, "take preconditions not met", metadata=metadata
                    )
                # Fault only the handoff after genuine public typed adjudication.
                if omit_context:
                    metadata.pop("take_adjudication_context")
                if malformed is not None:
                    malformed(context)
                if before_return is not None:
                    before_return()
                return decision

        engine = HostEngine()
        engine.policy = h.runtime.event_processor.take_policy
        return engine

    @staticmethod
    def submit_candidate(h, engine, route):
        rt = h.runtime
        attempt = ActionPipeline().create_attempt(
            ActionProposal(
                "generic-host-take",
                h.owner,
                "take",
                ["object:" + h.panel],
                {"method": "take the item", "item_operation": "take"},
            )
        )
        if route == "flow":
            return ActionResolutionFlow(
                engine,
                world_state=rt.context.world_state,
                event_history=rt.context.event_history,
            ).execute_with_result(attempt, simulation_tick=rt.context.clock.capture())
        from cognitive_world.event.factory import EventFactory

        engine.simulation_time = rt.context.clock.capture()
        result = engine.resolve(attempt)
        factory = EventFactory(safety_governance=rt.context.safety_governance)
        return result, factory.create_from_resolution(result)


@pytest.mark.parametrize("route", ["flow", "factory"])
@pytest.mark.parametrize("successful", [True, False])
def test_generic_live_take_missing_context_rejected(route, successful):
    from cognitive_world.items.take import TakePolicy

    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        if not successful:
            rt.event_processor.take_policy = TakePolicy(1, "open", "absent_capability")

        def replace_policy():
            if not successful:
                rt.event_processor.take_policy = TakePolicy(
                    1, "open", "manual_manipulation"
                )

        engine = GenericTakeHostPolicy.engine(
            h, omit_context=True, before_return=replace_policy
        )
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            result, event = GenericTakeHostPolicy.submit_candidate(h, engine, route)
            assert result.confirmed and result.success is successful
            rt.event_processor.process_with_evidence(event, rt.context.world_state)
        assert engine.calls == 1 and take_snapshot(h) == before and not observations(h)
        assert not rt.write_fence.recovery_required
        assert not rt.context.event_history.requires_recovery()
        fresh, event = prepare(h)
        assert fresh.success
        rt.event_processor.dispatch_with_evidence(event)
        assert engine.calls == 1


@pytest.mark.parametrize("structure", ["attached_to", "part_of"])
def test_generic_missing_context_failed_take_structure_change(structure):
    from cognitive_world.core.physical import PhysicalRelation

    h = make_host(False)
    rt = h.runtime
    with rt.write_fence.operation():
        after_change = []

        def change_structure():
            pair = (h.panel, h.target)
            change(h, "relationships", {pair: PhysicalRelation(1, *pair, (structure,))})
            after_change.append(take_snapshot(h))

        engine = GenericTakeHostPolicy.engine(
            h, omit_context=True, before_return=change_structure
        )
        # The trusted system fixture uses the real processor; it is not a
        # production attach/detach feature and does not insert history directly.
        with pytest.raises(PermissionError):
            _, event = GenericTakeHostPolicy.submit_candidate(h, engine, "flow")
            rt.event_processor.process_with_evidence(event, rt.context.world_state)
        assert take_snapshot(h) == after_change[0]
        assert engine.calls == 1 and not observations(h)
        history = rt.context.event_history
        assert not rt.write_fence.recovery_required and not history.requires_recovery()
        assert all(
            e.changes[0] != {"success": False, "outcome": "take preconditions not met"}
            for e in history.get_events()
            if e.type == "resolution"
        )
        current = take_snapshot(h)
        fresh, event = prepare(h)
        assert not fresh.confirmed and event is None
        assert take_snapshot(h) == current


@pytest.mark.parametrize("route", ["flow", "factory"])
@pytest.mark.parametrize(
    "endpoint", ["process", "process_with_evidence", "dispatch_with_evidence"]
)
@pytest.mark.parametrize("successful", [True, False])
@pytest.mark.parametrize("unrelated", [False, True])
def test_generic_context_valid_across_public_entries(
    route, endpoint, successful, unrelated
):
    h = make_host(successful)
    rt = h.runtime
    w = rt.context.world_state
    with rt.write_fence.operation():
        engine = GenericTakeHostPolicy.engine(h)
        result, event = GenericTakeHostPolicy.submit_candidate(h, engine, route)
        assert result.confirmed and result.success is successful
        if unrelated:
            change(h, "facts", {"independent-host-work": True})
        before = take_snapshot(h)
        if endpoint == "dispatch_with_evidence":
            rt.event_processor.dispatch_with_evidence(event)
        else:
            getattr(rt.event_processor, endpoint)(event, w)
        assert len(rt.context.event_history.get_events()) == len(before[3]) + 1
        assert rt.context.event_history.get_persistence_record(event.id) is not None
        if successful:
            assert w.get_location(h.panel) == h.owner
        else:
            assert take_snapshot(h)[:3] == before[:3] and not observations(h)
        assert engine.calls == 1 and not rt.write_fence.recovery_required


@pytest.mark.parametrize("route", ["flow", "factory"])
def test_generic_valid_context_failed_candidate_policy_becomes_stale(route):
    from cognitive_world.items.take import TakePolicy

    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        rt.event_processor.take_policy = TakePolicy(1, "open", "absent_capability")
        engine = GenericTakeHostPolicy.engine(h)
        result, event = GenericTakeHostPolicy.submit_candidate(h, engine, route)
        assert result.confirmed and not result.success
        rt.event_processor.take_policy = TakePolicy(1, "open", "manual_manipulation")
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            rt.event_processor.dispatch_with_evidence(event)
        assert take_snapshot(h) == before and not observations(h) and engine.calls == 1
        assert (
            not rt.write_fence.recovery_required
            and not rt.context.event_history.requires_recovery()
        )
        fresh, event = prepare(h)
        assert fresh.success
        rt.event_processor.dispatch_with_evidence(event)


@pytest.mark.parametrize("structure", ["attached_to", "part_of"])
def test_generic_valid_context_failed_candidate_structure_becomes_stale(structure):
    from cognitive_world.core.physical import PhysicalRelation

    h = make_host(False)
    rt = h.runtime
    with rt.write_fence.operation():
        engine = GenericTakeHostPolicy.engine(h)
        result, event = GenericTakeHostPolicy.submit_candidate(h, engine, "factory")
        assert result.confirmed and not result.success
        pair = (h.panel, h.target)
        change(h, "relationships", {pair: PhysicalRelation(1, *pair, (structure,))})
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            rt.event_processor.process_with_evidence(event, rt.context.world_state)
        assert take_snapshot(h) == before and engine.calls == 1 and not observations(h)
        assert (
            not rt.write_fence.recovery_required
            and not rt.context.event_history.requires_recovery()
        )
        fresh, new_event = prepare(h)
        assert not fresh.confirmed and new_event is None


@pytest.mark.parametrize(
    "defect", ["version", "unknown", "fingerprint", "attempt", "negative"]
)
def test_generic_factory_rejects_invalid_take_context(defect):
    h = make_host()
    rt = h.runtime

    def damage(context):
        if defect == "version":
            context["version"] = 99
        elif defect == "unknown":
            context["unknown"] = True
        elif defect == "fingerprint":
            context["policy_fingerprint"] = "0" * 64
        elif defect == "negative":
            context.pop("expected_no_holder")
        else:
            snapshot = list(context["attempt_snapshot"])
            snapshot[0] = "wrong-attempt"
            context["attempt_snapshot"] = tuple(snapshot)

    with rt.write_fence.operation():
        engine = GenericTakeHostPolicy.engine(h, malformed=damage)
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            GenericTakeHostPolicy.submit_candidate(h, engine, "factory")
        assert take_snapshot(h) == before and engine.calls == 1 and not observations(h)
        assert (
            not rt.write_fence.recovery_required
            and not rt.context.event_history.requires_recovery()
        )
        result, event = prepare(h)
        assert result.success
        rt.event_processor.dispatch_with_evidence(event)


def test_unrelated_live_operation_is_not_classified_by_outcome_or_metadata():
    from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision

    h = make_host()
    rt = h.runtime

    class Unrelated(ResolutionEngine):
        simulation_time = None

        def _adjudicate(self, attempt):
            return ResolutionDecision(
                False,
                "take preconditions not met",
                metadata={
                    "simulation_tick": self.simulation_time.tick,
                    "operation": "take",
                    "action_type": "take",
                },
            )

    with rt.write_fence.operation():
        attempt = ActionPipeline().create_attempt(
            ActionProposal(
                "unrelated-live-test", h.owner, "wait", [], {"method": "wait"}
            )
        )
        flow = ActionResolutionFlow(
            Unrelated(),
            world_state=rt.context.world_state,
            event_history=rt.context.event_history,
        )
        _, event = flow.execute_with_result(
            attempt, simulation_tick=rt.context.clock.capture()
        )
        assert "take_adjudication_context" not in event.metadata
        before = take_snapshot(h)
        rt.event_processor.dispatch_with_evidence(event)
        assert take_snapshot(h)[:3] == before[:3]
        assert len(rt.context.event_history.get_events()) == len(before[3]) + 1
        assert not observations(h)


def test_historical_resolution_is_evidence_not_new_apply_authority(monkeypatch):
    from cognitive_world.event.persistence import verify_and_restore_event_records

    h = make_host()
    rt = h.runtime
    codec = rt.event_processor.persistence_codec
    with rt.write_fence.operation():
        _, event = prepare(h)
        rt.event_processor.dispatch_with_evidence(event)
    records = rt.context.event_history.export_persisted_records()
    events, _, _ = verify_and_restore_event_records(
        records,
        codec=codec,
        trust=h.trust,
        expected_timeline_id=rt.context.event_history.timeline_id,
    )
    historical = events[-1]
    assert historical.has_trusted_source("resolution")
    assert historical._trusted_live_resolution_origin() is None
    assert codec.dumps(historical) == records[-1].event_payload
    assert event._trusted_live_resolution_origin() is not None
    assert codec.dumps(event) == records[-1].event_payload
    other = make_host()
    before = take_snapshot(other)
    with (
        other.runtime.write_fence.operation(),
        pytest.raises(PermissionError, match="historical Resolution"),
    ):
        other.runtime.event_processor.dispatch_with_evidence(historical)
    assert take_snapshot(other) == before and not observations(other)
    assert not other.runtime.write_fence.recovery_required
    assert not other.runtime.context.event_history.requires_recovery()
    # Decode a separate historical copy: do not reuse the other Runtime's permit.
    events, _, _ = verify_and_restore_event_records(
        records,
        codec=codec,
        trust=h.trust,
        expected_timeline_id=rt.context.event_history.timeline_id,
    )
    before = take_snapshot(h)

    def forbid_apply(*args):
        pytest.fail("historical delivery must not reapply acquisition")

    monkeypatch.setattr(rt.context.world_state, "apply_event", forbid_apply)
    with rt.write_fence.operation():
        rt.event_processor.dispatch_with_evidence(events[-1])
    assert take_snapshot(h) == before and len(observations(h)) == 1
    first = consume(h)
    assert "percept:" + observations(h)[0].observation_id in first.percept_ids
    assert not consume(h).percept_ids


def test_generic_noncanonical_take_identity_cannot_be_erased():
    from enum import Enum
    from cognitive_world.items.take import TakePolicy, is_registered_take_operation
    from cognitive_world.event.factory import EventFactory

    class HostOperation(str, Enum):
        TAKE = "take"

    h = make_host()
    rt = h.runtime
    with rt.write_fence.operation():
        rt.event_processor.take_policy = TakePolicy(1, "open", "absent_capability")
        engine = GenericTakeHostPolicy.engine(h, omit_context=True)
        engine.simulation_time = rt.context.clock.capture()
        attempt = ActionPipeline().create_attempt(
            ActionProposal(
                "noncanonical-host-operation",
                h.owner,
                "take",
                ["object:" + h.panel],
                {"method": "take the item", "item_operation": HostOperation.TAKE},
            )
        )
        assert is_registered_take_operation(
            attempt.action_type, attempt.parameters["item_operation"]
        )
        result = engine.resolve(attempt)
        before = take_snapshot(h)
        with pytest.raises(PermissionError):
            EventFactory(
                safety_governance=rt.context.safety_governance
            ).create_from_resolution(result)
        assert take_snapshot(h) == before and not observations(h) and engine.calls == 1
        assert (
            not rt.write_fence.recovery_required
            and not rt.context.event_history.requires_recovery()
        )
        valid, event = prepare(h)
        assert valid.confirmed and not valid.success
        rt.event_processor.dispatch_with_evidence(event)
