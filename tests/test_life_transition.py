"""Public Resolution/Factory/Processor life-operation regressions."""
from copy import deepcopy
import pytest
from cognitive_world.core.entity import Entity
from cognitive_world.core.life import LifeState
from cognitive_world.core.world_state import WorldState
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event.factory import EventFactory
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.decision.attempt import Attempt
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.life import LifeTransitionAuthority, LifeTransitionEngine


def host():
    w = WorldState()
    w.load_entity(Entity("b", "character", state={"life": LifeState(1, "alive")}))
    w.load_entity(Entity("d", "character"))
    w.load_entity(Entity("k", "object", owner_id="d"))
    w.load_location("b", "room")
    w.load_location("k", "b")
    from cognitive_world.core.physical import PhysicalRelation
    w.load_relationship(PhysicalRelation(1, "k", "b", ("held_by",)))
    w.load_relationship(PhysicalRelation(1, "k", "d", ("owned_by",)))
    p = EventProcessor(world_state=w, event_history=EventHistory(timeline_id="life"),
        simulation_clock=SimulationClock(), write_fence=RuntimeWriteFence(),
        persistence_trust=HmacPersistenceTrust(b"l" * 32))
    a = LifeTransitionAuthority(p)
    p.life_authority = a
    return w, p, a


def attempt(target="b", identifier="request"):
    return Attempt(identifier, "host", "proposal", "life_transition", ["entity:" + target],
                   {"transition": "alive_to_dead"})


def prepare(p, a, request=None, *, recipients=()):
    request = request or attempt()
    authorization = a.authorize(request, recipients=recipients)
    flow = ActionResolutionFlow(LifeTransitionEngine(authorization), EventFactory(life_authority=a))
    return flow.execute_with_result(request)[1], authorization


def snapshot(w, p):
    from cognitive_world.core.world_state import WorldStateSlot
    return deepcopy((dict(w.entities), dict(w.locations), dict(w.relationships),
        p.event_history.get_events(),
        w.read_state_slot(WorldStateSlot("entities", "b", ("state", "life", "value")), event_history=p.event_history),
        () if p.observation_store is None else tuple(p.observation_store.all())))


def test_authorized_alive_to_dead_commits_once():
    w, p, a = host()
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        assert w.get_entity("b").state["life"].value == "alive"
        evidence = p.dispatch_with_evidence(e)
        assert p.dispatch_with_evidence(e) == evidence
    assert w.get_entity("b").state["life"] == LifeState(1, "dead")
    assert len(p.event_history.get_events()) == 1
    assert p.event_history.get_persistence_record(e.id) is not None
    assert not evidence.observable_facts


@pytest.mark.parametrize("defect", ["authorization", "target", "version", "extra", "failure"])
def test_unauthorized_or_unsupported_life_transition_rejected(defect):
    from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision
    w, p, a = host()
    with p.write_fence.operation():
        req = attempt()
        auth = a.authorize(req)
        if defect == "authorization": auth["signature"] = "forged"
        if defect == "target": auth["body"]["target"] = "d"
        if defect == "version": auth["body"]["contract"] = "LifeTransition/v2"
        class Generic(ResolutionEngine):
            def _adjudicate(self, request):
                effect = {"effect_type": "life_transition_v2", "authorization": auth}
                return ResolutionDecision(defect != "failure", "life state changed",
                    metadata={"simulation_tick": 0},
                    world_effects=(effect, {"effect_type": "drop"}) if defect == "extra" else (effect,))
        before = snapshot(w, p)
        with pytest.raises((PermissionError, ValueError)):
            ActionResolutionFlow(Generic(), EventFactory(life_authority=a)).execute(req)
        assert snapshot(w, p) == before
        assert not p.write_fence.recovery_required and not p.event_history.requires_recovery()


