from cognitive_world.cognition import MemoryProposal


def test_memory_proposal_can_be_created():
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id="event_001",
        owner_id="owner_001",
        memory_type="experience",
        content={"summary": ["candidate", {"detail": True}]},
        importance=0.8,
    )

    assert isinstance(proposal, MemoryProposal)


def test_memory_proposal_preserves_fields_and_extended_metadata():
    content = {"structured": {"items": ["one", 2]}}
    metadata = {"review": {"flags": ["custom"]}, "extension": 1}
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id="event_001",
        owner_id="owner_001",
        memory_type="fact",
        content=content,
        importance=0.65,
        metadata=metadata,
    )

    assert proposal.id == "proposal_001"
    assert proposal.source_event_id == "event_001"
    assert proposal.owner_id == "owner_001"
    assert proposal.memory_type == "fact"
    assert proposal.content == content
    assert proposal.importance == 0.65
    assert proposal.metadata == metadata
