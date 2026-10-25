import json

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    Emotion,
    EmotionDimensionProfile,
    EmotionProfile,
    EmotionReaction,
    Goal,
    MemoryStore,
    Personality,
    SelfModel,
)
from cognitive_world.cognition.runtime import CognitionState
from cognitive_world.cognition.emotion_system import DecisionModulation
from cognitive_world.cognition.emotion_system import DeterministicDecisionModulationPolicy
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import (
    ActionCandidate,
    ActionPipeline,
    AgentDecision,
    BoundedDecisionReviewPolicy,
    DeterministicActionEvaluationPolicy,
    DeterministicSituationAssessmentPolicy,
    ModelAssistedCandidatePolicy,
    OpenAICompatibleDecisionProvider,
    SituationAssessment,
)
from cognitive_world.decision.autonomous import SituationFact
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.context import DecisionContext
from cognitive_world.event import EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory
from cognitive_world.observation import ObservationStore
from cognitive_world.presentation import InMemoryChatOutputGateway, PresentationPipeline
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.engine import ResolutionEngine
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent


class _Provider:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def generate_candidates(self, situation, *, max_candidates, max_output_chars):
        self.calls += 1
        assert max_candidates <= 6
        assert max_output_chars <= 16_000
        if self.error:
            raise self.error
        return self.payload


def _assessment(context=None):
    context = context or DecisionContext(cognition_state=CognitionState("agent-a"))
    return DeterministicSituationAssessmentPolicy().assess(context)


def _candidate(owner, *, candidate_id, risk, commitment, goal="goal"):
    return ActionCandidate(
        candidate_id=candidate_id,
        owner_id=owner,
        goal_id=goal,
        intent=f"Try {candidate_id}",
        target=None,
        method=f"Use the {candidate_id} method",
        tools=(),
        required_capabilities=(),
        preconditions=(),
        steps=("Attempt one step, then reassess from the actual result.",),
        expected_result="Possible progress if Resolution confirms the attempt.",
        uncertainties=("Outcome is unknown until Resolution.",),
        estimated_risk=risk,
        estimated_cost=None,
        commitment=commitment,
        source_refs=(),
        strategy="test candidate",
    )


def test_situation_assessment_keeps_five_layers_and_evidence_categories_distinct():
    owner = "agent-a"
    cognition = CognitionContainer()
    goal = Goal("goal-a", owner, "protect the room", 0.8, "active")
    belief = Belief("belief-a", owner, {"claim": "the door is safe"}, ["obs-a"], 0.2)
    cognition.add_goal(goal)
    cognition.add_belief(belief)
    cognition.add_personality(Personality(
        owner, traits={"cautious": 0.8}, preferences={"method": "quiet"}, values={"value": "honesty"}
    ))
    cognition.add_self_model(SelfModel(owner, capabilities={"observe": True}, limitations={"injury": "wrist"}))
    cognition.add_emotion(Emotion("emotion-a", owner, levels={"fear": 0.4, "resolve": 0.3}))
    character = Character(
        "character-a", owner, owner, belief_ids=[belief.belief_id], goal_ids=[goal.goal_id], emotion_id="emotion-a"
    )
    context = CognitionContext.from_character(character, cognition, MemoryStore())
    decision_context = DecisionContext(
        cognition_state=CognitionState(owner),
        personality=context.get_personality(), self_model=context.get_self_model(),
        beliefs=context.get_beliefs(), goals=context.get_goals(), emotion=context.get_emotion(),
    )
    situation = DeterministicSituationAssessmentPolicy().assess(decision_context)

    assert situation.owner_id == owner
    assert situation.beliefs[0].claim == "claim the door is safe"
    assert situation.beliefs[0].confidence == pytest.approx(0.2)
    assert situation.observed_facts == ()  # subjective belief is not an observed fact
    assert situation.goals[0].goal_id == "goal-a"
    assert situation.capabilities == (("observe", True),)
    assert situation.personality_preferences == ("method", "quiet")
    assert situation.personality_values == ("value", "honesty")
    assert set(dict(situation.emotion_levels)) == {"fear", "resolve"}


