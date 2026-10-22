from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    CognitiveRuntime,
    Goal,
    MemoryStore,
    Personality,
    SelfModel,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision, DecisionContext
from cognitive_world.event.history import EventHistory


class CapturingDecision(AgentDecision):
    def __init__(self):
        self.context = None

    def propose(self, context):
        self.context = context
        return super().propose(context)


def test_agent_turn_reads_each_cognition_type_from_its_authoritative_store():
    container = CognitionContainer()
    personality = Personality(
        owner_id="agent-1", traits={"patience": 0.8}
    )
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": "path is clear"},
        source_refs=["observation-1"],
        confidence=0.75,
    )
    goal = Goal(
        goal_id="goal-1",
        owner_id="agent-1",
        description="Reach the station",
        priority=0.9,
    )
    self_model = SelfModel(
        owner_id="agent-1", capabilities={"navigation": True}
    )

    container.add_personality(personality)
    container.add_belief(belief)
    container.add_goal(goal)
    container.add_self_model(self_model)

    character = Character(
        id="character-1",
        agent_id="agent-1",
        personality_id=personality.id,
        belief_ids=[belief.id],
        goal_ids=[goal.id],
    )
    cognition_context = CognitionContext.from_character(
        character, container, MemoryStore()
    )
    runtime = CognitiveRuntime()
    decision = CapturingDecision()
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    facts_before = world_state.facts
    event_history = EventHistory()
    event_history.append(Event("existing-event", "record", "t0"))
    events_before = event_history.get_events()

    proposal = AgentTurn(cognitive_runtime=runtime).execute(
        RuntimeAgent("agent-1", "character-1"), cognition_context, decision
    )

    assert isinstance(decision.context, DecisionContext)
    assert decision.context.personality.traits["patience"] == 0.8
    assert decision.context.self_model.capabilities["navigation"] is True
    assert tuple(item.belief_id for item in decision.context.beliefs) == ("belief-1",)
    assert tuple(item.goal_id for item in decision.context.goals) == ("goal-1",)
    assert decision.context.cognition_state.belief_ids == ("belief-1",)
    assert decision.context.cognition_state.goal_ids == ("goal-1",)
    assert isinstance(proposal, ActionProposal)
    assert proposal.agent_id == "agent-1"
    assert world_state.facts == facts_before
    assert event_history.get_events() == events_before


def test_cognitive_runtime_has_no_hidden_long_term_store_defaults():
    runtime = CognitiveRuntime()

    assert runtime.belief_store is None
    assert runtime.goal_store is None
    assert runtime.self_model_store is None
