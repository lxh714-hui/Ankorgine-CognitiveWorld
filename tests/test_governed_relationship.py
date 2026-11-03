from copy import deepcopy
from dataclasses import replace

import pytest

from cognitive_world.core.entity import Entity
from cognitive_world.core.physical import PhysicalRelation
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldStateSlot
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event.factory import EventFactory, SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.items.relationship import RelationshipAuthority, RelationshipResolutionEngine
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from test_life_transition import host, prepare as prepare_death


class Allow:
    policy_id = "explicit-test-policy"
    policy_version = "1"
    def evaluate(self, captured): return True


def setup():
    w, p, death = host()
    w.load_entity(Entity("room", "location"))
    w.load_entity(Entity("a", "character", physical_capabilities=("manual_manipulation",)))
    w.load_entity(Entity("bag", "object", physical_capabilities=("container", "detachable")))
    w.load_location("a", "room")
    w.load_location("d", "room")
    w.load_location("bag", "room")
    auth = RelationshipAuthority(p, Allow())
    p.relationship_authority = auth
    return w, p, death, auth


def request(op, target="k", ident="relation", **params):
    return Attempt(ident, "a", "proposal", op, ["object:" + target], params)


def prepare(p, auth, attempt):
    grant = auth.authorize(attempt)
    event = ActionResolutionFlow(RelationshipResolutionEngine(grant),
        EventFactory(relationship_authority=auth)).execute(attempt)
    return event, grant


def snap(w, p):
    return deepcopy((dict(w.entities), dict(w.locations), dict(w.relationships), p.event_history.get_events()))


def ordinary(p, target, payload, operation="update"):
    class Patch(EventHandler):
        def handle(self, event): return WorldUpdate(target, operation, payload)
    p.register_handler("patch", Patch())
    event = SystemEventFactory().create(event_id="patch", event_type="patch", timestamp="", simulation_tick=0)
    return p.dispatch_with_evidence(event)


@pytest.mark.parametrize("case", ["owner", "mixed", "add", "delete", "contain", "identity"])
def test_ordinary_worldupdate_cannot_bypass_actual_write_barrier(case):
    w, p, _, _ = setup()
    before = snap(w, p)
    with p.write_fence.operation(), pytest.raises(PermissionError):
        if case in {"owner", "mixed"}:
            replacement = replace(w.get_entity("k"), owner_id="a")
            if case == "mixed": replacement = replace(replacement, state={"extra": True})
            ordinary(p, "entities", {"k": replacement})
        elif case == "identity":
            ordinary(p, "entities", {"k": replace(w.get_entity("k"), id="bag")})
        elif case == "add":
            ordinary(p, "relationships", {("bag", "a"): PhysicalRelation(1, "bag", "a", ("owned_by",))})
        elif case == "delete":
            ordinary(p, "relationships", {k: v for k,v in w.relationships.items() if "owned_by" not in v.kinds}, "set")
        else:
            ordinary(p, "relationships", {("k", "bag"): PhysicalRelation(2, "k", "bag", ("contained_in",))})
    assert snap(w, p) == before


def test_death_release_contain_release_and_transfer_are_separate_commits():
    w, p, death, auth = setup()
    initial = (w.get_entity("k"), w.locations, w.relationships)
    with p.write_fence.operation():
        e, _ = prepare_death(p, death)
        p.dispatch_with_evidence(e)
        assert (w.get_entity("k"), w.locations, w.relationships) == initial
        e, _ = prepare(p, auth, request("release", parent="b"))
        evidence = p.dispatch_with_evidence(e)
        assert p.dispatch_with_evidence(e) == evidence
    assert w.get_location("k") == "room" and w.get_entity("k").owner_id == "d"
    with p.write_fence.operation():
        e, _ = prepare(p, auth, request("contain", ident="contain", parent="bag"))
        p.dispatch_with_evidence(e)
    assert w.get_location("k") == "bag"
    with p.write_fence.operation():
        e, _ = prepare(p, auth, request("release", ident="release2", parent="bag"))
        p.dispatch_with_evidence(e)
    spatial = (w.locations, tuple((k,r) for k,r in w.relationships.items() if "owned_by" not in r.kinds))
    with p.write_fence.operation():
        e, _ = prepare(p, auth, request("transfer", ident="transfer", old_owner="d", new_owner="a"))
        p.dispatch_with_evidence(e)
    assert w.get_entity("k").owner_id == "a"
    assert w.relationships[("k", "a")].kinds == ("owned_by",)
    assert ("k", "d") not in w.relationships
    assert w.locations == spatial[0]
    assert tuple((k,r) for k,r in w.relationships.items() if "owned_by" not in r.kinds) == spatial[1]


