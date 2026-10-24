"""B3: real selection, immutable evidence, commit isolation and checkpoint recovery."""
from dataclasses import replace
from copy import deepcopy
from contextvars import copy_context
from threading import Event, Thread

import pytest
from cognitive_world.cognition.action_expectation import (
    ActionExpectationRecord, ActionResultAssociation, EXPECTATION_TYPE, ASSOCIATION_TYPE,
    EXPECTATION_PURPOSE, ASSOCIATION_PURPOSE, expectation_id, association_id,
    verify_records, validate_structure,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, cognitive_snapshot_codec
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
from cognitive_world.runtime.recovery import RestoreCoordinator, ActiveRuntimeSlot
from test_runtime_reconstruction import _dependency_manifest
from test_save_restore_end_to_end import (
    _live_runtime, _observe_door, AGENT_ID, DOOR_ID, PARENT, DoorRuntimeAssembler,
)
from test_l1_instance import _fixture, _capture, _save


def _fresh():
    trust = HmacPersistenceTrust(b"b3-test-key-immutable-result-000000")
    runtime, cognition, store = _live_runtime(trust, door_locked=True)
    _observe_door(runtime, "b3-known-door")
    return runtime, cognition, store, trust


def _selected(runtime):
    agent = runtime.context.agent_registry.get(AGENT_ID)
    context = runtime.cognition_context_provider(agent)
    loop = runtime.agent_action_loop
    proposal = loop.agent_turn.execute(agent, context, runtime.agent_decision,
                                      simulation_tick=runtime.context.clock.capture())
    attempt = loop.action_pipeline.create_attempt(proposal)
    return proposal, attempt


def _kind(store, kind):
    return tuple(m for m in store.get_all_memories() if m.type == kind)


def _verify(runtime, store, trust, records=None):
    verify_records(store.get_all_memories() if records is None else records,
        history=runtime.context.event_history, trust=trust,
        checkpoint_tick=runtime.context.clock.current_time, lineage=runtime.memory_revision_lineage)


def test_freeze_is_before_first_resolution_and_not_a_world_or_semantic_fact(monkeypatch):
    runtime, cognition, store, trust = _fresh()
    loop = runtime.agent_action_loop; flow = loop.action_resolution_flow
    resolve = flow.resolution_engine.resolve
    before = deepcopy((dict(cognition.beliefs), dict(cognition.goals), dict(cognition.self_models)))
    calls = []
    def checked(attempt):
        record, = _kind(store, EXPECTATION_TYPE)
        assert type(record.content) is ActionExpectationRecord
        assert record.content.attempt_id == attempt.attempt_id
        assert record.content.attempt_fingerprint == attempt.content_fingerprint()
        assert record.content.expected_text == attempt.parameters["expected_result"]
        assert record.content.decision_tick == record.content.freeze_tick == 4
        assert not _kind(store, ASSOCIATION_TYPE)
        assert not store.is_semantically_retrievable(record)
        calls.append(attempt.attempt_id)
        return resolve(attempt)
    monkeypatch.setattr(flow.resolution_engine, "resolve", checked)
    with runtime.write_fence.operation():
        proposal, _ = _selected(runtime)
        execution = loop.run_proposal_with_result(proposal, simulation_tick=runtime.context.clock.capture())
        assert len(runtime.context.event_history.get_events()) == 1
        runtime.event_processor.dispatch_with_evidence(execution.event)
    assert len(calls) == 1 and len(_kind(store, ASSOCIATION_TYPE)) == 1
    _verify(runtime, store, trust)
    assert before == (dict(cognition.beliefs), dict(cognition.goals), dict(cognition.self_models))
    assert not runtime.context.world_state.environment[DOOR_ID].is_open


def test_freeze_retry_keeps_identity_tick_and_rejects_changed_attempt(monkeypatch):
    runtime, _, store, trust = _fresh(); issuer = runtime.event_processor.action_expectations
    with runtime.write_fence.operation():
        proposal, attempt = _selected(runtime)
        original = issuer.freeze(attempt, proposal, origin="npc")
        runtime.context.clock.advance(3)
        assert issuer.freeze(attempt, proposal, origin="npc") == original
        changed = type(attempt)(attempt_id=attempt.attempt_id, agent_id=attempt.agent_id,
            action_proposal_id=attempt.action_proposal_id, action_type=attempt.action_type,
            target_refs=attempt.target_refs, parameters={**attempt.parameters, "method": "pull"}, metadata=attempt.metadata)
        with pytest.raises(PermissionError, match="conflicting"):
            issuer.freeze(changed, proposal, origin="npc")
    assert original.freeze_tick == 4 and len(_kind(store, EXPECTATION_TYPE)) == 1
    _verify(runtime, store, trust)


@pytest.mark.parametrize("stage", ["validation", "sign", "store_validation", "store_before", "store_after"])
def test_registration_failure_prevents_resolution(stage, monkeypatch):
    from cognitive_world.cognition import action_expectation as module
    runtime, _, store, _ = _fresh(); loop = runtime.agent_action_loop
    commit = MemoryStore._commit_action_record
    sign = HmacPersistenceTrust.sign
    def broken(*args, **kwargs): raise OSError("registration injected")
    if stage == "validation":
        validate=module.validate_structure
        def expected_only(record):
            if type(record) is ActionExpectationRecord:broken()
            return validate(record)
        monkeypatch.setattr(module,"validate_structure",expected_only)
    elif stage == "sign":
        def signing(self, purpose, payload):
            if purpose == EXPECTATION_PURPOSE: broken()
            return sign(self, purpose, payload)
        monkeypatch.setattr(HmacPersistenceTrust, "sign", signing)
    else:
        def writing(self, memory, **kwargs):
            if memory.type!=EXPECTATION_TYPE:return commit(self,memory,**kwargs)
            if stage == "store_after": commit(self, memory, **kwargs)
            if stage == "store_validation":
                return commit(self, replace(memory, owner_id="wrong-owner"), **kwargs)
            broken()
        monkeypatch.setattr(MemoryStore, "_commit_action_record", writing)
    monkeypatch.setattr(loop.action_resolution_flow.resolution_engine, "resolve",
                        lambda _: pytest.fail("Resolution called after failed registration"))
    with runtime.write_fence.operation():
        proposal, _ = _selected(runtime)
        with pytest.raises((OSError, PermissionError)):
            loop.run_proposal_with_result(proposal, simulation_tick=runtime.context.clock.capture())
    assert len(runtime.context.event_history.get_events()) == 1
    assert not _kind(store, ASSOCIATION_TYPE)
    assert len(_kind(store, EXPECTATION_TYPE)) == (1 if stage == "store_after" else 0)
    assert runtime.write_fence.recovery_required == (stage != "validation")


@pytest.mark.parametrize("stage", ["validate", "sign", "store_before", "store_after"])
def test_event_commit_association_failure_freezes_without_replay(stage, monkeypatch):
    from cognitive_world.cognition import action_expectation as module
    runtime, cognition, store, trust = _fresh(); loop = runtime.agent_action_loop
    with runtime.write_fence.operation():
        proposal, _ = _selected(runtime)
        execution = loop.run_proposal_with_result(proposal, simulation_tick=runtime.context.clock.capture())
        original_context = copy_context()
    commit = MemoryStore._commit_action_record; sign = HmacPersistenceTrust.sign
    def broken(*args, **kwargs): raise OSError("association injected")
    if stage == "validate": monkeypatch.setattr(module, "verify_records", broken)
    elif stage == "sign":
        def signing(self, purpose, payload):
            if purpose == ASSOCIATION_PURPOSE: broken()
            return sign(self, purpose, payload)
        monkeypatch.setattr(HmacPersistenceTrust, "sign", signing)
    else:
        def writing(self, memory, **kwargs):
            if memory.type == ASSOCIATION_TYPE:
                if stage == "store_after": commit(self, memory, **kwargs)
                broken()
            return commit(self, memory, **kwargs)
        monkeypatch.setattr(MemoryStore, "_commit_action_record", writing)
    # Resume the exact original operation context; a fresh permit is not a
    # substitute for the Event's originating capability.
    with pytest.raises((OSError, PermissionError)):
        original_context.run(runtime.event_processor.dispatch_with_evidence, execution.event)
    assert runtime.context.event_history.get_event(execution.event.id) is not None
    assert len(runtime.context.event_history.get_events()) == 2
    assert runtime.write_fence.recovery_required
    assert len(_kind(store, ASSOCIATION_TYPE)) == (1 if stage == "store_after" else 0)
    with pytest.raises(PermissionError): _capture(runtime, cognition, store, trust)
    assert not runtime.context.world_state.environment[DOOR_ID].is_open


def test_duplicate_processing_and_delivery_failure_do_not_repeat_action_or_consume(monkeypatch):
    runtime, _, store, trust = _fresh(); loop = runtime.agent_action_loop
    with runtime.write_fence.operation():
        proposal, _ = _selected(runtime)
        execution = loop.run_proposal_with_result(proposal, simulation_tick=runtime.context.clock.capture())
        original = runtime.context.observation_store.add
        def unavailable(_): raise OSError("delivery failed")
        monkeypatch.setattr(runtime.context.observation_store, "add", unavailable)
        with pytest.raises(RuntimeError, match="Observation delivery failed"):
            runtime.event_processor.dispatch_with_evidence(execution.event)
        association, = _kind(store, ASSOCIATION_TYPE)
        assert len(runtime.context.event_history.get_events()) == 2
        assert not runtime.write_fence.recovery_required
        monkeypatch.setattr(runtime.context.observation_store, "add", original)
        monkeypatch.setattr(loop.action_resolution_flow.resolution_engine, "resolve",
                            lambda _: pytest.fail("action replay"))
        runtime.event_processor.dispatch_with_evidence(execution.event)
        runtime.event_processor.dispatch_with_evidence(execution.event)
    assert _kind(store, ASSOCIATION_TYPE) == (association,)
    assert not any(m.type.startswith("system_l1_") for m in store.get_all_memories())
    _verify(runtime, store, trust)


@pytest.mark.parametrize("field,value", [
    ("owner_id", "other"), ("timeline_id", "sibling"), ("attempt_id", "different"),
    ("attempt_fingerprint", "0"*64), ("event_id", "different"),
    ("event_digest", "0"*64), ("resolution_id", "different"),
    ("expectation_digest", "0"*64), ("expectation_id", "different"),
    ("version", 99), ("policy", "unknown/v9"), ("classification", "success"),
])
def test_resigned_association_mismatches_fail_closed(field, value):
    runtime, _, store, trust, _, _ = _fixture()
    memory, = _kind(store, ASSOCIATION_TYPE)
    changed = replace(memory.content, **{field:value})
    changed = replace(changed, signature_hex=trust.sign(ASSOCIATION_PURPOSE, changed.body()).hex())
    records = tuple(replace(m, content=changed) if m.id == memory.id else m for m in store.get_all_memories())
    with pytest.raises(PermissionError): _verify(runtime, store, trust, records)


@pytest.mark.parametrize("field,value", [
    ("owner_id", "other"), ("timeline_id", "sibling"), ("attempt_id", "different"),
    ("attempt_fingerprint", "0"*64), ("expected_text", "a different prediction"),
    ("candidate_id", "different"), ("freeze_tick", 99), ("decision_tick", 99),
    ("representation", "typed"), ("version", 99), ("policy", "unknown/v9"),
])
def test_resigned_expectation_mismatches_fail_closed(field, value):
    runtime, _, store, trust, _, _ = _fixture()
    memory, = _kind(store, EXPECTATION_TYPE)
    changed = replace(memory.content, **{field:value})
    changed = replace(changed, signature_hex=trust.sign(EXPECTATION_PURPOSE, changed.body()).hex())
    records = tuple(replace(m, content=changed) if m.id == memory.id else m for m in store.get_all_memories())
    with pytest.raises(PermissionError): _verify(runtime, store, trust, records)


def test_incomplete_event_association_is_not_repaired_during_capture():
    runtime, cognition, store, trust, _, _ = _fixture()
    records = tuple(m for m in store.get_all_memories() if m.type != ASSOCIATION_TYPE)
    with pytest.raises(PermissionError, match="incomplete"):
        _verify(runtime, store, trust, records)
    assert len(_kind(store, ASSOCIATION_TYPE)) == 1


def test_restore_preserves_exact_records_without_signing(tmp_path, monkeypatch):
    runtime, cognition, store, trust, _, _ = _fixture()
    manager = SaveManager(tmp_path / "saves", trust=trust)
    saved = _save(manager, runtime, cognition, store)
    original = HmacPersistenceTrust.sign
    def signing(self, purpose, payload):
        if purpose in (EXPECTATION_PURPOSE, ASSOCIATION_PURPOSE): pytest.fail("historical B3 re-signing")
        return original(self, purpose, payload)
    # HmacPersistenceTrust.verify normally calls sign internally. Preserve
    # exact HMAC verification while distinguishing verification from issuance.
    from hmac import compare_digest
    monkeypatch.setattr(HmacPersistenceTrust, "verify",
        lambda self, purpose, payload, signature: compare_digest(original(self, purpose, payload), signature))
    monkeypatch.setattr(HmacPersistenceTrust, "sign", signing)
    restored = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
        timeline_id=PARENT, assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())).current
    restored_store = restored.cognition_context_provider(restored.context.agent_registry.get(AGENT_ID)).memory_store
    assert restored_store.get_all_memories() == store.get_all_memories()
    _verify(restored, restored_store, trust)


