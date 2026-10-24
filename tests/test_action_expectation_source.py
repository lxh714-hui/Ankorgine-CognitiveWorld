"""Trusted source binding: coordinated semantics tampering must fail closed."""
from dataclasses import replace
from hashlib import sha256
from copy import deepcopy
import pytest

from cognitive_world.cognition.action_expectation import (
    EXPECTATION_TYPE,ASSOCIATION_TYPE,EXPECTATION_PURPOSE,ASSOCIATION_PURPOSE,verify_records,
)
from cognitive_world.cognition.snapshot import (
    CognitiveStateSnapshot,cognitive_snapshot_codec,reconstruct_isolated,
)
from cognitive_world.core.persistence import sha256_hex
from test_l1_instance import _fixture,_capture
from test_action_expectation import _fresh,_selected,_kind


def _resigned_snapshot(snapshot,records,trust):
    from cognitive_world.cognition import snapshot as module
    codec=cognitive_snapshot_codec();by_id={m.id:m for m in records};groups=[]
    for group in snapshot.body.stores:
        if group.store_name!="memories":groups.append(group);continue
        values=tuple(replace(r,value=by_id[r.record_id]) for r in group.records if r.record_id in by_id)
        unsigned=replace(group,records=values,state_version="sha256:pending")
        groups.append(replace(unsigned,state_version="sha256:"+sha256_hex(codec.dumps(unsigned))))
    body=replace(snapshot.body,stores=tuple(groups));encoded=codec.dumps(body)
    purpose=getattr(module,"_COGNITIVE_SNAPSHOT_PURPOSE_V"+str(body.schema_version))
    return CognitiveStateSnapshot(body,"sha256:"+sha256_hex(encoded),trust.sign(purpose,encoded).hex())


@pytest.mark.parametrize("boundary",["issuance","records","decode","restore"])
def test_coordinated_semantics_attack_is_rejected_at_every_boundary(boundary,monkeypatch):
    if boundary=="issuance":
        runtime,cognition,store,trust=_fresh()
        with runtime.write_fence.operation():
            proposal,attempt=_selected(runtime)
            before=store.get_all_memories()
            events=runtime.context.event_history.get_events()
            with pytest.raises(PermissionError):
                runtime.event_processor.action_expectations.freeze(attempt,proposal,origin="player")
        assert store.get_all_memories()==before
        assert runtime.context.event_history.get_events()==events
        assert not _kind(store,EXPECTATION_TYPE) and not _kind(store,ASSOCIATION_TYPE)
        assert not runtime.write_fence.recovery_required
        _capture(runtime,cognition,store,trust)
        return
    runtime,cognition,store,trust,event,_=_fixture()
    snapshot=_capture(runtime,cognition,store,trust)
    before=store.get_all_memories();events=runtime.context.event_history.get_events()
    state=deepcopy((dict(runtime.context.world_state.environment),dict(runtime.context.world_state.locations)))
    expected=next(m for m in before if m.type==EXPECTATION_TYPE)
    association=next(m for m in before if m.type==ASSOCIATION_TYPE)
    changed=replace(expected.content,origin="player",representation="expectation_absent",
        expected_text=None,decision_tick=None,candidate_id=None,signature_hex="")
    changed=replace(changed,signature_hex=trust.sign(EXPECTATION_PURPOSE,changed.body()).hex())
    linked=replace(association.content,expectation_digest=sha256(changed.body()).hexdigest(),signature_hex="")
    linked=replace(linked,signature_hex=trust.sign(ASSOCIATION_PURPOSE,linked.body()).hex())
    assert changed.attempt_json==expected.content.attempt_json
    assert changed.attempt_fingerprint==expected.content.attempt_fingerprint
    records=tuple(replace(m,content=changed) if m.id==expected.id else
                  replace(m,content=linked) if m.id==association.id else m for m in before)
    tampered=_resigned_snapshot(snapshot,records,trust)
    flow=runtime.agent_action_loop.action_resolution_flow
    def replay(*args,**kwargs):pytest.fail("historical action or Event replayed")
    monkeypatch.setattr(flow.resolution_engine,"resolve",replay)
    monkeypatch.setattr(runtime.event_processor,"dispatch_with_evidence",replay)
    with pytest.raises(PermissionError):
        if boundary=="records":
            verify_records(records,history=runtime.context.event_history,trust=trust,
                checkpoint_tick=runtime.context.clock.current_time,lineage=runtime.memory_revision_lineage)
        elif boundary=="decode":
            CognitiveStateSnapshot.from_bytes(tampered.to_bytes(),trust=trust)
        else:
            reconstruct_isolated(tampered,trust=trust,expected_agents=snapshot.body.expected_agents,
                event_history=runtime.context.event_history,memory_revision_lineage=runtime.memory_revision_lineage)
    assert store.get_all_memories()==before and runtime.context.event_history.get_events()==events
    assert state==(dict(runtime.context.world_state.environment),dict(runtime.context.world_state.locations))
    assert not runtime.write_fence.recovery_required


