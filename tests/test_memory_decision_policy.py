from dataclasses import replace

import pytest

from cognitive_world.cognition.memory import Memory, MemoryDecisionProvenanceV2
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.l1_consumption_proof import (
    NONVERBAL_PROOF_MEMORY_TYPE, PROOF_MEMORY_TYPE,
)
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.memory.decision_policy import MemoryDecisionResult, MemoryPolicyOutput
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.cognition.consolidator import MemoryDecisionEngine
from test_runtime_reconstruction import FakeTrust
from test_save_restore_end_to_end import AGENT_ID, _live_runtime, _observe_door


class FixedPolicy:
    policy_id = "test-host-policy"
    policy_version = "1.0"

    def __init__(self, result=MemoryDecisionResult.ACCEPTED):
        self.result = result

    def evaluate(self, decision_input):
        return MemoryPolicyOutput(self.result, 0.65, "policy.reviewed")


def _proposal(proposal_id="proposal-1", *, content=None, logical_id=None, predecessor=None):
    return MemoryProposal(
        proposal_id, "source-event", AGENT_ID, "experience",
        {"summary": "candidate"} if content is None else content, 0.4,
        logical_record_id=logical_id, supersedes_record_id=predecessor,
    )


def _configured(policy=None):
    trust = FakeTrust()
    runtime, _, store = _live_runtime(trust, timeline_id="timeline-test")
    source = _observe_door(runtime, "source-event")
    fence = runtime.write_fence
    history = runtime.context.event_history
    verified_events, _, _ = history.verify_persisted_lineage(
        codec=PersistedValueCodec(), trust=trust,
    )
    assert source.id in {event.id for event in verified_events}
    authority = MemoryDecisionAuthority()
    engine = MemoryDecisionEngine(
        policy=policy, authority=authority, event_history=history, write_fence=fence,
    )
    persistence = MemoryPersistence(store, history, write_fence=fence)
    return fence, history, store, authority, engine, persistence


def _decide_and_request(fence, engine, proposal):
    with fence.operation():
        decision = engine.decide(proposal)
        request = MemoryWriteFactory().create_request(decision, proposal)
    return decision, request


def test_formal_policy_decision_persists_v2_only_through_fenced_pipeline():
    fence, _, store, _, engine, persistence = _configured(FixedPolicy())
    proposal = None
    with fence.operation():
        proposal = _proposal()
        decision = engine.decide(proposal)
        assert decision.is_policy_authorized()
        request = MemoryWriteFactory().create_request(decision, proposal)
        saved = persistence.save(request)
    assert saved.schema_version == 2
    assert saved.decision_provenance.outcome == "accepted"
    assert saved.decision_provenance.policy_id == "test-host-policy"
    assert saved.decision_provenance.proposal_id == proposal.id
    assert saved.decision_provenance.owner_id == proposal.owner_id
    assert store.get_memory(saved.id) == saved


def test_missing_policy_and_legacy_self_report_cannot_authorize_v2():
    fence, _, store, authority, engine, persistence = _configured()
    with fence.operation():
        proposal = _proposal()
        with pytest.raises(NotImplementedError, match="no Memory decision policy"):
            engine.decide(proposal)

        legacy = authority.issue(
            proposal, accepted=True, importance=0.9, memory_type=proposal.memory_type,
        )
        request = MemoryWriteFactory().create_request(legacy, proposal)
        assert request.schema_version == 1
        saved = persistence.save(request)
        assert saved.schema_version == 1
        assert saved.decision_provenance is None
    assert len(store.memories) == 1


@pytest.mark.parametrize("result", [MemoryDecisionResult.REJECTED, MemoryDecisionResult.DEFERRED])
def test_rejected_and_deferred_policy_results_have_no_store_effect(result):
    fence, _, store, _, engine, _ = _configured(FixedPolicy(result))
    with fence.operation():
        proposal = _proposal()
        decision = engine.decide(proposal)
        assert decision.result is result
        assert not decision.accepted
        with pytest.raises(ValueError, match="requires an accepted decision"):
            MemoryWriteFactory().create_request(decision, proposal)
    assert store.memories == {}


@pytest.mark.parametrize("policy", [
    type("RaisingPolicy", (), {
        "policy_id": "raise", "policy_version": "1",
        "evaluate": lambda self, _: (_ for _ in ()).throw(RuntimeError("policy failed")),
    })(),
    type("InvalidOutputPolicy", (), {
        "policy_id": "invalid", "policy_version": "1",
        "evaluate": lambda self, _: object(),
    })(),
])
def test_policy_exception_or_untyped_output_fails_closed(policy):
    fence, _, store, _, engine, _ = _configured(policy)
    with fence.operation():
        with pytest.raises((RuntimeError, ValueError), match="policy failed|unsupported output"):
            engine.decide(_proposal())
    assert store.memories == {}


def test_unknown_policy_output_schema_and_proposal_mutation_fail_closed():
    class UnknownSchemaPolicy:
        policy_id = "schema-policy"
        policy_version = "1"

        def evaluate(self, decision_input):
            result = MemoryPolicyOutput(MemoryDecisionResult.ACCEPTED, 0.5, "valid")
            invalid = object.__new__(type(result))
            object.__setattr__(invalid, "schema_version", 2)
            return invalid

    fence, _, store, _, engine, _ = _configured(UnknownSchemaPolicy())
    with fence.operation():
        with pytest.raises(ValueError, match="unsupported output"):
            engine.decide(_proposal())
    assert store.memories == {}

    mutated_proposal = _proposal("mutated")

    class MutatingPolicy(FixedPolicy):
        def evaluate(self, decision_input):
            mutated_proposal.content["summary"] = "changed during call"
            return super().evaluate(decision_input)

    fence, _, store, _, engine, _ = _configured(MutatingPolicy())
    with fence.operation():
        # The candidate is created inside this operation so its original permit is retained.
        mutated_proposal = _proposal("mutated")
        with pytest.raises(PermissionError, match="changed during policy"):
            engine.decide(mutated_proposal)
    assert store.memories == {}


