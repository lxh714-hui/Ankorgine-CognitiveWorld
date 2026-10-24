"""B2 production-bound acceptance, proof, recovery and compatibility tests."""
from contextvars import copy_context
from dataclasses import replace
from threading import Barrier, Thread

import pytest

from cognitive_world.cognition.l1_instance import (
    L1ConsumptionInstance, InstanceL1ConsumptionProof, INSTANCE_PROOF_MEMORY_TYPE,
    INSTANCE_PROOF_PURPOSE, RESULT_RULE, verify_instance_proof, default_instance_id,
)
from cognitive_world.cognition.l1_consumption_proof import _observation_digest
from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, cognitive_snapshot_codec, reconstruct_isolated
from cognitive_world.core.persistence import HmacPersistenceTrust, PersistedValueCodec
from cognitive_world.observation.generator import ObservationGenerator
from cognitive_world.observation.historical_rules import HistoricalObservationRuleRegistry
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from test_runtime_reconstruction import _dependency_manifest
from test_save_restore_end_to_end import (
    _live_runtime, _observe_door, _fail_open_door_in_turn, DoorRuntimeAssembler,
    AGENT_ID, DOOR_ID, PARENT,
)


def _fixture():
    trust = HmacPersistenceTrust(b'b2-instance-test-trust-material-32')
    runtime, cognition, memory = _live_runtime(trust, door_locked=True)
    _observe_door(runtime, 'b2-initial-door')
    event = _fail_open_door_in_turn(runtime)
    observation, = [o for o in runtime.context.observation_store.get_by_observer(AGENT_ID)
                    if o.content.fact_type == 'action_result']
    return runtime, cognition, memory, trust, event, observation


def _accept(runtime, observation):
    turn = runtime.agent_action_loop.agent_turn
    context = runtime.cognition_context_provider(runtime.context.agent_registry.get(AGENT_ID))
    return turn.l1_consumption_issuer.accept_owner_result(
        owner_id=AGENT_ID, observation=observation, cognitive_runtime=turn.cognitive_runtime,
        memory_store=context.memory_store)


def _proofs(memory):
    return tuple(m.content for m in memory.get_all_memories() if m.type == INSTANCE_PROOF_MEMORY_TYPE)


def _capture(runtime, cognition, memory, trust):
    context = runtime.cognition_context_provider(runtime.context.agent_registry.get(AGENT_ID))
    with runtime.write_fence.operation():
        return CognitiveStateSnapshot.capture(runtime=runtime, cognition=cognition, memory_store=memory,
            agent_contexts=(context,), timeline_id=runtime.context.event_history.timeline_id, trust=trust)


def _save(manager, runtime, cognition, memory):
    context = runtime.cognition_context_provider(runtime.context.agent_registry.get(AGENT_ID))
    return manager.create_manual_save(runtime=runtime, cognition=cognition, memory_store=memory,
                                     agent_contexts=(context,))


def _reissue(runtime, event_id):
    history = runtime.context.event_history
    count = len(history.get_events())
    with runtime.write_fence.operation():
        runtime.event_processor.dispatch_with_evidence(history.get_event(event_id))
    issued = [o for o in runtime.context.observation_store.get_by_observer(AGENT_ID)
              if o.source_event_id == event_id]
    assert len(issued) == 1 and len(history.get_events()) == count
    return issued[0]


def test_real_agent_turn_consumes_once_without_semantic_revision_or_world_replay():
    runtime, cognition, memory, trust, event, observation = _fixture()
    assert not _proofs(memory)
    context = runtime.cognition_context_provider(runtime.context.agent_registry.get(AGENT_ID))
    before = (dict(cognition.beliefs), dict(cognition.goals), dict(cognition.self_models))
    count = len(runtime.context.event_history.get_events())
    with runtime.write_fence.operation():
        runtime.agent_action_loop.agent_turn.prepare_decision_context(
            runtime.context.agent_registry.get(AGENT_ID), context,
            simulation_tick=runtime.context.clock.capture())
    proof, = _proofs(memory)
    assert proof.instance.consumption_tick == runtime.context.clock.current_time
    assert proof.instance.owner_id == AGENT_ID and proof.instance.timeline_id == PARENT
    assert proof.instance.observation_id == observation.observation_id
    assert proof.instance.observation_sha256 == _observation_digest(observation)
    assert proof.source_event_id == event.id and proof.fact_id == observation.content.fact_id
    assert proof.attempt_id == event.cause
    verify_instance_proof(proof, history=runtime.context.event_history, trust=trust,
        checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time)
    assert count == len(runtime.context.event_history.get_events())
    assert not runtime.context.world_state.environment[DOOR_ID].is_open
    assert before == (dict(cognition.beliefs), dict(cognition.goals), dict(cognition.self_models))
    assert context.get_memories() == ()
    records = memory.get_all_memories()
    b2_records = tuple(item for item in records if item.type == INSTANCE_PROOF_MEMORY_TYPE)
    assert len(b2_records) == 1 and b2_records[0].content == proof
    from cognitive_world.cognition.action_expectation import EXPECTATION_TYPE, ActionExpectationRecord
    b3_records = tuple(item for item in records if item.type == EXPECTATION_TYPE)
    assert len(b3_records) == 1 and type(b3_records[0].content) is ActionExpectationRecord
    assert records.index(b3_records[0]) < records.index(b2_records[0])
    assert b3_records[0].type != INSTANCE_PROOF_MEMORY_TYPE
    assert not memory.is_semantically_retrievable(b3_records[0])


def test_duplicate_input_retrieval_and_delivery_preserve_instance_time_and_percept():
    runtime, _, memory, _, _, observation = _fixture()
    with runtime.write_fence.operation():
        first = _accept(runtime, observation)
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    receipt = l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)]
    for _ in range(2):
        runtime.context.clock.advance(3)
        runtime.context.observation_store.add(observation)
        retrieved = runtime.context.observation_store.get(observation.observation_id)
        with runtime.write_fence.operation():
            assert _accept(runtime, retrieved) == first
        l1.process(AGENT_ID, (retrieved,))
        assert l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)] == receipt
    assert len(_proofs(memory)) == 1
    assert l1.working_memory_store.get(AGENT_ID).percept_ids.count('percept:' + observation.observation_id) == 1
    assert default_instance_id(PARENT, AGENT_ID, observation.observation_id) == first.instance.instance_id


