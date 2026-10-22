from copy import deepcopy

from cognitive_world.cognition import (
    BeliefChange,
    BeliefUpdateProposal,
    CognitiveUpdateValidator,
    GoalChange,
    GoalUpdateProposal,
    ValidationResult,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState


def test_validator_accepts_belief_and_goal_proposals_with_sources_and_matching_owner():
    validator = CognitiveUpdateValidator()
    belief_proposal = BeliefUpdateProposal(
        owner_id="agent-1",
        belief_id="belief-1",
        change=BeliefChange("replace", "old", "new", "update", ["event-1"]),
        source_refs=["observation-1"],
    )
    goal_proposal = GoalUpdateProposal(
        owner_id="agent-1",
        goal_id="goal-1",
        change=GoalChange(
            "update", "active", "completed", 0.4, 0.8, "test", ["event-1"]
        ),
        source_refs=["event-1"],
    )

    belief_result = validator.validate(belief_proposal, {"agent_id": "agent-1"})
    goal_result = validator.validate(goal_proposal, {"agent_id": "agent-1"})

    assert isinstance(belief_result, ValidationResult)
    assert belief_result.accepted is True
    assert goal_result.accepted is True


def test_validator_rejects_proposal_without_source_refs():
    proposal = GoalUpdateProposal(
        owner_id="agent-1",
        goal_id="goal-1",
        change=GoalChange(
            "update", "active", "failed", 0.5, 0.1, "test", []
        ),
    )

    result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-1"})

    assert result.accepted is False
    assert "source_refs" in result.reason


def test_validator_rejects_agent_mismatch():
    proposal = BeliefUpdateProposal(
        owner_id="agent-1",
        belief_id="belief-1",
        change=BeliefChange("replace", "old", "new", "update", ["event-1"]),
        source_refs=["event-1"],
    )

    result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-2"})

    assert result.accepted is False
    assert "owner" in result.reason


def test_validation_does_not_mutate_proposal_or_context():
    proposal = BeliefUpdateProposal(
        owner_id="agent-1",
        belief_id="belief-1",
        change=BeliefChange(
            "replace",
            {"claim": ["old"]},
            {"claim": ["new"]},
            "update",
            ["event-1"],
        ),
        source_refs=["event-1"],
        metadata={"nested": [1]},
    )
    context = {"agent_id": "agent-1", "metadata": {"context": [1]}}
    proposal_before = deepcopy(proposal)
    context_before = deepcopy(context)

    result = CognitiveUpdateValidator().validate(proposal, context)
    result.metadata["external"] = True

    assert proposal == proposal_before
    assert context == context_before
    assert "external" not in CognitiveUpdateValidator().validate(
        proposal, context
    ).metadata


def test_validation_has_no_world_or_event_side_effects():
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    event = Event("event-1", "existing", "t1")
    event_before = deepcopy(event)
    proposal = GoalUpdateProposal(
        owner_id="agent-1",
        goal_id="goal-1",
        change=GoalChange(
            "update", "active", "abandoned", 0.6, 0.1, "test", ["event-1"]
        ),
        source_refs=["event-1"],
    )

    result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-1"})

    assert result.accepted
    assert world_state.facts == {"existing": {"value": 1}}
    assert event == event_before
