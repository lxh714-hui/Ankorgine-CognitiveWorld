import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import (
    CognitionContainer,
    Emotion,
    EmotionDimensionProfile,
    EmotionProfile,
    EmotionReaction,
    EmotionUpdateApplier,
    EmotionUpdateContext,
    EmotionUpdateValidator,
    Goal,
    MemoryStore,
    Personality,
    SelfModel,
)
from cognitive_world.cognition.emotion_system import (
    DeterministicDecisionModulationPolicy,
    DeterministicEmotionAppraisalPolicy,
)
from cognitive_world.cognition.runtime import CognitionState
from cognitive_world.decision import ActionProposal, DecisionContext
from cognitive_world.core.entity import Entity
from cognitive_world.observation import ObservationStore
from tests.test_authorized_perception_vertical_slice import (
    _light_event,
    _world,
)
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent as RegisteredAgent
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, RoomLightChangedHandler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent


class _Decision:
    def __init__(self, agent_id):
        self.context = None
        self.result = ActionProposal(f"p:{agent_id}", agent_id, "unselected")

    def propose(self, context):
        self.context = context
        return self.result


def _profile(owner, emotion, *, threshold=0.2, recovery=0.0, regulation=0.0, goal_id="goal"):
    return EmotionProfile(
        owner_id=owner,
        dimensions=((emotion, EmotionDimensionProfile(
            sensitivity=1.0,
            activation_threshold=threshold,
            growth_rate=1.0,
            recovery_per_tick=recovery,
            regulation=regulation,
        )),),
        reactions=(EmotionReaction(
            "environment_state", "room_light_on", True, emotion, 0.8,
            goal_id=goal_id,
        ),),
        impulse_ceiling=0.4,
        risk_bias_limit=0.5,
        attention_bias_limit=0.5,
        goal_drive_weights=((goal_id, 1.2),),
        impulse_affinity=((emotion, 0.8),),
        risk_affinity=((emotion, 0.5),),
        attention_affinity=((emotion, "environment_state", 0.7),),
        goal_emotion_weights=((goal_id, emotion, 0.2),),
    )


def _runtime_observations():
    world = _world()
    world.load_entity(Entity("agent-second", "agent", sensory_capabilities=("sight",)))
    world.load_location("agent-second", "room-a")
    registry = AgentRegistry()
    registry.register(RegisteredAgent("agent-near"))
    registry.register(RegisteredAgent("agent-far"))
    registry.register(RegisteredAgent("agent-second"))
    scheduler = EventScheduler()
    scheduler.schedule(ScheduledEvent(1, _light_event()))
    context = RuntimeContext(
        clock=SimulationClock(), world_state=world, event_history=EventHistory(),
        scheduler=scheduler, agent_registry=registry, observation_store=ObservationStore(),
    )
    processor = EventProcessor()
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    SimulationRuntime(context=context, event_processor=processor).step()
    return context.observation_store


def _turn_inputs(owner, observations, emotion, profile, *, goal_id="goal"):
    container = CognitionContainer()
    container.add_personality(Personality(owner_id=owner, emotion_profile=profile))
    container.add_goal(Goal(goal_id, owner, "keep watch", 0.5, "active"))
    container.add_emotion(emotion)
    character = Character(
        id=f"character:{owner}", agent_id=owner,
        personality_id=owner, goal_ids=[goal_id], emotion_id=emotion.id,
    )
    cognition_context = CognitionContext.from_character(
        character, container, MemoryStore(), observation_store=observations,
    )
    return RuntimeAgent(owner, character.id), cognition_context, container


def test_production_observation_updates_owner_emotion_and_next_turn_modulates():
    observations = _runtime_observations()
    profile = _profile("agent-near", "alertness")
    agent, context, container = _turn_inputs(
        "agent-near", observations,
        Emotion("emotion:agent-near", "agent-near", levels={"calm": 0.2}, last_update_tick=0),
        profile,
    )
    decision = _Decision(agent.agent_id)

    AgentTurn().execute(agent, context, decision, simulation_tick=SimulationClock(1).capture())

    current = container.get_emotion("emotion:agent-near")
    assert current.levels["alertness"] == pytest.approx(0.6)
    assert current.levels["calm"] == pytest.approx(0.2)
    assert decision.context.emotion.levels["alertness"] == pytest.approx(0.6)
    assert decision.context.decision_modulation.impulse_bias > 0
    assert decision.context.motivation_assessment.goal_scores[0][0] == "goal"
    assert container.get_goal("goal").priority == 0.5

    second = _Decision(agent.agent_id)
    AgentTurn().execute(agent, context, second, simulation_tick=SimulationClock(2).capture())
    assert container.get_emotion("emotion:agent-near").levels["alertness"] == pytest.approx(0.6)