def test_late_signing_does_not_change_original_consumption_tick(monkeypatch):
    runtime, _, memory, _, _, observation = _fixture()
    trust = runtime.agent_action_loop.agent_turn.l1_consumption_issuer.trust
    original = HmacPersistenceTrust.sign
    original_tick = runtime.context.clock.current_time
    def delayed(self, purpose, body):
        if purpose == INSTANCE_PROOF_PURPOSE:
            runtime.context.clock.advance(4)
        return original(self, purpose, body)
    monkeypatch.setattr(HmacPersistenceTrust, 'sign', delayed)
    with runtime.write_fence.operation():
        proof = _accept(runtime, observation)
    assert proof.instance.consumption_tick == original_tick
    assert len(_proofs(memory)) == 1


@pytest.mark.parametrize('field', ['observer_id', 'observation_id', 'source_event_id', 'content'])
def test_tampered_observation_rejected_before_l1(field):
    runtime, _, memory, _, _, observation = _fixture()
    bad = replace(observation, **{field: 'forged' if field != 'content' else replace(observation.content, subject_ref='other-door')})
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError):
            _accept(runtime, bad)
    assert not _proofs(memory) and not runtime.write_fence.recovery_required


@pytest.mark.parametrize('stage', ['working_memory', 'receipt', 'construct', 'sign', 'validation', 'store_before', 'store_after'])
def test_post_l1_failures_freeze_writes_and_capture_without_replay(stage, monkeypatch):
    from cognitive_world.cognition import l1_instance
    from cognitive_world.cognition.memory_store import MemoryStore
    from cognitive_world.cognition.working_memory import WorkingMemoryStore
    from cognitive_world.cognition.runtime import CognitiveRuntime
    runtime, cognition, memory, trust, event, observation = _fixture()
    count = len(runtime.context.event_history.get_events())
    original_commit = MemoryStore._commit_system_proof
    def fail(*args, **kwargs):
        raise RuntimeError('injected ' + stage)
    if stage == 'working_memory':
        monkeypatch.setattr(WorkingMemoryStore, 'update', fail)
    elif stage == 'receipt':
        monkeypatch.setattr(CognitiveRuntime, '_publish_result_receipt', fail)
    elif stage == 'construct':
        monkeypatch.setattr(l1_instance, '_construct_instance_proof', fail)
    elif stage == 'sign':
        original = HmacPersistenceTrust.sign
        def sign(self, purpose, payload):
            if purpose == INSTANCE_PROOF_PURPOSE: fail()
            return original(self, purpose, payload)
        monkeypatch.setattr(HmacPersistenceTrust, 'sign', sign)
    elif stage == 'validation':
        def invalid(self, record, **kwargs):
            return original_commit(self, replace(record, owner_id='wrong'), **kwargs)
        monkeypatch.setattr(MemoryStore, '_commit_system_proof', invalid)
    else:
        def broken(self, *args, **kwargs):
            if stage == 'store_after': original_commit(self, *args, **kwargs)
            fail()
        monkeypatch.setattr(MemoryStore, '_commit_system_proof', broken)
    with runtime.write_fence.operation():
        with pytest.raises((RuntimeError, PermissionError)):
            _accept(runtime, observation)
    assert runtime.write_fence.recovery_required and runtime.write_fence.frozen
    assert len(_proofs(memory)) == (1 if stage == 'store_after' else 0)
    with pytest.raises(PermissionError):
        with runtime.write_fence.operation(): pass
    with pytest.raises(PermissionError):
        _capture(runtime, cognition, memory, trust)
    assert len(runtime.context.event_history.get_events()) == count
    assert not runtime.context.world_state.environment[DOOR_ID].is_open


def test_runtime_stops_on_actual_production_signing_failure(monkeypatch):
    runtime, _, memory, _, _, _ = _fixture()
    original = HmacPersistenceTrust.sign
    def sign(self, purpose, payload):
        if purpose == INSTANCE_PROOF_PURPOSE: raise RuntimeError('injected signing failure')
        return original(self, purpose, payload)
    monkeypatch.setattr(HmacPersistenceTrust, 'sign', sign)
    runtime.context.agent_scheduler.schedule_agent(AGENT_ID, runtime.context.clock.current_time + 1)
    runtime.step()
    assert runtime.write_fence.recovery_required and not runtime.running
    assert runtime.last_agent_turn_results[0].failure_type == 'RuntimeError'
    with pytest.raises(RuntimeError, match='recovery'):
        runtime.step()
    assert not _proofs(memory)


def test_concurrent_acceptance_has_one_instance_and_one_signature(monkeypatch):
    runtime, _, memory, _, _, observation = _fixture()
    barrier = Barrier(3)
    results, errors, signatures = [], [], []
    original = HmacPersistenceTrust.sign
    def sign(self, purpose, payload):
        if purpose == INSTANCE_PROOF_PURPOSE: signatures.append(payload)
        return original(self, purpose, payload)
    monkeypatch.setattr(HmacPersistenceTrust, 'sign', sign)
    def accept():
        try:
            with runtime.write_fence.operation():
                barrier.wait(5)
                results.append(_accept(runtime, observation))
        except BaseException as error: errors.append(error)
    threads = [Thread(target=accept) for _ in range(2)]
    for thread in threads: thread.start()
    barrier.wait(5)
    for thread in threads: thread.join(10)
    assert not errors and all(not t.is_alive() for t in threads)
    assert results[0] == results[1] and len(_proofs(memory)) == 1
    # HMAC verify calls sign too; every invocation must use the identical body.
    assert signatures and len(set(signatures)) == 1


@pytest.mark.parametrize('kind', ['cancel', 'generation', 'no_permit'])
def test_invalidated_acceptance_cannot_commit(kind):
    runtime, _, memory, _, _, observation = _fixture()
    with runtime.write_fence.operation() as permit:
        context = copy_context()
        if kind == 'cancel': assert runtime.write_fence.revoke_uncommitted(permit)
    if kind == 'generation':
        runtime.write_fence.freeze_and_advance(); runtime.write_fence.unfreeze()
    with pytest.raises(PermissionError):
        (_accept(runtime, observation) if kind == 'no_permit' else context.run(_accept, runtime, observation))
    assert not _proofs(memory)


