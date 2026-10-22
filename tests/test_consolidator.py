import pytest

from cognitive_world.cognition import (
    MemoryConsolidator,
    MemoryDecisionEngine,
    MemoryProposal,
    MemoryStore,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState


def test_memory_consolidator_decide_interface_exists():
    assert MemoryConsolidator is MemoryDecisionEngine
    assert callable(MemoryConsolidator().decide)
    assert callable(MemoryDecisionEngine().decide)
    assert MemoryConsolidator.decide.__annotations__["proposal"] == "MemoryProposal"
    assert MemoryConsolidator.decide.__annotations__["return"] == "MemoryDecision"


def test_unimplemented_decision_does_not_write_memory_or_change_world_or_event():
    consolidator = MemoryConsolidator()
    memory_store = MemoryStore()
    world_state = WorldState()
    event = Event(
        id="event_001",
        type="generic",
        timestamp="t1",
        changes=[{"fact": ["confirmed"]}],
    )
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id=event.id,
        owner_id="owner_001",
        memory_type="experience",
        content={"event": event.id},
        importance=0.5,
    )

    with pytest.raises(NotImplementedError):
        consolidator.decide(proposal)

    assert isinstance(proposal, MemoryProposal)
    assert memory_store.get_all_memories() == ()
    assert dict(world_state.facts) == {}
    assert event.changes == [{"fact": ["confirmed"]}]