def test_decision_subclass_without_parent_init_uses_immutable_default_policies():
    class CapturingDecision(AgentDecision):
        def __init__(self):
            self.received = None

        def propose(self, context):
            self.received = context
            return super().propose(context)

    agent, cognition_context, _ = _agent_decision_inputs(
        "agent-a", ObservationStore(), "protect", "investigate", None
    )
    decision = CapturingDecision()
    proposal = AgentTurn().execute(agent, cognition_context, decision)

    assert isinstance(decision.received, DecisionContext)
    assert proposal.agent_id == "agent-a"
    assert proposal.action_type != "unselected"


def test_cross_agent_owner_isolation_is_checked_before_situation_assessment():
    with pytest.raises(PermissionError, match="another Agent"):
        DeterministicSituationAssessmentPolicy().assess(DecisionContext(
            cognition_state=CognitionState("agent-a"),
            goals=(Goal("secret-goal", "agent-b", "private", 1.0),),
        ))


def test_model_candidate_accepts_novel_open_method():
    situation = _assessment()
    raw = json.dumps({
        "candidates": [{
            "intent": "Reach the upper shelf",
            "method": "Use the folded curtain as a temporary sling to move the box without lifting it directly",
            "tools": ["curtain"],
            "required_capabilities": ["knot tying"],
            "preconditions": ["The curtain is within reach"],
            "steps": ["Inspect the fabric", "Form a support loop", "Test the load gradually"],
            "expected_result": "The box may become reachable if the attempt is feasible",
            "uncertainties": ["Fabric strength is unknown"],
            "estimated_risk": 0.3,
            "estimated_cost": 0.2,
        }],
    })
    candidate = ModelAssistedCandidatePolicy(_Provider(raw)).generate(situation)[0][0]
    assert "folded curtain" in candidate.method
    assert len(candidate.steps) == 3
    proposal = AgentDecision(candidate_policy=ModelAssistedCandidatePolicy(_Provider(raw))).propose(
        DecisionContext(cognition_state=CognitionState("agent-a"))
    )
    assert proposal.parameters["method"] == candidate.method
    assert proposal.parameters["expected_result"].startswith("The box may")


def test_model_candidate_target_must_match_owner_authorized_observation():
    from cognitive_world.decision.autonomous import parse_untrusted_candidates

    situation = SituationAssessment(
        **{
            **_assessment().__dict__,
            "observed_facts": (
                SituationFact(
                    "percept:door", "event:door", "environment_state",
                    "door_open", "False", "fact:door", "object:door-a",
                ),
            ),
        }
    )
    valid_payload = json.dumps({"candidates": [{
        "intent": "try the observed door",
        "target": "object:door-a",
        "method": "push the door",
    }]})
    parsed = parse_untrusted_candidates(valid_payload, situation)
    assert parsed[0].target == "object:door-a"

    invented_payload = json.dumps({"candidates": [{
        "intent": "try an unseen target",
        "target": "object:unobserved-room",
        "method": "open it",
    }]})
    with pytest.raises(PermissionError, match="target is not present"):
        parse_untrusted_candidates(invented_payload, situation)


def test_openai_decision_provider_receives_only_situation_target_references(monkeypatch):
    situation = SituationAssessment(
        **{
            **_assessment().__dict__,
            "observed_facts": (
                SituationFact(
                    "percept:door", "event:door", "environment_state",
                    "door_open", "False", "fact:door", "object:door-a",
                ),
            ),
        }
    )
    captured = {}

    def fake_post(_url, _path, body, **_kwargs):
        captured["request"] = json.loads(body.decode("utf-8"))
        return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()

    monkeypatch.setattr(
        "cognitive_world.decision.autonomous.post_provider_json", fake_post
    )
    provider = OpenAICompatibleDecisionProvider(
        "http://127.0.0.1:11434", "test-model"
    )
    provider.generate_candidates(
        situation, max_candidates=6, max_output_chars=16_000
    )
    prompt = captured["request"]["messages"][0]["content"]
    encoded_view = prompt.split("Situation:\n", 1)[1]
    assert json.loads(encoded_view)["authorized_target_refs"] == ["object:door-a"]
    assert captured["request"]["model"] == "test-model"


