import pytest

from cognitive_world.cognition import (
    MemoryDecision,
    MemoryDecisionAuthority,
    MemoryProposal,
    MemoryWriteFactory,
)


def make_proposal():
    return MemoryProposal(
        id="proposal_001",
        source_event_id="event_001",
        owner_id="owner_001",
        memory_type="experience",
        content={"detail": {"items": [1]}},
        importance=0.4,
        metadata={"proposal": ["source"]},
    )


def test_accepted_decision_creates_write_request():
    proposal = make_proposal()
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.9,
        memory_type="fact",
        metadata={"review": "accepted"},
    )

    request = MemoryWriteFactory().create_request(decision, proposal)

    assert request.memory_id == "memory:proposal_001"
    assert request.owner_id == proposal.owner_id
    assert request.source_event_id == proposal.source_event_id
    assert request.content == proposal.content
    assert request.memory_type == decision.memory_type
    assert request.importance == decision.importance


def test_rejected_decision_does_not_create_request():
    proposal = make_proposal()
    decision = MemoryDecision(
        proposal_id=proposal.id,
        accepted=False,
        importance=0.0,
        memory_type=proposal.memory_type,
        proposal=proposal,
    )

    with pytest.raises(ValueError, match="requires an accepted decision"):
        MemoryWriteFactory().create_request(decision, proposal)


def test_decision_must_reference_the_supplied_proposal():
    proposal = make_proposal()
    snapshot = make_proposal()
    snapshot.content = {"detail": {"items": ["different"]}}
    decision = MemoryDecision(
        proposal_id=proposal.id,
        accepted=True,
        importance=0.7,
        memory_type="experience",
        proposal=snapshot,
    )

    with pytest.raises(ValueError, match="does not reference the supplied proposal"):
        MemoryWriteFactory().create_request(decision, proposal)
