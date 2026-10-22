import json
import os

import pytest

from cognitive_world.agent import Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.cognition import (
    Belief,
    BeliefRevisionSuggestion,
)
from cognitive_world.cognition.causal_review import (
    CognitiveEvidence,
    BeliefSnapshot,
    CognitiveReview,
    CognitiveReviewInput,
    OpenAICompatibleCognitiveReviewProvider,
    OllamaCognitiveReviewProvider,
    parse_cognitive_review,
)
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.event import EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory
from cognitive_world.observation import Observation, ObservationStore
from cognitive_world.runtime.clock import SimulationClock


class RecordingReviewProvider:
    def __init__(self, review):
        self.review_result = review
        self.requests = []

    def review(self, request):
        self.requests.append(request)
        return self.review_result


class CapturingDecision:
    def __init__(self):
        self.beliefs_seen = []
        self.feedback_seen = []

    def propose(self, context):
        self.beliefs_seen.append(tuple(context.beliefs))
        self.feedback_seen.append(context.metacognitive_feedback)
        owner = context.cognition_state.agent_id
        return ActionProposal("proposal-1", owner, "wait")


class CapturingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete_structured(self, instruction, payload, *, max_output_chars):
        self.calls.append((instruction, payload, max_output_chars))
        return self.response


def production_observation():
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    world.load_entity(Entity("agent-a", "agent", sensory_capabilities=("sight",)))
    world.load_location("agent-a", "room-a")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a", "character-a"))
    store = ObservationStore()
    clock = SimulationClock()
    history = EventHistory()
    processor = EventProcessor(
        world_state=world,
        event_history=history,
        simulation_clock=clock,
        agent_registry=registry,
        observation_store=store,
    )
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    event = SystemEventFactory().create(
        event_id="light-event-a",
        event_type="room_light_changed",
        timestamp="descriptive-time",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
        metadata={"private": "must not enter cognition"},
    )
    clock.tick()
    processor.dispatch_with_evidence(event)
    observation = store.get_by_observer("agent-a")[0]
    assert observation.has_trusted_provenance()
    return world, history, event, observation, store


def cognition_context(observations, *, owner="agent-a", beliefs=()):
    cognition = CognitionContainer()
    for belief in beliefs:
        cognition.add_belief(belief)
    character = Character(
        id=f"character-{owner}",
        agent_id=owner,
        personality_id="",
        belief_ids=[belief.belief_id for belief in beliefs],
    )
    return CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=observations
    )


def test_real_trusted_observation_revises_owner_belief_and_next_turn_reads_it():
    world, history, event, observation, observations = production_observation()
    old = Belief("belief-a", "agent-a", {"claim": "light is off"}, ["old-event"], 0.7)
    context = cognition_context(observations, beliefs=(old,))
    provider = RecordingReviewProvider(CognitiveReview(
        assessment="The new observation conflicts with the earlier belief.",
        uncertainty="The observation is direct, but it only describes this room at this time.",
        revision=BeliefRevisionSuggestion(
            belief_id="belief-a",
            proposed_content={"claim": "room light is on"},
            confidence=0.85,
            reason="Revise the room-light belief using the new observation.",
            observation_ids=(observation.observation_id,),
        ),
    ))
    turn = AgentTurn(cognitive_review_provider=provider)
    decision = CapturingDecision()
    before_world = {key: dict(value) for key, value in world.environment.items()}
    before_history = history.get_events()

    first_proposal = turn.execute(
        RuntimeAgent("agent-a", "character-agent-a"),
        context,
        decision,
    )
    updated = context.get_beliefs()[0]

    assert first_proposal.agent_id == "agent-a"
    assert updated.content == {"claim": "room light is on"}
    assert updated.confidence == 0.85
    assert updated.source_refs == [observation.observation_id]
    assert updated.metadata["source_event_ids"] == (event.id,)
    assert decision.beliefs_seen[-1][0].content == updated.content
    assert provider.requests[0].owner_id == "agent-a"
    assert provider.requests[0].evidence[0].observation_id == observation.observation_id
    assert provider.requests[0].evidence[0].source_event_id == event.id
    assert "private" not in repr(provider.requests[0])

    # Replaying the stored Observation does not run the semantic provider again.
    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)
    assert len(provider.requests) == 1
    assert decision.beliefs_seen[-1][0].content == updated.content
    assert world.environment == before_world
    assert history.get_events() == before_history
    assert len(history.get_events()) == 1