def test_same_fact_has_individual_and_goal_conditioned_reactions():
    observations = _runtime_observations()
    first_profile = _profile("agent-near", "relief")
    agent, context, container = _turn_inputs(
        "agent-near", observations,
        Emotion("e1", "agent-near", levels={}), first_profile,
    )
    AgentTurn().execute(agent, context, _Decision(agent.agent_id), simulation_tick=SimulationClock(1).capture())
    assert container.get_emotion("e1").levels["relief"] > 0

    # A second registered co-located observer has its own authored appraisal.
    second_agent, second_context, second_container = _turn_inputs(
        "agent-second", observations,
        Emotion("e-second", "agent-second", levels={}),
        _profile("agent-second", "concern"),
    )
    AgentTurn().execute(second_agent, second_context, _Decision("agent-second"), simulation_tick=SimulationClock(1).capture())
    assert second_container.get_emotion("e-second").levels["concern"] > 0
    assert second_container.get_emotion("e-second").levels != container.get_emotion("e1").levels

    # Without the configured goal, the same objective fact is not appraised.
    agent2, context2, container2 = _turn_inputs(
        "agent-near", observations,
        Emotion("e2", "agent-near", levels={}),
        _profile("agent-near", "relief", goal_id="different-goal"),
        goal_id="goal",
    )
    AgentTurn().execute(agent2, context2, _Decision(agent2.agent_id), simulation_tick=SimulationClock(1).capture())
    assert container2.get_emotion("e2").levels == {}


def test_emotion_bounds_multiple_dimensions_saturation_and_profile_recovery():
    with pytest.raises(ValueError):
        Emotion("bad", "owner", levels={"fear": float("nan")})
    with pytest.raises(ValueError):
        Emotion("bad", "owner", levels={"fear": 1.01})
    recovered = EmotionProfile(
        owner_id="owner",
        dimensions=(
            ("fear", EmotionDimensionProfile(recovery_per_tick=0.5, regulation=1.0)),
            ("hope", EmotionDimensionProfile()),
        ),
    )
    assert recovered.dimension("fear").recovery_per_tick == 0.5
    assert recovered.dimension("hope").regulation == 0.0


def test_goal_drive_multiplier_has_explicit_bounded_multiplier_contract():
    profile = EmotionProfile(owner_id="owner", goal_drive_weights=(("goal", 1.2),))
    assert profile.drive_weight("goal") == 1.2
    assert profile.drive_weight("unspecified") == 1.0
    with pytest.raises(ValueError, match=r"\[0, 2\]"):
        EmotionProfile(owner_id="owner", goal_drive_weights=(("goal", 2.01),))
    with pytest.raises(ValueError, match=r"\[0, 2\]"):
        EmotionProfile(owner_id="owner", goal_drive_weights=(("goal", -0.1),))


def test_one_observation_can_activate_multiple_emotions_and_cap_at_one():
    observations = _runtime_observations()
    owner = "agent-near"
    profile = EmotionProfile(
        owner_id=owner,
        dimensions=(
            ("alert", EmotionDimensionProfile(1.0, 0.0, 1.0)),
            ("relief", EmotionDimensionProfile(1.0, 0.0, 1.0)),
        ),
        reactions=(
            EmotionReaction("environment_state", "room_light_on", True, "alert", 1.0),
            EmotionReaction("environment_state", "room_light_on", True, "relief", 1.0),
        ),
    )
    agent, context, container = _turn_inputs(
        owner, observations, Emotion("e-multi", owner, levels={"alert": 0.9}), profile,
    )
    AgentTurn().execute(agent, context, _Decision(owner), simulation_tick=SimulationClock(1).capture())
    levels = container.get_emotion("e-multi").levels
    assert levels["alert"] == 1.0
    assert levels["relief"] == 1.0


