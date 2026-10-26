from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent import AgentActionLoop, AgentRegistry
from cognitive_world.cognition import (
    CognitionContainer,
    MemoryStore,
    Personality,
    SelfModel,
    SelfModelEvolutionSuggestion,
    SelfModelReview,
    SelfModelReviewInput,
    CognitiveEvidence,
    SelfModelUpdateProposal,
    OllamaSelfModelReviewProvider,
)
from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
from cognitive_world.cognition.validation import CognitiveUpdateValidator
from cognitive_world.observation import ObservationStore
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory
from cognitive_world.runtime import AgentScheduler, RuntimeContext, SimulationClock, SimulationRuntime
from tests._l1_history_support import light_history, qualified_turn


class SuggestionProvider:
    def __init__(self, claim="I can keep my balance on uneven ground.", observation_ids=None):
        self.claim = claim
        self.observation_ids = observation_ids
        self.requests = []

    def review(self, request):
        self.requests.append(request)
        ids = self.observation_ids or (request.evidence[0].observation_id,)
        return SelfModelReview(
            "The new experience may inform a tentative self-understanding.",
            "One experience does not establish a stable capability.",
            SelfModelEvolutionSuggestion(self.claim, tuple(ids), "Tentative, evidence-linked inference."),
        )


class CapturingDecision:
    def __init__(self):
        self.contexts = []

    def propose(self, context):
        self.contexts.append(context)
        from cognitive_world.decision import ActionProposal
        return ActionProposal(f"proposal-{len(self.contexts)}", context.cognition_state.agent_id, "wait")


def make_context(owner="agent-a", observation_id="observation-a", event_id="event-a"):
    history_context, observation = light_history(owner, event_id)
    observations = history_context.observation_store
    container = CognitionContainer()
    container.add_personality(Personality(owner, traits={"steadiness": 0.4}))
    model = SelfModel(owner, identity={"role": "traveler"}, self_beliefs=[{"claim": "I am inexperienced.", "status": "tentative"}])
    container.add_self_model(model)
    character = Character(f"character-{owner}", owner, "",)
    context = CognitionContext.from_character(character, container, MemoryStore(), observation_store=observations)
    return context, observation, model, history_context


def test_agent_turn_l1_experience_is_governed_and_read_on_following_turn():
    context, observation, original, history_context = make_context()
    provider = SuggestionProvider()
    turn = qualified_turn(history_context, self_model_review_provider=provider)
    decision = CapturingDecision()
    before = context.get_self_model()
    personality_before = context.cognition_container.get_personality("agent-a")

    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)

    updated = context.get_self_model()
    assert len(provider.requests) == 1
    assert provider.requests[0].owner_id == "agent-a"
    assert [item.observation_id for item in provider.requests[0].evidence] == [observation.observation_id]
    assert provider.requests[0].evidence[0].content == {
        "fact_type": observation.content.fact_type,
        "predicate": observation.content.predicate,
        "value": observation.content.value,
        "subject_ref": observation.content.subject_ref,
        "location_id": observation.content.location_id,
    }
    assert observation.has_trusted_provenance()
    assert context.get_observations()[0] == observation
    assert updated.owner_id == original.owner_id
    assert updated.identity == before.identity
    assert updated.capabilities == before.capabilities
    assert updated.self_beliefs[:-1] == before.self_beliefs
    assert updated.self_beliefs[-1] == {
        "claim": "I can keep my balance on uneven ground.",
        "status": "tentative",
        "source_refs": [observation.observation_id],
        "source_event_ids": [observation.source_event_id],
    }
    assert context.cognition_container.get_personality("agent-a") == personality_before
    assert decision.contexts[0].self_model.self_beliefs[-1]["claim"] == updated.self_beliefs[-1]["claim"]

    # The same Observation is not a new L1 experience and cannot be applied twice.
    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)
    assert len(provider.requests) == 1
    assert context.get_self_model() == updated
    assert decision.contexts[-1].self_model.self_beliefs[-1]["claim"] == updated.self_beliefs[-1]["claim"]


