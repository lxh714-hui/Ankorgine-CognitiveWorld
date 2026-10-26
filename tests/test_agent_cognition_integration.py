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
from tests._l1_history_support import light_history


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
    history_context, observation = light_history("agent-1", "event-1")
    observations = history_context.observation_store
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
    return context, observations, observation, history_context


def test_agent_turn_processes_observations_and_passes_cognition_state():
    context, _, observation, history_context = make_context()
    context.cognition_container.add_belief(
        Belief("belief-1", "agent-1", "claim", ["event-1"], 0.7)
    )
    context.cognition_container.add_goal(
        Goal("goal-1", "agent-1", "objective", 0.8, "active")
    )
    runtime = CognitiveRuntime()
    runtime._bind_observation_history(history_context.event_history)
    agent = RuntimeAgent("agent-1", "character-1", goal_ids=["goal-1"])
    decision = CapturingDecision()

    proposal = AgentTurn(cognitive_runtime=runtime).execute(agent, context, decision)

    assert isinstance(decision.received, DecisionContext)
    assert decision.received.cognition_state.record_type.endswith(".CognitionState")
    assert decision.received.cognition_state.agent_id == "agent-1"
    assert decision.received.cognition_state.percept_ids == (
        "percept:" + observation.observation_id,
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
        "percept:" + observation.observation_id
    ]


def test_agent_turn_builds_decision_context_without_explicit_runtime():
    context, _, observation, history_context = make_context()
    decision = LegacyDecision()

    turn = AgentTurn()
    proposal = turn.execute(RuntimeAgent("agent-1"), context, decision)

    assert proposal.proposal_id == "legacy-proposal"
    assert isinstance(decision.received, DecisionContext)
    assert decision.received.cognition_state.agent_id == "agent-1"
    assert decision.received.cognition_state.percept_ids == ()
    item, = decision.received.cognition_state.metadata["l1_ingestion"]["items"]
    assert item["source"] == "eligible" and item["history"] == "undetermined"
    assert item["consumption"] == "not_consumed"
    assert turn.cognitive_runtime.working_memory_store.get("agent-1") is None
    assert not turn.cognitive_runtime.has_consumed_observation(
        "agent-1", observation, source_event_id=observation.source_event_id)


def test_cognition_integration_has_no_world_or_event_side_effects():
    context, _, source_observation, history_context = make_context()
    runtime = CognitiveRuntime()
    runtime._bind_observation_history(history_context.event_history)
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
    assert source_observation.content.predicate == "room_light_on"
    assert source_observation.content.value is True


def test_agent_action_loop_keeps_legacy_path_working():
    context, _, observation, history_context = make_context()

    action_loop = AgentActionLoop(
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=ConfirmedResolutionEngine()
        )
    )
    action_loop.agent_turn.cognitive_runtime._bind_observation_history(history_context.event_history)
    event = action_loop.run_turn(
        RuntimeAgent("agent-1"), context, AgentDecision()
    )

    assert isinstance(event, Event)
    assert event.metadata["action_proposal_id"] == (
        "action-proposal:agent-1:placeholder"
    )
