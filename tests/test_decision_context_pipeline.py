from copy import deepcopy

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import (
    Belief,
    BeliefStore,
    CognitionContainer,
    CognitiveRuntime,
    Goal,
    GoalStore,
    MemoryStore,
    Personality,
    SelfModel,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision, DecisionContext
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import Observation, ObservationStore
from tests._trusted_observation_support import make_trusted_observation


class CapturingDecision(AgentDecision):
    def __init__(self):
        self.received = None

    def propose(self, context):
        self.received = context
        return super().propose(context)


class MutatingDecision(AgentDecision):
    def propose(self, context):
        context.personality.traits["caution"] = 0
        context.self_model.capabilities["travel"] = False
        context.beliefs[0].content["claim"] = "changed"
        context.goals[0].description = "changed"
        return super().propose(context)


def make_pipeline():
    cognition = CognitionContainer()
    personality = Personality(
        owner_id="agent-1", traits={"caution": 0.8}, preferences={"risk": "low"}
    )
    belief = Belief(
        id="belief-1",
        owner_id="agent-1",
        content={"claim": "route is safe"},
        source="observation-1",
        confidence=0.7,
    )
    goal = Goal(
        id="goal-1",
        owner_id="agent-1",
        description="Reach the station",
        priority=0.9,
        status="active",
    )
    cognition.add_personality(personality)
    cognition.add_belief(belief)
    cognition.add_goal(goal)

    self_models = cognition.self_model_store
    self_model = SelfModel(
        owner_id="agent-1",
        identity={"role": "scout"},
        capabilities={"travel": True},
        limitations={"visibility": "low"},
    )
    self_models.add(self_model)

    observations = ObservationStore()
    observation = make_trusted_observation(
        observation_id="observation-1",
        observer_id="agent-1",
        source_event_id="event-1",
        content={"noticed": "the route"},
    )
    observations.add(observation)
    character = Character(
        id="character-1",
        agent_id="agent-1",
        personality_id=personality.id,
        belief_ids=[belief.id],
        goal_ids=[goal.id],
    )
    context = CognitionContext.from_character(
        character,
        cognition,
        MemoryStore(),
        observation_store=observations,
    )
    stale_beliefs = BeliefStore()
    stale_beliefs.add(
        Belief("stale-belief", "agent-1", {"claim": "stale"})
    )
    stale_goals = GoalStore()
    stale_goals.add(Goal("stale-goal", "agent-1", "Stale", 0.1, "active"))
    runtime = CognitiveRuntime(
        belief_store=stale_beliefs,
        goal_store=stale_goals,
    )
    return (
        context,
        runtime,
        cognition,
        self_models,
        observation,
        personality,
        belief,
        goal,
    )


def test_agent_turn_builds_complete_decision_context_and_proposal():
    context, runtime, _, _, _, personality, belief, goal = make_pipeline()
    decision = CapturingDecision()

    proposal = AgentTurn(cognitive_runtime=runtime).execute(
        RuntimeAgent("agent-1", "character-1"), context, decision
    )

    decision_context = decision.received
    assert isinstance(decision_context, DecisionContext)
    assert decision_context.cognition_state.agent_id == "agent-1"
    assert decision_context.cognition_state.percept_ids == (
        "percept:observation-1",
    )
    assert decision_context.personality.traits["caution"] == 0.8
    assert decision_context.self_model.owner_id == "agent-1"
    assert tuple(item.belief_id for item in decision_context.beliefs) == (
        belief.belief_id,
    )
    assert tuple(item.goal_id for item in decision_context.goals) == (goal.goal_id,)
    assert isinstance(proposal, ActionProposal)
    assert proposal.agent_id == "agent-1"


def test_decision_only_receives_snapshots_and_cannot_mutate_authoritative_inputs():
    context, runtime, cognition, self_models, observation, personality, belief, goal = (
        make_pipeline()
    )
    personality_before = deepcopy(cognition.get_personality(personality.id))
    belief_before = deepcopy(cognition.get_belief(belief.id))
    goal_before = deepcopy(cognition.get_goal(goal.id))
    self_model_before = deepcopy(self_models.get("agent-1"))
    observation_before = deepcopy(observation)
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    world_before = world_state.facts
    event_history = EventHistory()
    event_history.append(Event("existing-event", "record", "t0"))
    events_before = event_history.get_events()

    with pytest.raises(TypeError):
        AgentTurn(cognitive_runtime=runtime).execute(
            RuntimeAgent("agent-1", "character-1"),
            context,
            MutatingDecision(),
        )

    assert cognition.get_personality(personality.id) == personality_before
    assert cognition.get_belief(belief.id) == belief_before
    assert cognition.get_goal(goal.id) == goal_before
    assert self_models.get("agent-1") == self_model_before
    assert context.get_observations()[0] == observation_before
    assert world_state.facts == world_before
    assert event_history.get_events() == events_before
