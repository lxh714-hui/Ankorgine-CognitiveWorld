from copy import deepcopy

import pytest

from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.memory.memory_decision import (
    MemoryDecision,
    MemoryDecisionAuthority,
)
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory


def make_proposal(source_event_id: str = "event-1") -> MemoryProposal:
    return MemoryProposal(
        id="proposal-1",
        source_event_id=source_event_id,
        owner_id="agent-1",
        memory_type="experience",
        content={"observation": {"items": ["bridge opened"]}},
        importance=0.8,
        metadata={"source_observation_id": "observation-1"},
    )


def make_history() -> EventHistory:
    history = EventHistory()
    history.append(
        Event(
            id="event-1",
            type="world_change",
            timestamp="t1",
            changes=[{"fact": "bridge opened"}],
        )
    )
    return history


def issue_decision(proposal: MemoryProposal):
    return MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=0.95,
        memory_type="long_term_experience",
        metadata={"review": "approved"},
    )


def test_authorized_proposal_decision_request_persistence_flow():
    proposal = make_proposal()
    decision = issue_decision(proposal)
    store = MemoryStore()
    history = make_history()
    event_before = history.get_event("event-1")
    world_state = WorldState()
    world_state.load_fact("untouched", {"value": [1]})
    world_before = world_state.facts

    request = MemoryWriteFactory().create_request(decision, proposal)
    saved = MemoryPersistence(store, history).save(request)

    assert saved == store.get_memory(saved.id)
    assert saved.content == proposal.content
    assert request.authorization_snapshot.proposal == proposal
    assert request.authorization_snapshot.source_refs == (
        "event-1",
        "observation-1",
    )
    assert history.get_event("event-1") == event_before
    assert world_state.facts == world_before


def test_forged_accepted_decision_is_rejected():
    proposal = make_proposal()
    forged = MemoryDecision(
        proposal_id=proposal.id,
        accepted=True,
        importance=1.0,
        memory_type="experience",
        proposal=proposal,
    )

    with pytest.raises(PermissionError, match="not issued by an authority"):
        MemoryWriteFactory().create_request(forged, proposal)


def test_modified_issued_request_is_rejected_before_write():
    proposal = make_proposal()
    request = MemoryWriteFactory().create_request(issue_decision(proposal), proposal)
    request._content["observation"]["items"].append("tampered")
    store = MemoryStore()

    with pytest.raises(ValueError, match="modified after authorization"):
        MemoryPersistence(store, make_history()).save(request)

    assert store.get_all_memories() == ()


def test_request_source_must_match_authorized_proposal_source():
    proposal = make_proposal()
    request = MemoryWriteFactory().create_request(issue_decision(proposal), proposal)
    request._source_event_id = "other-event"
    store = MemoryStore()

    with pytest.raises(ValueError, match="modified after authorization"):
        MemoryPersistence(store, make_history()).save(request)

    assert store.get_all_memories() == ()


def test_missing_or_mismatched_source_event_is_rejected_without_world_changes():
    proposal = make_proposal(source_event_id="missing-event")
    request = MemoryWriteFactory().create_request(issue_decision(proposal), proposal)
    store = MemoryStore()
    history = make_history()
    world_state = WorldState()
    world_state.load_fact("stable", {"nested": ["value"]})
    # WorldState exposes a read-only mapping proxy; snapshot its already
    # detached values without attempting to pickle the proxy itself.
    world_before = deepcopy(dict(world_state.facts))
    event_before = history.get_events()

    with pytest.raises(ValueError, match="source Event not found in EventHistory"):
        MemoryPersistence(store, history).save(request)

    assert store.get_all_memories() == ()
    assert dict(world_state.facts) == world_before
    assert history.get_events() == event_before