def test_review_does_not_run_without_new_l1_percept_or_trusted_observation():
    world, _, _, _, _ = production_observation()
    store = ObservationStore()
    store.add(Observation("manual", "agent-a", "forged-event", {"claim": "seen"}))
    context = cognition_context(store)
    provider = RecordingReviewProvider(CognitiveReview("", "not enough evidence"))
    turn = AgentTurn(cognitive_review_provider=provider)

    proposal = turn.execute(
        RuntimeAgent("agent-a", "character-agent-a"), context, CapturingDecision()
    )

    assert proposal.agent_id == "agent-a"
    assert provider.requests == []
    assert world.environment["room-a"]["light_on"] is True


def test_revision_cannot_cite_another_observation_or_other_agents_belief():
    _, _, _, observation, observations = production_observation()
    own = Belief("belief-a", "agent-a", "old", ["old"], 0.5)
    other = Belief("belief-b", "agent-b", "private", ["private-event"], 0.8)
    cognition = CognitionContainer()
    cognition.add_belief(own)
    cognition.add_belief(other)
    character = Character("character-a", "agent-a", "", belief_ids=["belief-a", "belief-b"])
    context = CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=observations
    )
    provider = RecordingReviewProvider(CognitiveReview(
        "possible mismatch", "uncertain",
        BeliefRevisionSuggestion(
            "belief-a", "new", 0.8, "review", ("observation:forged",)
        ),
    ))
    turn = AgentTurn(cognitive_review_provider=provider)

    decision = CapturingDecision()
    turn.execute(RuntimeAgent("agent-a", "character-a"), context, decision)

    assert {item.belief_id for item in provider.requests[0].beliefs} == {"belief-a"}
    assert cognition.get_belief("belief-a").content == "old"
    assert cognition.get_belief("belief-b").content == "private"
    assert "possible mismatch" not in repr(decision.feedback_seen[-1])
    assert observation.observer_id == "agent-a"


def test_assessment_without_revision_preserves_existing_uncertainty():
    _, _, _, _, observations = production_observation()
    old = Belief("belief-a", "agent-a", {"claim": "unsure"}, ["old"], 0.35)
    context = cognition_context(observations, beliefs=(old,))
    provider = RecordingReviewProvider(CognitiveReview(
        "Two interpretations remain plausible.", "Evidence does not distinguish them."
    ))
    decision = CapturingDecision()

    AgentTurn(cognitive_review_provider=provider).execute(
        RuntimeAgent("agent-a", "character-agent-a"), context, decision
    )

    assert context.get_beliefs()[0] == old
    assert decision.beliefs_seen[-1][0].content == old.content
    assert provider.requests[0].evidence


def test_openai_compatible_review_adapter_uses_shared_transport_and_strict_schema():
    transport = CapturingTransport(
        '{"assessment":"uncertain","uncertainty":"two readings", "revision":null}'
    )
    request = CognitiveReviewInput(
        "agent-private-id",
        (CognitiveEvidence("obs-1", "event-1", {"fact": "seen"}),),
        (),
    )

    result = OpenAICompatibleCognitiveReviewProvider(transport).review(request)

    assert result.assessment == "uncertain"
    assert len(transport.calls) == 1
    assert "owner_id" not in transport.calls[0][1]
    with pytest.raises(PermissionError, match="unsupported fields"):
        parse_cognitive_review(
            '{"assessment":"x","uncertainty":"","revision":null,"owner_id":"agent-a"}'
        )


def test_ollama_review_reuses_dialogue_loopback_transport_and_is_strict(monkeypatch):
    from cognitive_world.dialogue import ollama as dialogue_ollama

    response = {
        "choices": [{"message": {"content": json.dumps({
            "assessment": "New evidence supports revisiting the belief.",
            "uncertainty": "It is limited to the observed room and time.",
            "revision": {
                "belief_id": "belief-a", "proposed_content": {"claim": "light on"},
                "confidence": 0.8, "reason": "The new observation is direct.",
                "observation_ids": ["observation-1"],
            },
        })}}],
    }
    captured = []

    def fake_local_transport(base_url, body, *, timeout_seconds, maximum_bytes):
        captured.append((base_url, json.loads(body), timeout_seconds, maximum_bytes))
        return json.dumps(response).encode("utf-8")

    monkeypatch.setattr(dialogue_ollama, "_post_loopback_json", fake_local_transport)
    provider = OllamaCognitiveReviewProvider(
        "http://127.0.0.1:11434/v1", "test-model", maximum_tokens=128
    )
    request = CognitiveReviewInput(
        "agent-a",
        (CognitiveEvidence("observation-1", "event-1", {"predicate": "light_on", "value": True}),),
        (BeliefSnapshot("belief-a", {"claim": "light off"}, 0.6, ("old-event",)),),
    )

    review = provider.review(request)

    assert review.revision is not None
    assert review.revision.belief_id == "belief-a"
    assert review.revision.observation_ids == ("observation-1",)
    url, body, timeout, maximum_bytes = captured[0]
    assert url == "http://127.0.0.1:11434/v1"
    assert body["model"] == "test-model"
    assert body["max_tokens"] == 128
    assert body["messages"][1]["content"].find("agent-a") == -1
    assert "world_state" not in body["messages"][1]["content"]
    assert timeout == 30.0
    assert maximum_bytes == 4 * 4000