from cognitive_world.cognition.action_expectation_source import (
    ActionExpectationSourceBinding,NpcSelectedExpectation,PlayerExpectationAbsent,
    SOURCE_TYPE,SOURCE_PURPOSE,SOURCE_POLICY,SOURCE_REF_KEY,PLAYER_ABSENCE_POLICY,
    _PLAYER_ENTRY_AUTHORITY,source_digest,verify_source_records,AmbiguousActionExpectationSource,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.persistence import HmacPersistenceTrust


def test_genuine_npc_source_is_separate_and_bound_to_final_attempt():
    runtime,cognition,store,trust=_fresh()
    with runtime.write_fence.operation():
        proposal,attempt=_selected(runtime)
        binding,=_kind(store,SOURCE_TYPE)
        assert type(binding.content) is ActionExpectationSourceBinding
        assert type(binding.content.source_data) is NpcSelectedExpectation
        assert binding.content.source_data.expected_text==proposal.parameters["expected_result"]
        assert binding.content.source_data.candidate_id==proposal.metadata["selected_candidate_id"]
        assert binding.content.source_data.decision_tick==proposal._b3_selection.tick==4
        reference=attempt.metadata[SOURCE_REF_KEY]
        assert reference=={"version":1,"record_id":binding.id,"content_digest":source_digest(binding.content)}
        expected=runtime.event_processor.action_expectations.freeze(attempt,proposal,origin="npc")
    assert expected.expected_text==binding.content.source_data.expected_text
    assert expected.candidate_id==binding.content.source_data.candidate_id
    assert expected.decision_tick==binding.content.source_data.decision_tick
    assert not store.is_semantically_retrievable(binding)
    assert binding.type!=EXPECTATION_TYPE and binding.type!=ASSOCIATION_TYPE
    assert _capture(runtime,cognition,store,trust).body.schema_version==5
    assert "permit" not in binding.content.__dataclass_fields__


def test_player_absence_uses_entry_provenance_not_open_parameter_presence():
    from pathlib import Path
    from anchor_desktop.world_packages import WorldPackageCatalog
    from anchor_desktop.host import start_new_world
    from cognitive_world.decision.action_proposal import ActionProposal
    from cognitive_world.decision.action_pipeline import ActionPipeline
    package=WorldPackageCatalog(Path(__file__).parents[1]/"src"/"anchor_desktop"/"worlds").package("clockwork-library")
    session=start_new_world(package,trust=HmacPersistenceTrust(b"source-player-test-key-0000000000"))
    try:
        issuer=session.runtime.event_processor.action_expectations
        owner=session.runtime.context.player_session.controlled_agent_id
        with session.runtime.write_fence.operation():
            proposal=ActionProposal("player-source-case",owner,"inspect",parameters={
                "method":"look","expected_result":"unrelated open parameter; not a player prediction"})
            binding=issuer.issue_player_source(proposal,authority=_PLAYER_ENTRY_AUTHORITY)
            first=binding
            session.runtime.context.clock.advance(2)
            assert issuer.issue_player_source(proposal,authority=_PLAYER_ENTRY_AUTHORITY)==first
            attempt=ActionPipeline().create_attempt(proposal)
            record=issuer.freeze(attempt,proposal,origin="player")
            assert issuer.freeze(attempt,proposal,origin="player")==record
        assert type(binding.source_data) is PlayerExpectationAbsent
        assert record.representation=="expectation_absent" and record.expected_text is None
        assert record.decision_tick is None and record.candidate_id is None
        assert attempt.parameters["expected_result"] is not None
        verify_source_records(session.memory_store.get_all_memories(),issuer.trust)
        assert len(_kind(session.memory_store,SOURCE_TYPE))==1
    finally:session.close()


@pytest.mark.parametrize("field,value",[("origin","player"),("decision_tick",0),("candidate_id","wrong"),
    ("representation","expectation_absent"),("expected_text",None)])
def test_signed_individual_semantic_claims_cannot_override_source(field,value):
    runtime,cognition,store,trust,_,_=_fixture()
    snapshot=_capture(runtime,cognition,store,trust);before=store.get_all_memories()
    expected=next(m for m in before if m.type==EXPECTATION_TYPE)
    association=next(m for m in before if m.type==ASSOCIATION_TYPE)
    changed=replace(expected.content,**{field:value},signature_hex="")
    changed=replace(changed,signature_hex=trust.sign(EXPECTATION_PURPOSE,changed.body()).hex())
    link=replace(association.content,expectation_digest=sha256(changed.body()).hexdigest(),signature_hex="")
    link=replace(link,signature_hex=trust.sign(ASSOCIATION_PURPOSE,link.body()).hex())
    records=tuple(replace(m,content=changed) if m.id==expected.id else
        replace(m,content=link) if m.id==association.id else m for m in before)
    with pytest.raises(PermissionError):
        CognitiveStateSnapshot.from_bytes(_resigned_snapshot(snapshot,records,trust).to_bytes(),trust=trust)
    assert store.get_all_memories()==before


@pytest.mark.parametrize("field,value",[("timeline_id","foreign-timeline"),("proposal_id","foreign-proposal"),
    ("proposal_digest","0"*64),("policy","unknown/v2"),("version",99)])
def test_source_binding_resigning_cannot_change_fingerprint_reference(field,value):
    runtime,cognition,store,trust,_,_=_fixture()
    snapshot=_capture(runtime,cognition,store,trust);before=store.get_all_memories()
    source=next(m for m in before if m.type==SOURCE_TYPE)
    changed=replace(source.content,**{field:value},signature_hex="")
    changed=replace(changed,signature_hex=trust.sign(SOURCE_PURPOSE,changed.body()).hex())
    records=tuple(replace(m,content=changed) if m.id==source.id else m for m in before)
    with pytest.raises(PermissionError):
        CognitiveStateSnapshot.from_bytes(_resigned_snapshot(snapshot,records,trust).to_bytes(),trust=trust)
    assert store.get_all_memories()==before


def test_resigned_source_kind_and_all_expectation_claims_still_cannot_change_attempt():
    runtime,cognition,store,trust,_,_=_fixture()
    snapshot=_capture(runtime,cognition,store,trust);before=store.get_all_memories()
    source=next(m for m in before if m.type==SOURCE_TYPE)
    expected=next(m for m in before if m.type==EXPECTATION_TYPE)
    association=next(m for m in before if m.type==ASSOCIATION_TYPE)
    binding=replace(source.content,source_kind="player_action",representation="expectation_absent",
        source_data=PlayerExpectationAbsent(PLAYER_ABSENCE_POLICY),signature_hex="")
    binding=replace(binding,signature_hex=trust.sign(SOURCE_PURPOSE,binding.body()).hex())
    changed=replace(expected.content,origin="player",representation="expectation_absent",expected_text=None,
        decision_tick=None,candidate_id=None,signature_hex="")
    changed=replace(changed,signature_hex=trust.sign(EXPECTATION_PURPOSE,changed.body()).hex())
    linked=replace(association.content,expectation_digest=sha256(changed.body()).hexdigest(),signature_hex="")
    linked=replace(linked,signature_hex=trust.sign(ASSOCIATION_PURPOSE,linked.body()).hex())
    contents={source.id:binding,expected.id:changed,association.id:linked}
    records=tuple(replace(m,content=contents[m.id]) if m.id in contents else m for m in before)
    assert changed.attempt_json==expected.content.attempt_json
    with pytest.raises(PermissionError,match="source binding mismatch"):
        CognitiveStateSnapshot.from_bytes(_resigned_snapshot(snapshot,records,trust).to_bytes(),trust=trust)


@pytest.mark.parametrize("stage",["validate","sign","store_validate","store_before","store_after"])
def test_source_publication_failure_stops_before_attempt_and_freezes_when_uncertain(stage,monkeypatch):
    from cognitive_world.cognition import action_expectation as module
    runtime,cognition,store,trust=_fresh()
    validate=module.validate_structure;commit=MemoryStore._commit_action_record;sign=HmacPersistenceTrust.sign
    def fail(*args,**kwargs):raise OSError("source publication injection")
    if stage=="validate":
        def validating(record):
            if type(record) is ActionExpectationSourceBinding:fail()
            return validate(record)
        monkeypatch.setattr(module,"validate_structure",validating)
    elif stage=="sign":
        def signing(self,purpose,payload):
            if purpose==SOURCE_PURPOSE:fail()
            return sign(self,purpose,payload)
        monkeypatch.setattr(HmacPersistenceTrust,"sign",signing)
    else:
        def committing(self,memory,**kwargs):
            if memory.type==SOURCE_TYPE:
                if stage=="store_validate":return commit(self,replace(memory,owner_id="wrong"),**kwargs)
                if stage=="store_after":commit(self,memory,**kwargs)
                fail()
            return commit(self,memory,**kwargs)
        monkeypatch.setattr(MemoryStore,"_commit_action_record",committing)
    def replay(*args,**kwargs):pytest.fail("Attempt or Resolution reached after source failure")
    monkeypatch.setattr(runtime.agent_action_loop.action_pipeline,"create_attempt",replay)
    monkeypatch.setattr(runtime.agent_action_loop.action_resolution_flow.resolution_engine,"resolve",replay)
    with runtime.write_fence.operation():
        with pytest.raises((OSError,PermissionError)):_selected(runtime)
    assert len(runtime.context.event_history.get_events())==1
    assert not _kind(store,EXPECTATION_TYPE) and not _kind(store,ASSOCIATION_TYPE)
    assert len(_kind(store,SOURCE_TYPE))==(1 if stage=="store_after" else 0)
    assert runtime.write_fence.recovery_required==(stage!="validate")
    monkeypatch.undo()
    if stage!="validate":
        with pytest.raises(PermissionError):_capture(runtime,cognition,store,trust)
    else:_capture(runtime,cognition,store,trust)


def test_source_issuance_retry_and_conflict_keep_original_identity_and_tick(monkeypatch):
    from cognitive_world.cognition import action_expectation as module
    runtime,_,store,_=_fresh();issuer=runtime.event_processor.action_expectations
    real_bind=module.bind_selection;captured=[]
    def capture(proposal,stamp,*,selected=None):
        captured.append((proposal,stamp,selected))
        return real_bind(proposal,stamp,selected=selected)
    monkeypatch.setattr(module,"bind_selection",capture)
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime);first=_kind(store,SOURCE_TYPE)[0].content
        runtime.context.clock.advance(3)
        with module.selection_scope(issuer):
            real_bind(proposal,captured[0][1],selected=captured[0][2])
        assert _kind(store,SOURCE_TYPE)[0].content==first and first.issued_tick==4
        proposal.action_type="changed after original selection"
        with module.selection_scope(issuer):
            with pytest.raises(PermissionError,match="conflicting"):
                real_bind(proposal,captured[0][1],selected=captured[0][2])
    assert len(_kind(store,SOURCE_TYPE))==1