def test_child_inheritance_sibling_isolation_and_ancestor_attempt_no_replay(tmp_path):
    runtime, cognition, store, trust, _, _ = _fixture()
    manager = SaveManager(tmp_path / "saves", trust=trust)
    saved = _save(manager, runtime, cognition, store)
    stage = manager.stage_restore(saved.save_id, timeline_id=PARENT, active_runtime=runtime,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(), new_timeline_id="b3-child")
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(stage)
    child_store = child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID)).memory_store
    assert child_store.get_all_memories() == store.get_all_memories()
    _verify(child, child_store, trust)
    parent_expectation, = _kind(child_store, EXPECTATION_TYPE)
    import json
    values = json.loads(parent_expectation.content.attempt_json)
    from cognitive_world.decision.attempt import Attempt
    attempt = Attempt(attempt_id=values[0],agent_id=values[1],action_proposal_id=values[2],
        action_type=values[3],target_refs=values[4],parameters=values[5],metadata=values[6],
        intent_id=values[7],initiator_id=values[8])
    with child.write_fence.operation():
        with pytest.raises(PermissionError, match="ancestor"):
            child.event_processor.action_expectations.freeze(attempt,None,origin="npc")
    assert len(child.context.event_history.get_events()) == len(runtime.context.event_history.get_events())