def test_owner_and_l1_source_boundaries_reject_cross_agent_and_forged_refs():
    context, observation, _, history_context = make_context()
    provider = SuggestionProvider(observation_ids=("observation-other",))
    turn = qualified_turn(history_context, self_model_review_provider=provider)
    decision = CapturingDecision()

    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)

    assert context.get_self_model().self_beliefs == [{"claim": "I am inexperienced.", "status": "tentative"}]
    assert decision.contexts[-1].self_model.self_beliefs[0]["claim"] == "I am inexperienced."
    assert provider.requests[0].owner_id == "agent-a"
    assert all(item.observation_id != "observation-other" for item in provider.requests[0].evidence)


def test_semantic_candidate_without_new_l1_consumption_is_not_sent_or_applied():
    context, _, original, history_context = make_context()
    turn = qualified_turn(history_context, self_model_review_provider=SuggestionProvider())
    decision = CapturingDecision()
    agent = RuntimeAgent("agent-a", "character-agent-a")

    turn.execute(agent, context, decision)
    changed = context.get_self_model()
    turn.execute(agent, context, decision)

    assert changed != original
    assert context.get_self_model() == changed


def test_self_model_store_cannot_be_written_with_a_forged_or_mismatched_proposal():
    context, observation, original, history_context = make_context()
    forged = SelfModelUpdateProposal(
        owner_id="agent-a",
        previous_self_beliefs=tuple(original.self_beliefs),
        claim="A forged update",
        source_refs=(observation.observation_id,),
        source_event_ids=("unrelated-event",),
    )
    validator = CognitiveUpdateValidator()
    result = validator.validate(forged, {
        "agent_id": "agent-a",
        "authorized_source_refs": (observation.observation_id,),
        "authorized_event_ids": (observation.source_event_id,),
        "authorized_source_event_pairs": {observation.observation_id: observation.source_event_id},
    })
    assert not result.accepted
    applier = CognitiveUpdateApplier(
        context.cognition_container.belief_store,
        context.cognition_container.goal_store,
        context.cognition_container.self_model_store,
    )
    try:
        applier.apply(forged, result)
    except PermissionError:
        pass
    else:
        raise AssertionError("invalid SelfModel proposal was applied")
    assert context.get_self_model() == original

    cross_owner = SelfModelUpdateProposal(
        owner_id="agent-b",
        previous_self_beliefs=tuple(original.self_beliefs),
        claim="Cross-owner update",
        source_refs=(observation.observation_id,),
        source_event_ids=(observation.source_event_id,),
    )
    cross_result = validator.validate(cross_owner, {
        "agent_id": "agent-a",
        "authorized_source_refs": (observation.observation_id,),
        "authorized_event_ids": (observation.source_event_id,),
        "authorized_source_event_pairs": {observation.observation_id: observation.source_event_id},
    })
    assert not cross_result.accepted
    assert context.get_self_model() == original


def test_provider_failure_preserves_self_model_and_world_independent_state():
    context, _, original, history_context = make_context()

    class FailingProvider:
        def review(self, request):
            raise TimeoutError("offline")

    decision = CapturingDecision()
    qualified_turn(history_context, self_model_review_provider=FailingProvider()).execute(
        RuntimeAgent("agent-a", "character-agent-a"), context, decision
    )

    assert context.get_self_model() == original
    assert decision.contexts[-1].self_model.self_beliefs[0]["claim"] == original.self_beliefs[0]["claim"]


def test_no_candidate_or_invalid_provider_result_keeps_previous_self_model():
    context, _, original, history_context = make_context()

    class NoCandidate:
        def review(self, request):
            return SelfModelReview("No supported revision.", "Evidence is insufficient.")

    class InvalidResult:
        def review(self, request):
            return {"claim": "not a typed review"}

    agent = RuntimeAgent("agent-a", "character-agent-a")
    decision = CapturingDecision()
    qualified_turn(history_context, self_model_review_provider=NoCandidate()).execute(agent, context, decision)
    assert context.get_self_model() == original

    # A fresh runtime is a distinct L1 consumer; malformed output still cannot
    # reach the canonical owner Store.
    qualified_turn(history_context, self_model_review_provider=InvalidResult()).execute(agent, context, decision)
    assert context.get_self_model() == original


def test_personality_fields_are_outside_the_self_model_evolution_contract():
    context, _, original, history_context = make_context()
    personality = context.cognition_container.get_personality("agent-a")
    assert personality.traits == {"steadiness": 0.4}
    assert set(original.__dict__) == {
        "owner_id", "identity", "capabilities", "limitations", "self_beliefs", "metadata"
    }