def test_policy_decision_cannot_be_reused_for_another_proposal_or_owner():
    fence, _, store, _, engine, _ = _configured(FixedPolicy())
    with fence.operation():
        proposal = _proposal()
        decision = engine.decide(proposal)
        other = _proposal("other")
        other.owner_id = "owner-b"
        with pytest.raises(ValueError, match="does not reference"):
            MemoryWriteFactory().create_request(decision, other)
    assert store.memories == {}


def test_v2_store_rejects_forged_provenance_and_direct_low_level_commit():
    fence, _, store, _, engine, _ = _configured(FixedPolicy())
    with fence.operation():
        proposal = _proposal()
        decision = engine.decide(proposal)
        request = MemoryWriteFactory().create_request(decision, proposal)
        valid = Memory(
            id=request.memory_id, owner_id=request.owner_id, type=request.memory_type,
            content=request.content, importance=request.importance,
            source_event=request.source_event_id, schema_version=2,
            decision_provenance=request.decision_provenance,
            logical_record_id=request.logical_record_id,
            supersedes_record_id=request.supersedes_record_id,
        )
        with pytest.raises(PermissionError, match="formal persistence request"):
            store._commit_memory(valid)
        forged = replace(
            valid,
            decision_provenance=replace(valid.decision_provenance, reason_code="forged"),
        )
        with pytest.raises(PermissionError, match="formal persistence request"):
            store._commit_memory(forged)
    assert store.memories == {}


def test_formal_write_is_fenced_idempotent_and_rejects_identity_conflicts():
    fence, _, store, _, engine, persistence = _configured(FixedPolicy())
    with fence.operation():
        first = _proposal("stable")
        decision = engine.decide(first)
        request = MemoryWriteFactory().create_request(decision, first)
        saved = persistence.save(request)
        assert persistence.save(request) == saved

        conflict = _proposal("stable", content={"summary": "different"})
        conflict_decision = engine.decide(conflict)
        conflict_request = MemoryWriteFactory().create_request(conflict_decision, conflict)
        with pytest.raises(PermissionError, match="conflicting immutable"):
            persistence.save(conflict_request)
    assert store.get_memory(saved.id) == saved
    assert len(store.memories) == 1


def test_stale_permit_cannot_commit_formal_memory_after_generation_change():
    fence, _, store, _, engine, persistence = _configured(FixedPolicy())
    with fence.operation():
        proposal = _proposal("late")
        decision = engine.decide(proposal)
        request = MemoryWriteFactory().create_request(decision, proposal)
    fence.freeze_and_advance()
    fence.unfreeze()
    with fence.operation():
        with pytest.raises(PermissionError, match="candidate is not bound"):
            persistence.save(request)
    assert store.get_memory("memory:late") is None


def test_formal_memory_revision_uses_new_identity_and_explicit_predecessor():
    fence, _, store, _, engine, persistence = _configured(FixedPolicy())
    with fence.operation():
        first = _proposal("revision-1", logical_id="logical-a")
        first_request = MemoryWriteFactory().create_request(engine.decide(first), first)
        first_memory = persistence.save(first_request)
    with fence.operation():
        second = _proposal(
            "revision-2", logical_id="logical-a", predecessor=first_memory.id,
        )
        second_request = MemoryWriteFactory().create_request(engine.decide(second), second)
        second_memory = persistence.save(second_request)
    assert second_memory.id != first_memory.id
    assert second_memory.supersedes_record_id == first_memory.id
    assert store.get_memory(first_memory.id) == first_memory
    assert store.get_memory(second_memory.id) == second_memory


def test_forged_policy_output_provenance_constructor_is_not_a_store_capability():
    provenance = MemoryDecisionProvenanceV2(
        schema_version=2, decision_id="forged-decision", policy_id="claimed",
        policy_version="1", proposal_id="proposal", proposal_digest="a" * 64,
        input_digest="b" * 64, reason_code="claimed", owner_id="owner-a",
        source_event_ids=("source-event",), timeline_id="timeline-test",
        session_id="memory-policy-session", restore_generation=0,
    )
    forged = Memory(
        "memory:proposal", "owner-a", "experience", {"summary": "forged"}, 0.5,
        "source-event", schema_version=2, decision_provenance=provenance,
        logical_record_id="memory:proposal",
    )
    store = MemoryStore()
    with pytest.raises(PermissionError, match="fenced formal persistence request"):
        store._commit_memory(forged)
    assert store.memories == {}


@pytest.mark.parametrize("proof_type", [PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE])
def test_formal_policy_cannot_create_system_only_proof_records(proof_type):
    fence, _, store, _, engine, persistence = _configured(FixedPolicy())
    with fence.operation():
        proposal = MemoryProposal(
            "proof-attempt", "source-event", AGENT_ID, proof_type,
            {"untrusted": True}, 0.5,
        )
        decision = engine.decide(proposal)
        request = MemoryWriteFactory().create_request(decision, proposal)
        with pytest.raises(PermissionError, match="cannot create system L1 proofs"):
            persistence.save(request)
    assert store.memories == {}