def test_restored_pending_expectation_cannot_restart_resolution(tmp_path):
    runtime, cognition, store, trust = _fresh(); issuer = runtime.event_processor.action_expectations
    with runtime.write_fence.operation():
        proposal, attempt = _selected(runtime)
        expectation = issuer.freeze(attempt, proposal, origin="npc")
    manager = SaveManager(tmp_path / "saves", trust=trust)
    saved = _save(manager, runtime, cognition, store)
    restored = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
        timeline_id=PARENT, assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())).current
    with restored.write_fence.operation():
        with pytest.raises(PermissionError, match="restored incomplete"):
            restored.event_processor.action_expectations.begin_resolution(expectation)
    assert not _kind(store, ASSOCIATION_TYPE)


def test_unresolved_and_preexecution_rejection_have_no_formal_result(monkeypatch):
    runtime, _, store, _ = _fresh(); loop=runtime.agent_action_loop
    from cognitive_world.resolution.result import ResolutionResult
    monkeypatch.setattr(loop.action_resolution_flow.resolution_engine,"resolve",
        lambda attempt: ResolutionResult("unresolved",attempt.attempt_id,False,"unresolved"))
    with runtime.write_fence.operation():
        proposal, _ = _selected(runtime)
        result=loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
    assert result.event is None and not _kind(store,ASSOCIATION_TYPE)
    assert len(runtime.context.event_history.get_events())==1