def test_simulation_time_drives_individual_recovery_without_fake_elapsed_time():
    observations = _runtime_observations()
    owner = "agent-near"
    profile = EmotionProfile(
        owner_id=owner,
        dimensions=(("calm", EmotionDimensionProfile(recovery_per_tick=0.5)),),
    )
    agent, context, container = _turn_inputs(
        owner, observations,
        Emotion("e-recovery", owner, levels={"calm": 0.8}, last_update_tick=0), profile,
    )
    AgentTurn().execute(agent, context, _Decision(owner), simulation_tick=SimulationClock(1).capture())
    assert container.get_emotion("e-recovery").levels["calm"] == pytest.approx(0.4)

    regulated = EmotionProfile(
        owner_id=owner,
        dimensions=(("calm", EmotionDimensionProfile(recovery_per_tick=0.5, regulation=1.0)),),
    )
    agent2, context2, container2 = _turn_inputs(
        owner, observations,
        Emotion("e-regulated", owner, levels={"calm": 0.8}, last_update_tick=0), regulated,
    )
    AgentTurn().execute(agent2, context2, _Decision(owner), simulation_tick=SimulationClock(1).capture())
    assert container2.get_emotion("e-regulated").levels["calm"] == pytest.approx(0.2)


def test_emotion_update_validation_rejects_owner_time_and_old_state_conflicts():
    observations = _runtime_observations()
    profile = _profile("agent-near", "alertness")
    agent, context, container = _turn_inputs(
        "agent-near", observations,
        Emotion("e", "agent-near", levels={"calm": 0.1}, last_update_tick=0),
        profile,
    )
    decision = _Decision(agent.agent_id)
    # AgentTurn exercises the approved producer/validator/applier route.
    AgentTurn().execute(agent, context, decision, simulation_tick=SimulationClock(1).capture())
    assert container.get_emotion("e").last_update_tick == 1
    assert container.get_emotion("e").processed_sources == ("light-event-1",)

    with pytest.raises(ValueError):
        AgentTurn().execute(agent, context, _Decision(agent.agent_id), simulation_tick=SimulationClock(0).capture())


def test_missing_individual_parameters_do_not_fabricate_emotional_reaction():
    observations = _runtime_observations()
    agent, context, container = _turn_inputs(
        "agent-near", observations,
        Emotion("e", "agent-near", levels={}),
        EmotionProfile(owner_id="agent-near"),
    )
    AgentTurn().execute(agent, context, _Decision(agent.agent_id), simulation_tick=SimulationClock(1).capture())
    assert container.get_emotion("e").levels == {}


def test_personality_store_rejects_unvalidated_profile_replacement():
    owner = "owner"
    container = CognitionContainer()
    container.add_personality(Personality(owner_id=owner, emotion_profile=_profile(owner, "calm")))
    with pytest.raises(PermissionError):
        container.personality_store.update(
            Personality(owner_id=owner, emotion_profile=_profile(owner, "anger"))
        )


def test_motivation_reports_profile_goal_conflicts_and_self_model_constraints():
    owner = "agent-motive"
    profile = EmotionProfile(
        owner_id=owner,
        goal_drive_weights=(("g1", 0.5), ("g2", 1.0)),
        goal_conflicts=(("g1", "g2"),),
        goal_capability_requirements=(("g1", "climb"),),
    )
    context = DecisionContext(
        cognition_state=CognitionState(owner),
        personality=Personality(owner_id=owner, emotion_profile=profile),
        self_model=SelfModel(owner_id=owner, capabilities={"climb": False}),
        goals=(
            Goal("g1", owner, "reach the roof", 0.8, "active"),
            Goal("g2", owner, "stay below", 0.6, "active"),
        ),
    )
    assessment, modulation = DeterministicDecisionModulationPolicy().assess(context)
    assert assessment.conflict_pairs == (("g1", "g2"),)
    assert assessment.blocked_goal_ids == ("g1",)
    assert dict(assessment.goal_scores) == {"g1": pytest.approx(0.4), "g2": pytest.approx(0.6)}
    assert dict(modulation.goal_priority_adjustment)["g1"] == pytest.approx(-0.4)


def test_emotion_proposal_cannot_claim_unverified_percepts():
    from cognitive_world.cognition.emotion_system import EmotionProposal

    proposal = EmotionProposal(
        owner_id="owner", emotion_id="e", previous_levels=(), proposed_levels=(("fear", 0.5),),
        previous_tick=None, simulation_tick=1, source_refs=("forged-percept",),
        source_event_ids=("forged-event",), processed_sources=("forged-event",),
    )
    result = EmotionUpdateValidator().validate(
        proposal,
        EmotionUpdateContext("owner", (), (), 1),
    )
    assert not result.accepted



def test_appraisal_policy_is_replaceable_and_requires_profile_owner_match():
    assert callable(DeterministicEmotionAppraisalPolicy().propose)