def test_legacy_direct_process_cannot_be_promoted_to_b2():
    runtime, _, memory, _, _, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    l1.process(AGENT_ID, (observation,))
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError, match='ambiguous'):
            _accept(runtime, observation)
        with pytest.raises(PermissionError, match='B2 requires'):
            runtime.agent_action_loop.agent_turn.l1_consumption_issuer.issue_after_l1(
                owner_id=AGENT_ID, observation=observation, cognitive_runtime=l1, memory_store=memory)
    assert not _proofs(memory)


def test_signed_snapshot_roundtrip_verifies_without_issuer(monkeypatch):
    from cognitive_world.cognition.l1_consumption_proof import L1ConsumptionIssuer
    runtime, cognition, memory, trust, _, observation = _fixture()
    with runtime.write_fence.operation():
        proof = _accept(runtime, observation)
    snapshot = _capture(runtime, cognition, memory, trust)
    def forbidden(*args, **kwargs): pytest.fail('restore must not issue a proof')
    monkeypatch.setattr(L1ConsumptionIssuer, 'accept_owner_result', forbidden)
    monkeypatch.setattr(L1ConsumptionIssuer, 'issue_after_l1', forbidden)
    decoded = CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust)
    restored = reconstruct_isolated(decoded, trust=trust, expected_agents=snapshot.body.expected_agents,
        event_history=runtime.context.event_history)
    assert _proofs(restored.memory_store) == (proof,)


@pytest.mark.parametrize('field', ['version', 'fact_id', 'source_event_id', 'attempt_id', 'attempt_fingerprint',
                                 'source_timeline_id', 'event_tick', 'visibility_rule', 'signature_hex'])
def test_even_resigned_semantically_mismatched_proof_rejects(field):
    runtime, _, _, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    bad = replace(proof, **{field: 99 if field in {'version', 'event_tick'} else 'wrong'})
    bad = replace(bad, signature_hex=trust.sign(INSTANCE_PROOF_PURPOSE, bad.body()).hex())
    if field == 'signature_hex': bad = replace(bad, signature_hex='00' * 32)
    with pytest.raises(PermissionError):
        verify_instance_proof(bad, history=runtime.context.event_history, trust=trust,
            checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time)


def test_missing_historical_rule_fails_closed():
    runtime, _, _, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    with pytest.raises(PermissionError):
        verify_instance_proof(proof, history=runtime.context.event_history, trust=trust,
            checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time,
            rule_registry=HistoricalObservationRuleRegistry(()))


@pytest.mark.parametrize('with_proof', [False, True])
def test_cold_resume_existing_timeline_preserves_proof_or_defers_ambiguous_history(tmp_path, monkeypatch, with_proof):
    runtime, cognition, memory, trust, event, observation = _fixture()
    proof = None
    if with_proof:
        with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    stage = manager.stage_cold_resume(saved.save_id, timeline_id=PARENT,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())
    cold = ColdRuntimePublisher().activate(stage).current
    owner = cold.context.agent_registry.get(AGENT_ID)
    restored_memory = cold.cognition_context_provider(owner).memory_store
    delivered = _reissue(cold, event.id)
    count = len(cold.context.event_history.get_events())
    with cold.write_fence.operation():
        if with_proof:
            assert _accept(cold, delivered) == proof
        else:
            with pytest.raises(PermissionError, match='ambiguous'):
                _accept(cold, delivered)
    assert len(cold.context.event_history.get_events()) == count
    assert _proofs(restored_memory) == ((proof,) if with_proof else ())
    assert not cold.write_fence.recovery_required
    # New post-restore source Events are not the ambiguous historical input.
    from cognitive_world.decision import ActionPipeline
    from cognitive_world.decision.context import DecisionContext
    from cognitive_world.cognition.action_expectation import selection_scope
    # A fresh physical action now needs a genuine entry source. Establish fresh
    # authorized door evidence without promoting the ambiguous old result.
    _observe_door(cold,'post-resume-known-door')
    context=cold.cognition_context_provider(owner)
    l1=cold.agent_action_loop.agent_turn.cognitive_runtime
    current_observations=tuple(o for o in cold.context.observation_store.get_by_observer(AGENT_ID)
        if o.source_event_id=='post-resume-known-door')
    with cold.write_fence.operation():
        state=l1.process(AGENT_ID,current_observations,
            beliefs=context.get_beliefs(),goals=context.get_goals())
        decision_context=DecisionContext(cognition_state=state,percepts=tuple(state.percepts),
            goals=tuple(context.get_goals()),beliefs=tuple(context.get_beliefs()),
            self_model=context.get_self_model(),personality=context.get_personality(),
            working_memory=l1.working_memory_store.get(AGENT_ID))
        with selection_scope(cold.event_processor.action_expectations):
            proposal=cold.agent_decision.propose(decision_context)
        assert proposal.target_refs==[DOOR_ID]
        new_event = cold.agent_action_loop.action_resolution_flow.execute(
            ActionPipeline().create_attempt(proposal), simulation_tick=cold.context.clock.capture())
        cold.event_processor.dispatch_with_evidence(new_event)
        new_observation = next(o for o in cold.context.observation_store.get_by_observer(AGENT_ID)
                               if o.source_event_id == new_event.id)
        new_proof = _accept(cold, new_observation)
    assert new_proof.instance.timeline_id == PARENT
    assert new_proof.instance.observation_id != observation.observation_id