@pytest.mark.parametrize("kind", ["cancel", "generation"])
def test_stale_origin_cannot_register_or_execute(kind):
    runtime, _, store, _ = _fresh(); fence=runtime.write_fence
    with fence.operation() as permit:
        context=copy_context()
        if kind=="cancel":
            # Cancellation must win before the newly protected source write.
            assert fence.revoke_uncommitted(permit)
            with pytest.raises(PermissionError):context.run(_selected,runtime)
        else:
            proposal, _ = _selected(runtime)
    if kind=="generation":
        fence.freeze_and_advance();fence.unfreeze()
        with pytest.raises(PermissionError):
            context.run(runtime.agent_action_loop.run_proposal_with_result,proposal,
                        simulation_tick=runtime.context.clock.capture())
    assert not _kind(store,EXPECTATION_TYPE) and len(runtime.context.event_history.get_events())==1


def test_player_absent_expectation_uses_real_product_path():
    from pathlib import Path
    from anchor_desktop.world_packages import WorldPackageCatalog
    from anchor_desktop.host import start_new_world
    from cognitive_world.player.service import PlayerActionRequest
    packages=Path(__file__).parents[1]/"src"/"anchor_desktop"/"worlds"
    package=WorldPackageCatalog(packages).package("clockwork-library")
    session=start_new_world(package,trust=HmacPersistenceTrust(b"b3-player-key-00000000000000000000"))
    try:
        service=session.player_service;binding=session.runtime.context.player_session
        target=next(ref for c,ref in service._request_candidates() if c.kind=="door")
        with session.runtime.write_fence.operation():
            outcome=service.submit(PlayerActionRequest("b3-player",binding.session_id,
                package.world_id,"open","push the door",target))
        assert outcome.status in ("resolved","failed")
        store=session.memory_store
        expected,=_kind(store,EXPECTATION_TYPE)
        assert expected.content.representation=="expectation_absent"
        assert expected.content.expected_text is None and expected.content.decision_tick is None
        assert expected.content.origin=="player" and len(_kind(store,ASSOCIATION_TYPE))==1
    finally: session.close()