def test_source_reference_cannot_be_transplanted_to_another_proposal():
    from cognitive_world.decision.action_proposal import ActionProposal
    from cognitive_world.decision.action_pipeline import ActionPipeline
    runtime,_,store,_=_fresh()
    with runtime.write_fence.operation():
        proposal,_=_selected(runtime)
        other=ActionProposal("another-proposal",proposal.agent_id,proposal.action_type,
            proposal.target_refs,proposal.parameters,proposal.reasoning_refs,proposal.metadata)
        other._b3_source=proposal._b3_source
        with pytest.raises(PermissionError):ActionPipeline().create_attempt(other)
    assert len(_kind(store,SOURCE_TYPE))==1 and not _kind(store,EXPECTATION_TYPE)


@pytest.mark.parametrize("when",["before_source","after_source"])
def test_runtime_generation_and_cancellation_do_not_authorize_delayed_source(when):
    from contextvars import copy_context
    runtime,_,store,_=_fresh();fence=runtime.write_fence
    if when=="before_source":
        with fence.operation() as permit:
            context=copy_context();assert fence.revoke_uncommitted(permit)
        with pytest.raises(PermissionError):context.run(_selected,runtime)
        assert not _kind(store,SOURCE_TYPE)
    else:
        with fence.operation() as permit:
            proposal,attempt=_selected(runtime);context=copy_context()
            assert not fence.revoke_uncommitted(permit)
        fence.freeze_and_advance();fence.unfreeze()
        with pytest.raises(PermissionError):
            context.run(runtime.event_processor.action_expectations.freeze,attempt,proposal,origin="npc")
        assert len(_kind(store,SOURCE_TYPE))==1 and not _kind(store,EXPECTATION_TYPE)