def test_agent_turn_limits_model_target_to_owner_observed_refs():
    world, runtime_context = _real_room_light_runtime()
    observations = runtime_context.observation_store
    agent, cognition_context, _ = _agent_decision_inputs(
        "agent-first", observations, "investigate the room", "protect the room", None
    )
    before_world = dict(world.environment)
    before_events = runtime_context.event_history.get_events()

    class TargetProvider:
        def __init__(self, target):
            self.target = target
            self.seen_targets = ()

        def generate_candidates(self, situation, *, max_candidates, max_output_chars):
            self.seen_targets = situation.authorized_target_refs
            return json.dumps({"candidates": [{
                "intent": "inspect the observed location",
                "target": self.target,
                "method": "inspect the location using only available information",
            }]})

    provider = TargetProvider("room-a")
    proposal = _bound_turn(runtime_context.event_history).execute(
        agent, cognition_context,
        AgentDecision(candidate_policy=ModelAssistedCandidatePolicy(provider)),
    )
    assert provider.seen_targets == ("room-a",)
    assert proposal.agent_id == "agent-first"
    assert proposal.target_refs == ["room-a"]
    assert "decision-light-on" in proposal.reasoning_refs
    assert proposal.metadata["status"] == "attempt_proposed"
    assert world.environment == before_world
    assert runtime_context.event_history.get_events() == before_events

    forged = TargetProvider("room-hidden")
    with pytest.raises(PermissionError, match="target is not present"):
        _bound_turn(runtime_context.event_history).execute(
            agent, cognition_context,
            AgentDecision(candidate_policy=ModelAssistedCandidatePolicy(forged)),
        )
    assert forged.seen_targets == ("room-a",)
    assert world.environment == before_world
    assert runtime_context.event_history.get_events() == before_events


@pytest.mark.parametrize("field", ["npc_reactions", "permissions", "owner_id", "observed_facts"])
def test_model_cannot_inject_reactions_authority_or_facts(field):
    raw = json.dumps({"candidates": [{"intent": "try", "method": "novel method", field: ["forged"]}]})
    with pytest.raises(PermissionError):
        ModelAssistedCandidatePolicy(_Provider(raw)).generate(_assessment())


@pytest.mark.parametrize("field", ["success", "confirmed", "outcome", "world_changes", "result"])
@pytest.mark.parametrize("location", ["root", "candidate"])
def test_model_outcome_fields_are_rejected_not_silently_stripped(field, location):
    candidate = {"intent": "try", "method": "open method"}
    payload = {"candidates": [candidate]}
    if location == "root":
        payload[field] = True
    else:
        candidate[field] = True
    raw = json.dumps(payload)
    with pytest.raises(PermissionError):
        ModelAssistedCandidatePolicy(_Provider(raw)).generate(_assessment())


@pytest.mark.parametrize("provider", [_Provider("not-json"), _Provider(error=OSError("offline")), None])
def test_invalid_or_unavailable_model_uses_explicit_deterministic_fallback(provider):
    candidates, mode = ModelAssistedCandidatePolicy(provider).generate(_assessment())
    assert candidates
    assert mode.startswith("deterministic_")


def test_provider_failure_does_not_try_a_backup_remote_endpoint():
    calls = []

    class FailingProvider:
        def generate_candidates(self, *_args, **_kwargs):
            calls.append("injected-provider")
            raise OSError("offline")

    candidates, mode = ModelAssistedCandidatePolicy(FailingProvider()).generate(_assessment())
    assert candidates
    assert mode == "deterministic_fallback_after_provider_error"
    assert calls == ["injected-provider"]


def test_candidate_count_and_review_budgets_cannot_be_expanded():
    from cognitive_world.decision.autonomous import DeterministicOpenEndedCandidatePolicy

    with pytest.raises(ValueError):
        DeterministicOpenEndedCandidatePolicy(maximum_candidates=7)
    with pytest.raises(ValueError):
        ModelAssistedCandidatePolicy(maximum_model_calls=2)
    with pytest.raises(ValueError):
        BoundedDecisionReviewPolicy(maximum_rounds=2)