@pytest.mark.parametrize("capture_first", [False, True])
def test_b3_event_and_association_share_snapshot_fence(capture_first, monkeypatch):
    runtime, cognition, store, trust = _fresh()
    loop=runtime.agent_action_loop
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime)
        execution=loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
        event_context=copy_context()
    reached,release=Event(),Event()
    snapshots=[];errors=[];order=[]
    commit=MemoryStore._commit_action_record
    def gated(self,memory,**kwargs):
        if memory.type==ASSOCIATION_TYPE:
            assert runtime.context.event_history.get_event(execution.event.id) is not None
            reached.set()
            if not release.wait(10): raise AssertionError("association gate not released")
        commit(self,memory,**kwargs)
        if memory.type==ASSOCIATION_TYPE:order.append("association")
    monkeypatch.setattr(MemoryStore,"_commit_action_record",gated)
    def process():
        try:event_context.run(runtime.event_processor.dispatch_with_evidence,execution.event)
        except BaseException as e:errors.append(e)
    def capture():
        try:snapshots.append(_capture(runtime,cognition,store,trust));order.append("capture")
        except BaseException as e:errors.append(e)
    if capture_first:
        with runtime.write_fence.operation():
            with runtime.write_fence.snapshot_scope():
                worker=Thread(target=process);worker.start()
                capture();release.set()
        worker.join(10)
        assert order==["capture","association"]
    else:
        worker=Thread(target=process);worker.start();assert reached.wait(10)
        observer=Thread(target=capture);observer.start();release.set()
        worker.join(10);observer.join(10)
        assert not observer.is_alive() and order==["association","capture"]
    assert not worker.is_alive() and not errors and len(snapshots)==1
    records=[r.value for group in snapshots[0].body.stores if group.store_name=="memories" for r in group.records]
    assert len([m for m in records if m.type==EXPECTATION_TYPE])==1
    assert len([m for m in records if m.type==ASSOCIATION_TYPE])==(0 if capture_first else 1)


def test_same_selected_proposal_cannot_execute_a_second_attempt(monkeypatch):
    runtime,_,store,_=_fresh();loop=runtime.agent_action_loop
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime)
        execution=loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
        runtime.event_processor.dispatch_with_evidence(execution.event)
        monkeypatch.setattr(loop.action_resolution_flow.resolution_engine,"resolve",
                            lambda _:pytest.fail("duplicate Resolution"))
        with pytest.raises(PermissionError,match="already bound"):
            loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
    assert len(_kind(store,EXPECTATION_TYPE))==len(_kind(store,ASSOCIATION_TYPE))==1
    assert len(runtime.context.event_history.get_events())==2


def test_selected_original_proposal_mutation_is_rejected():
    runtime,_,store,_=_fresh()
    with runtime.write_fence.operation():
        proposal,attempt=_selected(runtime)
        proposal.action_type="different action"
        with pytest.raises(PermissionError,match="selected proposal changed"):
            runtime.event_processor.action_expectations.freeze(attempt,proposal,origin="npc")
    assert not _kind(store,EXPECTATION_TYPE)


@pytest.mark.parametrize("point",["encoding","before_publish","committed_error"])
def test_b3_checkpoint_failure_keeps_exact_canonical_records(tmp_path,monkeypatch,point):
    from cognitive_world.runtime.save_manager import SaveCommittedError
    from cognitive_world.core.persistence import PersistedValueCodec
    runtime,cognition,store,trust,_,_=_fixture()
    manager=SaveManager(tmp_path/"saves",trust=trust)
    baseline=store.get_all_memories()
    if point=="encoding":
        dumps=PersistedValueCodec.dumps
        def encode(self,value):
            if type(value).__name__=="CognitiveSnapshotBody":raise OSError("encoding injection")
            return dumps(self,value)
        monkeypatch.setattr(PersistedValueCodec,"dumps",encode)
    elif point=="before_publish":
        def fail(*args,**kwargs):raise OSError("publication injection")
        monkeypatch.setattr(manager,"_write_catalog",fail)
    else:
        append=manager._append_journal
        def fail(record):
            if record["phase"]=="COMMITTED":raise OSError("committed publication injection")
            return append(record)
        monkeypatch.setattr(manager,"_append_journal",fail)
    with pytest.raises(SaveCommittedError if point=="committed_error" else OSError):
        _save(manager,runtime,cognition,store)
    monkeypatch.undo()
    assert store.get_all_memories()==baseline
    saves=manager.list_saves()
    assert len(saves)==(1 if point=="committed_error" else 0)
    assert not runtime.write_fence.recovery_required
    if saves:
        restored=ColdRuntimePublisher().activate(manager.stage_cold_resume(saves[0].save_id,
            timeline_id=PARENT,assembler=DoorRuntimeAssembler(trust),dependencies=_dependency_manifest())).current
        restored_store=restored.cognition_context_provider(restored.context.agent_registry.get(AGENT_ID)).memory_store
        assert restored_store.get_all_memories()==baseline


