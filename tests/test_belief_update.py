from copy import deepcopy

from cognitive_world.cognition import (
    Belief,
    BeliefChange,
    BeliefStore,
    BeliefUpdateProposal,
    BeliefUpdater,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState


def test_belief_update_proposal_captures_explicit_candidate_values():
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": "door is open"},
        source_refs=["observation-1"],
        confidence=0.4,
    )
    context = {
        "new_value": {"claim": "door is closed"},
        "operation": "replace",
        "reason": "new observation",
        "evidence_refs": ["observation-2"],
        "source_refs": ["observation-2"],
        "confidence": 0.8,
        "metadata": {"basis": ["new input"]},
    }

    proposal = BeliefUpdater().propose_update(belief, context)

    assert isinstance(proposal, BeliefUpdateProposal)
    assert proposal.owner_id == "agent-1"
    assert proposal.belief_id == "belief-1"
    assert isinstance(proposal.change, BeliefChange)
    assert proposal.change.operation == "replace"
    assert proposal.change.previous_value == {"claim": "door is open"}
    assert proposal.change.proposed_value == {"claim": "door is closed"}
    assert proposal.change.reason == "new observation"
    assert proposal.change.evidence_refs == ["observation-2"]
    assert proposal.source_refs == ["observation-2"]
    assert proposal.confidence == 0.8
    assert proposal.metadata == {"basis": ["new input"]}


def test_belief_update_defaults_to_existing_source_and_confidence():
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": ["unchanged"]},
        source_refs=["event-1"],
        confidence=0.6,
    )

    proposal = BeliefUpdater().propose_update(belief, object())

    assert proposal.change.previous_value == {"claim": ["unchanged"]}
    assert proposal.change.proposed_value == {"claim": ["unchanged"]}
    assert proposal.source_refs == ["event-1"]
    assert proposal.confidence == 0.6


def test_proposal_and_updater_do_not_mutate_belief_or_store():
    store = BeliefStore()
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": ["original"]},
        source_refs=["event-1"],
        confidence=0.5,
    )
    store.add(belief)
    original = deepcopy(belief)
    proposal = BeliefUpdater().propose_update(
        belief,
        {"new_value": {"claim": ["candidate"]}, "source_refs": ["event-2"]},
    )
    proposal.change.proposed_value["claim"].append("external")
    proposal.change.evidence_refs.append("external")
    proposal.source_refs.append("external")

    assert belief == original
    assert store.get("agent-1") == original
    assert proposal.change.proposed_value == {"claim": ["candidate", "external"]}
    assert proposal.change.evidence_refs == ["event-2", "external"]


def test_belief_update_proposal_has_no_world_event_or_goal_side_effects():
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    event = Event("event-1", "existing", "t1")
    event_before = deepcopy(event)
    belief = Belief("belief-1", "agent-1", {"claim": "original"})

    proposal = BeliefUpdater().propose_update(
        belief, {"new_value": {"claim": "candidate"}}
    )

    assert proposal.change.proposed_value == {"claim": "candidate"}
    assert world_state.facts == {"existing": {"value": 1}}
    assert event == event_before
    assert not hasattr(proposal, "world_state")
    assert not hasattr(proposal, "goal_store")