@pytest.mark.parametrize("change", ["revoke", "tick"])
def test_missing_or_stale_life_evidence_rejected(change):
    w, p, a = host()
    with p.write_fence.operation():
        e, auth = prepare(p, a)
        if change == "revoke": a.revoke(auth)
        else: p.simulation_clock.advance(1)
        before = snapshot(w, p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
        assert snapshot(w, p) == before
        assert not p.write_fence.recovery_required and not p.event_history.requires_recovery()


def test_death_preserves_held_item_and_relations():
    w, p, a = host()
    before = (w.get_entity("k"), w.locations, w.relationships)
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        p.dispatch_with_evidence(e)
    assert (w.get_entity("k"), w.locations, w.relationships) == before
    assert w.get_entity("b").id == "b" and w.get_entity("b").type == "character"


def test_life_processor_independently_rejects_invalid_candidate():
    w, p, a = host()
    with p.write_fence.operation():
        e, auth = prepare(p, a)
        # Valid Factory-issued source is retained. Invalidate host authorization
        # after Factory acceptance, so only the Processor can enforce rejection.
        a.revoke(auth)
        before = snapshot(w, p)
        with pytest.raises(PermissionError): p.process_with_evidence(e, w)
        assert snapshot(w, p) == before
        assert not p.event_history.requires_recovery()


def test_uncertain_life_append_freezes(monkeypatch):
    w, p, a = host()
    original = p.event_history.append
    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("uncertain append")
    monkeypatch.setattr(p.event_history, "append", uncertain)
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        with pytest.raises(RuntimeError): p.dispatch_with_evidence(e)
    assert w.get_entity("b").state["life"].value == "dead"
    assert p.write_fence.recovery_required and p.event_history.requires_recovery()


def change_item(p, w, *, life=None):
    from dataclasses import replace
    from cognitive_world.event.factory import SystemEventFactory
    from cognitive_world.event.handler import EventHandler
    from cognitive_world.core.update import WorldUpdate
    class Independent(EventHandler):
        def handle(self, event):
            target = "b" if life is not None else "k"
            entity = w.get_entity(target)
            state = dict(entity.state)
            state["life" if life is not None else "independent"] = life if life is not None else True
            return WorldUpdate("entities", "update", {target: replace(entity, state=state)})
    p.register_handler("independent", Independent())
    e = SystemEventFactory().create(event_id="independent:" + str(len(p.event_history.get_events())),
        event_type="independent", timestamp="", simulation_tick=0)
    p.dispatch_with_evidence(e)


def test_life_candidate_does_not_overwrite_independent_item_change():
    w, p, a = host()
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        change_item(p, w)
        expected = w.get_entity("k")
        p.dispatch_with_evidence(e)
    assert w.get_entity("k") == expected
    assert w.get_entity("k").state["independent"] is True
    assert w.get_entity("b").state["life"] == LifeState(1, "dead")


@pytest.mark.parametrize("restored", [False, True])
def test_life_same_value_different_source_is_stale(restored):
    w, p, a = host()
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        change_item(p, w, life=LifeState(1, "dead"))
        if restored: change_item(p, w, life=LifeState(1, "alive"))
        before = snapshot(w, p)
        with pytest.raises(PermissionError): p.dispatch_with_evidence(e)
        assert snapshot(w, p) == before
        assert not p.write_fence.recovery_required


def test_signed_life_history_is_not_new_execution_permission():
    from cognitive_world.event.persistence import verify_and_restore_event_records
    w, p, a = host()
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        p.dispatch_with_evidence(e)
    records = p.event_history.export_persisted_records()
    events, _, _ = verify_and_restore_event_records(records, codec=p.persistence_codec,
        trust=p.persistence_trust, expected_timeline_id="life")
    assert p.persistence_codec.dumps(events[0]) == records[0].event_payload
    with p.write_fence.operation():
        assert p.dispatch_with_evidence(events[0]).source_event_id == e.id
    other, other_p, _ = host()
    before = snapshot(other, other_p)
    with other_p.write_fence.operation(), pytest.raises(PermissionError):
        other_p.dispatch_with_evidence(events[0])
    assert snapshot(other, other_p) == before
    assert not other_p.write_fence.recovery_required


@pytest.mark.parametrize("defect", ["missing", "attempt", "operation", "timeline", "tick", "write_set", "shape", "signature", "failed", "empty"])
def test_processor_defense_without_factory_validation(defect, monkeypatch):
    from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision
    from cognitive_world.observation.store import ObservationStore
    from cognitive_world.core.world_state import WorldStateSlot
    import cognitive_world.event.factory as factory_module
    w, p, a = host()
    p.observation_store = ObservationStore()
    with p.write_fence.operation():
        req = attempt()
        auth = a.authorize(req)
        effect = {"effect_type": "life_transition_v2", "authorization": auth}
        if defect == "missing": effect.pop("authorization")
        if defect == "attempt": auth["body"]["attempt"] = attempt(identifier="other")._resolution_snapshot()
        if defect == "operation": auth["body"]["operation"] = "revive"
        if defect == "timeline": auth["body"]["timeline"] = "sibling"
        if defect == "tick": auth["body"]["tick"] = 4
        if defect == "write_set": auth["body"]["write_set"] = (("k", "owner_id"),)
        if defect == "shape": auth["body"]["authorized"] = True
        if defect == "signature": auth["signature"] = "caller assertion"
        class Generic(ResolutionEngine):
            calls = 0
            def _adjudicate(self, request):
                self.calls += 1
                return ResolutionDecision(defect != "failed", "life state changed",
                    metadata={"simulation_tick": 0}, world_effects=() if defect == "empty" else (effect,))
        engine = Generic()
        # Disable exactly Factory's check; retain genuine Resolution confirmation
        # and source issuance. Restore it before calling the real Processor.
        with monkeypatch.context() as patch:
            patch.setattr(factory_module, "validate_live_resolution_entry", lambda *args: None)
            event = ActionResolutionFlow(engine, EventFactory(life_authority=a)).execute(req)
        before = snapshot(w, p)
        read = w.read_state_slot(WorldStateSlot("entities", "b", ("state", "life", "value")), event_history=p.event_history)
        with pytest.raises((PermissionError, ValueError)):
            p.dispatch_with_evidence(event)
        assert snapshot(w, p) == before
        assert w.read_state_slot(read.slot, event_history=p.event_history) == read
        assert p.observation_store.all() == () or not p.observation_store.all()
        assert engine.calls == 1
        assert not p.event_history.requires_recovery() and not p.write_fence.recovery_required


@pytest.mark.parametrize("operation_request", [attempt("missing"), attempt("d"),
    Attempt("revive", "host", "proposal", "life_transition", ["entity:b"], {"transition": "dead_to_alive"}),
    Attempt("wrong", "host", "proposal", "other", ["entity:b"], {"transition": "alive_to_dead"})])
def test_invalid_requests_rejected_without_effects(operation_request):
    w, p, a = host()
    before = snapshot(w, p)
    with p.write_fence.operation(), pytest.raises(PermissionError):
        a.authorize(operation_request)
    assert snapshot(w, p) == before
    assert not p.event_history.requires_recovery() and not p.write_fence.recovery_required


def test_new_request_after_death_is_not_duplicate_delivery():
    w, p, a = host()
    with p.write_fence.operation():
        e, _ = prepare(p, a)
        first = p.dispatch_with_evidence(e)
        before = snapshot(w, p)
        with pytest.raises(PermissionError): prepare(p, a, attempt(identifier="second"))
        assert p.dispatch_with_evidence(e) == first
        assert snapshot(w, p) == before


def test_life_checkpoint_cold_restore_children_and_siblings(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_runtime_content_commit_boundary import _signed_runtime
    from test_item_take import save
    from test_runtime_reconstruction import _dependency_manifest
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    from cognitive_world.runtime.recovery import RestoreCoordinator
    import cognitive_world.event.processor as processing
    rt, cognition, memory, installer = _signed_runtime()
    initial, _, _ = host()
    world = rt.context.world_state
    world.load_entity(Entity("room", "location"))
    for entity in initial.entities.values(): world.load_entity(entity)
    for key, value in initial.locations.items(): world.load_location(key, value)
    for relation in initial.relationships.values(): world.load_relationship(relation)
    h = SimpleNamespace(runtime=rt, cognition=cognition, memory=memory, trust=rt.event_processor.persistence_trust)
    authority = LifeTransitionAuthority(rt.event_processor)
    rt.event_processor.life_authority = authority
    from test_runtime_content_commit_boundary import _install
    with rt.write_fence.operation(): _install(installer)
    manager, alive = save(h, tmp_path / "saves")
    with rt.write_fence.operation():
        event, old_auth = prepare(rt.event_processor, authority, recipients=("a",))
        rt.event_processor.dispatch_with_evidence(event)
    _, dead = save(h, tmp_path / "saves")
    signed = rt.context.event_history.get_persistence_record(event.id).to_json_record()
    class Assembler:
        def assemble(self, inputs):
            runtime, c, m, _ = _signed_runtime(h.trust, inputs)
            self.runtime = runtime
            return runtime
    def cold(checkpoint):
        assembler = Assembler()
        slot = ColdRuntimePublisher().activate(manager.stage_cold_resume(checkpoint.save_id,
            timeline_id=checkpoint.timeline_id, assembler=assembler, dependencies=_dependency_manifest()))
        return slot, assembler.runtime
    with monkeypatch.context() as patch:
        patch.setattr(LifeTransitionEngine, "_adjudicate", lambda *args: pytest.fail("restore re-adjudicated"))
        patch.setattr(processing, "make_persisted_event_record", lambda *args, **kw: pytest.fail("restore re-signed"))
        _, restored = cold(dead)
        rw, rh = restored.context.world_state, restored.context.event_history
        assert rw.get_entity("b").state["life"] == LifeState(1, "dead")
        assert rw.get_entity("b").id == "b" and rw.get_entity("b").type == "character"
        assert rw.locations == world.locations and rw.relationships == world.relationships
        assert rw.get_entity("k") == world.get_entity("k")
        assert rh.get_persistence_record(event.id).to_json_record() == signed
        from cognitive_world.resolution.life import verify_bound_recipients
        assert verify_bound_recipients(rh.get_event(event.id).changes[1], h.trust,
            event_id=event.id) == ("a",)
        historic = rh.get_event(event.id)
        assert historic._runtime_write_permit is None
        assert restored.event_processor.life_authority is None
        count = len(rh.get_events())
        with patch.context() as no_apply:
            no_apply.setattr(rw, "apply_event", lambda *args: pytest.fail("duplicate applied"))
            with restored.write_fence.operation():
                restored.event_processor.dispatch_with_evidence(historic)
                restored.event_processor.dispatch_with_evidence(historic)
        assert len(rh.get_events()) == count
        assert not restored.context.observation_store.all()
    # Fork two independent children of the same living checkpoint.
    def branch(name, checkpoint=alive):
        slot, parent = cold(checkpoint)
        assembler = Assembler()
        staged = manager.stage_restore(checkpoint.save_id, timeline_id=checkpoint.timeline_id,
            active_runtime=parent, assembler=assembler, dependencies=_dependency_manifest(), new_timeline_id=name)
        return RestoreCoordinator(slot).activate(staged)
    child, sibling = branch("life-child"), branch("life-sibling")
    ca = LifeTransitionAuthority(child.event_processor)
    child.event_processor.life_authority = ca
    with child.write_fence.operation():
        ce, _ = prepare(child.event_processor, ca, attempt(identifier="child-request"))
        child.event_processor.dispatch_with_evidence(ce)
    assert child.context.world_state.get_entity("b").state["life"].value == "dead"
    assert sibling.context.world_state.get_entity("b").state["life"].value == "alive"
    assert sibling.context.event_history.get_event(ce.id) is None
    assert not sibling.context.observation_store.all()
    before = snapshot(sibling.context.world_state, sibling.event_processor)
    with sibling.write_fence.operation(), pytest.raises(PermissionError):
        sibling.event_processor.dispatch_with_evidence(ce)
    assert snapshot(sibling.context.world_state, sibling.event_processor) == before

    inherited = branch("life-dead-child", dead)
    ancestor = inherited.context.event_history.get_event(event.id)
    inherited_world = inherited.context.world_state
    with monkeypatch.context() as patch:
        patch.setattr(inherited_world, "apply_event", lambda *args: pytest.fail("ancestor reapplied"))
        with inherited.write_fence.operation():
            inherited.event_processor.dispatch_with_evidence(ancestor)
    assert inherited_world.get_entity("b").state["life"].value == "dead"
    assert inherited.context.event_history.get_persistence_record(event.id).to_json_record() == signed
    assert inherited.event_processor.life_authority is None
    with child.write_fence.operation(), pytest.raises(PermissionError):
        ActionResolutionFlow(LifeTransitionEngine(old_auth), EventFactory(life_authority=ca)).execute(attempt())
    assert not child.write_fence.recovery_required


def test_uncertain_life_write_blocks_real_checkpoint(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_runtime_content_commit_boundary import _signed_runtime, _install
    from test_item_take import save
    rt, c, m, installer = _signed_runtime()
    rt.context.world_state.load_entity(Entity("b", "character", state={"life": LifeState(1, "alive")}))
    with rt.write_fence.operation(): _install(installer)
    p = rt.event_processor
    a = LifeTransitionAuthority(p)
    p.life_authority = a
    original = p.event_history.append
    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("uncertain write")
    monkeypatch.setattr(p.event_history, "append", uncertain)
    with rt.write_fence.operation():
        e, _ = prepare(p, a)
        with pytest.raises(RuntimeError): p.dispatch_with_evidence(e)
    assert p.event_history.requires_recovery() and rt.write_fence.recovery_required
    assert not rt.context.observation_store.all()
    h = SimpleNamespace(runtime=rt, cognition=c, memory=m, trust=p.persistence_trust)
    with pytest.raises((PermissionError, RuntimeError)): save(h, tmp_path / "blocked")
    with pytest.raises((PermissionError, RuntimeError)), rt.write_fence.operation():
        p.dispatch_with_evidence(e)
    assert rt.context.world_state.get_entity("b").state["life"] == LifeState(1, "dead")
    assert sum(x.id == e.id for x in p.event_history.get_events()) == 1


@pytest.mark.parametrize("defect", ["missing", "shape", "version", "encoding", "signature", "duplicates", "event", "attempt", "target", "transition"])
@pytest.mark.parametrize("processor_only", [False, True])
def test_recipient_binding_is_independently_required_at_submission(defect, processor_only, monkeypatch):
    from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision
    from cognitive_world.observation.store import ObservationStore
    import cognitive_world.event.factory as factory_module
    w, p, a = host()
    p.observation_store = ObservationStore()
    with p.write_fence.operation():
        req = attempt()
        auth = a.authorize(req, recipients=("a",))
        binding = auth["body"]["recipient_binding"]
        if defect == "missing": del auth["body"]["recipient_binding"]
        elif defect == "shape": binding["body"]["authorized"] = True
        elif defect == "version": binding["body"]["version"] = 9
        elif defect == "encoding": binding["signature"] = "%%%"
        elif defect == "signature": binding["signature"] = "Zm9yZ2Vk"
        elif defect == "duplicates": binding["body"]["recipients"] = ["a", "a"]
        elif defect == "event": binding["body"]["event_id"] = "other"
        elif defect == "attempt": binding["body"]["attempt_fingerprint"] = "other"
        elif defect == "target": binding["body"]["target_id"] = "other"
        elif defect == "transition": binding["body"]["transition"] = ["dead", "alive"]
        class Generic(ResolutionEngine):
            calls = 0
            def _adjudicate(self, request):
                self.calls += 1
                return ResolutionDecision(True, "life state changed", metadata={"simulation_tick": 0},
                    world_effects=({"effect_type": "life_transition_v2", "authorization": auth},))
        engine = Generic()
        before = snapshot(w, p)
        if processor_only:
            with monkeypatch.context() as patch:
                patch.setattr(factory_module, "validate_live_resolution_entry", lambda *args: None)
                e = ActionResolutionFlow(engine, EventFactory(life_authority=a)).execute(req)
            with pytest.raises((PermissionError, ValueError)): p.dispatch_with_evidence(e)
        else:
            with pytest.raises((PermissionError, ValueError)):
                ActionResolutionFlow(engine, EventFactory(life_authority=a)).execute(req)
        assert snapshot(w, p) == before
        assert engine.calls == 1
        assert not p.event_history.requires_recovery() and not p.write_fence.recovery_required


def test_recipient_binding_valid_commit_and_postcommit_revocation():
    from cognitive_world.resolution.life import verify_bound_recipients
    w, p, a = host()
    before = (w.get_entity("k"), w.locations, w.relationships)
    with p.write_fence.operation():
        request = attempt()
        auth = a.authorize(request, recipients=("a", "c"))
        event = ActionResolutionFlow(LifeTransitionEngine(auth), EventFactory(life_authority=a)).execute(request)
        evidence = p.dispatch_with_evidence(event)
        a.revoke(auth)
        assert p.dispatch_with_evidence(event) == evidence
    assert verify_bound_recipients(event.changes[1], p.persistence_trust, event_id=event.id) == ("a", "c")
    assert (w.get_entity("k"), w.locations, w.relationships) == before
    assert not evidence.observable_facts


def test_original_ab_signed_fixture_is_readable_without_recipient_upgrade():
    import json
    from pathlib import Path
    from cognitive_world.event.persistence import PersistedEventRecord, verify_and_restore_event_records
    from cognitive_world.resolution.life import verify_bound_recipients
    from cognitive_world.observation.generator import ObservationGenerator
    w, p, a = host()
    records = tuple(PersistedEventRecord.from_json_record(r) for r in json.loads(
        Path(__file__).with_name("life_ab_legacy_event.json").read_text(encoding="utf-8")))
    events, evidence, _ = verify_and_restore_event_records(records, codec=p.persistence_codec,
        trust=p.persistence_trust, expected_timeline_id="life")
    event = events[0]
    assert event.changes[1]["effect_type"] == "life_transition_v1"
    assert verify_bound_recipients(event.changes[1], p.persistence_trust) == ()
    assert p.persistence_codec.dumps(event) == records[0].event_payload
    assert ObservationGenerator().generate_authorized(event, evidence[0], observer_id="a", event_history=p.event_history) == ()
    before = snapshot(w, p)
    with p.write_fence.operation(), pytest.raises(PermissionError): p.dispatch_with_evidence(event)
    assert snapshot(w, p) == before