@pytest.mark.parametrize("version",[2,3])
def test_legacy_snapshot_without_b3_uses_original_purpose_and_no_inference(version):
    from cognitive_world.cognition import snapshot as module
    from cognitive_world.core.persistence import sha256_hex
    runtime,cognition,store,trust=_fresh()
    original=_capture(runtime,cognition,store,trust)
    assert original.body.schema_version==3
    body=replace(original.body,schema_version=version)
    encoded=cognitive_snapshot_codec().dumps(body)
    purpose=module._COGNITIVE_SNAPSHOT_PURPOSE_V2 if version==2 else module._COGNITIVE_SNAPSHOT_PURPOSE_V3
    legacy=CognitiveStateSnapshot(body,"sha256:"+sha256_hex(encoded),trust.sign(purpose,encoded).hex())
    decoded=CognitiveStateSnapshot.from_bytes(legacy.to_bytes(),trust=trust)
    decoded.validate(trust=trust,event_history=runtime.context.event_history,
        memory_revision_lineage=runtime.memory_revision_lineage)
    assert not _kind(store,EXPECTATION_TYPE)


def test_missing_and_future_b3_snapshot_records_fail_even_when_resigned():
    from cognitive_world.core.persistence import sha256_hex
    from cognitive_world.cognition import snapshot as module
    runtime,cognition,store,trust,_,_=_fixture()
    snapshot=_capture(runtime,cognition,store,trust)
    codec=cognitive_snapshot_codec()
    for mode in ("missing_association","unknown_type","version3"):
        groups=[]
        for group in snapshot.body.stores:
            if group.store_name!="memories":groups.append(group);continue
            if mode=="missing_association":
                records=tuple(r for r in group.records if r.value.type!=ASSOCIATION_TYPE)
            elif mode=="unknown_type":
                records=tuple(replace(r,value=replace(r.value,type="system_action_future_v99"))
                    if r.value.type==ASSOCIATION_TYPE else r for r in group.records)
            else:records=group.records
            unsigned=replace(group,records=records,state_version="sha256:pending")
            groups.append(replace(unsigned,state_version="sha256:"+sha256_hex(codec.dumps(unsigned))))
        body=replace(snapshot.body,stores=tuple(groups),schema_version=3 if mode=="version3" else 4)
        data=codec.dumps(body)
        purpose=module._COGNITIVE_SNAPSHOT_PURPOSE_V3 if mode=="version3" else module._COGNITIVE_SNAPSHOT_PURPOSE_V4
        changed=CognitiveStateSnapshot(body,"sha256:"+sha256_hex(data),trust.sign(purpose,data).hex())
        with pytest.raises(PermissionError):
            decoded=CognitiveStateSnapshot.from_bytes(changed.to_bytes(),trust=trust)
            decoded.validate(trust=trust,event_history=runtime.context.event_history,
                memory_revision_lineage=runtime.memory_revision_lineage)


def test_model_prediction_conflicting_with_failure_is_preserved_without_learning():
    from cognitive_world.cognition.action_expectation import selection_scope
    # Use the real validated candidate selection seam, not a prewritten receipt.
    runtime,cognition,store,trust=_fresh()
    agent=runtime.context.agent_registry.get(AGENT_ID)
    context=runtime.cognition_context_provider(agent)
    loop=runtime.agent_action_loop
    decision=runtime.agent_decision
    policy=decision.candidate_policy
    class WrongPrediction:
        def generate(self,situation):
            batch,mode=policy.generate(situation)
            return tuple(replace(c,expected_result="The door will definitely open.") for c in batch),mode
    decision.candidate_policy=WrongPrediction()
    before=deepcopy((dict(cognition.beliefs),dict(cognition.goals),dict(cognition.self_models)))
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime)
        execution=loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
        runtime.event_processor.dispatch_with_evidence(execution.event)
    expectation,=_kind(store,EXPECTATION_TYPE)
    association,=_kind(store,ASSOCIATION_TYPE)
    assert expectation.content.expected_text=="The door will definitely open."
    assert execution.resolution.success is False and association.content.classification=="uncomparable"
    assert not runtime.context.world_state.environment[DOOR_ID].is_open
    assert before==(dict(cognition.beliefs),dict(cognition.goals),dict(cognition.self_models))
    assert context.get_memories()==()
    _verify(runtime,store,trust)


