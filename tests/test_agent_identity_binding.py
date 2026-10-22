import pytest

from cognitive_world.agent import (
    AgentContext,
    AgentTurn,
    Character,
    CognitionContext,
    RuntimeAgent,
)
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    Goal,
    MemoryStore,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision, DecisionContext
from cognitive_world.event.history import EventHistory


class CapturingDecision(AgentDecision):
    def __init__(self):
        self.received = None

    def propose(self, context):
        self.received = context
        return ActionProposal("proposal-1", context.cognition_state.agent_id, "wait")


def make_context(owner_id: str, character_id: str = "character-1"):
    container = CognitionContainer()
    # The Character deliberately references records owned by a different Agent.
    # CognitionContext must filter these before constructing DecisionContext.
    container.add_belief(
        Belief("belief-private", "agent-2", {"claim": "private"}, confidence=0.9)
    )
    container.add_goal(
        Goal("goal-private", "agent-2", "private goal", 0.9, "active")
    )
    character = Character(
        id=character_id,
        agent_id=owner_id,
        personality_id="",
        belief_ids=["belief-private"],
        goal_ids=["goal-private"],
    )
    return CognitionContext.from_character(character, container, MemoryStore()), container


def test_same_agent_context_executes_and_decision_context_is_owner_scoped():
    context, container = make_context("agent-1")
    agent = RuntimeAgent(
        "agent-1",
        "character-1",
        context=AgentContext("agent-1", character_id="character-1"),
    )
    decision = CapturingDecision()
    world_state = WorldState()
    world_state.load_fact("stable", {"value": [1]})
    history = EventHistory()
    history.append(Event("event-1", "record", "t1"))
    before_world = world_state.facts
    before_events = history.get_events()

    result = AgentTurn().execute(agent, context, decision)

    assert isinstance(result, ActionProposal)
    assert isinstance(decision.received, DecisionContext)
    assert decision.received.cognition_state.agent_id == "agent-1"
    assert decision.received.beliefs == ()
    assert decision.received.goals == ()
    assert container.get_belief("belief-private").owner_id == "agent-2"
    assert container.get_goal("goal-private").owner_id == "agent-2"
    assert world_state.facts == before_world
    assert history.get_events() == before_events


def test_different_agent_cognition_context_is_rejected_before_decision():
    context, container = make_context("agent-2", character_id="character-2")
    agent = RuntimeAgent("agent-1", "character-1")
    decision = CapturingDecision()
    world_state = WorldState()
    history = EventHistory()
    beliefs_before = container.belief_store.get_all()
    goals_before = container.goal_store.get_all()
    before_world = world_state.facts
    before_events = history.get_events()

    with pytest.raises(
        ValueError,
        match="RuntimeAgent agent_id must match CognitionContext owner_id",
    ):
        AgentTurn().execute(agent, context, decision)

    assert decision.received is None
    assert world_state.facts == before_world
    assert history.get_events() == before_events
    assert container.belief_store.get_all() == beliefs_before
    assert container.goal_store.get_all() == goals_before


def test_runtime_agent_rejects_context_owned_by_another_agent():
    with pytest.raises(ValueError, match="must match its AgentContext agent_id"):
        RuntimeAgent("agent-1", context=AgentContext("agent-2"))


def test_runtime_agent_and_cognition_context_character_binding_must_match():
    context, _ = make_context("agent-1", character_id="character-other")
    agent = RuntimeAgent(
        "agent-1",
        "character-1",
        context=AgentContext("agent-1", character_id="character-1"),
    )

    with pytest.raises(ValueError, match="AgentContext character_id must match"):
        AgentTurn().execute(agent, context, CapturingDecision())
