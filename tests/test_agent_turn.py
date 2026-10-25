from copy import deepcopy

import pytest

from cognitive_world.agent import (
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
from cognitive_world.decision import ActionProposal
from cognitive_world.decision.context import DecisionContext
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import Observation, ObservationStore
from tests._trusted_observation_support import make_trusted_observation


class RecordingDecision:
    def __init__(self):
        self.received_context = None
        self.proposal = ActionProposal("proposal_001", "agent_001", "wait")

    def propose(self, context):
        self.received_context = context
        return self.proposal


class MutatingDecision(RecordingDecision):
    def propose(self, context):
        context.cognition_state.goal_ids.append("external")
        context.cognition_state.percept_ids.append("external")
        context.goals[0].description = "changed"
        context.beliefs[0].content["claim"] = "changed"
        return self.proposal


def make_inputs():
    container = CognitionContainer()
    goal = Goal("goal_001", "agent_001", "original goal", 0.5, "active")
    belief = Belief("belief_001", "agent_001", {"claim": "original"}, 0.7, "record")
    container.add_goal(goal)
    container.add_belief(belief)
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
        goal_ids=[goal.id],
        belief_ids=[belief.id],
        emotion_id="emotion_001",
    )
    # Attach an emotion through the container using a local import to keep fixtures clear.
    from cognitive_world.cognition import Emotion

    emotion = Emotion("emotion_001", "agent_001", "calm", 0.2)
    container.add_emotion(emotion)
    observation_store = ObservationStore()
    observation = make_trusted_observation(
        "obs_001", "agent_001", "event_001", {"detail": "seen"}
    )
    observation_store.add(observation)
    cognition_context = CognitionContext.from_character(
        character,
        container,
        MemoryStore(),
        observation_store=observation_store,
    )
    agent = RuntimeAgent("agent_001", character.id, goal_ids=[goal.id])
    return agent, cognition_context, container, observation_store


def test_agent_turn_calls_decision_and_returns_action_proposal():
    agent, cognition_context, _, _ = make_inputs()
    decision = RecordingDecision()

    from test_cognitive_runtime import _real_input
    runtime, observation = _real_input(agent.agent_id, "agent-turn-input")
    store = ObservationStore()
    store.add(observation)
    cognition_context.observation_store = store
    proposal = AgentTurn(cognitive_runtime=runtime).execute(agent, cognition_context, decision)

    assert proposal is decision.proposal
    assert isinstance(proposal, ActionProposal)
    assert isinstance(decision.received_context, DecisionContext)
    assert decision.received_context.cognition_state.agent_id == "agent_001"
    assert decision.received_context.cognition_state.goal_ids == ("goal_001",)
    assert len(decision.received_context.goals) == 1
    assert decision.received_context.cognition_state.percept_ids == (
        "percept:" + observation.observation_id,
    )


def test_decision_cannot_mutate_agent_or_cognition_context_stores():
    agent, cognition_context, container, observation_store = make_inputs()
    original_agent = deepcopy(agent)
    decision = MutatingDecision()

    with pytest.raises(AttributeError):
        AgentTurn().execute(agent, cognition_context, decision)

    assert agent.agent_id == original_agent.agent_id
    assert agent.get_goals() == original_agent.get_goals()
    assert container.get_goal("goal_001").description == "original goal"
    assert container.get_belief("belief_001").content == {"claim": "original"}
    assert observation_store.get("obs_001").content == {"detail": "seen"}
    assert cognition_context.get_emotion().state == "calm"


def test_agent_turn_has_no_event_or_world_state_side_effects():
    agent, cognition_context, _, _ = make_inputs()
    decision = RecordingDecision()
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("event_001", "existing", "t1"))
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    AgentTurn().execute(agent, cognition_context, decision)

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