@pytest.mark.parametrize("defect", ["signature", "item", "owner", "new_owner", "timeline", "revoke", "tick"])
def test_mutated_or_revoked_grant_never_changes_world(defect):
    w, p, _, auth = setup()
    with p.write_fence.operation():
        req = request("transfer", old_owner="d", new_owner="a")
        grant = auth.authorize(req)
        if defect == "signature": grant["signature"] = "forged"
        elif defect == "item": grant["body"]["attempt"][4][0] = "object:bag"
        elif defect in {"owner", "new_owner"}:
            grant["body"]["attempt"][5]["old_owner" if defect == "owner" else "new_owner"] = "b"
        elif defect == "timeline": grant["body"]["timeline"] = "sibling"
        elif defect == "revoke": auth.revoke(grant)
        elif defect == "tick": p.simulation_clock.advance(1)
        before = snap(w, p)
        with pytest.raises((PermissionError, ValueError)):
            e = ActionResolutionFlow(RelationshipResolutionEngine(grant), EventFactory(relationship_authority=auth)).execute(req)
            p.dispatch_with_evidence(e)
        assert snap(w,p) == before


@pytest.mark.parametrize("policy", [None, False, "raise"])
def test_missing_declining_or_raising_policy_has_no_state_effect(policy):
    w, p, _, auth = setup()
    class Policy(Allow):
        def evaluate(self, captured):
            if policy == "raise": raise RuntimeError("policy fault")
            return False
    auth.policy = None if policy is None else Policy()
    before = snap(w,p)
    with p.write_fence.operation(), pytest.raises((PermissionError, RuntimeError)):
        auth.authorize(request("transfer", old_owner="d", new_owner="a"))
    assert snap(w,p) == before


def test_release_then_real_take_then_transfer_keeps_custody_independent():
    from cognitive_world.agent.registry import AgentRegistry
    from cognitive_world.agent.runtime_agent import RuntimeAgent
    from cognitive_world.core.physical import PhysicalPropertyDefinition, PhysicalValue, PhysicalStateSet
    from cognitive_world.items.take import ItemTakeResolutionEngine, TakePolicy
    w, p, death, auth = setup()
    k = w.get_entity("k")
    w.load_entity(replace(k, state={"physical": PhysicalStateSet(1, "k", (
        PhysicalValue(PhysicalPropertyDefinition(1, "takeable", "boolean", None), True),))}))
    p.agent_registry = AgentRegistry()
    p.agent_registry.register(RuntimeAgent("a"))
    p.take_policy = TakePolicy(1, "takeable", "manual_manipulation")
    with p.write_fence.operation():
        died, _ = prepare_death(p, death)
        p.dispatch_with_evidence(died)
        assert w.get_location("k") == "b" and w.get_entity("k").owner_id == "d"
        released, _ = prepare(p, auth, request("release", parent="b"))
        p.dispatch_with_evidence(released)
        take = Attempt("take-after-death", "a", "take-proposal", "take", ["object:k"], {"item_operation": "take"})
        flow = ActionResolutionFlow(ItemTakeResolutionEngine(w, p.event_history, p.agent_registry, p.take_policy),
                                    world_state=w, event_history=p.event_history)
        result, acquired = flow.execute_with_result(take, simulation_tick=p.simulation_clock.capture())
        assert result.success
        p.dispatch_with_evidence(acquired)
        assert w.get_entity("k").owner_id == "d" and w.get_location("k") == "a"
        transfer, _ = prepare(p, auth, request("transfer", ident="title", old_owner="d", new_owner="a"))
        p.dispatch_with_evidence(transfer)
    assert w.get_entity("k").owner_id == "a" and w.get_location("k") == "a"
    assert set(w.relationships[("k", "a")].kinds) == {"held_by", "owned_by"}