def test_verified_fork_inherits_ancestor_and_isolates_new_child_consumption(tmp_path):
    runtime, cognition, memory, trust, event, observation = _fixture()
    with runtime.write_fence.operation(): parent_proof = _accept(runtime, observation)
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    def fork(active, name):
        stage = manager.stage_restore(saved.save_id, timeline_id=PARENT, active_runtime=active,
            assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(), new_timeline_id=name)
        return RestoreCoordinator(ActiveRuntimeSlot(active)).activate(stage)
    child = fork(runtime, 'b2-child')
    child_store = child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID)).memory_store
    assert _proofs(child_store) == (parent_proof,)
    verify_instance_proof(parent_proof, history=child.context.event_history, trust=trust,
        checkpoint_timeline_id='b2-child', checkpoint_tick=child.context.clock.current_time,
        memory_revision_lineage=child.memory_revision_lineage)
    with child.write_fence.operation(): child_proof = _accept(child, _reissue(child, event.id))
    assert child_proof.instance.timeline_id == 'b2-child'
    assert child_proof.instance.instance_id != parent_proof.instance.instance_id
    assert child_proof.source_timeline_id == PARENT
    parent_stage = manager.stage_cold_resume(saved.save_id, timeline_id=PARENT,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())
    independent_parent = ColdRuntimePublisher().activate(parent_stage).current
    sibling = fork(independent_parent, 'b2-sibling')
    sibling_store = sibling.cognition_context_provider(sibling.context.agent_registry.get(AGENT_ID)).memory_store
    assert _proofs(sibling_store) == (parent_proof,)
    with pytest.raises(PermissionError):
        verify_instance_proof(child_proof, history=sibling.context.event_history, trust=trust,
            checkpoint_timeline_id='b2-sibling', checkpoint_tick=sibling.context.clock.current_time)


@pytest.mark.parametrize('field', ['owner_id', 'timeline_id', 'observation_id', 'observation_sha256', 'consumption_tick', 'version', 'instance_id'])
def test_instance_binding_tampering_rejects_even_with_new_signature(field):
    runtime, _, _, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    changed = replace(proof.instance, **{field: -1 if field == 'consumption_tick' else 99 if field == 'version' else 'wrong'})
    bad = replace(proof, instance=changed)
    bad = replace(bad, signature_hex=trust.sign(INSTANCE_PROOF_PURPOSE, bad.body()).hex())
    with pytest.raises(PermissionError):
        verify_instance_proof(bad, history=runtime.context.event_history, trust=trust,
            checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time)


def test_modified_proof_payload_without_resigning_is_invalid():
    runtime, _, _, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    bad = replace(proof, instance=replace(proof.instance, consumption_tick=proof.instance.consumption_tick + 1))
    with pytest.raises(PermissionError, match='signature'):
        verify_instance_proof(bad, history=runtime.context.event_history, trust=trust,
            checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time + 1)


def test_source_signature_failure_rejects_before_l1():
    runtime, _, memory, _, _, observation = _fixture()
    issuer = runtime.agent_action_loop.agent_turn.l1_consumption_issuer
    original = issuer.trust
    class BadVerifier:
        def verify(self, purpose, payload, signature): return False
        def sign(self, *args): pytest.fail('invalid source must not be signed')
    issuer.trust = BadVerifier()
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError): _accept(runtime, observation)
    assert not _proofs(memory) and not runtime.write_fence.recovery_required


def test_unsupported_non_result_never_enters_instance_path():
    runtime, _, memory, _, _, _ = _fixture()
    ordinary = next(o for o in runtime.context.observation_store.get_by_observer(AGENT_ID)
                    if o.content.fact_type == 'environment_state')
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError): _accept(runtime, ordinary)
    assert not _proofs(memory) and not runtime.write_fence.recovery_required


def test_working_memory_write_then_raise_is_uncertain_and_frozen(monkeypatch):
    from cognitive_world.cognition.working_memory import WorkingMemoryStore
    runtime, _, memory, _, _, observation = _fixture()
    original = WorkingMemoryStore.update
    def uncertain(self, value):
        original(self, value)
        raise OSError('written then failed')
    monkeypatch.setattr(WorkingMemoryStore, 'update', uncertain)
    with runtime.write_fence.operation():
        with pytest.raises(OSError): _accept(runtime, observation)
    assert runtime.write_fence.recovery_required and not _proofs(memory)
    assert 'percept:' + observation.observation_id in runtime.agent_action_loop.agent_turn.cognitive_runtime.working_memory_store.get(AGENT_ID).percept_ids


def test_cancellation_after_commit_entry_cannot_rollback(monkeypatch):
    runtime, _, memory, _, _, observation = _fixture()
    original = runtime.agent_action_loop.agent_turn.cognitive_runtime._publish_result_receipt
    with runtime.write_fence.operation() as permit:
        def after_entry(*args, **kwargs):
            assert not runtime.write_fence.revoke_uncommitted(permit)
            return original(*args, **kwargs)
        monkeypatch.setattr(runtime.agent_action_loop.agent_turn.cognitive_runtime, '_publish_result_receipt', after_entry)
        proof = _accept(runtime, observation)
    assert _proofs(memory) == (proof,)


def test_snapshot_encoding_failure_does_not_change_committed_proof(monkeypatch):
    runtime, cognition, memory, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    codec = cognitive_snapshot_codec()
    from cognitive_world.core.persistence import PersistedValueCodec
    original = PersistedValueCodec.dumps
    def broken(self, value):
        if type(value).__name__ == 'CognitiveSnapshotBody': raise ValueError('encoding failed')
        return original(self, value)
    monkeypatch.setattr(PersistedValueCodec, 'dumps', broken)
    with pytest.raises(ValueError, match='encoding failed'): _capture(runtime, cognition, memory, trust)
    assert _proofs(memory) == (proof,)
    assert not runtime.write_fence.recovery_required


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_checkpoint_publication_boundary_keeps_exact_proof(tmp_path, monkeypatch, phase):
    from cognitive_world.runtime.save_manager import SaveCommittedError
    runtime, cognition, memory, trust, _, observation = _fixture()
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    baseline = _save(manager, runtime, cognition, memory)
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    if phase == 'before':
        def fail(*args, **kwargs): raise OSError('before catalog commit')
        monkeypatch.setattr(manager, '_write_catalog', fail)
        with pytest.raises(OSError): _save(manager, runtime, cognition, memory)
    else:
        append = manager._append_journal
        def fail(record):
            if record['phase'] == 'COMMITTED': raise OSError('after catalog commit')
            return append(record)
        monkeypatch.setattr(manager, '_append_journal', fail)
        with pytest.raises(SaveCommittedError): _save(manager, runtime, cognition, memory)
    monkeypatch.undo()
    saves = manager.list_saves()
    assert len(saves) == (1 if phase == 'before' else 2)
    latest = next(s for s in saves if s.save_id != baseline.save_id) if phase == 'after' else baseline
    stage = manager.stage_cold_resume(latest.save_id, timeline_id=PARENT,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())
    restored = ColdRuntimePublisher().activate(stage).current
    store = restored.cognition_context_provider(restored.context.agent_registry.get(AGENT_ID)).memory_store
    assert _proofs(store) == ((proof,) if phase == 'after' else ())
    assert _proofs(memory) == (proof,)