def test_parent_postfork_and_sibling_records_cannot_enter_child(tmp_path):
    runtime,cognition,store,trust,_,_=_fixture()
    manager=SaveManager(tmp_path/"saves",trust=trust)
    saved=_save(manager,runtime,cognition,store)
    inherited={m.id for m in store.get_all_memories()}
    stage=manager.stage_restore(saved.save_id,timeline_id=PARENT,active_runtime=runtime,
        assembler=DoorRuntimeAssembler(trust),dependencies=_dependency_manifest(),new_timeline_id="b3-child-isolated")
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime)
        execution=runtime.agent_action_loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
        runtime.event_processor.dispatch_with_evidence(execution.event)
    parent_late=tuple(m for m in store.get_all_memories() if m.id not in inherited)
    child=RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(stage)
    child_store=child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID)).memory_store
    with pytest.raises(PermissionError,match="inherited checkpoint"):
        _verify(child,child_store,trust,(*child_store.get_all_memories(),*parent_late))
    _observe_door(child,"b3-child-door")
    before={m.id for m in child_store.get_all_memories()}
    with child.write_fence.operation():
        proposal,_=_selected(child)
        result=child.agent_action_loop.run_proposal_with_result(proposal,simulation_tick=child.context.clock.capture())
        child.event_processor.dispatch_with_evidence(result.event)
    child_suffix=tuple(m for m in child_store.get_all_memories() if m.id not in before)
    assert {m.content.timeline_id for m in child_suffix}=={"b3-child-isolated"}
    parent=ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
        timeline_id=PARENT,assembler=DoorRuntimeAssembler(trust),dependencies=_dependency_manifest())).current
    sibling_stage=manager.stage_restore(saved.save_id,timeline_id=PARENT,active_runtime=parent,
        assembler=DoorRuntimeAssembler(trust),dependencies=_dependency_manifest(),new_timeline_id="b3-sibling")
    sibling=RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(sibling_stage)
    sibling_store=sibling.cognition_context_provider(sibling.context.agent_registry.get(AGENT_ID)).memory_store
    with pytest.raises(PermissionError,match="Timeline ancestry"):
        _verify(sibling,sibling_store,trust,(*sibling_store.get_all_memories(),*child_suffix))
    _verify(sibling,sibling_store,trust)


@pytest.mark.parametrize("stage",["preexecution_rejected","resolution_error","event_processing_error"])
def test_execution_failures_preserve_exact_boundary(stage,monkeypatch):
    runtime,cognition,store,trust=_fresh();loop=runtime.agent_action_loop
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime)
        if stage=="preexecution_rejected":
            def reject(*args,**kwargs):raise PermissionError("preexecution rejected")
            monkeypatch.setattr(loop.safety_governance,"require_action_allowed",reject)
        elif stage=="resolution_error":
            def reject(*args,**kwargs):raise OSError("unconfirmed Resolution")
            monkeypatch.setattr(loop.action_resolution_flow.resolution_engine,"resolve",reject)
        else:
            def reject(*args,**kwargs):raise OSError("Event append failed")
            monkeypatch.setattr(runtime.context.event_history,"append",reject)
        with pytest.raises((OSError,PermissionError)):
            execution=loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
            runtime.event_processor.dispatch_with_evidence(execution.event)
    assert len(runtime.context.event_history.get_events())==1
    assert not _kind(store,ASSOCIATION_TYPE)
    assert len(_kind(store,EXPECTATION_TYPE))==(0 if stage=="preexecution_rejected" else 1)
    assert runtime.write_fence.recovery_required==(stage=="event_processing_error")
    monkeypatch.undo()
    if stage=="event_processing_error":
        with pytest.raises(PermissionError):_capture(runtime,cognition,store,trust)
    else:
        snapshot=_capture(runtime,cognition,store,trust)
        assert snapshot is not None
    assert not runtime.context.world_state.environment[DOOR_ID].is_open


@pytest.mark.parametrize("kind",["cancel","generation"])
def test_stale_result_cannot_commit_association(kind):
    runtime,_,store,_=_fresh();loop=runtime.agent_action_loop;fence=runtime.write_fence
    with fence.operation() as permit:
        proposal,_=_selected(runtime)
        result=loop.run_proposal_with_result(proposal,simulation_tick=runtime.context.clock.capture())
        context=copy_context()
    # Resolution crossed an existing non-cancellable section; cancellation
    # cannot pretend to roll it back. Generation invalidation still fences it.
    if kind=="cancel":assert not fence.revoke_uncommitted(permit)
    fence.freeze_and_advance();fence.unfreeze()
    with pytest.raises(PermissionError):context.run(runtime.event_processor.dispatch_with_evidence,result.event)
    assert len(runtime.context.event_history.get_events())==1 and not _kind(store,ASSOCIATION_TYPE)
    assert len(_kind(store,EXPECTATION_TYPE))==1