def test_legacy_attempt_without_binding_keeps_exact_old_pipeline_fingerprint(monkeypatch):
    import subprocess,types,sys
    from cognitive_world.decision import action_pipeline as current
    from cognitive_world.decision.action_proposal import ActionProposal
    source=subprocess.check_output(['git','show','HEAD:src/cognitive_world/decision/action_pipeline.py'],text=True,encoding='utf-8')
    legacy=types.ModuleType('b3_legacy_pipeline_test')
    monkeypatch.setitem(sys.modules,legacy.__name__,legacy)
    exec(compile(source,'<archived-action-pipeline>','exec'),legacy.__dict__)
    fixed=lambda:types.SimpleNamespace(hex="unchanged-legacy-attempt")
    legacy.uuid4=fixed;monkeypatch.setattr(current,'uuid4',fixed)
    proposal=ActionProposal("legacy-proposal","owner","open",["object:door"],{"method":"push the door"},
        ["old-reference"],{"legacy":True})
    old=legacy.ActionPipeline().create_attempt(proposal)
    new=current.ActionPipeline().create_attempt(proposal)
    assert new._resolution_snapshot()==old._resolution_snapshot()
    assert new.content_fingerprint()==old.content_fingerprint()
    assert SOURCE_REF_KEY not in new.metadata


