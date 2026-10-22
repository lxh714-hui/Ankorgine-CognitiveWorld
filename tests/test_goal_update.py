from copy import deepcopy

from cognitive_world.cognition import (
    Goal,
    GoalChange,
    GoalStore,
    GoalUpdateProposal,
    GoalUpdater,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState


def test_goal_update_proposal_captures_state_priority_and_sources():
    goal = Goal(
        "goal-1",
        "agent-1",
        "Explore the area",
        0.4,
        "active",
        source_refs=["event-1"],
    )
    context = {
        "new_state": "completed",
        "new_priority": 0.9,
        "operation": "complete",
        "reason": "objective fulfilled",
        "evidence_refs": ["event-2"],
        "source_refs": ["event-2", "belief-1"],
        "metadata": {"basis": ["new information"]},
    }

    proposal = GoalUpdater().propose_update(goal, context)

    assert isinstance(proposal, GoalUpdateProposal)
    assert proposal.owner_id == "agent-1"
    assert proposal.goal_id == "goal-1"
    assert isinstance(proposal.change, GoalChange)
    assert proposal.change.operation == "complete"
    assert proposal.change.previous_state == "active"
    assert proposal.change.proposed_state == "completed"
    assert proposal.change.previous_priority == 0.4
    assert proposal.change.proposed_priority == 0.9
    assert proposal.change.reason == "objective fulfilled"
    assert proposal.change.evidence_refs == ["event-2"]
    assert proposal.source_refs == ["event-2", "belief-1"]
    assert proposal.metadata == {"basis": ["new information"]}


def test_goal_update_defaults_to_current_goal_state():
    goal = Goal(
        "goal-1", "agent-1", "Keep watch", 0.7, "active", ["source-1"]
    )

    proposal = GoalUpdater().propose_update(goal, object())

    assert proposal.change.previous_state == proposal.change.proposed_state == "active"
    assert proposal.change.previous_priority == proposal.change.proposed_priority == 0.7
    assert proposal.source_refs == ["source-1"]


def test_proposal_does_not_modify_goal_or_goal_store():
    store = GoalStore()
    goal = Goal(
        "goal-1",
        "agent-1",
        "Original goal",
        0.3,
        "active",
        ["source-1"],
        {"nested": ["original"]},
    )
    store.add(goal)
    original = deepcopy(goal)
    context = {
        "new_state": "failed",
        "new_priority": 0.1,
        "source_refs": ["source-2"],
        "metadata": {"nested": ["candidate"]},
    }

    proposal = GoalUpdater().propose_update(goal, context)
    context["source_refs"].append("external")
    context["metadata"]["nested"].append("external")
    proposal.source_refs.append("proposal mutation")
    proposal.metadata["nested"].append("proposal mutation")
    proposal.change.evidence_refs.append("proposal mutation")

    assert goal == original
    assert store.get("agent-1")[0] == original
    assert proposal.source_refs == ["source-2", "proposal mutation"]
    assert proposal.metadata == {"nested": ["candidate", "proposal mutation"]}
    assert proposal.change.evidence_refs == ["source-2", "proposal mutation"]


def test_goal_update_has_no_world_event_or_belief_side_effects():
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    event = Event("event-1", "existing", "t1")
    event_before = deepcopy(event)
    goal = Goal("goal-1", "agent-1", "Original", 0.5, "active")

    proposal = GoalUpdater().propose_update(
        goal, {"new_state": "abandoned", "new_priority": 0.2}
    )

    assert proposal.change.proposed_state == "abandoned"
    assert world_state.facts == {"existing": {"value": 1}}
    assert event == event_before
    assert not hasattr(proposal, "world_state")
    assert not hasattr(proposal, "belief_store")