def test_fresh_process_cold_restore_verifies_original_proof_without_issuer(tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    runtime, cognition, memory, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    script = r"""
import sys
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
from cognitive_world.cognition.l1_consumption_proof import L1ConsumptionIssuer
from cognitive_world.cognition.l1_instance import INSTANCE_PROOF_MEMORY_TYPE, verify_instance_proof
from test_save_restore_end_to_end import DoorRuntimeAssembler, AGENT_ID, PARENT
from test_runtime_reconstruction import _dependency_manifest
trust = HmacPersistenceTrust(b'b2-instance-test-trust-material-32')
def forbidden(*args, **kwargs): raise AssertionError('historical issuance called')
L1ConsumptionIssuer.accept_owner_result = forbidden
L1ConsumptionIssuer.issue_after_l1 = forbidden
manager = SaveManager(sys.argv[1], trust=trust)
stage = manager.stage_cold_resume(sys.argv[2], timeline_id=PARENT,
    assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())
runtime = ColdRuntimePublisher().activate(stage).current
store = runtime.cognition_context_provider(runtime.context.agent_registry.get(AGENT_ID)).memory_store
proofs = [m.content for m in store.get_all_memories() if m.type == INSTANCE_PROOF_MEMORY_TYPE]
assert len(proofs) == 1 and proofs[0].proof_id == sys.argv[3] and proofs[0].signature_hex == sys.argv[4]
verify_instance_proof(proofs[0], history=runtime.context.event_history, trust=trust,
    checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time)
"""
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(Path.cwd()/'src'), str(Path.cwd()/'tests')))
    completed = subprocess.run([sys.executable, '-B', '-c', script, str(manager.root), saved.save_id,
        proof.proof_id, proof.signature_hex], env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize('corruption', ['proof_version', 'instance_version', 'future_type', 'outer_version', 'signature', 'owner'])
def test_resigned_snapshot_rejects_unknown_or_mismatched_inner_instance(corruption):
    from cognitive_world.cognition.snapshot import _COGNITIVE_SNAPSHOT_PURPOSE
    from cognitive_world.core.persistence import sha256_hex
    runtime, cognition, memory, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): _accept(runtime, observation)
    snapshot = _capture(runtime, cognition, memory, trust)
    codec = cognitive_snapshot_codec()
    stores = list(snapshot.body.stores)
    index = next(i for i, store in enumerate(stores) if store.store_name == 'memories')
    store = stores[index]
    record = next(r for r in store.records if r.value.type == INSTANCE_PROOF_MEMORY_TYPE)
    value = record.value
    if corruption == 'proof_version': value = replace(value, content=replace(value.content, version=99))
    elif corruption == 'instance_version': value = replace(value, content=replace(value.content,
        instance=replace(value.content.instance, version=99)))
    elif corruption == 'future_type': value = replace(value, type='system_l1_future_v99', content={'claim': 'consumed'})
    elif corruption == 'signature': value = replace(value, content=replace(value.content, signature_hex='00' * 32))
    elif corruption == 'owner': value = replace(value, content=replace(value.content,
        instance=replace(value.content.instance, owner_id='other')))
    unsigned = replace(store, records=tuple(replace(r, value=value) if r is record else r for r in store.records), state_version='sha256:pending')
    stores[index] = replace(unsigned, state_version='sha256:' + sha256_hex(codec.dumps(unsigned)))
    if corruption == 'outer_version':
        with pytest.raises(ValueError, match='unsupported CognitiveStateSnapshot schema version'):
            replace(snapshot.body, schema_version=99)
        return
    body = replace(snapshot.body, stores=tuple(stores))
    encoded = codec.dumps(body)
    changed = CognitiveStateSnapshot(body, 'sha256:' + sha256_hex(encoded),
        trust.sign(_COGNITIVE_SNAPSHOT_PURPOSE, encoded).hex())
    with pytest.raises((PermissionError, ValueError)):
        decoded = CognitiveStateSnapshot.from_bytes(changed.to_bytes(), trust=trust)
        reconstruct_isolated(decoded, trust=trust, expected_agents=snapshot.body.expected_agents,
            event_history=runtime.context.event_history)


def test_child_cold_resume_retains_two_proofs_and_does_not_infer_missing_child_consumption(tmp_path):
    runtime, cognition, memory, trust, event, observation = _fixture()
    with runtime.write_fence.operation(): parent_proof = _accept(runtime, observation)
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    stage = manager.stage_restore(saved.save_id, timeline_id=PARENT, active_runtime=runtime,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(), new_timeline_id='b2-child')
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(stage)
    context = child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID))
    before = _save(manager, child, context.cognition_container, context.memory_store)
    cold = ColdRuntimePublisher().activate(manager.stage_cold_resume(before.save_id,
        timeline_id='b2-child', assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())).current
    with cold.write_fence.operation():
        with pytest.raises(PermissionError, match='ambiguous'):
            _accept(cold, _reissue(cold, event.id))
    with child.write_fence.operation(): child_proof = _accept(child, _reissue(child, event.id))
    after = _save(manager, child, context.cognition_container, context.memory_store)
    resumed = ColdRuntimePublisher().activate(manager.stage_cold_resume(after.save_id,
        timeline_id='b2-child', assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())).current
    restored_store = resumed.cognition_context_provider(resumed.context.agent_registry.get(AGENT_ID)).memory_store
    assert set(_proofs(restored_store)) == {parent_proof, child_proof}
    with resumed.write_fence.operation(): assert _accept(resumed, _reissue(resumed, event.id)) == child_proof