def test_explicit_candidate_policy_is_not_classified_as_legacy_default():
    from cognitive_world.decision import DeterministicOpenEndedCandidatePolicy

    decision = AgentDecision(candidate_policy=DeterministicOpenEndedCandidatePolicy())
    assert decision.has_custom_autonomous_policies()


def test_emotion_risk_and_individual_impulse_cap_change_candidate_ordering():
    bold = _assessment(DecisionContext(
        cognition_state=CognitionState("agent-a"),
        goals=(Goal("goal", "agent-a", "act", 0.5),),
        decision_modulation=DecisionModulation(
            "agent-a", risk_bias=0.8, impulse_bias=0.8, impulse_probability_ceiling=0.1
        ),
    ))
    cautious = SituationAssessment(
        **{**bold.__dict__, "risk_bias": -0.8, "impulse_bias": -0.8}
    )
    choices = (
        _candidate("agent-a", candidate_id="careful", risk=0.1, commitment=0.1),
        _candidate("agent-a", candidate_id="committed", risk=0.9, commitment=0.9),
    )
    evaluator = DeterministicActionEvaluationPolicy()
    bold_scores = {item.candidate_id: item.score for item in evaluator.evaluate(bold, choices)}
    cautious_scores = {item.candidate_id: item.score for item in evaluator.evaluate(cautious, choices)}
    assert bold_scores["committed"] > bold_scores["careful"]
    assert cautious_scores["careful"] > cautious_scores["committed"]
    bold_factors = dict(evaluator.evaluate(bold, choices)[1].factors)
    assert abs(bold_factors["bounded_impulse"]) <= 0.04
    assert abs(bold_factors["bounded_impulse"]) == pytest.approx(0.04)


def _real_room_light_runtime():
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    registry = AgentRegistry()
    for owner in ("agent-first", "agent-second"):
        world.load_entity(Entity(owner, "agent", sensory_capabilities=("sight",)))
        world.load_location(owner, "room-a")
        registry.register(RuntimeAgent(owner))
    event = SystemEventFactory().create(
        event_id="decision-light-on",
        event_type="room_light_changed",
        timestamp="text-time-is-not-authoritative",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
        metadata={"debug": "must not enter cognition"},
    )
    scheduler = EventScheduler()
    scheduler.schedule(ScheduledEvent(1, event))
    runtime_context = RuntimeContext(
        clock=SimulationClock(), world_state=world, event_history=EventHistory(),
        scheduler=scheduler, agent_registry=registry, observation_store=ObservationStore(),
        player_session=PlayerSessionBinding(
            "decision-session", "player-view", PlayerMode.OBSERVER,
            observer_agent_id="agent-first",
        ),
    )
    processor = EventProcessor()
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    SimulationRuntime(context=runtime_context, event_processor=processor).step()
    return world, runtime_context


def _agent_decision_inputs(owner, observations, first_goal, second_goal, profile):
    cognition = CognitionContainer()
    cognition.add_personality(Personality(owner, emotion_profile=profile))
    cognition.add_goal(Goal(first_goal, owner, f"advance {first_goal}", 0.5, "active"))
    cognition.add_goal(Goal(second_goal, owner, f"advance {second_goal}", 0.5, "active"))
    cognition.add_emotion(Emotion(f"emotion:{owner}", owner, levels={"calm": 0.2}))
    character = Character(
        f"character:{owner}", owner, owner, goal_ids=[first_goal, second_goal], emotion_id=f"emotion:{owner}"
    )
    context = CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=observations
    )
    return RuntimeAgent(owner, character.id), context, cognition


class _RecordingUnresolvedResolution(ResolutionEngine):
    def __init__(self):
        self.attempts = []

    def resolve(self, attempt):
        self.attempts.append(attempt)
        return super().resolve(attempt)


