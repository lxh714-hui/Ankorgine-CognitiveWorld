from cognitive_world.cognition import MemoryDecision, MemoryProposal


def test_memory_decision_stores_all_fields():
    metadata = {"review": {"labels": ["manual"]}}
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id="event_001",
        owner_id="owner_001",
        memory_type="experience",
        content={"record": "candidate"},
        importance=0.4,
    )
    decision = MemoryDecision(
        proposal_id="proposal_001",
        accepted=True,
        importance=0.75,
        memory_type="experience",
        proposal=proposal,
        metadata=metadata,
    )

    assert decision.proposal_id == "proposal_001"
    assert decision.accepted is True
    assert decision.importance == 0.75
    assert decision.memory_type == "experience"
    assert decision.metadata == metadata
    assert decision.proposal == proposal