def test_same_id_different_intact_payload_is_a_conflict(monkeypatch):
    # Even an intact alternative receipt cannot use its digest as a new identity.
    runtime, _, memory, _, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    from cognitive_world.observation.observation import _ObservationProvenance, _OBSERVATION_RECEIPT_SEAL
    changed = replace(observation, metadata={'new': 'payload'})
    object.__setattr__(changed, '_provenance', _ObservationProvenance(
        _OBSERVATION_RECEIPT_SEAL, changed._snapshot(), 'test-only-intact-receipt', PARENT,
        runtime.write_fence.session_id, runtime.write_fence.restore_generation))
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError): _accept(runtime, changed)
    assert _proofs(memory) == (proof,)
    assert not runtime.write_fence.recovery_required



def test_no_independent_instance_boolean_or_caller_identity_api():
    runtime, _, memory, _, _, observation = _fixture()
    issuer = runtime.agent_action_loop.agent_turn.l1_consumption_issuer
    with runtime.write_fence.operation():
        with pytest.raises(TypeError):
            issuer.accept_owner_result(owner_id=AGENT_ID, observation=observation,
                cognitive_runtime=runtime.agent_action_loop.agent_turn.cognitive_runtime,
                memory_store=memory, new_instance=True)
        with pytest.raises(TypeError):
            issuer.accept_owner_result(owner_id=AGENT_ID, observation=observation,
                cognitive_runtime=runtime.agent_action_loop.agent_turn.cognitive_runtime,
                memory_store=memory, consumption_instance_id='caller-selected')
    assert not _proofs(memory)


def test_restored_delivery_does_not_run_resolution_or_handler(tmp_path, monkeypatch):
    runtime, cognition, memory, trust, event, observation = _fixture()
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    stage = manager.stage_cold_resume(saved.save_id, timeline_id=PARENT,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())
    cold = ColdRuntimePublisher().activate(stage).current
    def forbidden(*args, **kwargs): pytest.fail('committed world operation replayed')
    handler = cold.event_processor._handlers['resolution']
    monkeypatch.setattr(type(handler), 'handle_with_world_state', forbidden)
    monkeypatch.setattr(cold.agent_action_loop.action_resolution_flow.resolution_engine, 'resolve', forbidden)
    reissued = _reissue(cold, event.id)
    assert reissued.observation_id == observation.observation_id
    assert not cold.context.world_state.environment[DOOR_ID].is_open
    assert len([e for e in cold.context.event_history.get_events() if e.id == event.id]) == 1



def test_valid_parent_proof_created_after_fork_checkpoint_is_not_inherited_even_same_tick(tmp_path):
    runtime, cognition, memory, trust, event, observation = _fixture()
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    stage = manager.stage_restore(saved.save_id, timeline_id=PARENT, active_runtime=runtime,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(), new_timeline_id='b2-child')
    with runtime.write_fence.operation(): late_parent_proof = _accept(runtime, observation)
    assert late_parent_proof.instance.consumption_tick == saved.simulation_tick
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(stage)
    with pytest.raises(PermissionError, match='inherited checkpoint'):
        verify_instance_proof(late_parent_proof, history=child.context.event_history, trust=trust,
            checkpoint_timeline_id='b2-child', checkpoint_tick=child.context.clock.current_time,
            memory_revision_lineage=child.memory_revision_lineage)



@pytest.mark.parametrize('capture_first', [False, True])
def test_b2_acceptance_proof_and_checkpoint_capture_are_serialized(capture_first, monkeypatch):
    from threading import Event
    from cognitive_world.cognition.memory_store import MemoryStore
    runtime, cognition, memory, trust, _, observation = _fixture()
    reached, release = Event(), Event()
    snapshots, errors, ordering = [], [], []
    original = MemoryStore._commit_system_proof
    def gated(store, record, **kwargs):
        if store is memory and record.type == INSTANCE_PROOF_MEMORY_TYPE:
            reached.set()
            if not release.wait(10): raise AssertionError('commit gate not released')
        result = original(store, record, **kwargs)
        ordering.append('commit')
        return result
    monkeypatch.setattr(MemoryStore, '_commit_system_proof', gated)
    def consume():
        try:
            with runtime.write_fence.operation(): _accept(runtime, observation)
        except BaseException as error: errors.append(error)
    def capture():
        try:
            snapshots.append(_capture(runtime, cognition, memory, trust))
            ordering.append('capture')
        except BaseException as error: errors.append(error)
    if capture_first:
        with runtime.write_fence.operation():
            with runtime.write_fence.snapshot_scope():
                worker = Thread(target=consume)
                worker.start()
                capture()
                release.set()
        worker.join(10)
        assert ordering == ['capture', 'commit']
    else:
        worker = Thread(target=consume)
        worker.start()
        assert reached.wait(10)
        capture_worker = Thread(target=capture)
        capture_worker.start()
        release.set()
        worker.join(10); capture_worker.join(10)
        assert not capture_worker.is_alive() and ordering == ['commit', 'capture']
    assert not worker.is_alive() and not errors and len(_proofs(memory)) == 1
    captured = [r.value for store in snapshots[0].body.stores if store.store_name == 'memories'
                for r in store.records if r.value.type == INSTANCE_PROOF_MEMORY_TYPE]
    assert len(captured) == (0 if capture_first else 1)



@pytest.mark.parametrize('field,value', [('subject_ref', 'wrong-door'), ('location_id', 'wrong-place'),
    ('predicate', 'different-result'), ('value', False), ('fact_id', 'different-fact')])
def test_fact_field_tampering_cannot_reuse_original_observation_provenance(field, value):
    runtime, _, memory, _, _, observation = _fixture()
    bad = replace(observation, content=replace(observation.content, **{field: value}))
    object.__setattr__(bad, '_provenance', observation._provenance)
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError): _accept(runtime, bad)
    assert not _proofs(memory) and not runtime.write_fence.recovery_required


def test_internally_consistent_resigned_wrong_owner_fails_domain_authorization():
    from cognitive_world.cognition.l1_instance import instance_proof_id
    runtime, _, _, trust, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    instance = replace(proof.instance, owner_id='other-owner',
        instance_id=default_instance_id(PARENT, 'other-owner', observation.observation_id))
    bad = replace(proof, instance=instance, proof_id=instance_proof_id(instance))
    bad = replace(bad, signature_hex=trust.sign(INSTANCE_PROOF_PURPOSE, bad.body()).hex())
    with pytest.raises(PermissionError, match='original confirmed-failure owner'):
        verify_instance_proof(bad, history=runtime.context.event_history, trust=trust,
            checkpoint_timeline_id=PARENT, checkpoint_tick=runtime.context.clock.current_time)