def test_cognitive_ollama_requires_separate_explicit_opt_in_and_shared_settings(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_COGNITIVE_REVIEW_PROVIDER", raising=False)
    monkeypatch.setenv("COGNITIVEWORLD_DIALOGUE_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "shared-local-model")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    assert OllamaCognitiveReviewProvider.from_environment() is None

    monkeypatch.setenv("COGNITIVEWORLD_COGNITIVE_REVIEW_PROVIDER", "ollama")
    provider = OllamaCognitiveReviewProvider.from_environment()
    assert provider is not None
    assert provider.model == "shared-local-model"
    assert provider.base_url == "http://127.0.0.1:11434/v1"
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "https://remote.example/v1")
    with pytest.raises(ValueError, match="loopback"):
        OllamaCognitiveReviewProvider.from_environment()


def test_ollama_review_invalid_output_keeps_prior_belief(monkeypatch):
    from cognitive_world.dialogue import ollama as dialogue_ollama

    world, history, _, _, observations = production_observation()
    old = Belief("belief-a", "agent-a", {"claim": "uncertain"}, ["prior-event"], 0.45)
    context = cognition_context(observations, beliefs=(old,))
    monkeypatch.setattr(
        dialogue_ollama,
        "_post_loopback_json",
        lambda *_args, **_kwargs: json.dumps({"choices": [{"message": {
            "content": '{"assessment":"x","uncertainty":"","revision":null,"owner_id":"agent-b"}'
        }}]}).encode(),
    )
    turn = AgentTurn(cognitive_review_provider=OllamaCognitiveReviewProvider(
        "http://127.0.0.1:11434/v1", "test-model"
    ))

    proposal = turn.execute(
        RuntimeAgent("agent-a", "character-agent-a"), context, CapturingDecision()
    )

    assert proposal.agent_id == "agent-a"
    assert context.get_beliefs()[0] == old
    assert len(history.get_events()) == 1
    assert world.environment["room-a"]["light_on"] is True


def test_ollama_review_timeout_keeps_prior_belief_and_world(monkeypatch):
    from cognitive_world.dialogue import ollama as dialogue_ollama

    world, history, _, _, observations = production_observation()
    old = Belief("belief-a", "agent-a", {"claim": "uncertain"}, ["prior-event"], 0.45)
    context = cognition_context(observations, beliefs=(old,))
    calls = []

    def timeout_transport(*_args, **_kwargs):
        calls.append(1)
        raise TimeoutError("local model generation exceeded its budget")

    monkeypatch.setattr(dialogue_ollama, "_post_loopback_json", timeout_transport)
    turn = AgentTurn(cognitive_review_provider=OllamaCognitiveReviewProvider(
        "http://127.0.0.1:11434/v1", "test-model"
    ))
    decision = CapturingDecision()
    before_events = history.get_events()

    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)
    turn.execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)

    assert calls == [1]
    assert context.get_beliefs()[0] == old
    assert decision.beliefs_seen[-1][0].content == old.content
    assert history.get_events() == before_events
    assert world.environment["room-a"]["light_on"] is True


