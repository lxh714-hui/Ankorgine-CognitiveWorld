from importlib import import_module

import pytest

from cognitive_world.cognition import MemoryConsolidator as LegacyDecisionName
from cognitive_world.cognition import MemoryDecisionAuthority, MemoryDecisionEngine
from cognitive_world.cognition.consolidator import (
    MemoryConsolidator as LegacyCognitionConsolidator,
)
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.memory import (
    EventMemoryProposalFactory,
    MemoryCandidate,
    MemoryConsolidator as LegacyEventName,
    MemoryPersistence,
    MemoryWriteFactory,
)
from cognitive_world.memory.consolidation import (
    MemoryConsolidator as LegacyMemoryConsolidator,
)


def test_new_and_legacy_names_import_without_a_cycle():
    assert import_module("cognitive_world.memory.consolidation").EventMemoryProposalFactory
    assert import_module("cognitive_world.cognition.consolidator").MemoryDecisionEngine
    assert LegacyEventName is EventMemoryProposalFactory
    assert LegacyMemoryConsolidator is EventMemoryProposalFactory
    assert LegacyDecisionName is MemoryDecisionEngine
    assert LegacyCognitionConsolidator is MemoryDecisionEngine
    assert EventMemoryProposalFactory is not MemoryDecisionEngine



def test_event_memory_proposal_factory_preserves_event_to_proposal_behavior():
    event = Event(
        id="event-1",
        type="world_change",
        timestamp="t1",
        changes=[{"fact": "bridge opened"}],
    )
    world = WorldState()
    world.load_fact("stable", {"value": [1]})
    facts_before = world.facts

    proposal = EventMemoryProposalFactory().propose(
        event,
        {
            "owner_id": "agent-1",
            "memory_type": "experience",
            "content": {"seen": "bridge opened"},
            "importance": 0.6,
            "confidence": 0.8,
        },
    )

    assert type(proposal) is MemoryProposal
    assert isinstance(proposal, MemoryCandidate)
    assert proposal.source_event_id == event.id
    assert proposal.source_event_ids == [event.id]
    assert proposal.content == {"seen": "bridge opened"}
    assert proposal.importance == 0.6
    assert proposal.confidence == 0.8
    assert world.facts == facts_before


def test_memory_decision_engine_keeps_its_existing_placeholder_behavior():
    proposal = MemoryProposal(
        id="proposal-1",
        source_event_id="event-1",
        owner_id="agent-1",
        memory_type="experience",
        content={"seen": True},
        importance=0.5,
    )

    with pytest.raises(NotImplementedError, match="no Memory decision policy is installed"):
        MemoryDecisionEngine().decide(proposal)


def test_authorized_proposal_decision_write_path_keeps_source_and_world_unchanged():
    event = Event("event-1", "world_change", "t1", changes=[{"fact": "confirmed"}])
    history = EventHistory()
    history.append(event)
    store = MemoryStore()
    world = WorldState()
    world.load_fact("unchanged", {"value": "stable"})
    facts_before = world.facts

    proposal = EventMemoryProposalFactory().propose(
        event,
        {"owner_id": "agent-1", "content": {"experience": "confirmed"}},
    )
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.9,
        memory_type=proposal.memory_type,
    )
    request = MemoryWriteFactory().create_request(decision, proposal)
    memory = MemoryPersistence(store, history).save(request)

    assert memory.source_event == event.id
    assert store.get_memory(memory.id) == memory
    assert history.get_event(event.id) == event
    assert world.facts == facts_before


def test_unissued_accepted_decision_still_cannot_write():
    proposal = MemoryProposal(
        id="proposal-2",
        source_event_id="event-2",
        owner_id="agent-1",
        memory_type="experience",
        content={"claim": "candidate"},
        importance=0.5,
    )
    from cognitive_world.memory.memory_decision import MemoryDecision

    unissued = MemoryDecision(
        proposal_id=proposal.id,
        accepted=True,
        importance=1.0,
        memory_type=proposal.memory_type,
        proposal=proposal,
    )

    with pytest.raises(PermissionError, match="not issued by an authority"):
        MemoryWriteFactory().create_request(unissued, proposal)