def test_concurrent_registration_has_one_identity_and_original_tick():
    from threading import Barrier
    runtime,_,store,_=_fresh();issuer=runtime.event_processor.action_expectations
    with runtime.write_fence.operation():
        proposal,attempt=_selected(runtime);context=copy_context()
    barrier=Barrier(3);results=[];errors=[]
    def work():
        try:
            barrier.wait(5)
            results.append(context.copy().run(issuer.freeze,attempt,proposal,origin="npc"))
        except BaseException as e:errors.append(e)
    workers=[Thread(target=work) for _ in range(2)]
    for t in workers:t.start()
    barrier.wait(5)
    for t in workers:t.join(10)
    assert not errors and all(not t.is_alive() for t in workers)
    assert len(results)==2 and results[0]==results[1]
    assert len(_kind(store,EXPECTATION_TYPE))==1 and results[0].freeze_tick==4


def test_proposal_reference_mismatch_stops_before_resolution(monkeypatch):
    runtime,_,store,_=_fresh();flow=runtime.agent_action_loop.action_resolution_flow
    with runtime.write_fence.operation():
        proposal,attempt=_selected(runtime)
        monkeypatch.setattr(flow.resolution_engine,"resolve",lambda _:pytest.fail("Resolution called"))
        with pytest.raises(PermissionError,match="proposal/Attempt"):
            flow.execute_with_result(attempt,action_proposal=proposal,action_proposal_id="another-proposal",
                simulation_tick=runtime.context.clock.capture())
    assert not _kind(store,EXPECTATION_TYPE) and len(runtime.context.event_history.get_events())==1


def test_actual_selection_tick_is_not_reconstructed_at_later_freeze(monkeypatch):
    from cognitive_world.cognition import action_expectation as module
    runtime,_,store,_=_fresh();original=module.bind_selection
    def delay_after_selection(proposal,tick,**kwargs):
        with runtime.write_fence.commit_scope():runtime.context.clock.advance(3)
        return original(proposal,tick,**kwargs)
    monkeypatch.setattr(module,"bind_selection",delay_after_selection)
    with runtime.write_fence.operation():
        proposal,attempt=_selected(runtime)
        record=runtime.event_processor.action_expectations.freeze(attempt,proposal,origin="npc")
    assert record.decision_tick==4 and record.freeze_tick==7
    assert len(_kind(store,EXPECTATION_TYPE))==1


def test_communication_with_typed_claim_remains_outside_physical_b3():
    from test_npc_social_interaction import _world,_CommunicationProvider,AttributedClaimDraft
    store=MemoryStore()
    runtime,_,_,history,_=_world(communication=True,
        trust=HmacPersistenceTrust(b"b3-communication-independent-key00"),
        shared_memory_store=store,structured_claim=True)
    runtime.npc_communication_provider=_CommunicationProvider(claim=AttributedClaimDraft(
        "room","environment.light_on","boolean",False,0,5,"room:room"))
    runtime.step()
    event=next(e for e in history.get_events() if e.type=="dialogue_input")
    assert event.dialogue_payload.claim.speaker_id=="npc-a"
    assert "action_expectation_id" not in event.metadata
    assert not any(m.owner_id=="npc-a" for m in _kind(store,EXPECTATION_TYPE))
    assert not runtime.write_fence.recovery_required


def test_association_retry_does_not_reapply_behavior_feedback_or_consume():
    runtime,cognition,store,trust,event,_=_fixture()
    before=deepcopy((runtime.behavior_feedback.history,runtime.behavior_feedback._seen_events,
        dict(cognition.beliefs),dict(cognition.goals),dict(cognition.self_models)))
    records=store.get_all_memories()
    with runtime.write_fence.operation():
        runtime.event_processor.action_expectations.associate(event)
        runtime.event_processor.action_expectations.associate(event)
    assert before==(runtime.behavior_feedback.history,runtime.behavior_feedback._seen_events,
        dict(cognition.beliefs),dict(cognition.goals),dict(cognition.self_models))
    assert store.get_all_memories()==records
    assert not any(m.type.startswith("system_l1_") for m in records)
    _verify(runtime,store,trust)


def test_b3_fields_preserve_existing_positional_flow_constructor():
    from cognitive_world.resolution.action_flow import ActionResolutionFlow
    from cognitive_world.resolution.engine import ResolutionEngine
    from cognitive_world.event.factory import EventFactory
    from cognitive_world.core.world_state import WorldState
    engine,factory,world=ResolutionEngine(),EventFactory(),WorldState()
    flow=ActionResolutionFlow(engine,factory,world)
    assert flow.world_state is world and flow.resolution_engine is engine
    assert flow.event_factory is factory and flow.action_expectations is None
