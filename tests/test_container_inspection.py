"""Real processor -> private delivery -> ordinary L1, including hostile inputs."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.core.entity import Entity
from cognitive_world.core.physical import PhysicalRelation
from cognitive_world.core.update import WorldUpdate
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.observation import Observation, ObservationStore
from cognitive_world.observation.container_inspection import ContainerInspectionAuthority, capture
from cognitive_world.observation.generator import ObservationGenerator
from test_governed_relationship import setup, prepare, request


class Policy:
    policy_id, policy_version = "test-direct-inspection", "1"

    def evaluate(self, state):
        if state["actor"] != "a":
            return False
        return tuple(i for i in state["direct"] if i == "x")


def scene():
    w, p, _, relation = setup()
    w.load_entity(Entity("a", "character", sensory_capabilities=("sight",),
                         physical_capabilities=("manual_manipulation",)))
    w.load_entity(Entity("other", "character", sensory_capabilities=("sight",)))
    w.load_location("other", "room")
    w.load_entity(Entity("x", "object", owner_id="d", attributes={"secret": "not disclosed"}))
    w.load_entity(Entity("hidden", "object"))
    w.load_entity(Entity("bottle", "object", physical_capabilities=("container",)))
    w.load_entity(Entity("nested", "object"))
    w.load_entity(Entity("extra", "object"))
    w.load_location("extra", "room")
    for item, parent in (("x", "bag"), ("hidden", "bag"), ("bottle", "bag"), ("nested", "bottle")):
        w.load_location(item, parent)
        w.load_relationship(PhysicalRelation(2, item, parent, ("contained_in",)))
    p.agent_registry, p.observation_store = AgentRegistry(), ObservationStore()
    for owner in ("a", "other"):
        p.agent_registry.register(RuntimeAgent(owner))
    auth = ContainerInspectionAuthority(p, Policy())
    p.container_inspection_authority = auth
    return w, p, relation, auth


def inspect(p, auth, ident="inspect", actor="a", container="bag", deliver=True):
    e = auth.create_event(actor, container, event_id=ident)
    evidence = (p.dispatch_with_evidence(e) if deliver else p.process_with_evidence(e, p.world_state))
    return e, evidence


def consumer(p):
    runtime = CognitiveRuntime()
    runtime._bind_observation_history(p.event_history, codec=p.persistence_codec, trust=p.persistence_trust)
    return runtime


def test_creation_delivery_and_real_agent_turn_consumption_are_independent():
    w, p, _, auth = scene()
    before = deepcopy((dict(w.entities), dict(w.locations), dict(w.relationships)))
    cognition, memory = CognitionContainer(), MemoryStore()
    runtime = consumer(p)
    turn = AgentTurn(cognitive_runtime=runtime, write_fence=p.write_fence)
    ctx = CognitionContext.from_character(Character("a", "a", ""), cognition, memory,
                                         observation_store=p.observation_store)
    with p.write_fence.operation():
        e = auth.create_event("a", "bag", event_id="inspect")
        assert p.observation_store.all() == () and not p.event_history.get_events()
        p.process_with_evidence(e, w)
        assert p.observation_store.all() == ()
        empty, _ = turn.prepare_decision_context(RuntimeAgent("a"), ctx)
        assert not empty.cognition_state.percepts
        p.dispatch_with_evidence(e)
        observation, = p.observation_store.get_by_observer("a")
        assert not runtime.has_consumed_observation("a", observation, source_event_id=e.id)
        assert p.observation_store.get_by_observer("other") == ()
        decision, _ = turn.prepare_decision_context(RuntimeAgent("a"), ctx)
        assert len(decision.cognition_state.percepts) == 1
        assert runtime.has_consumed_observation("a", observation, source_event_id=e.id)
        fact = decision.cognition_state.percepts[0].content
        assert (fact.subject_ref, fact.predicate, fact.value) == ("x", "directly_contained_in", "bag")
        assert "secret" not in repr(fact) and "nested" not in repr(fact) and "owner" not in repr(fact)
        p.dispatch_with_evidence(e)
        again, _ = turn.prepare_decision_context(RuntimeAgent("a"), ctx)
        assert not again.cognition_state.percept_ids
        assert len(p.observation_store.all()) == 1 and len(p.event_history.get_events()) == 1
    assert (w.entities, w.locations, w.relationships) == before
    assert not memory.get_all_memories() and not cognition.beliefs


@pytest.mark.parametrize("defect", ["none", "deny", "exception", "bool", "nested", "unknown", "duplicates", "bystander"])
def test_default_deny_and_policy_cannot_select_non_direct_or_fake_results(defect):
    w, p, _, auth = scene()
    if defect == "none": auth.policy = None
    elif defect != "bystander":
        def evaluate(state):
            if defect == "exception": raise RuntimeError("policy down")
            return {"deny": False, "bool": True, "nested": ("nested",), "unknown": ("fake",),
                    "duplicates": ("x", "x")}.get(defect)
        auth.policy.evaluate = evaluate
    with p.write_fence.operation(), pytest.raises(PermissionError):
        auth.create_event("other" if defect == "bystander" else "a", "bag", event_id="denied")
    assert not p.event_history.get_events() and not p.observation_store.all()


@pytest.mark.parametrize("field", ["actor", "container", "selected", "token", "signature", "event_id"])
def test_reconstructed_system_event_cannot_replace_signed_binding(field):
    w, p, _, auth = scene()
    with p.write_fence.operation():
        e = auth.create_event("a", "bag", event_id="inspect")
        grant = deepcopy(e.changes[0])
        if field in {"actor", "container"}: grant["body"]["capture"][field] = "other"
        elif field == "selected": grant["body"][field] = ("hidden",)
        elif field == "signature": grant[field] = "0" * 64
        else: grant["body"][field] = "0" * 48
        fake = SystemEventFactory().create(event_id=e.id, event_type=e.type, timestamp="",
                simulation_tick=0, participants=e.participants, changes=[grant])
        with pytest.raises(PermissionError): p.dispatch_with_evidence(fake)
    assert not p.event_history.get_events() and not p.write_fence.recovery_required


@pytest.mark.parametrize("defect", ["revoke", "policy", "tick", "timeline", "generation", "new_operation"])
def test_pending_grant_requires_original_live_scope(defect):
    w, p, _, auth = scene()
    with p.write_fence.operation():
        e = auth.create_event("a", "bag", event_id="pending")
        if defect == "revoke": auth.revoke(e)
        elif defect == "policy": auth.policy = Policy()
        elif defect == "tick": p.simulation_clock.advance(1)
        elif defect == "timeline": p.event_history.timeline_id = "sibling"
        if defect not in {"generation", "new_operation"}:
            with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
    if defect in {"generation", "new_operation"}:
        if defect == "generation":
            p.write_fence.freeze_and_advance(); p.write_fence.unfreeze()
        with p.write_fence.operation(), pytest.raises(PermissionError): p.dispatch_with_evidence(e)
    assert not p.event_history.get_events() and not p.observation_store.all()


@pytest.mark.parametrize("mutation", ["release", "aba", "container_move", "owner", "nested_move", "add"])
def test_pending_inspection_is_invalidated_by_physical_or_provenance_change(mutation):
    w, p, relation, auth = scene()
    w.load_entity(Entity("room2", "location"))
    with p.write_fence.operation():
        e = auth.create_event("a", "bag", event_id="pending")
        if mutation in {"release", "aba"}:
            r, _ = prepare(p, relation, request("release", target="x", parent="bag", ident="release"))
            p.dispatch_with_evidence(r)
            if mutation == "aba":
                r, _ = prepare(p, relation, request("contain", target="x", parent="bag", ident="return"))
                p.dispatch_with_evidence(r)
        elif mutation == "owner":
            r, _ = prepare(p, relation, request("transfer", target="x", old_owner="d", new_owner="a"))
            p.dispatch_with_evidence(r)
        elif mutation == "nested_move":
            r, _ = prepare(p, relation, request("release", target="bottle", parent="bag"))
            p.dispatch_with_evidence(r)
        elif mutation == "add":
            r, _ = prepare(p, relation, request("contain", target="extra", parent="bag"))
            p.dispatch_with_evidence(r)
        else:
            class Move(EventHandler):
                def handle(self, event): return WorldUpdate("locations", "update", {"bag": "room2"})
            p.register_handler("move", Move())
            p.dispatch_with_evidence(SystemEventFactory().create(event_id="move", event_type="move", timestamp="", simulation_tick=0))
        with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
    assert not p.observation_store.all() and not p.event_history.get_event(e.id)


def test_old_delivered_observation_is_consumable_history_after_content_release():
    w, p, relation, auth = scene()
    with p.write_fence.operation():
        e, evidence = inspect(p, auth)
        observation, = p.observation_store.all()
        r, _ = prepare(p, relation, request("release", target="x", parent="bag"))
        p.dispatch_with_evidence(r)
        assert w.get_location("x") == "room"
        with pytest.raises(PermissionError): auth.validate(e)
        runtime = consumer(p)
        state = runtime.process("a", [observation])
        assert len(state.percepts) == 1 and state.percepts[0].content == observation.content
        assert p.dispatch_with_evidence(e) == evidence
        assert w.get_location("x") == "room" and len(p.observation_store.all()) == 1


@pytest.mark.parametrize("defect", ["recipient", "id", "fact", "manual", "cross_actor"])
def test_l1_refuses_replaced_or_other_actor_observation(defect):
    _, p, _, auth = scene()
    with p.write_fence.operation():
        inspect(p, auth)
        observation, = p.observation_store.all()
        if defect == "recipient": observation = replace(observation, observer_id="other")
        elif defect == "id": observation = replace(observation, observation_id="fake")
        elif defect == "fact": observation = replace(observation, content=replace(observation.content, subject_ref="hidden"))
        elif defect == "manual": observation = Observation(observation.observation_id, "a", observation.source_event_id, observation.content)
        state = consumer(p).process("other" if defect in {"recipient", "cross_actor"} else "a", [observation])
        assert state.percepts == [] and state.percept_ids == []


def test_delivery_failure_retries_without_world_replay(monkeypatch):
    _, p, _, auth = scene()
    with p.write_fence.operation():
        e = auth.create_event("a", "bag", event_id="inspect")
        add = p.observation_store.add
        monkeypatch.setattr(p.observation_store, "add", lambda _: (_ for _ in ()).throw(OSError("offline")))
        with pytest.raises(RuntimeError, match="delivery failed"): p.dispatch_with_evidence(e)
        assert len(p.event_history.get_events()) == 1 and not p.observation_store.all()
        auth.revoke(e)
        monkeypatch.setattr(p.observation_store, "add", add)
        p.dispatch_with_evidence(e)
        assert len(p.event_history.get_events()) == 1 and len(p.observation_store.all()) == 1


@pytest.mark.parametrize("role", ["container_owner", "container_holder", "content_owner", "content_owner_and_container_holder", "unrelated"])
def test_ownership_or_custody_never_substitutes_for_installed_disclosure_policy(role):
    w, p, _, auth = scene()
    # These are distinct legitimate initial configurations, not runtime patches.
    if role == "container_owner": w.load_entity(replace(w.get_entity("bag"), owner_id="other"))
    elif role == "container_holder":
        w.load_location("bag", "other")
        w.load_relationship(PhysicalRelation(1, "bag", "other", ("held_by",)))
    elif role == "content_owner": w.load_entity(replace(w.get_entity("x"), owner_id="other"))
    elif role == "content_owner_and_container_holder":
        # A contained item's holder is not conflated with its owner. Here the
        # actor holds the container, not the independently identified contents.
        w.load_location("bag", "other")
        w.load_relationship(PhysicalRelation(1, "bag", "other", ("held_by",)))
        w.load_entity(replace(w.get_entity("x"), owner_id="other"))
    with p.write_fence.operation():
        with pytest.raises(PermissionError): auth.create_event("other", "bag", event_id="denied")
        inspect(p, auth)
    assert len(p.observation_store.get_by_observer("a")) == 1
    assert not p.observation_store.get_by_observer("other")


def test_authorized_outer_inspection_never_recursively_discloses_nested_content():
    _, p, _, auth = scene()
    auth.policy.evaluate = lambda c: c["direct"]
    with p.write_fence.operation(): inspect(p, auth)
    facts = [o.content for o in p.observation_store.all()]
    assert {f.subject_ref for f in facts} == {"x", "hidden", "bottle"}
    assert all(f.value == "bag" for f in facts) and all(f.subject_ref != "nested" for f in facts)


def test_unrelated_handler_cannot_manufacture_container_fact():
    from cognitive_world.observation.observable import ObservableFactDraft
    _, p, _, _ = scene()
    class Forge(EventHandler):
        def handle(self, event): return WorldUpdate("environment", "update", {})
        def observable_facts(self, event, update):
            return (ObservableFactDraft("container_content", "directly_contained_in", "bag", "x", "room"),)
    p.register_handler("fake", Forge())
    with p.write_fence.operation(), pytest.raises(PermissionError):
        p.dispatch_with_evidence(SystemEventFactory().create(event_id="fake", event_type="fake", timestamp="", simulation_tick=0))
    assert not p.event_history.get_events() and not p.write_fence.recovery_required


def test_checkpoint_cold_restore_and_real_siblings_preserve_history_not_authority(tmp_path, monkeypatch):
    from test_runtime_content_commit_boundary import _signed_runtime, _install
    from test_item_take import save
    from test_runtime_reconstruction import _dependency_manifest
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    from cognitive_world.runtime.recovery import RestoreCoordinator
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_MEMORY_TYPE, verify_nonverbal_proof
    import cognitive_world.event.processor as processing

    runtime, cognition, memory, installer = _signed_runtime()
    initial, _, _, _ = scene()
    w, p = runtime.context.world_state, runtime.event_processor
    for entity in initial.entities.values(): w.load_entity(entity)
    for key, value in initial.locations.items(): w.load_location(key, value)
    for relation in initial.relationships.values(): w.load_relationship(relation)
    for owner in ("a", "other"): p.agent_registry.register(RuntimeAgent(owner, owner))
    authority = ContainerInspectionAuthority(p, Policy()); p.container_inspection_authority = authority
    with runtime.write_fence.operation():
        from cognitive_world.cognition.personality import Personality
        for owner in ("a", "other"): cognition.add_personality(Personality(owner))
        _install(installer)
        e, _ = inspect(p, authority)
        observation, = p.observation_store.get_by_observer("a")
        assert not any(m.type == NONVERBAL_PROOF_MEMORY_TYPE for m in memory.get_all_memories())
        turn = runtime.agent_action_loop.agent_turn
        actor = p.agent_registry.get("a")
        ctx = runtime.cognition_context_provider(actor)
        turn.prepare_decision_context(actor, ctx)
        records = tuple(m.content for m in memory.get_all_memories() if m.type == NONVERBAL_PROOF_MEMORY_TYPE and m.owner_id == "a")
        assert len(records) == 1 and records[0].observation_id == observation.observation_id
        turn.prepare_decision_context(actor, ctx)
        assert len([m for m in memory.get_all_memories() if m.type == NONVERBAL_PROOF_MEMORY_TYPE and m.owner_id == "a"]) == 1
        # Leave another uncommitted grant in the original host; no restore may execute it.
        pending = authority.create_event("a", "bag", event_id="pending")
    manager, saved = save(SimpleNamespace(runtime=runtime, cognition=cognition, memory=memory, trust=p.persistence_trust), tmp_path/"saves")
    signed = p.event_history.export_persisted_records()
    class Assembler:
        def assemble(self, inputs):
            self.runtime, self.cognition, self.memory, _ = _signed_runtime(p.persistence_trust, inputs)
            return self.runtime
    assembled = Assembler()
    with monkeypatch.context() as guard:
        guard.setattr(processing, "make_persisted_event_record", lambda *a, **kw: pytest.fail("restore must not re-sign"))
        ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id, timeline_id=saved.timeline_id,
            assembler=assembled, dependencies=_dependency_manifest()))
    restored = assembled.runtime
    assert restored.event_processor.container_inspection_authority is None
    assert restored.context.observation_store.all() == ()
    assert restored.context.event_history.export_persisted_records() == signed
    from cognitive_world.observation.historical_rules import HISTORICAL_OBSERVATION_RULES
    history = restored.context.event_history
    historical = HISTORICAL_OBSERVATION_RULES.for_source(history.get_event(e.id), history.get_processing_evidence(e.id)).issue(
        history.get_event(e.id), history.get_processing_evidence(e.id), "a", observation.content.fact_id)
    assert historical._snapshot() == observation._snapshot()
    assert historical.trusted_source_runtime_binding() is None
    assert restored.context.observation_store.all() == ()
    assert len([m for m in assembled.memory.get_all_memories() if m.type == NONVERBAL_PROOF_MEMORY_TYPE and m.owner_id == "a"]) == 1
    assert not restored.agent_action_loop.agent_turn.cognitive_runtime.has_consumed_observation("a", observation, source_event_id=e.id)
    with restored.write_fence.operation(), pytest.raises(PermissionError): restored.event_processor.dispatch_with_evidence(pending)
    children = []
    for name in ("inspection-child", "inspection-sibling"):
        parent = Assembler()
        slot = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id, timeline_id=saved.timeline_id,
                assembler=parent, dependencies=_dependency_manifest()))
        child = Assembler()
        children.append((RestoreCoordinator(slot).activate(manager.stage_restore(saved.save_id,
            timeline_id=saved.timeline_id, active_runtime=slot.current, assembler=child,
            dependencies=_dependency_manifest(), new_timeline_id=name)), child))
    for branch, assembly in children:
        assert branch.event_processor.container_inspection_authority is None
        assert branch.context.observation_store.all() == ()
        verify_nonverbal_proof(records[0], history=branch.context.event_history, trust=p.persistence_trust,
                              checkpoint_timeline_id=branch.context.event_history.timeline_id,
                              checkpoint_tick=branch.context.clock.current_time)
    child, _ = children[0]; sibling, _ = children[1]
    new_authority = ContainerInspectionAuthority(child.event_processor, Policy())
    child.event_processor.container_inspection_authority = new_authority
    with child.write_fence.operation():
        ce, _ = inspect(child.event_processor, new_authority, ident="child-inspect")
    assert len(child.context.observation_store.get_by_observer("a")) == 1
    assert sibling.context.observation_store.all() == ()
    with sibling.write_fence.operation(), pytest.raises(PermissionError): sibling.event_processor.dispatch_with_evidence(ce)


@pytest.mark.parametrize("defect", ["container", "missing", "wrong_location", "second_parent", "no_sight", "no_registry"])
def test_invalid_current_state_cannot_become_inspection_evidence(defect):
    w, p, _, auth = scene()
    with pytest.raises((PermissionError, ValueError)):
        if defect == "container": w.load_entity(replace(w.get_entity("bag"), physical_capabilities=()))
        elif defect == "missing":
            w.load_relationship(PhysicalRelation(2, "absent", "bag", ("contained_in",)))
        elif defect == "wrong_location": w.load_location("x", "room")
        elif defect == "second_parent":
            w.load_relationship(PhysicalRelation(2, "x", "bottle", ("contained_in",)))
        elif defect == "no_sight": w.load_entity(replace(w.get_entity("a"), sensory_capabilities=()))
        else: p.agent_registry.remove("a")
        with p.write_fence.operation(): auth.create_event("a", "bag", event_id="invalid")
    assert not p.event_history.get_events() and not p.observation_store.all()


def test_content_budget_exhaustion_is_not_partial_success():
    w, p, _, auth = scene()
    for i in range(30):
        identity = "extra-" + str(i)
        w.load_entity(Entity(identity, "object"))
        w.load_location(identity, "bag")
        w.load_relationship(PhysicalRelation(2, identity, "bag", ("contained_in",)))
    with p.write_fence.operation(), pytest.raises(PermissionError, match="budget"):
        auth.create_event("a", "bag", event_id="over-budget")
    assert not p.event_history.get_events() and not p.observation_store.all()


def test_inspection_application_failure_keeps_recovery_required(monkeypatch):
    w, p, _, auth = scene()
    before = (dict(w.entities), dict(w.locations), dict(w.relationships))
    def uncertain(*args, **kwargs): raise OSError("uncertain write boundary")
    monkeypatch.setattr(w, "apply_event", uncertain)
    with p.write_fence.operation():
        e = auth.create_event("a", "bag", event_id="uncertain")
        with pytest.raises(OSError): p.dispatch_with_evidence(e)
    assert p.write_fence.recovery_required and p.event_history.requires_recovery()
    assert not p.observation_store.all() and (w.entities, w.locations, w.relationships) == before
    with pytest.raises((PermissionError, RuntimeError)): p.dispatch_with_evidence(e)


def test_old_inspection_does_not_supply_take_or_relationship_authority():
    w, p, relation, auth = scene()
    with p.write_fence.operation():
        e, _ = inspect(p, auth)
        observation, = p.observation_store.all()
        runtime = consumer(p)
        assert runtime.process("a", [observation]).percept_ids
        relation.policy = None
        with pytest.raises(PermissionError): relation.authorize(request("release", target="x", parent="bag"))
    assert w.get_location("x") == "bag" and w.get_entity("x").owner_id == "d"


def test_negative_relationship_aba_invalidates_grant_without_location_write():
    from cognitive_world.core.world_state import WorldStateSlot
    w, p, _, auth = scene()
    class Relations(EventHandler):
        def handle(self, event): return WorldUpdate("relationships", "set", event.changes[0])
    p.register_handler("relations", Relations())
    with p.write_fence.operation():
        pending = auth.create_event("a", "bag", event_id="pending")
        before = w.read_state_slot(WorldStateSlot("locations", "x"), event_history=p.event_history).to_record()
        relations = dict(w.relationships)
        added = {**relations, ("x", "other"): PhysicalRelation(1, "x", "other", ("controls",))}
        for ident, payload in (("add-control", added), ("remove-control", relations)):
            p.dispatch_with_evidence(SystemEventFactory().create(event_id=ident, event_type="relations",
                timestamp="", simulation_tick=0, changes=[payload]))
        assert dict(w.relationships) == relations
        assert w.read_state_slot(WorldStateSlot("locations", "x"), event_history=p.event_history).to_record() == before
        with pytest.raises(PermissionError): p.dispatch_with_evidence(pending)
    assert not p.observation_store.all()


def test_policy_gets_detached_identity_state_and_timeline_not_world_writer():
    w, p, _, auth = scene()
    seen = []
    def evaluate(c):
        assert c["timeline"] == p.event_history.timeline_id and c["tick"] == 0
        assert next(s for s in c["state"] if s["id"] == "x")["owner"] == "d"
        c["state"][0]["owner"] = "fake"
        seen.append(c)
        return ("x",)
    auth.policy.evaluate = evaluate
    with p.write_fence.operation(): inspect(p, auth)
    assert seen and w.get_entity("x").owner_id == "d" and len(p.observation_store.all()) == 1