def test_owner_aba_and_relationship_aba_reject_pending_grants():
    w, p, _, auth = setup()
    with p.write_fence.operation():
        stale, _ = prepare(p, auth, request("transfer", ident="stale", old_owner="d", new_owner="a"))
        for ident, old, new in (("forward", "d", "a"), ("back", "a", "d")):
            e, _ = prepare(p, auth, request("transfer", ident=ident, old_owner=old, new_owner=new))
            p.dispatch_with_evidence(e)
        before = snap(w,p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(stale)
        assert snap(w,p) == before and not p.write_fence.recovery_required
        e, _ = prepare(p, auth, request("release", ident="release", parent="b"))
        p.dispatch_with_evidence(e)
        e, _ = prepare(p, auth, request("contain", ident="in", parent="bag"))
        p.dispatch_with_evidence(e)
        stale, _ = prepare(p, auth, request("release", ident="old-release", parent="bag"))
        for ident, op in (("out", "release"), ("back-in", "contain")):
            e, _ = prepare(p, auth, request(op, ident=ident, parent="bag"))
            p.dispatch_with_evidence(e)
        before = snap(w,p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(stale)
        assert snap(w,p) == before


def test_absent_relation_aba_with_unchanged_location_invalidates_grant():
    w,p,_,auth=setup()
    w.load_entity(replace(w.get_entity("room"),physical_capabilities=("container",)))
    with p.write_fence.operation():
        released,_=prepare(p,auth,request("release",ident="to-room",parent="b"))
        p.dispatch_with_evidence(released)
        pending,_=prepare(p,auth,request("contain",ident="pending-room",parent="room"))
        location_before=w.read_state_slot(WorldStateSlot("locations","k"),event_history=p.event_history).to_record()
        for ident,op in (("enter-room","contain"),("leave-room","release")):
            e,_=prepare(p,auth,request(op,ident=ident,parent="room"));p.dispatch_with_evidence(e)
        assert w.get_location("k")=="room" and ("k","room") not in w.relationships
        assert w.read_state_slot(WorldStateSlot("locations","k"),event_history=p.event_history).to_record()==location_before
        before=snap(w,p)
        with pytest.raises(PermissionError):p.dispatch_with_evidence(pending)
        assert snap(w,p)==before and not p.write_fence.recovery_required


@pytest.mark.parametrize("op,parent,target", [("release", "bag", "k"), ("release", "b", "bag"),
                                               ("detach", "b", "k")])
def test_exact_relationship_and_item_are_required(op, parent, target):
    w,p,_,auth = setup()
    with p.write_fence.operation(), pytest.raises(PermissionError):
        auth.authorize(request(op, target=target, parent=parent))


def test_detach_is_exact_and_never_removes_part_of():
    w,p,_,auth = setup()
    w.load_entity(Entity("cap", "object", owner_id="d", physical_capabilities=("detachable",)))
    w.load_location("cap", "bag")
    w.load_relationship(PhysicalRelation(1, "cap", "bag", ("attached_to", "controls")))
    with p.write_fence.operation():
        e,_ = prepare(p,auth,request("detach", target="cap", parent="bag"))
        p.dispatch_with_evidence(e)
    assert w.get_location("cap") == "room" and w.get_entity("cap").owner_id == "d"
    assert w.relationships[("cap", "bag")].kinds == ("controls",)
    w,p,_,auth = setup()
    w.load_entity(Entity("cap", "object", physical_capabilities=("detachable",)))
    w.load_location("cap", "bag")
    w.load_relationship(PhysicalRelation(1,"cap","bag",("attached_to","part_of")))
    with p.write_fence.operation(), pytest.raises(PermissionError):
        auth.authorize(request("detach", target="cap", parent="bag"))


def test_take_container_moves_effective_contents_not_their_title_or_direct_links():
    from cognitive_world.agent.registry import AgentRegistry
    from cognitive_world.agent.runtime_agent import RuntimeAgent
    from cognitive_world.core.physical import PhysicalStateSet, PhysicalPropertyDefinition, PhysicalValue
    from cognitive_world.items.take import ItemTakeResolutionEngine, TakePolicy
    from cognitive_world.items.containment import effective_location
    w,p,_,auth=setup()
    w.load_entity(replace(w.get_entity("bag"),state={"physical": PhysicalStateSet(1,"bag",(
        PhysicalValue(PhysicalPropertyDefinition(1,"takeable","boolean",None),True),))}))
    p.agent_registry=AgentRegistry(); p.agent_registry.register(RuntimeAgent("a"))
    p.take_policy=TakePolicy(1,"takeable","manual_manipulation")
    with p.write_fence.operation():
        e,_=prepare(p,auth,request("release",parent="b"));p.dispatch_with_evidence(e)
        e,_=prepare(p,auth,request("contain",ident="in-bag",parent="bag"));p.dispatch_with_evidence(e)
        req=Attempt("take-container","a","proposal","take",["object:bag"],{"item_operation":"take"})
        flow=ActionResolutionFlow(ItemTakeResolutionEngine(w,p.event_history,p.agent_registry,p.take_policy),
                                  world_state=w,event_history=p.event_history)
        result,e=flow.execute_with_result(req,simulation_tick=p.simulation_clock.capture())
        assert result.success
        p.dispatch_with_evidence(e)
    assert w.get_location("bag")=="a" and w.get_location("k")=="bag"
    assert effective_location(w,"k")=="room" and w.get_entity("k").owner_id=="d"
    assert ("k","a") not in w.relationships


def test_old_permit_policy_replacement_and_foreign_processor_reject():
    w,p,_,auth = setup()
    with p.write_fence.operation():
        e, grant = prepare(p,auth,request("transfer", old_owner="d",new_owner="a"))
    p.write_fence.freeze_and_advance(); p.write_fence.unfreeze()
    before = snap(w,p)
    with p.write_fence.operation(), pytest.raises(PermissionError): p.dispatch_with_evidence(e)
    assert snap(w,p) == before
    w,p,_,auth = setup()
    with p.write_fence.operation():
        e,_ = prepare(p,auth,request("transfer",old_owner="d",new_owner="a"))
        auth.policy = Allow()
        with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
    w2,p2,_,a2 = setup()
    p2.event_history.timeline_id = "sibling"
    with p2.write_fence.operation(), pytest.raises(PermissionError):
        ActionResolutionFlow(RelationshipResolutionEngine(grant), EventFactory(relationship_authority=a2)).execute(
            request("transfer",old_owner="d",new_owner="a"))
    assert snap(w2,p2)[3] == ()


def test_old_grant_cannot_be_rebound_to_a_new_operation_in_same_generation():
    w,p,_,auth=setup()
    req=request("transfer",old_owner="d",new_owner="a")
    with p.write_fence.operation(): grant=auth.authorize(req)
    before=snap(w,p)
    with p.write_fence.operation(),pytest.raises(PermissionError,match="candidate is not bound"):
        ActionResolutionFlow(RelationshipResolutionEngine(grant),EventFactory(relationship_authority=auth)).execute(req)
    assert snap(w,p)==before and not p.write_fence.recovery_required


def test_dead_entity_is_same_container_and_policy_can_require_actual_death():
    from cognitive_world.core.life import LifeState
    w,p,death,auth=setup()
    w.load_entity(replace(w.get_entity("b"),physical_capabilities=("container",)))
    w.load_entity(Entity("x","object",owner_id="b"))
    w.load_location("x","b")
    w.load_relationship(PhysicalRelation(2,"x","b",("contained_in","owned_by")))
    class DeadParentPolicy(Allow):
        def evaluate(self,captured):
            parent=captured["attempt"][5].get("parent")
            return any(row["id"]==parent and row["life"]==LifeState(1,"dead") for row in captured["state"])
    auth.policy=DeadParentPolicy()
    with p.write_fence.operation():
        req=request("release",target="x",parent="b")
        with pytest.raises(PermissionError): auth.authorize(req)
        e,_=prepare_death(p,death);p.dispatch_with_evidence(e)
        assert w.get_location("x")=="b" and w.get_entity("x").owner_id=="b"
        assert w.relationships[("x","b")].kinds==("contained_in","owned_by")
        e,_=prepare(p,auth,req);p.dispatch_with_evidence(e)
    assert w.get_entity("b").id=="b" and w.get_location("x")=="room"
    assert w.get_entity("x").owner_id=="b"
    assert w.relationships[("x","b")].kinds==("owned_by",)


def test_processor_rechecks_grant_when_factory_has_already_accepted():
    w,p,_,auth=setup()
    with p.write_fence.operation():
        e,grant=prepare(p,auth,request("transfer",old_owner="d",new_owner="a"))
        auth.revoke(grant)
        before=snap(w,p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
        assert snap(w,p)==before and not p.write_fence.recovery_required


def rejection_snapshot(w, p, event_id):
    """Public observations of this fixture's data, relevant origins and delivery."""
    slots = []
    for identity, entity in w.entities.items():
        slots.extend(WorldStateSlot("entities", identity, (field,))
                     for field in ("id", "type", "owner_id"))
        if "life" in entity.state:
            slots.extend(WorldStateSlot("entities", identity, ("state", "life", field))
                         for field in ("version", "value"))
    slots.extend(WorldStateSlot("locations", identity) for identity in w.locations)
    for pair in w.relationships:
        slots.extend(WorldStateSlot("relationships", pair, (field,))
                     for field in ("version", "source", "target", "kinds"))
    return deepcopy((snap(w, p), dict(w.facts), dict(w.environment),
        tuple(w.read_state_slot(slot, event_history=p.event_history).to_record() for slot in slots),
        p.event_history.get_processing_status(event_id),
        p.event_history.get_processing_evidence(event_id),
        p.event_history.get_persistence_record(event_id),
        () if p.observation_store is None else p.observation_store.all(),
        p.event_history.requires_recovery(), p.write_fence.recovery_required,
        p.event_history.timeline_id, p.write_fence.restore_generation))


def forbid_application_and_delivery(monkeypatch, w, p):
    from cognitive_world.observation.store import ObservationStore
    from cognitive_world.observation.generator import ObservationGenerator
    import cognitive_world.event.processor as processing
    if p.observation_store is None:
        p.observation_store = ObservationStore()
    def forbidden(*args, **kwargs):
        pytest.fail("preflight rejection reached application/evidence/delivery")
    for obj, name in ((w, "apply_event"), (p.event_history, "mark_applying_world_update"),
                      (p.event_history, "append"), (p.event_history, "mark_observations_pending"),
                      (p.observation_store, "add"), (ObservationGenerator, "generate_authorized"),
                      (processing, "_issue_processing_evidence")):
        monkeypatch.setattr(obj, name, forbidden)


@pytest.mark.parametrize("claimed_flag", [False, True])
def test_ordinary_handler_cannot_forge_joint_update_or_claim_authorized_flag(monkeypatch, claimed_flag):
    w,p,_,auth=setup()
    with p.write_fence.operation():
        e,grant=prepare(p,auth,request("transfer",old_owner="d",new_owner="a"))
        class Fake(EventHandler):
            def handle(self,event):
                return WorldUpdate("object_relationship","apply",deepcopy(e.changes[1]),
                                   {"ownership_authorized":True} if claimed_flag else {})
        p.register_handler("fake",Fake())
        bad=SystemEventFactory().create(event_id="fake",event_type="fake",timestamp="",simulation_tick=0)
        before=snap(w,p)
        forbid_application_and_delivery(monkeypatch, w, p)
        failure_before = rejection_snapshot(w, p, bad.id)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(bad)
        assert snap(w,p)==before
        assert rejection_snapshot(w, p, bad.id) == failure_before
        assert p.event_history.get_processing_status(bad.id) is None
        assert not p.event_history.requires_recovery() and not p.write_fence.recovery_required


@pytest.mark.parametrize("defect", ["target", "operation", "payload", "metadata", "extra_relation", "extra_entity"])
def test_relationship_write_mismatch_aborts_before_application(monkeypatch, defect):
    from cognitive_world.items.relationship import current_update
    w,p,_,auth = setup()
    with p.write_fence.operation():
        event,_ = prepare(p,auth,request("release", parent="b"))
        update = current_update(event, p)
        if defect == "target": update.target_id = "facts"
        elif defect == "operation": update.operation = "update"
        elif defect == "payload": update.payload = {}
        elif defect == "metadata": update.metadata["authorized"] = True
        elif defect == "extra_relation":
            update = WorldUpdate("relationships", "update", {("bag","a"):PhysicalRelation(1,"bag","a",("controls",))})
        else:
            update = WorldUpdate("entities", "update", {"bag":replace(w.get_entity("bag"),attributes={"extra":True})})
        class Bad(EventHandler):
            def handle(self, e): return update
        p.register_handler("resolution", Bad())
        forbid_application_and_delivery(monkeypatch, w, p)
        before = rejection_snapshot(w, p, event.id)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(event)
        assert rejection_snapshot(w, p, event.id) == before
        assert p.event_history.get_processing_status(event.id) is None


def test_relationship_final_scope_still_rejects_changed_submission(monkeypatch):
    w,p,_,auth = setup()
    original = w.apply_event
    def changed(event, update):
        update.metadata["authorized"] = True
        return original(event, update)
    monkeypatch.setattr(w, "apply_event", changed)
    with p.write_fence.operation():
        event,_ = prepare(p,auth,request("release", parent="b"))
        before = rejection_snapshot(w, p, event.id)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(event)
    assert snap(w,p) == before[0]
    assert rejection_snapshot(w,p,event.id)[3] == before[3]
    assert p.event_history.get_processing_evidence(event.id) is None
    assert p.event_history.get_event(event.id) is None
    assert p.event_history.requires_recovery() and p.write_fence.recovery_required


def test_valid_transfer_event_cannot_be_used_for_a_mixed_generic_patch():
    w,p,_,auth=setup()
    with p.write_fence.operation():
        e,_=prepare(p,auth,request("transfer",old_owner="d",new_owner="a"))
        class Mixed(EventHandler):
            def handle(self,event):
                return WorldUpdate("entities","update",{
                    "k":replace(w.get_entity("k"),owner_id="a"),
                    "bag":replace(w.get_entity("bag"),owner_id="a")})
        p.register_handler("resolution",Mixed())
        before=snap(w,p)
        with pytest.raises(PermissionError):p.dispatch_with_evidence(e)
        assert snap(w,p)==before


def test_formal_containment_cannot_create_a_cycle_or_second_parent():
    w,p,_,auth=setup()
    w.load_entity(Entity("crate","object",physical_capabilities=("container",)))
    w.load_location("crate","room")
    with p.write_fence.operation():
        e,_=prepare(p,auth,request("contain",target="bag",parent="crate"))
        p.dispatch_with_evidence(e)
        before=snap(w,p)
        with pytest.raises((PermissionError,ValueError)):
            auth.authorize(request("contain",target="crate",parent="bag"))
        with pytest.raises(PermissionError):
            auth.authorize(request("contain",target="bag",parent="b"))
        assert snap(w,p)==before


@pytest.mark.parametrize("defect",["remove","move"])
def test_ordinary_updates_cannot_remove_or_invalidate_containment(defect):
    w,p,_,auth=setup()
    with p.write_fence.operation():
        e,_=prepare(p,auth,request("release",parent="b"));p.dispatch_with_evidence(e)
        e,_=prepare(p,auth,request("contain",ident="inside",parent="bag"));p.dispatch_with_evidence(e)
        before=snap(w,p)
        with pytest.raises((PermissionError,ValueError)):
            if defect=="remove":
                ordinary(p,"relationships",{k:r for k,r in w.relationships.items() if k!=("k","bag")},"set")
            else:ordinary(p,"locations",{"k":"room"})
        assert snap(w,p)==before


def test_post_apply_fault_freezes_without_replaying(monkeypatch):
    w,p,_,auth = setup()
    original = p.event_history.append
    def failed(*a,**kw):
        original(*a,**kw)
        raise OSError("uncertain append")
    monkeypatch.setattr(p.event_history,"append",failed)
    with p.write_fence.operation():
        e,_ = prepare(p,auth,request("transfer",old_owner="d",new_owner="a"))
        with pytest.raises(OSError): p.dispatch_with_evidence(e)
    assert w.get_entity("k").owner_id == "a"
    assert w.relationships[("k","a")].kinds == ("owned_by",)
    assert p.write_fence.recovery_required and p.event_history.requires_recovery()


def test_checkpoint_restore_and_real_sibling_do_not_restore_authority(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_runtime_content_commit_boundary import _signed_runtime, _install
    from test_item_take import save
    from test_runtime_reconstruction import _dependency_manifest
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    from cognitive_world.runtime.recovery import RestoreCoordinator
    import cognitive_world.event.processor as processing
    rt,c,m,installer = _signed_runtime()
    initial,_,_,_ = setup()
    for entity in initial.entities.values(): rt.context.world_state.load_entity(entity)
    for key,value in initial.locations.items(): rt.context.world_state.load_location(key,value)
    for relation in initial.relationships.values(): rt.context.world_state.load_relationship(relation)
    p=rt.event_processor
    auth=RelationshipAuthority(p,Allow()); p.relationship_authority=auth
    with rt.write_fence.operation():
        _install(installer)
        e,_=prepare(p,auth,request("release",parent="b")); p.dispatch_with_evidence(e)
        e,_=prepare(p,auth,request("contain",ident="contain",parent="bag")); p.dispatch_with_evidence(e)
    h=SimpleNamespace(runtime=rt,cognition=c,memory=m,trust=p.persistence_trust)
    manager,saved=save(h,tmp_path/"saves")
    signed=p.event_history.export_persisted_records()
    class Assembler:
        def assemble(self,inputs):
            self.runtime,self.cognition,self.memory,_=_signed_runtime(h.trust,inputs)
            return self.runtime
    assembler=Assembler()
    with monkeypatch.context() as patch:
        patch.setattr(processing,"make_persisted_event_record",lambda *a,**kw: pytest.fail("historical re-sign"))
        slot=ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,timeline_id=saved.timeline_id,
            assembler=assembler,dependencies=_dependency_manifest()))
        restored=assembler.runtime
        assert restored.event_processor.relationship_authority is None
        assert restored.context.world_state.get_location("k")=="bag"
        assert restored.context.world_state.relationships[("k","bag")].version==2
        assert restored.context.event_history.export_persisted_records()==signed
        with restored.write_fence.operation():
            restored.event_processor.dispatch_with_evidence(restored.context.event_history.get_event(e.id))
    children=[]
    for name in ("relation-child","relation-sibling"):
        # Each sibling is activated from a separately cold-restored parent;
        # activating a sibling on an already active child is rightly denied.
        parent_assembly=Assembler()
        parent_slot=ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
            timeline_id=saved.timeline_id,assembler=parent_assembly,dependencies=_dependency_manifest()))
        assembly=Assembler()
        staged=manager.stage_restore(saved.save_id,timeline_id=saved.timeline_id,active_runtime=parent_slot.current,
            assembler=assembly,dependencies=_dependency_manifest(),new_timeline_id=name)
        children.append(RestoreCoordinator(parent_slot).activate(staged))
    child,sibling=children
    child_auth=RelationshipAuthority(child.event_processor,Allow()); child.event_processor.relationship_authority=child_auth
    with child.write_fence.operation():
        ce,_=prepare(child.event_processor,child_auth,request("transfer",ident="child-title",old_owner="d",new_owner="a"))
        child.event_processor.dispatch_with_evidence(ce)
    assert child.context.world_state.get_entity("k").owner_id=="a"
    assert sibling.context.world_state.get_entity("k").owner_id=="d"
    assert sibling.event_processor.relationship_authority is None
    with sibling.write_fence.operation(),pytest.raises(PermissionError): sibling.event_processor.dispatch_with_evidence(ce)
    with child.write_fence.operation():
        released,_=prepare(child.event_processor,child_auth,request("release",ident="child-release",parent="bag"))
        child.event_processor.dispatch_with_evidence(released)
    assert child.context.world_state.get_location("k")=="room"
    assert sibling.context.world_state.get_location("k")=="bag"
    context=child.cognition_context_provider(child.context.agent_registry.all_agents()[0])
    saved_host=SimpleNamespace(runtime=child,cognition=context.cognition_container,
                               memory=context.memory_store,trust=h.trust)
    _, transferred=save(saved_host,tmp_path/"saves")
    final=Assembler()
    with monkeypatch.context() as patch:
        patch.setattr(processing,"make_persisted_event_record",lambda *a,**kw:pytest.fail("transfer restore re-sign"))
        ColdRuntimePublisher().activate(manager.stage_cold_resume(transferred.save_id,
            timeline_id=transferred.timeline_id,assembler=final,dependencies=_dependency_manifest()))
    fw=final.runtime.context.world_state
    assert fw.get_entity("k").owner_id=="a" and fw.get_location("k")=="room"
    assert fw.relationships[("k","a")].kinds==("owned_by",)
    assert final.runtime.event_processor.relationship_authority is None
    assert final.runtime.context.event_history.get_persistence_record(ce.id)==child.context.event_history.get_persistence_record(ce.id)