def test_legacy_unbound_b3_is_readable_but_not_promoted_to_verified_history():
    import json
    from cognitive_world.decision.attempt import Attempt
    from cognitive_world.cognition import snapshot as module
    runtime,cognition,store,trust=_fresh()
    with runtime.write_fence.operation():
        proposal,attempt=_selected(runtime)
        expected=runtime.event_processor.action_expectations.freeze(attempt,proposal,origin="npc")
    snapshot=_capture(runtime,cognition,store,trust)
    values=json.loads(expected.attempt_json);values[6].pop(SOURCE_REF_KEY)
    from cognitive_world.cognition.action_expectation_source import canonical
    legacy=replace(expected,attempt_json=canonical(values).decode(),
        attempt_fingerprint=Attempt.fingerprint_snapshot(values),signature_hex="")
    legacy=replace(legacy,signature_hex=trust.sign(EXPECTATION_PURPOSE,legacy.body()).hex())
    records=tuple(replace(m,content=legacy) if m.type==EXPECTATION_TYPE else m
        for m in store.get_all_memories() if m.type!=SOURCE_TYPE)
    changed=_resigned_snapshot(snapshot,records,trust)
    body=replace(changed.body,schema_version=4);codec=cognitive_snapshot_codec();data=codec.dumps(body)
    old=CognitiveStateSnapshot(body,"sha256:"+sha256_hex(data),
        trust.sign(module._COGNITIVE_SNAPSHOT_PURPOSE_V4,data).hex())
    raw=codec.loads(old.to_bytes())
    assert raw.body.schema_version==4
    with pytest.raises(AmbiguousActionExpectationSource):CognitiveStateSnapshot.from_bytes(old.to_bytes(),trust=trust)
    with pytest.raises(AmbiguousActionExpectationSource):
        reconstruct_isolated(raw,trust=trust,expected_agents=snapshot.body.expected_agents,
            event_history=runtime.context.event_history,memory_revision_lineage=runtime.memory_revision_lineage)
    assert store.get_all_memories()!=records and len(_kind(store,SOURCE_TYPE))==1