def test_restore_after_actual_post_l1_signing_failure_never_fabricates_consumption(tmp_path, monkeypatch):
    runtime, cognition, memory, trust, event, observation = _fixture()
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    original = HmacPersistenceTrust.sign
    def unavailable(self, purpose, payload):
        if purpose == INSTANCE_PROOF_PURPOSE: raise OSError('post-L1 signing unavailable')
        return original(self, purpose, payload)
    monkeypatch.setattr(HmacPersistenceTrust, 'sign', unavailable)
    with runtime.write_fence.operation():
        with pytest.raises(OSError): _accept(runtime, observation)
    assert runtime.write_fence.recovery_required and not _proofs(memory)
    assert runtime.agent_action_loop.agent_turn.cognitive_runtime.has_consumed_observation(
        AGENT_ID, observation, source_event_id=event.id)
    monkeypatch.undo()
    restored = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,
        timeline_id=PARENT, assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest())).current
    assert [e.id for e in restored.context.event_history.get_events()] == [e.id for e in runtime.context.event_history.get_events()]
    restored_memory = restored.cognition_context_provider(restored.context.agent_registry.get(AGENT_ID)).memory_store
    with restored.write_fence.operation():
        with pytest.raises(PermissionError, match='ambiguous'):
            _accept(restored, _reissue(restored, event.id))
    assert not _proofs(restored_memory) and not restored.context.world_state.environment[DOOR_ID].is_open



@pytest.mark.parametrize("failure_point", ["working_memory", "legacy_receipt"])
def test_legacy_partial_write_without_receipt_is_not_new_b2_consumption(monkeypatch, failure_point):
    from cognitive_world.cognition.working_memory import WorkingMemoryStore
    runtime, cognition, memory, trust, event, observation = _fixture()
    assert runtime.context.clock.current_time == 5
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    key = (AGENT_ID, observation.observation_id)
    pid = 'percept:' + observation.observation_id
    original_update = WorkingMemoryStore.update
    def legacy_write_then_fail(store, value):
        original_update(store, value)
        if store is l1.working_memory_store:
            raise OSError('legacy failed after the real WorkingMemory write')
    with monkeypatch.context() as patch:
        if failure_point == 'working_memory':
            patch.setattr(WorkingMemoryStore, 'update', legacy_write_then_fail)
        else:
            from cognitive_world.cognition import runtime as runtime_module
            def fail_receipt(*args, **kwargs):
                raise OSError('legacy failed before recording its receipt')
            patch.setattr(runtime_module, '_L1ConsumptionReceipt', fail_receipt)
        with pytest.raises(OSError, match='legacy failed'):
            l1.process(AGENT_ID, (observation,))
    before = l1.working_memory_store.get(AGENT_ID)
    assert before.percept_ids.count(pid) == 1
    assert key not in l1._l1_consumption_receipts
    assert not l1.has_consumed_observation(AGENT_ID, observation, source_event_id=event.id)
    assert not _proofs(memory) and not runtime.write_fence.recovery_required
    event_ids = tuple(e.id for e in runtime.context.event_history.get_events())
    with runtime.write_fence.operation():
        with runtime.write_fence.commit_scope(): runtime.context.clock.advance(3)
    assert runtime.context.clock.current_time == 8
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError, match='ambiguous') as failure:
            _accept(runtime, observation)
    assert getattr(failure.value, 'code', None) == 'ambiguous_l1_consumption'
    assert key not in l1._l1_consumption_receipts
    assert l1.working_memory_store.get(AGENT_ID) == before
    assert not _proofs(memory)
    assert event_ids == tuple(e.id for e in runtime.context.event_history.get_events())
    assert not runtime.context.world_state.environment[DOOR_ID].is_open
    # Rejection preceded any new protected mutation: the legacy workspace stays
    # transient/ambiguous, while a checkpoint may safely contain no B2 proof.
    assert not runtime.write_fence.recovery_required
    snapshot = _capture(runtime, cognition, memory, trust)
    assert not any(record.value.type == INSTANCE_PROOF_MEMORY_TYPE
                   for store in snapshot.body.stores if store.store_name == 'memories'
                   for record in store.records)



def test_legacy_receipt_without_working_memory_cursor_still_is_ambiguous():
    from cognitive_world.cognition.working_memory import WorkingMemory
    from cognitive_world.cognition.l1_instance import AmbiguousL1ConsumptionError
    runtime, _, memory, _, event, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    l1.process(AGENT_ID, (observation,))
    receipt = l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)]
    l1.working_memory_store.update(WorkingMemory(AGENT_ID))
    assert receipt.instance is None
    assert not l1.has_consumed_observation(AGENT_ID, observation, source_event_id=event.id)
    with runtime.write_fence.operation():
        with pytest.raises(AmbiguousL1ConsumptionError): _accept(runtime, observation)
    assert l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)] == receipt
    assert not _proofs(memory) and not runtime.write_fence.recovery_required


def test_reused_percept_between_precheck_and_acceptance_cannot_publish_instance(monkeypatch):
    from cognitive_world.cognition.l1_instance import AmbiguousL1ConsumptionError
    runtime, cognition, memory, trust, _, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    process = l1.process
    def intervening_legacy_acceptance(owner, observations, **kwargs):
        process(owner, observations, **kwargs)  # real insertion by compatibility path
        return process(owner, observations, **kwargs)  # real reuse, no new ID
    monkeypatch.setattr(l1, 'process', intervening_legacy_acceptance)
    count = len(runtime.context.event_history.get_events())
    with runtime.write_fence.operation():
        with pytest.raises(AmbiguousL1ConsumptionError): _accept(runtime, observation)
    assert runtime.write_fence.recovery_required
    receipt = l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)]
    assert receipt.instance is None and not _proofs(memory)
    assert l1.working_memory_store.get(AGENT_ID).percept_ids.count('percept:' + observation.observation_id) == 1
    assert len(runtime.context.event_history.get_events()) == count
    with pytest.raises(PermissionError): _capture(runtime, cognition, memory, trust)


