from dataclasses import replace
from copy import deepcopy
import pytest
from cognitive_world.core.life import LifeState
from cognitive_world.core.physical import PhysicalRelation
from cognitive_world.core.update import WorldUpdate
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.factory import SystemEventFactory
from test_governed_relationship import setup, snap, rejection_snapshot, forbid_application_and_delivery
from test_life_transition import prepare


@pytest.mark.parametrize("case", ["dead", "remove", "delete", "mixed", "owner", "add", "invalid", "revive", "version", "bool_version"])
def test_generic_life_mutation_rejects_before_application(case, monkeypatch):
    w,p,life,auth=setup()
    if case=="revive":
        w.load_entity(replace(w.get_entity("b"),state={"life":LifeState(1,"dead")}))
    before=snap(w,p)
    entity=w.get_entity("b")
    if case=="add":
        entity=w.get_entity("a"); target="a"
    else: target="b"
    state=dict(entity.state)
    if case=="remove": state.pop("life")
    else: state["life"]=LifeState(1,"alive" if case=="revive" else "dead")
    replacement=replace(entity,state=state)
    if case=="invalid": replacement.state["life"]="dead"
    if case=="version": object.__setattr__(replacement.state["life"],"version",2)
    if case=="bool_version":
        replacement.state["life"]=LifeState(1,"alive")
        object.__setattr__(replacement.state["life"],"version",True)
    if case=="owner": replacement.owner_id="d"
    payload={target:replacement}
    if case=="mixed": payload["a"]=replace(w.get_entity("a"),state={"extra":True})
    if case=="delete": payload={k:v for k,v in w.entities.items() if k!="b"}
    class Bad(EventHandler):
        def handle(self,e): return WorldUpdate("entities","set" if case=="delete" else "update",payload)
    p.register_handler("bad",Bad())
    forbid_application_and_delivery(monkeypatch,w,p)
    failure_before = rejection_snapshot(w,p,"bad")
    with p.write_fence.operation(),pytest.raises(PermissionError):
        p.dispatch_with_evidence(SystemEventFactory().create(event_id="bad",event_type="bad",timestamp="",simulation_tick=0))
    assert snap(w,p)==before and not p.write_fence.recovery_required
    assert rejection_snapshot(w,p,"bad") == failure_before


@pytest.mark.parametrize("kind",["held_by","attached_to"])
@pytest.mark.parametrize("operation",["add","remove","version","legacy","endpoint","mixed"])
def test_generic_relationship_changes_reject_before_application(kind,operation,monkeypatch):
    from cognitive_world.core.relationship import Relationship
    w,p,_,_=setup()
    if kind=="attached_to":
        w.load_relationship(PhysicalRelation(1,"bag","b",("attached_to",)))
    key=("k","b") if kind=="held_by" else ("bag","b")
    relations=dict(w.relationships)
    if operation in {"add","mixed"}:
        key=("bag","a") if kind=="held_by" else ("a","bag")
        relations[key]=PhysicalRelation(1,*key,(kind,))
        if operation=="mixed": relations[("a","d")]=PhysicalRelation(1,"a","d",("controls",))
    elif operation=="endpoint":
        prior=relations.pop(key)
        relations[(key[0],"a")]=replace(prior,target="a")
    elif operation=="remove": del relations[key]
    elif operation=="legacy": relations[key]=Relationship(*key,{kind:True})
    else: relations[key]=replace(relations[key],version=2)
    before=snap(w,p)
    class Bad(EventHandler):
        def handle(self,e): return WorldUpdate("relationships","set",relations)
    p.register_handler("bad",Bad())
    forbid_application_and_delivery(monkeypatch,w,p)
    failure_before = rejection_snapshot(w,p,"bad")
    with p.write_fence.operation(),pytest.raises(PermissionError):
        p.dispatch_with_evidence(SystemEventFactory().create(event_id="bad",event_type="bad",timestamp="",simulation_tick=0))
    assert snap(w,p)==before and not p.write_fence.recovery_required
    assert rejection_snapshot(w,p,"bad") == failure_before