def test_simulation_runtime_explicitly_binds_self_model_review_to_agent_turn():
    cognition_context, observation, _, history_context = make_context()
    provider = SuggestionProvider()
    clock = SimulationClock()
    registry = AgentRegistry()
    agent = RuntimeAgent("agent-a", "character-agent-a")
    registry.register(agent)
    agent_scheduler = AgentScheduler()
    agent_scheduler.schedule_agent("agent-a", 1)
    world = history_context.world_state
    history = history_context.event_history
    before_history = history.get_events()
    runtime_context = RuntimeContext(
        clock,
        world,
        history,
        agent_scheduler=agent_scheduler,
        agent_registry=registry,
        observation_store=cognition_context.observation_store,
    )
    decision = CapturingDecision()
    runtime = SimulationRuntime(
        context=runtime_context,
        agent_action_loop=AgentActionLoop(),
        cognition_context_provider=lambda _agent: cognition_context,
        agent_decision=decision,
        self_model_review_provider=provider,
    )

    runtime.step()

    assert len(provider.requests) == 1
    assert provider.requests[0].evidence[0].observation_id == observation.observation_id
    assert cognition_context.get_self_model().self_beliefs[-1]["source_event_ids"] == [observation.source_event_id]
    assert decision.contexts[0].self_model.self_beliefs[-1]["claim"] == provider.claim
    assert runtime.last_agent_turn_results[0].agent_id == "agent-a"
    assert history.get_events() == before_history


def test_ollama_adapter_reuses_loopback_transport_with_bounded_structured_contract(monkeypatch):
    import json
    from cognitive_world.dialogue import ollama as dialogue_ollama

    captured = []
    response = {
        "assessment": "The experience is relevant but limited.",
        "uncertainty": "It does not establish a stable trait.",
        "suggestion": {
            "claim": "I may be able to keep my balance on uneven ground.",
            "observation_ids": ["observation-local"],
            "rationale": "This remains a tentative interpretation.",
        },
    }

    def fake_transport(url, body, *, timeout_seconds, maximum_bytes):
        captured.append((url, json.loads(body), timeout_seconds, maximum_bytes))
        return json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()

    monkeypatch.setattr(dialogue_ollama, "_post_loopback_json", fake_transport)
    provider = OllamaSelfModelReviewProvider("http://127.0.0.1:11434/v1", "local-test-model")
    request = SelfModelReviewInput(
        "agent-a",
        (CognitiveEvidence("observation-local", "event-local", {"experience": "synthetic"}),),
        ({"claim": "I am learning."},),
    )

    result = provider.review(request)

    assert result.suggestion.claim.startswith("I may be able")
    assert captured[0][0] == "http://127.0.0.1:11434/v1"
    assert captured[0][1]["max_tokens"] == provider.maximum_tokens
    assert "world_state" not in captured[0][1]["messages"][1]["content"]
    assert captured[0][2] == provider.timeout_seconds


def test_direct_compatibility_without_history_defers_before_review_and_keeps_cognition():
    from copy import deepcopy
    from cognitive_world.cognition import Emotion
    context, observation, original, _ = make_context()
    container = context.cognition_container
    container.add_emotion(Emotion("emotion-a", "agent-a", levels={"calm": 0.2}))
    before = deepcopy((container.get_self_model("agent-a"), container.get_emotion("emotion-a")))
    provider = SuggestionProvider()
    turn = AgentTurn(self_model_review_provider=provider)
    decision = CapturingDecision()
    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)
    item, = decision.contexts[-1].cognition_state.metadata["l1_ingestion"]["items"]
    assert item["source"] == "eligible" and item["history"] == "undetermined"
    assert item["consumption"] == "not_consumed"
    assert decision.contexts[-1].cognition_state.percept_ids == ()
    assert turn.cognitive_runtime.working_memory_store.get("agent-a") is None
    assert not turn.cognitive_runtime._l1_consumption_receipts
    assert not provider.requests
    assert (container.get_self_model("agent-a"), container.get_emotion("emotion-a")) == before
    assert context.get_self_model() == original