def test_real_event_observation_to_personalized_decision_and_unresolved_resolution():
    world, runtime_context = _real_room_light_runtime()
    before = dict(world.environment)
    observations = runtime_context.observation_store
    first_agent, first_context, _ = _agent_decision_inputs(
        "agent-first", observations, "protect", "investigate",
        EmotionProfile(
            "agent-first",
            dimensions=(("resolve", EmotionDimensionProfile(1.0, 0.0, 1.0)),),
            reactions=(EmotionReaction("environment_state", "room_light_on", True, "resolve", 1.0),),
            impulse_ceiling=0.6, risk_bias_limit=0.8,
            impulse_affinity=(("resolve", 1.0),), risk_affinity=(("resolve", 1.0),),
            goal_drive_weights=(("protect", 1.0), ("investigate", 1.0)),
        ),
    )
    second_agent, second_context, _ = _agent_decision_inputs(
        "agent-second", observations, "protect", "investigate",
        EmotionProfile(
            "agent-second",
            dimensions=(("apprehension", EmotionDimensionProfile(1.0, 0.0, 1.0)),),
            reactions=(EmotionReaction("environment_state", "room_light_on", True, "apprehension", 1.0),),
            impulse_ceiling=0.6, risk_bias_limit=0.8,
            impulse_affinity=(("apprehension", -1.0),),
            risk_affinity=(("apprehension", -1.0),),
            review_affinity=(("apprehension", 1.0),),
            goal_drive_weights=(("protect", 1.0), ("investigate", 1.0)),
        ),
    )
    first_proposal = _bound_turn(runtime_context.event_history).execute(
        first_agent, first_context, AgentDecision(), simulation_tick=runtime_context.clock.capture()
    )
    second_proposal = _bound_turn(runtime_context.event_history).execute(
        second_agent, second_context, AgentDecision(), simulation_tick=runtime_context.clock.capture()
    )
    assert first_context.get_emotion().levels["resolve"] == pytest.approx(1.0)
    assert second_context.get_emotion().levels["apprehension"] == pytest.approx(1.0)
    assert first_proposal.action_type.startswith("Advance the goal:")
    assert second_proposal.action_type == "Reduce uncertainty relevant to the current situation"
    assert first_proposal.parameters["expected_result"].startswith("Make progress")
    assert first_proposal.reasoning_refs
    assert "decision-light-on" in first_proposal.reasoning_refs
    assert "decision-light-on" in second_proposal.reasoning_refs

    first_motivation, first_modulation = DeterministicDecisionModulationPolicy().assess(
        DecisionContext(
            cognition_state=CognitionState("agent-first"),
            personality=first_context.get_personality(),
            goals=first_context.get_goals(),
            emotion=first_context.get_emotion(),
        )
    )
    second_motivation, second_modulation = DeterministicDecisionModulationPolicy().assess(
        DecisionContext(
            cognition_state=CognitionState("agent-second"),
            personality=second_context.get_personality(),
            goals=second_context.get_goals(),
            emotion=second_context.get_emotion(),
        )
    )
    assert first_motivation.goal_scores == second_motivation.goal_scores
    assert first_modulation.risk_bias > second_modulation.risk_bias
    assert first_modulation.impulse_bias > second_modulation.impulse_bias

    first_attempt = ActionPipeline().create_attempt(first_proposal)
    resolution = _RecordingUnresolvedResolution()
    flow = ActionResolutionFlow(resolution_engine=resolution)
    with pytest.raises(ValueError, match="valid confirmation"):
        flow.execute(first_attempt, action_proposal_id=first_proposal.proposal_id)
    assert len(resolution.attempts) == 1
    assert resolution.attempts[0].parameters["method"] == first_proposal.parameters["method"]
    assert world.environment == before  # no Event or WorldState change without Resolution
    assert tuple(item.id for item in runtime_context.event_history.get_events()) == ("decision-light-on",)

    gateway = InMemoryChatOutputGateway(runtime_context)
    visible = PresentationPipeline.for_runtime(runtime_context, gateway).publish_event("decision-light-on")
    assert len(visible.messages) == 1
    assert "score" not in visible.messages[0].content.casefold()
    assert "emotion" not in visible.messages[0].content.casefold()


def _bound_turn(history):
    turn = AgentTurn()
    turn.cognitive_runtime._bind_observation_history(history)
    return turn