def test_simulation_runtime_binds_opted_in_ollama_review_to_owner_turn(monkeypatch):
    from cognitive_world.agent.action_loop import AgentActionLoop
    from cognitive_world.agent.registry import AgentRegistry
    from cognitive_world.runtime import AgentScheduler, RuntimeContext, SimulationClock, SimulationRuntime
    from cognitive_world.event import EventProcessor
    from cognitive_world.dialogue import ollama as dialogue_ollama

    world, history, source_event, observation, observations = production_observation()
    old = Belief("belief-a", "agent-a", {"claim": "room light is off"}, ["old-event"], 0.6)
    cognition = CognitionContainer()
    cognition.add_belief(old)
    character = Character("character-agent-a", "agent-a", "", belief_ids=["belief-a"])
    context = CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=observations
    )
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a", "character-agent-a"))
    agent_scheduler = AgentScheduler()
    agent_scheduler.schedule_agent("agent-a", 1)
    clock = SimulationClock()
    runtime_context = RuntimeContext(
        clock, world, history, agent_scheduler=agent_scheduler,
        agent_registry=registry, observation_store=observations,
    )
    model_revision = {
        "assessment": "The trusted observation supports a limited revision.",
        "uncertainty": "Only the room at the observed time is established.",
        "revision": {
            "belief_id": "belief-a", "proposed_content": {"claim": "room light is on"},
            "confidence": 0.82, "reason": "Direct authorized observation.",
            "observation_ids": [observation.observation_id],
        },
    }
    calls = []

    def fake_local_transport(base_url, body, *, timeout_seconds, maximum_bytes):
        parsed = json.loads(body)
        calls.append(parsed)
        return json.dumps({"choices": [{"message": {"content": json.dumps(model_revision)}}]}).encode()

    monkeypatch.setattr(dialogue_ollama, "_post_loopback_json", fake_local_transport)
    monkeypatch.setenv("COGNITIVEWORLD_COGNITIVE_REVIEW_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "synthetic-local-model")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    processor = EventProcessor(
        world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
    )
    initial_events = history.get_events()
    runtime = SimulationRuntime(
        context=runtime_context,
        event_processor=processor,
        agent_action_loop=AgentActionLoop(),
        cognition_context_provider=lambda _agent: context,
        agent_decision=AgentDecision(),
    )

    runtime.step()

    assert len(calls) == 1
    assert len(calls[0]["messages"]) == 2
    assert "owner_id" not in calls[0]["messages"][1]["content"]
    assert "world_state" not in calls[0]["messages"][1]["content"]
    updated = cognition.get_belief("belief-a")
    assert updated.content == {"claim": "room light is on"}
    assert updated.owner_id == "agent-a"
    assert updated.source_refs == [observation.observation_id]
    assert updated.metadata["source_event_ids"] == (source_event.id,)
    assert history.get_events() == initial_events
    assert world.environment["room-a"]["light_on"] is True


@pytest.mark.skipif(
    os.environ.get("COGNITIVEWORLD_RUN_OLLAMA_COGNITIVE_INTEGRATION") != "1",
    reason="explicit opt-in required for the real local Ollama cognitive review",
)
def test_live_ollama_cognitive_review_runs_on_trusted_agent_turn():
    provider = OllamaCognitiveReviewProvider.from_environment()
    assert provider is not None
    world, history, source_event, observation, observations = production_observation()
    old = Belief("belief-live", "agent-a", {"claim": "room light is off"}, ["older-event"], 0.4)
    context = cognition_context(observations, beliefs=(old,))

    class RecordingLocalProvider:
        def __init__(self, inner):
            self.inner = inner
            self.requests = []
            self.result = None
            self.error = None

        def review(self, request):
            self.requests.append(request)
            try:
                self.result = self.inner.review(request)
            except Exception as error:
                self.error = f"{type(error).__name__}: {error}"
                raise
            return self.result

    recording = RecordingLocalProvider(provider)
    before_events = history.get_events()
    AgentTurn(cognitive_review_provider=recording).execute(
        RuntimeAgent("agent-a", "character-agent-a"), context, CapturingDecision()
    )

    assert len(recording.requests) == 1
    request = recording.requests[0]
    assert request.owner_id == "agent-a"
    assert [(item.observation_id, item.source_event_id) for item in request.evidence] == [
        (observation.observation_id, source_event.id)
    ]
    assert {item.belief_id for item in request.beliefs} == {"belief-live"}
    assert isinstance(recording.result, CognitiveReview), recording.error
    if recording.result.revision is None:
        assert context.get_beliefs()[0] == old
    else:
        updated = context.get_beliefs()[0]
        assert updated.source_refs == [observation.observation_id]
        assert updated.metadata["source_event_ids"] == (source_event.id,)
    assert history.get_events() == before_events
    assert world.environment["room-a"]["light_on"] is True