@pytest.mark.parametrize("bad_kind",["unknown_source","wrong_payload","invalid_absence_policy","future_version","future_time"])
def test_closed_source_schemas_and_checkpoint_time_reject_resigned_payloads(bad_kind):
    runtime,cognition,store,trust=_fresh()
    with runtime.write_fence.operation():proposal,_=_selected(runtime)
    snapshot=_capture(runtime,cognition,store,trust)
    memory,=_kind(store,SOURCE_TYPE);binding=memory.content
    if bad_kind=="unknown_source":binding=replace(binding,source_kind="model_claim")
    elif bad_kind=="wrong_payload":binding=replace(binding,source_data={"candidate_id":"forged","extra":True})
    elif bad_kind=="invalid_absence_policy":
        binding=replace(binding,source_kind="player_action",representation="expectation_absent",
                        source_data=PlayerExpectationAbsent("unregistered-player-contract"))
    elif bad_kind=="future_version":binding=replace(binding,version=99)
    else:
        binding=replace(binding,issued_tick=100,source_data=replace(binding.source_data,decision_tick=100))
    binding=replace(binding,signature_hex=trust.sign(SOURCE_PURPOSE,binding.body()).hex())
    records=tuple(replace(m,content=binding) if m.id==memory.id else m for m in store.get_all_memories())
    with pytest.raises(PermissionError):
        CognitiveStateSnapshot.from_bytes(_resigned_snapshot(snapshot,records,trust).to_bytes(),trust=trust)


def test_source_specific_dataclasses_have_no_missing_field_defaults_or_extra_fields():
    with pytest.raises(TypeError):NpcSelectedExpectation(candidate_id="candidate")
    with pytest.raises(TypeError):PlayerExpectationAbsent()
    with pytest.raises(TypeError):PlayerExpectationAbsent(PLAYER_ABSENCE_POLICY,candidate_id="not-player-data")


def test_missing_source_does_not_fall_back_to_record_origin():
    runtime,cognition,store,trust,_,_=_fixture()
    snapshot=_capture(runtime,cognition,store,trust)
    records=tuple(m for m in store.get_all_memories() if m.type!=SOURCE_TYPE)
    with pytest.raises(AmbiguousActionExpectationSource):
        CognitiveStateSnapshot.from_bytes(_resigned_snapshot(snapshot,records,trust).to_bytes(),trust=trust)


def test_mutable_receipt_claim_cannot_supply_a_source_reference():
    from types import SimpleNamespace
    from cognitive_world.decision.action_pipeline import ActionPipeline
    from cognitive_world.decision.action_proposal import ActionProposal
    proposal=ActionProposal("untrusted-source-receipt","actor","inspect",parameters={"method":"look"})
    class ForgedIssuer:
        def reference_for(self,*args):pytest.fail("untrusted issuer was called")
    proposal._b3_source=SimpleNamespace(issuer=ForgedIssuer())
    with pytest.raises(PermissionError,match="trusted source receipt"):
        ActionPipeline().create_attempt(proposal)


def test_final_attempt_freezing_stays_inside_original_source_fence(monkeypatch):
    from cognitive_world.decision import action_pipeline as module
    runtime,_,_,_=_fresh();original=module.Attempt;checked=[]
    def construct(**kwargs):
        with pytest.raises(RuntimeError,match="inside a commit"):
            runtime.write_fence.freeze_and_advance()
        attempt=original(**kwargs)
        assert attempt._frozen and SOURCE_REF_KEY in attempt.metadata
        checked.append(attempt.attempt_id)
        return attempt
    monkeypatch.setattr(module,"Attempt",construct)
    with runtime.write_fence.operation():_selected(runtime)
    assert len(checked)==1