@pytest.mark.parametrize('binding', ['state_owner', 'new_ids', 'percept_owner', 'observation', 'event', 'metadata'])
def test_current_l1_return_bindings_are_checked_before_receipt_publication(monkeypatch, binding):
    from cognitive_world.cognition.l1_instance import AmbiguousL1ConsumptionError
    runtime, _, memory, _, _, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    process = l1.process
    def wrong_result(owner, observations, **kwargs):
        result = process(owner, observations, **kwargs)
        if binding == 'state_owner': result.agent_id = 'another-owner'
        elif binding == 'new_ids': result.percept_ids = []
        elif binding == 'percept_owner': result.percepts[0].observer_id = 'another-owner'
        elif binding == 'observation': result.percepts[0].source_observation_id = 'another-observation'
        elif binding == 'event': result.percepts[0].content = replace(result.percepts[0].content, source_event_id='another-event')
        else: result.percepts[0].metadata = {'unbound': 'metadata'}
        return result
    monkeypatch.setattr(l1, 'process', wrong_result)
    with runtime.write_fence.operation():
        with pytest.raises(AmbiguousL1ConsumptionError): _accept(runtime, observation)
    assert runtime.write_fence.recovery_required and not _proofs(memory)
    assert l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)].instance is None


def test_foreign_owner_cursor_cannot_authorize_private_result():
    from cognitive_world.cognition.working_memory import WorkingMemory
    runtime, _, memory, _, _, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    other = WorkingMemory('other-owner', ['percept:' + observation.observation_id])
    l1.working_memory_store.update(other)
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError):
            runtime.agent_action_loop.agent_turn.l1_consumption_issuer.accept_owner_result(
                owner_id='other-owner', observation=observation, cognitive_runtime=l1, memory_store=memory)
    assert l1.working_memory_store.get('other-owner') == other
    assert not _proofs(memory) and not runtime.write_fence.recovery_required


def test_cursor_copied_from_parent_timeline_cannot_be_promoted_on_child(tmp_path):
    from cognitive_world.cognition.l1_instance import AmbiguousL1ConsumptionError
    runtime, cognition, memory, trust, event, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    l1.process(AGENT_ID, (observation,))  # legacy, no Timeline-bearing instance
    workspace = l1.working_memory_store.get(AGENT_ID)
    manager = SaveManager(tmp_path / 'saves', trust=trust)
    saved = _save(manager, runtime, cognition, memory)
    stage = manager.stage_restore(saved.save_id, timeline_id=PARENT, active_runtime=runtime,
        assembler=DoorRuntimeAssembler(trust), dependencies=_dependency_manifest(), new_timeline_id='p1-child')
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(stage)
    child_l1 = child.agent_action_loop.agent_turn.cognitive_runtime
    # Adversarial host supplies old transient workspace; it is not restored by
    # snapshots and cannot establish a new Timeline's consumption provenance.
    child_l1.working_memory_store.update(workspace)
    current = _reissue(child, event.id)
    assert current.trusted_source_runtime_binding() == (child.write_fence.session_id, child.write_fence.restore_generation)
    with child.write_fence.operation():
        with pytest.raises(AmbiguousL1ConsumptionError): _accept(child, current)
    store = child.cognition_context_provider(child.context.agent_registry.get(AGENT_ID)).memory_store
    assert not _proofs(store) and not child.write_fence.recovery_required
    assert child_l1.working_memory_store.get(AGENT_ID) == workspace


def test_preexisting_cursor_does_not_make_changed_digest_eligible():
    from cognitive_world.observation.observation import _ObservationProvenance, _OBSERVATION_RECEIPT_SEAL
    runtime, _, memory, _, _, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    l1.process(AGENT_ID, (observation,))
    before = l1.working_memory_store.get(AGENT_ID)
    changed = replace(observation, metadata={'changed': 'digest'})
    object.__setattr__(changed, '_provenance', _ObservationProvenance(
        _OBSERVATION_RECEIPT_SEAL, changed._snapshot(), 'test-only-intact-receipt', PARENT,
        runtime.write_fence.session_id, runtime.write_fence.restore_generation))
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError): _accept(runtime, changed)
    assert l1.working_memory_store.get(AGENT_ID) == before and not _proofs(memory)


def test_failure_after_instance_receipt_publication_freezes_original_tick(monkeypatch):
    runtime, cognition, memory, trust, _, observation = _fixture()
    l1 = runtime.agent_action_loop.agent_turn.cognitive_runtime
    publish = l1._publish_result_receipt
    def published_then_failed(*args, **kwargs):
        publish(*args, **kwargs)
        raise OSError('instance receipt published before failure')
    monkeypatch.setattr(l1, '_publish_result_receipt', published_then_failed)
    with runtime.write_fence.operation():
        with pytest.raises(OSError): _accept(runtime, observation)
    receipt = l1._l1_consumption_receipts[(AGENT_ID, observation.observation_id)]
    assert receipt.instance.consumption_tick == 5 and not _proofs(memory)
    assert runtime.write_fence.recovery_required
    with pytest.raises(PermissionError):
        with runtime.write_fence.operation(): pass
    with pytest.raises(PermissionError): _capture(runtime, cognition, memory, trust)


def test_valid_b2_identity_and_proof_formula_are_unchanged_by_ambiguity_fix():
    from hashlib import sha256
    runtime, _, memory, _, _, observation = _fixture()
    with runtime.write_fence.operation(): proof = _accept(runtime, observation)
    codec = PersistedValueCodec()
    expected_instance = 'l1-instance:' + sha256(codec.dumps((
        'l1-consumption-instance/v1', PARENT, AGENT_ID, observation.observation_id, 'default'))).hexdigest()
    expected_proof = 'l1-instance-proof:' + sha256(codec.dumps((2, expected_instance, RESULT_RULE))).hexdigest()
    assert proof.instance.instance_id == expected_instance and proof.proof_id == expected_proof
    runtime.context.clock.advance(3)
    with runtime.write_fence.operation(): assert _accept(runtime, observation) == proof
    assert proof.instance.consumption_tick == 5 and len(_proofs(memory)) == 1