def test_real_death_event_cannot_carry_extra_unprotected_writes():
    w,p,life,_=setup()
    class Mixed(EventHandler):
        def handle(self,event):
            return WorldUpdate("entities","update",{"b":replace(w.get_entity("b"),state={"life":LifeState(1,"dead")}),
                "a":replace(w.get_entity("a"),state={"extra":True})})
    with p.write_fence.operation():
        e,_=prepare(p,life)
        p.register_handler("resolution",Mixed())
        before=snap(w,p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
        assert snap(w,p)==before and not p.write_fence.recovery_required


@pytest.mark.parametrize("target",["facts","environment","entities"])
def test_valid_life_event_cannot_be_repurposed_for_other_writes(target):
    w,p,life,_=setup()
    class Bad(EventHandler):
        def handle(self,e):
            return WorldUpdate(target,"update",{"a":replace(w.get_entity("a"),state={"extra":True})}
                               if target=="entities" else {"extra":True})
    with p.write_fence.operation():
        event,_=prepare(p,life)
        p.register_handler("resolution",Bad())
        before=snap(w,p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(event)
        assert snap(w,p)==before and not p.write_fence.recovery_required


def test_ordinary_unprotected_and_same_value_life_update_remains_supported():
    w,p,_,_=setup()
    life=w.get_entity("b").state["life"]
    class Allowed(EventHandler):
        def handle(self,e): return WorldUpdate("entities","update",{
            "b":replace(w.get_entity("b"),attributes={"ordinary":True})})
    p.register_handler("ordinary",Allowed())
    with p.write_fence.operation():
        p.dispatch_with_evidence(SystemEventFactory().create(event_id="ordinary",event_type="ordinary",timestamp="",simulation_tick=0))
    assert w.get_entity("b").state["life"]==life and w.get_entity("b").attributes["ordinary"] is True


def test_legitimate_take_cannot_be_clipped_into_unrelated_update():
    from test_item_take import make_host, prepare as prepare_take, take_snapshot
    host=make_host()
    p=host.runtime.event_processor
    class Clipped(EventHandler):
        def handle(self,e): return WorldUpdate("facts","update",{"extra":True})
    with host.runtime.write_fence.operation():
        _,event=prepare_take(host)
        p.register_handler("resolution",Clipped())
        before=take_snapshot(host)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(event)
        assert take_snapshot(host)==before and not host.runtime.write_fence.recovery_required


def test_content_installation_is_not_existing_attachment_authority():
    w,p,_,_=setup()
    before=snap(w,p)
    class Install(EventHandler):
        def handle(self,e):
            return WorldUpdate("runtime_content","install",None,
                {"physical_relations":(PhysicalRelation(1,"bag","a",("attached_to",)),)})
    p.register_handler("runtime_content_installed",Install())
    with p.write_fence.operation(),pytest.raises(PermissionError,match="installation cannot"):
        p.dispatch_with_evidence(SystemEventFactory().create(event_id="install",event_type="runtime_content_installed",timestamp="",simulation_tick=0))
    assert snap(w,p)==before and not p.write_fence.recovery_required


@pytest.mark.parametrize("existing_kind", [None, "held_by", "attached_to"])
def test_valid_content_batch_preserves_new_identity_admission_and_existing_protection(monkeypatch, existing_kind):
    from types import SimpleNamespace
    from cognitive_world.content.installation import (
        ContentInstallationRecord, WorldContentBatch, _RuntimeContentHandler, installation_record_key)
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from cognitive_world.core.entity import Entity
    from cognitive_world.core.physical import validate_physical_world
    from test_governed_relationship import rejection_snapshot, forbid_application_and_delivery
    w,p,_,_ = setup()
    p.persistence_codec = scenario_snapshot_codec()
    event = SystemEventFactory().create(event_id="runtime-content:test-world:test-instance", event_type="runtime_content_installed",
        timestamp="", simulation_tick=0, changes=[{"world_id":"test-world", "instance_id":"test-instance",
            "template_id":"test-template", "proposal_digest":None}])
    record = ContentInstallationRecord("test-world", "test-instance", "test-template", "test-host",
        None, 0, "world_installed", event.id)
    item = Entity("new-item", "object", owner_id="d", state={"life":LifeState(1,"alive")})
    batch = WorldContentBatch((item,), ((item.id,"b"),), (),
        installation_record_key(record.world_id,record.instance_id),record)
    relations = (PhysicalRelation(1,item.id,"b",("held_by",)),)
    if existing_kind:
        relations += (PhysicalRelation(1,"bag","room" if existing_kind == "held_by" else item.id,(existing_kind,)),)
    # The full proposed graph is structurally valid; rejection must be governance,
    # not a malformed payload, missing endpoint or location conflict.
    validate_physical_world({**w.entities,item.id:item},{**w.locations,item.id:"b"},
        {**w.relationships,**{(r.source,r.target):r for r in relations}})
    handler = _RuntimeContentHandler(SimpleNamespace(world_state=w,clock=p.simulation_clock))
    handler.authorize(event,(batch,relations))
    p.register_handler(event.type,handler)
    with p.write_fence.operation():
        if existing_kind:
            forbid_application_and_delivery(monkeypatch,w,p)
            before = rejection_snapshot(w,p,event.id)
            with pytest.raises(PermissionError,match="installation cannot"):
                p.dispatch_with_evidence(event)
            assert rejection_snapshot(w,p,event.id) == before
            assert w.get_entity(item.id) is None
            assert batch.record_key not in w.facts
        else:
            evidence = p.dispatch_with_evidence(event)
            assert evidence.has_trusted_source(event)
            assert w.get_entity(item.id) == item
            assert w.locations[item.id] == "b"
            assert w.relationships[(item.id,"b")] == relations[0]
            assert w.facts[batch.record_key] == record
            assert p.event_history.get_persistence_record(event.id) is not None
            p.event_history.verify_persisted_lineage(codec=p.persistence_codec,trust=p.persistence_trust)
            assert not p.event_history.requires_recovery() and not p.write_fence.recovery_required
