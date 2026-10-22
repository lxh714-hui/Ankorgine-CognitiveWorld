from copy import deepcopy

import pytest

from cognitive_world.cognition import (
    Belief,
    CognitionState,
    Goal,
    Personality,
    SelfModel,
)
from cognitive_world.decision import ActionProposal, AgentDecision, DecisionContext


def make_decision_context():
    cognition_state = CognitionState(
        agent_id="agent-1",
        percept_ids=["percept-1"],
        belief_ids=["belief-1"],
        goal_ids=["goal-1"],
        focus={"topic": "nearby"},
    )
    personality = Personality(
        owner_id="agent-1",
        traits={"trust": 0.7},
        preferences={"risk": "cautious"},
        values={"honesty": 0.9},
    )
    self_model = SelfModel(
        owner_id="agent-1",
        identity={"role": "scout"},
        capabilities={"navigation": True},
        limitations={"visibility": "low"},
        self_beliefs=[{"claim": "careful", "confidence": 0.8}],
    )
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": "path is safe"},
        source_refs=["observation-1"],
        confidence=0.6,
    )
    return DecisionContext(
        cognition_state=cognition_state,
        personality=personality,
        self_model=self_model,
        goals=[Goal("goal-1", "agent-1", "Explore", 0.5, "active")],
        beliefs=[belief],
        metadata={"source": "test"},
    )


def test_decision_context_preserves_multi_source_state():
    context = make_decision_context()

    assert context.cognition_state.agent_id == "agent-1"
    assert context.cognition_state.percept_ids == ("percept-1",)
    assert context.personality.preferences == {"risk": "cautious"}
    assert context.self_model.capabilities == {"navigation": True}
    assert context.goals[0].goal_id == "goal-1"
    assert context.beliefs[0].belief_id == "belief-1"
    assert context.metadata == {"source": "test"}


def test_agent_decision_accepts_decision_context_and_returns_proposal():
    context = make_decision_context()

    proposal = AgentDecision().propose(context)

    assert isinstance(proposal, ActionProposal)
    assert proposal.agent_id == "agent-1"


def test_agent_decision_keeps_legacy_cognition_state_and_mapping_inputs():
    decision = AgentDecision()
    cognition_proposal = decision.propose(CognitionState(agent_id="agent-state"))
    mapping_proposal = decision.propose({"agent_id": "agent-mapping"})

    assert cognition_proposal.agent_id == "agent-state"
    assert mapping_proposal.agent_id == "agent-mapping"


def test_decision_context_and_decision_do_not_mutate_cognition_inputs():
    context = make_decision_context()
    source_personality = deepcopy(context.personality)
    source_self_model = deepcopy(context.self_model)
    source_belief = deepcopy(context.beliefs[0])
    source_goal = deepcopy(context.goals[0])

    # DecisionContext exposes recursively immutable snapshots.
    with pytest.raises(TypeError):
        context.personality.traits["trust"] = 0.0
    with pytest.raises(TypeError):
        context.self_model.capabilities["navigation"] = False
    with pytest.raises(TypeError):
        context.beliefs[0].content["claim"] = "changed"
    with pytest.raises(AttributeError):
        context.goals[0].description = "changed"
    assert source_personality.traits["trust"] == 0.7
    assert source_self_model.capabilities["navigation"] is True
    assert source_belief.content["claim"] == "path is safe"
    assert source_goal.description == "Explore"

    decision_context = make_decision_context()
    original = make_decision_context()
    proposal = AgentDecision().propose(decision_context)

    assert proposal.agent_id == "agent-1"
    assert decision_context == original
