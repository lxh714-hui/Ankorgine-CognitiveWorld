from cognitive_world.agent import (
    AgentActionLoop,
    AgentTurn,
    Character,
    CognitionContext,
    RuntimeAgent,
)
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    CognitionState,
    CognitiveRuntime,
    Goal,
    MemoryStore,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import Observation, ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.decision.context import DecisionContext
from cognitive_world.resolution.engine import ResolutionDecision
from _trusted_event_support import FixedResolutionEngine as TrustedTestResolutionEngine
from tests._trusted_observation_support import make_trusted_observation


class CapturingDecision(AgentDecision):
    def __init__(self):
        self.received = None

    def propose(self, context):
        self.received = context
        return super().propose(context)


class LegacyDecision:
    def __init__(self):
        self.received = None

    def propose(self, context):
        self.received = context
        return ActionProposal(
            "legacy-proposal", context.cognition_state.agent_id, "wait"
        )


class ConfirmedResolutionEngine(TrustedTestResolutionEngine):
    def __init__(self):
        super().__init__(ResolutionDecision(True, "confirmed"))


def make_context():
    observations = ObservationStore()
    observation = make_trusted_observation(
        "observation-1", "agent-1", "event-1", {"noticed": "a fact"}
    )
    observations.add(observation)
    character = Character(
        "character-1",
        "agent-1",
        "personality-1",
        goal_ids=["goal-1"],
        belief_ids=["belief-1"],
    )
    context = CognitionContext.from_character(
        character,
        CognitionContainer(),
        MemoryStore(),
        observation_store=observations,
    )
    return context, observations, observation


def test_agent_turn_processes_observations_and_passes_cognition_state():
    context, _, _ = make_context()
    context.cognition_container.add_belief(
        Belief("belief-1", "agent-1", "claim", ["event-1"], 0.7)
    )
    context.cognition_container.add_goal(
        Goal("goal-1", "agent-1", "objective", 0.8, "active")
    )
    runtime = CognitiveRuntime()
    agent = RuntimeAgent("agent-1", "character-1", goal_ids=["goal-1"])
    decision = CapturingDecision()

    proposal = AgentTurn(cognitive_runtime=runtime).execute(agent, context, decision)

    assert isinstance(decision.received, DecisionContext)
    assert decision.received.cognition_state.record_type.endswith(".CognitionState")
    assert decision.received.cognition_state.agent_id == "agent-1"
    assert decision.received.cognition_state.percept_ids == (
        "percept:observation-1",
    )
    assert decision.received.cognition_state.belief_ids == ("belief-1",)
    assert decision.received.cognition_state.goal_ids == ("goal-1",)
    assert tuple(belief.belief_id for belief in decision.received.beliefs) == (
        "belief-1",
    )
    assert tuple(goal.goal_id for goal in decision.received.goals) == ("goal-1",)
    assert decision.received.emotion is None
    assert isinstance(proposal, ActionProposal)
    assert proposal.agent_id == "agent-1"
    assert runtime.working_memory_store.get("agent-1").percept_ids == [
        "percept:observation-1"
    ]


def test_agent_turn_builds_decision_context_without_explicit_runtime():
    context, _, _ = make_context()
    decision = LegacyDecision()

    proposal = AgentTurn().execute(RuntimeAgent("agent-1"), context, decision)

    assert proposal.proposal_id == "legacy-proposal"
    assert isinstance(decision.received, DecisionContext)
    assert decision.received.cognition_state.agent_id == "agent-1"
    assert decision.received.cognition_state.percept_ids == (
        "percept:observation-1",
    )


def test_cognition_integration_has_no_world_or_event_side_effects():
    context, _, source_observation = make_context()
    runtime = CognitiveRuntime()
    world_state = WorldState()
    world_state.load_fact("unchanged", {"value": 1})
    event_history = EventHistory()
    event_history.append(Event("event-existing", "existing", "t1"))
    before_facts = world_state.facts
    before_events = event_history.get_events()

    AgentTurn(cognitive_runtime=runtime).execute(
        RuntimeAgent("agent-1"), context, AgentDecision()
    )

    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
    assert source_observation.content == {"noticed": "a fact"}


def test_agent_action_loop_keeps_legacy_path_working():
    context, _, _ = make_context()

    action_loop = AgentActionLoop(
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=ConfirmedResolutionEngine()
        )
    )
    event = action_loop.run_turn(
        RuntimeAgent("agent-1"), context, AgentDecision()
    )

    assert isinstance(event, Event)
    assert event.metadata["action_proposal_id"] == (
        "action-proposal:agent-1:placeholder"
    )
