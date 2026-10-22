import json
import os

import pytest

from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.causal_review import (
    CognitiveBeliefReview, CognitiveReview, CognitiveReviewInput, BeliefRevisionSuggestion,
)
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.autonomous import ActionCandidate
from cognitive_world.dialogue import (
    DialogueInterpretation,
    DialogueRequest,
    DialogueResponseCandidate,
    PlayerDialogueService,
    OllamaDialogueResponseCandidateProvider,
)
from cognitive_world.presentation import InMemoryChatOutputGateway, PresentationPipeline
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event import RoomLightChangedHandler, SystemEventFactory
from cognitive_world.observation.store import ObservationStore
from cognitive_world.observation.generator import ObservationGenerator
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding, RuntimeContext
from cognitive_world.dialogue import ollama as dialogue_ollama


class RequestInterpretation:
    def interpret(self, request):
        return DialogueInterpretation(
            meaning="The speaker may be asking for help.",
            possible_action_request="Consider helping the speaker.",
            uncertainty="The intent may be figurative.",
        )


class CapturingAgentDecision(AgentDecision):
    def propose(self, context):
        self.received_context = context
        return super().propose(context)


def make_dialogue(*, provider=None, decision=None, response_provider=None, expression_provider=None,
                  listener_id="listener", goal_priority=0.8, review_provider=None, beliefs=()):
    world = WorldState()
    for agent_id in ("speaker", listener_id):
        world.load_entity(Entity(agent_id, "character", sensory_capabilities=("sight",)))
        world.load_location(agent_id, "shared-room")
    registry = AgentRegistry()
    speaker = RuntimeAgent("speaker", "character:speaker")
    listener = RuntimeAgent(listener_id, f"character:{listener_id}")
    registry.register(speaker)
    registry.register(listener)
    observations = ObservationStore()
    history = EventHistory()
    clock = SimulationClock(4)
    context = RuntimeContext(
        clock, world, history, agent_registry=registry, observation_store=observations,
        player_session=PlayerSessionBinding(
            "session", "player", PlayerMode.ROLEPLAY, "speaker"
        ),
    )
    processor = EventProcessor(
        world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
    )
    container = CognitionContainer()
    for belief in beliefs:
        container.add_belief(belief)
    goal = Goal(f"{listener_id}-goal", listener_id, "understand and help nearby people", goal_priority, "active")
    container.add_goal(goal)
    character = Character(
        f"character:{listener_id}", listener_id, f"personality:{listener_id}",
        goal_ids=[goal.goal_id],
        belief_ids=[belief.belief_id for belief in beliefs],
    )
    cognition = CognitionContext.from_character(
        character, container, MemoryStore(), observation_store=observations
    )
    loop = AgentActionLoop()
    presentation = None
    if response_provider is not None or os.environ.get("COGNITIVEWORLD_DIALOGUE_PROVIDER") == "ollama":
        presentation = PresentationPipeline.for_runtime(
            context, InMemoryChatOutputGateway(context)
        )
    service = PlayerDialogueService(
        context, processor, loop, lambda agent: cognition, decision or AgentDecision(),
        interpretation_provider=provider,
        response_candidate_provider=response_provider,
        persuasion_review_provider=review_provider,
        expression_provider=expression_provider,
        presentation=presentation,
    )
    return service, context, processor, observations, history, loop


def test_speech_is_a_recipient_only_observation_and_not_a_world_claim():
    service, context, processor, observations, history, loop = make_dialogue()
    before_facts = context.world_state.facts
    request = DialogueRequest("message-1", "listener", "The old bridge is unsafe.")
    result = service.submit(request)

    assert result.status == "delivered_no_action"
    assert result.agent_execution is None
    assert context.world_state.facts == before_facts
    assert len(history.get_events()) == 1
    event = history.get_events()[0]
    assert event.type == "dialogue_input" and event.has_trusted_source("system")
    delivered = observations.get_by_observer("listener")
    assert len(delivered) == 1 and delivered[0].has_trusted_provenance()
    fact = delivered[0].content
    assert fact.predicate == "utterance_delivered"
    assert fact.value == "The old bridge is unsafe."
    assert observations.get_by_observer("speaker") == ()
    evidence = history.get_processing_evidence(event.id)
    assert ObservationGenerator().generate_authorized(
        event, evidence, observer_id="speaker"
    ) == ()
    assert ObservationGenerator().generate_authorized(
        event, evidence, observer_id="unregistered-agent"
    ) == ()
    assert loop.agent_turn.cognitive_runtime.has_consumed_observation(
        "listener", delivered[0], source_event_id=event.id
    )
    # Replaying the same request returns its outcome and does not redeliver.
    assert service.submit(request) == result
    assert len(history.get_events()) == 1
    assert len(observations.get_by_observer("listener")) == 1


class RecordingPersuasionReview:
    def __init__(self, review=None, *, fail=False):
        self.review_result = review
        self.fail = fail
        self.requests = []

    def review(self, request):
        self.requests.append(request)
        if self.fail:
            raise TimeoutError("local reviewer unavailable")
        return self.review_result or CognitiveReview("unresolved", "insufficient evidence")


def add_independent_light_observation(service, context, processor):
    context.world_state.load_environment_data("shared-room", {"light_on": False})
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    event = SystemEventFactory().create(
        event_id="independent-light-event", event_type="room_light_changed",
        timestamp="4", simulation_tick=context.clock.current_time,
        changes=[{"room_id": "shared-room", "from_light_on": False, "to_light_on": True}],
    )
    processor.dispatch_with_evidence(event)
    return context.observation_store.get_by_observer("listener")[0]


def test_persuasion_uses_receiver_l1_and_governed_existing_belief_revision():
    belief = Belief("light-belief", "listener", {"claim": "the light is off"}, ["initial"], 0.7)
    reviewer = RecordingPersuasionReview()
    service, context, processor, observations, history, loop = make_dialogue(
        beliefs=(belief,), review_provider=reviewer,
    )
    independent = add_independent_light_observation(service, context, processor)
    reviewer.review_result = CognitiveReview(
        "recipient considers the observed light", "the observation is local",
        BeliefRevisionSuggestion("light-belief", {"claim": "the light is on"}, 0.8,
                                 "independent observation supports reconsideration",
                                 ("pending", independent.observation_id)),
    )
    # The provider must cite the actual speech Observation issued by the
    # processor; a guessed identifier cannot authorize an update.
    original_review = reviewer.review
    def bound_review(request):
        reviewer.review_result = CognitiveReview(
            "recipient considers the observed light", "the observation is local",
            BeliefRevisionSuggestion("light-belief", {"claim": "the light is on"}, 0.8,
                                     "independent observation supports reconsideration",
                                     (request.speech_observation_id, independent.observation_id)),
        )
        return original_review(request)
    reviewer.review = bound_review
    before_world = dict(context.world_state.environment["shared-room"])
    result = service.submit(DialogueRequest("persuasion-1", "listener", "The light is on."))
    cognition = service.cognition_context_provider(context.agent_registry.get("listener"))
    updated = cognition.get_beliefs()[0]
    assert result.status == "delivered_no_action"
    assert updated.content == {"claim": "the light is on"}
    assert updated.source_refs == [result.observation_id, independent.observation_id]
    assert updated.metadata["source_event_ids"] == (result.delivery_event_id, "independent-light-event")
    assert reviewer.requests[0].owner_id == "listener"
    assert reviewer.requests[0].speech_observation_id == result.observation_id
    assert loop.agent_turn.cognitive_runtime.has_consumed_observation(
        "listener", observations.get_by_observer("listener")[-1],
        source_event_id=result.delivery_event_id,
    )
    next_context, _ = loop.agent_turn.prepare_decision_context(
        context.agent_registry.get("listener"), cognition,
    )
    assert next_context.beliefs[0].content == updated.content
    assert context.world_state.environment["shared-room"] == before_world
    assert len(history.get_events()) == 2  # independent fact and speech only
    assert service.submit(DialogueRequest("persuasion-1", "listener", "The light is on.")) == result
    assert len(reviewer.requests) == 1


@pytest.mark.parametrize("mode", ["speech_only", "wrong_source", "wrong_belief", "provider_failure", "no_revision"])
def test_persuasion_failure_keeps_canonical_belief_and_world(mode):
    belief = Belief("belief", "listener", "old", ["initial"], 0.4)
    other = Belief("private", "speaker", "private", ["private"], 0.8)
    reviewer = RecordingPersuasionReview(fail=mode == "provider_failure")
    service, context, processor, _, history, _ = make_dialogue(
        beliefs=(belief, other), review_provider=reviewer,
    )
    independent = None
    if mode != "speech_only":
        independent = add_independent_light_observation(service, context, processor)
    def choose(request):
        if mode != "provider_failure" and mode != "no_revision":
            refs = (request.speech_observation_id,)
            if independent is not None:
                refs += ("forged" if mode == "wrong_source" else independent.observation_id,)
            reviewer.review_result = CognitiveReview(
                "candidate", "uncertain",
                BeliefRevisionSuggestion(
                    "private" if mode == "wrong_belief" else "belief",
                    "new", 0.9, "candidate", refs,
                ),
            )
        return RecordingPersuasionReview.review(reviewer, request)
    reviewer.review = choose
    facts_before = dict(context.world_state.facts)
    result = service.submit(DialogueRequest("failed-" + mode, "listener", "Trust my claim."))
    cognition = service.cognition_context_provider(context.agent_registry.get("listener"))
    assert result.status == "delivered_no_action"
    assert cognition.get_beliefs()[0].content == "old"
    assert cognition.cognition_container.get_belief("private").content == "private"
    assert context.world_state.facts == facts_before
    assert len(history.get_events()) == (1 if independent is None else 2)
    assert len(reviewer.requests) == 1
    assert {item.belief_id for item in reviewer.requests[0].beliefs} == {"belief"}


@pytest.mark.parametrize("interference", ["changed_observation", "competing_belief", "advanced_clock"])
def test_persuasion_rechecks_evidence_prior_belief_and_tick_after_provider(interference):
    belief = Belief("belief", "listener", "old", ["initial"], 0.4)
    reviewer = RecordingPersuasionReview()
    service, context, processor, observations, history, _ = make_dialogue(
        beliefs=(belief,), review_provider=reviewer,
    )
    independent = add_independent_light_observation(service, context, processor)
    cognition = service.cognition_context_provider(context.agent_registry.get("listener"))
    def interfere(request):
        reviewer.requests.append(request)
        if interference == "changed_observation":
            observations._observations[independent.observation_id].content = "altered after authorization"
        elif interference == "advanced_clock":
            context.clock.tick()
        else:
            # A separate valid cognitive update wins the race; persuasion
            # cannot apply against the outdated Belief snapshot.
            independent_request = CognitiveReviewInput(
                request.owner_id, tuple(item for item in request.evidence
                                        if item.observation_id == independent.observation_id),
                request.beliefs,
            )
            CognitiveBeliefReview().apply(
                CognitiveReview("direct observation", "local",
                    BeliefRevisionSuggestion("belief", "competing", 0.6,
                                             "direct evidence", (independent.observation_id,))),
                independent_request, cognition.cognition_container,
            )
        return CognitiveReview("candidate", "uncertain",
            BeliefRevisionSuggestion("belief", "persuaded", 0.9, "proposed",
                                     (request.speech_observation_id, independent.observation_id)))
    reviewer.review = interfere
    result = service.submit(DialogueRequest("race-" + interference, "listener", "Please reconsider."))
    assert result.status == "delivered_no_action"
    assert cognition.get_beliefs()[0].content == (
        "competing" if interference == "competing_belief" else "old"
    )
    assert all(event.type != "belief_update" for event in history.get_events())
    assert len(reviewer.requests) == 1


def test_interpreted_request_still_runs_receiver_owned_agent_decision():
    decision = CapturingAgentDecision()
    service, _, processor, observations, history, _ = make_dialogue(
        provider=RequestInterpretation(), decision=decision
    )
    result = service.submit(
        DialogueRequest("message-2", "listener", "Could you help me with the door?")
    )

    assert result.interpretation is not None
    assert result.agent_execution is not None
    assert result.agent_execution.proposal.agent_id == "listener"
    assert result.agent_execution.attempt.agent_id == "listener"
    assert result.agent_execution.attempt.initiator_id == "speaker"
    assert any(
        cue.startswith("Untrusted dialogue interpretation candidate:")
        for cue in decision.received_context.metacognitive_feedback.review_cues
    )
    assert history.get_events()[0].type == "dialogue_input"
    assert observations.get_by_observer("listener")
    if result.agent_execution.event is not None:
        assert result.agent_execution.event.has_trusted_source("resolution")
        assert result.agent_execution.event.metadata["initiator_id"] == "speaker"
        assert processor.event_history.get_event(result.agent_execution.event.id) is not None


def test_unavailable_or_non_colocated_recipient_is_not_delivered():
    service, context, _, observations, history, _ = make_dialogue()
    context.world_state.load_location("listener", "other-room")
    try:
        service.submit(DialogueRequest("message-3", "listener", "Hello."))
    except PermissionError:
        pass
    else:
        raise AssertionError("non-colocated dialogue must be denied")
    assert observations.get_by_observer("listener") == ()
    assert history.get_events() == ()


def response_candidate(situation, event_id, *, outcome, content, goal_id=None, suffix="one", cost=0.0):
    return DialogueResponseCandidate(
        action=ActionCandidate(
            candidate_id=f"response:{suffix}", owner_id=situation.owner_id,
            goal_id=goal_id, intent="respond to the speaker",
            target="agent:speaker", method="speak or consider the request",
            tools=(), required_capabilities=(), preconditions=(), steps=(),
            expected_result="The speaker may hear the response",
            uncertainties=(), estimated_risk=0.0, estimated_cost=cost,
            commitment=0.5, source_refs=(event_id,), strategy="dialogue_candidate",
        ),
        request_outcome=outcome, semantic_content=content,
        inbound_event_id=event_id,
    )


class GoalBasedResponses:
    def propose(self, situation, interpretation, inbound_event_id):
        goal = situation.goals[0]
        return (
            response_candidate(situation, inbound_event_id, outcome="reject",
                               content="I will not do that.", suffix="unmotivated"),
            response_candidate(situation, inbound_event_id, outcome="clarify",
                               content="What exactly do you need?", goal_id=goal.goal_id,
                               suffix="goal-driven", cost=1.0),
        )


def test_npc_goal_scoring_selects_response_and_player_receives_only_addressed_speech():
    service, context, _, observations, history, _ = make_dialogue(
        response_provider=GoalBasedResponses()
    )
    result = service.submit(DialogueRequest("reply-1", "listener", "Can you help?"))
    assert result.status == "reply_delivered"
    assert result.request_outcome == "clarify"
    assert result.agent_execution is None
    assert result.reply_event_id is not None
    assert result.decision_candidate_id == "response:goal-driven"
    assert result.delivery_event_id in result.decision_source_refs
    assert len(history.get_events()) == 2
    reply = history.get_event(result.reply_event_id)
    assert reply.type == "dialogue_reply" and reply.cause == result.delivery_event_id
    assert reply.metadata["decision_candidate_id"] == result.decision_candidate_id
    assert reply.participants == ["listener", "speaker"]
    assert observations.get_by_observer("speaker")[0].source_event_id == reply.id
    assert service.presentation.gateway.messages_for("player")[0].content == "What exactly do you need?"
    assert context.world_state.facts == {}
    assert service.submit(DialogueRequest("reply-1", "listener", "Can you help?")) == result
    assert len(history.get_events()) == 2


def test_different_npc_goals_can_change_the_same_response_choice():
    high, _, _, _, _, _ = make_dialogue(
        response_provider=GoalBasedResponses(), listener_id="helper", goal_priority=0.9
    )
    low, _, _, _, _, _ = make_dialogue(
        response_provider=GoalBasedResponses(), listener_id="bystander", goal_priority=0.0
    )
    assert high.submit(DialogueRequest("high", "helper", "Can you help?")).request_outcome == "clarify"
    assert low.submit(DialogueRequest("low", "bystander", "Can you help?")).request_outcome == "reject"


class SingleResponse:
    def __init__(self, outcome, content):
        self.outcome, self.content = outcome, content

    def propose(self, situation, interpretation, inbound_event_id):
        return (response_candidate(
            situation, inbound_event_id, outcome=self.outcome,
            content=self.content, suffix=self.outcome
        ),)


def test_rejection_has_no_delegated_attempt_and_no_world_effect():
    service, context, _, _, history, _ = make_dialogue(
        provider=RequestInterpretation(),
        response_provider=SingleResponse("reject", "I decline your request."),
    )
    result = service.submit(DialogueRequest("reply-2", "listener", "Help me."))
    assert result.status == "reply_delivered" and result.request_outcome == "reject"
    assert result.agent_execution is None
    assert [event.type for event in history.get_events()] == ["dialogue_input", "dialogue_reply"]
    assert context.world_state.facts == {}


def test_acceptance_runs_existing_attempt_with_receiver_actor_and_original_initiator():
    service, _, _, _, _, _ = make_dialogue(
        provider=RequestInterpretation(),
        response_provider=SingleResponse("accept", "I will try."),
    )
    result = service.submit(DialogueRequest("reply-3", "listener", "Please help."))
    assert result.request_outcome == "accept"
    assert result.agent_execution is not None
    assert result.agent_execution.attempt.agent_id == "listener"
    assert result.agent_execution.attempt.initiator_id == "speaker"
    assert not result.agent_execution.resolution.confirmed


class ChangedExpression:
    def express(self, semantic_content):
        return semantic_content + " The door opened."


def test_expression_cannot_add_unsupported_claim_or_event():
    service, _, _, _, history, _ = make_dialogue(
        response_provider=SingleResponse("not_applicable", "I heard you."),
        expression_provider=ChangedExpression(),
    )
    result = service.submit(DialogueRequest("reply-4", "listener", "Hello."))
    assert result.status == "response_expression_failed"
    assert [event.type for event in history.get_events()] == ["dialogue_input"]


def test_clarification_followup_requires_a_delivered_matching_reply():
    service, _, _, _, history, _ = make_dialogue(
        response_provider=SingleResponse("clarify", "Which route do you mean?")
    )
    first = service.submit(DialogueRequest("clarify-1", "listener", "Which way?"))
    assert first.reply_delivered
    second = service.submit(DialogueRequest(
        "clarify-2", "listener", "The northern route.", in_reply_to="clarify-1"
    ))
    assert history.get_event(second.delivery_event_id).cause == first.reply_event_id
    assert second.agent_execution is None
    try:
        service.submit(DialogueRequest(
            "clarify-3", "listener", "I agree.", in_reply_to="missing"
        ))
    except PermissionError:
        pass
    else:
        raise AssertionError("an unlinked clarification cannot be accepted")


class FailingGateway:
    def send(self, batch):
        raise OSError("transport unavailable")


def test_delivery_retry_reuses_reply_event_and_does_not_rerun_decision():
    service, context, _, _, history, _ = make_dialogue(
        response_provider=SingleResponse("not_applicable", "I heard you.")
    )
    service.presentation.gateway = FailingGateway()
    result = service.submit(DialogueRequest("retry-1", "listener", "Hello."))
    assert result.status == "reply_delivery_failed"
    assert result.reply_event_id is not None and len(history.get_events()) == 2
    service.presentation.gateway = InMemoryChatOutputGateway(context)
    retried = service.retry_delivery("retry-1")
    assert retried.reply_delivered and len(history.get_events()) == 2
    assert service.presentation.gateway.messages_for("player")[0].content == "I heard you."
    assert service.submit(DialogueRequest("retry-1", "listener", "Hello.")) == retried


class ForgedResponse:
    def propose(self, situation, interpretation, inbound_event_id):
        item = response_candidate(
            situation, "forged:event", outcome="accept", content="I did it."
        )
        return (item,)


class ForgedTargetResponse:
    def propose(self, situation, interpretation, inbound_event_id):
        item = response_candidate(
            situation, inbound_event_id, outcome="not_applicable",
            content="I heard you.", suffix="forged-target",
        )
        return (DialogueResponseCandidate(
            action=ActionCandidate(
                **{**item.action.__dict__, "target": "agent:unobserved"}
            ),
            request_outcome=item.request_outcome,
            semantic_content=item.semantic_content,
            inbound_event_id=item.inbound_event_id,
        ),)


def test_forged_source_cannot_select_reply_or_execute_attempt():
    service, context, _, _, history, _ = make_dialogue(
        provider=RequestInterpretation(), response_provider=ForgedResponse()
    )
    result = service.submit(DialogueRequest("forged-1", "listener", "Please do it."))
    assert result.status == "response_decision_failed"
    assert result.agent_execution is None
    assert [event.type for event in history.get_events()] == ["dialogue_input"]
    assert context.world_state.facts == {}


def test_forged_target_cannot_select_reply_or_execute_attempt():
    service, _, _, _, history, _ = make_dialogue(response_provider=ForgedTargetResponse())
    result = service.submit(DialogueRequest("forged-target-1", "listener", "Hello."))
    assert result.status == "response_decision_failed"
    assert result.reply_event_id is None
    assert [event.type for event in history.get_events()] == ["dialogue_input"]


def test_undecided_npc_is_not_silently_classified_as_acceptance_or_refusal():
    service, _, _, _, history, _ = make_dialogue(
        provider=RequestInterpretation(),
        response_provider=SingleResponse("undecided", ""),
    )
    result = service.submit(DialogueRequest("undecided-1", "listener", "Please decide."))
    assert result.status == "response_undecided"
    assert result.request_outcome == "undecided"
    assert result.agent_execution is None and result.reply_event_id is None
    assert [event.type for event in history.get_events()] == ["dialogue_input"]


def test_delivery_retry_cannot_switch_to_a_different_player_session():
    service, context, _, _, history, _ = make_dialogue(
        response_provider=SingleResponse("not_applicable", "I heard you.")
    )
    service.presentation.gateway = FailingGateway()
    result = service.submit(DialogueRequest("retry-owner", "listener", "Hello."))
    assert result.status == "reply_delivery_failed"
    context.player_session = PlayerSessionBinding(
        "other-session", "other-player", PlayerMode.ROLEPLAY, "speaker"
    )
    try:
        service.retry_delivery("retry-owner")
    except PermissionError:
        pass
    else:
        raise AssertionError("retry must retain the original player session")
    assert len(history.get_events()) == 2


def test_handmade_system_reply_cannot_bypass_npc_decision_binding():
    service, context, processor, _, history, _ = make_dialogue()
    inbound = service.submit(DialogueRequest("source-forged", "listener", "Hello."))
    forged = service.factory.create(
        event_id="fake-reply", event_type="dialogue_reply", timestamp="4",
        simulation_tick=4, participants=["listener", "speaker"],
        cause=inbound.delivery_event_id,
        changes=[{"utterance": "I promise to do it."}],
        metadata={
            "sender_id": "listener", "recipient_id": "speaker",
            "location_id": "shared-room", "inbound_event_id": inbound.delivery_event_id,
            "decision_candidate_id": "invented", "decision_proposal_id": "invented",
        },
    )
    try:
        processor.dispatch_with_evidence(forged)
    except PermissionError:
        pass
    else:
        raise AssertionError("a fabricated response cannot impersonate an NPC decision")
    assert [event.type for event in history.get_events()] == ["dialogue_input"]
    assert context.world_state.facts == {}


def test_two_dialogue_services_share_one_reply_authority_in_the_same_runtime():
    first, context, processor, _, history, loop = make_dialogue(
        response_provider=SingleResponse("not_applicable", "I heard you.")
    )
    second = PlayerDialogueService(
        context, processor, loop, first.cognition_context_provider, first.decision,
        response_candidate_provider=SingleResponse("not_applicable", "I heard you."),
        presentation=first.presentation,
    )
    assert second.reply_handler is first.reply_handler
    original = first.submit(DialogueRequest("shared-1", "listener", "Hello."))
    assert original.reply_delivered
    assert second.submit(DialogueRequest("shared-1", "listener", "Hello.")) == original
    assert second.submit(DialogueRequest("shared-2", "listener", "Again.")).reply_delivered
    assert len(history.get_events()) == 4


def _ollama_envelope(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def _ollama_candidate_json(*, outcome="not_applicable", target="agent:speaker"):
    return json.dumps({"candidates": [{
        "request_outcome": outcome,
        "semantic_content": "I would like to hear more about that.",
        "goal_id": "listener-goal",
        "intent": "offer a conversational response",
        "target": target,
        "method": "express the proposed response to the speaker",
        "tools": [],
        "required_capabilities": [],
        "preconditions": [],
        "steps": [],
        "expected_result": "The speaker may receive the proposed words.",
        "uncertainties": [],
    }]})


def test_environment_selected_ollama_uses_production_dialogue_and_agentdecision_path(monkeypatch):
    monkeypatch.setenv("COGNITIVEWORLD_DIALOGUE_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "test-model")
    captured = {}

    def fake_local_transport(base_url, body, *, timeout_seconds, maximum_bytes):
        captured.update(url=base_url, timeout=timeout_seconds, body=json.loads(body))
        return _ollama_envelope(_ollama_candidate_json())

    monkeypatch.setattr(dialogue_ollama, "_post_loopback_json", fake_local_transport)
    service, _, _, observations, history, _ = make_dialogue()
    assert isinstance(service.response_candidate_provider, OllamaDialogueResponseCandidateProvider)
    result = service.submit(DialogueRequest(
        "ollama-configured", "listener", "I enjoyed walking in the rain today."
    ))

    assert result.status == "reply_delivered"
    assert result.request_outcome == "not_applicable"
    assert result.agent_execution is None
    assert result.decision_candidate_id
    assert [event.type for event in history.get_events()] == ["dialogue_input", "dialogue_reply"]
    assert observations.get_by_observer("speaker")[-1].source_event_id == result.reply_event_id
    assert captured["url"] == "http://127.0.0.1:11434/v1"
    prompt = captured["body"]["messages"][1]["content"]
    assert "I enjoyed walking in the rain today." in prompt
    assert "world_state" not in prompt.casefold()
    assert '"owner_id"' not in prompt
    assert "other-agent-private" not in prompt


def test_ollama_provider_rejects_non_loopback_address_and_authority_fields(monkeypatch):
    with pytest.raises(ValueError, match="loopback"):
        OllamaDialogueResponseCandidateProvider("http://example.com:11434/v1", "test-model")

    monkeypatch.setenv("COGNITIVEWORLD_DIALOGUE_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "test-model")
    unauthorized = json.loads(_ollama_candidate_json())["candidates"][0]
    unauthorized["owner_id"] = "speaker"
    monkeypatch.setattr(
        dialogue_ollama, "_post_loopback_json",
        lambda *args, **kwargs: _ollama_envelope(json.dumps({"candidates": [unauthorized]})),
    )
    service, _, _, _, history, _ = make_dialogue()
    result = service.submit(DialogueRequest("ollama-authority", "listener", "Hello."))
    assert result.status == "response_generation_failed"
    assert [event.type for event in history.get_events()] == ["dialogue_input"]


def test_ollama_candidate_target_must_be_in_current_authorized_target_set(monkeypatch):
    monkeypatch.setenv("COGNITIVEWORLD_DIALOGUE_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(
        dialogue_ollama, "_post_loopback_json",
        lambda *args, **kwargs: _ollama_envelope(
            _ollama_candidate_json(target="agent:unobserved")
        ),
    )
    service, _, _, _, history, _ = make_dialogue()
    result = service.submit(DialogueRequest("ollama-target", "listener", "Hello."))
    assert result.status == "response_generation_failed"
    assert [event.type for event in history.get_events()] == ["dialogue_input"]


def test_loopback_http_redirect_is_rejected_without_following_it(monkeypatch):
    calls = []

    class RedirectResponse:
        status = 302

    class RedirectConnection:
        def __init__(self, host, port, *, timeout):
            calls.append((host, port, timeout))

        def request(self, method, path, *, body, headers):
            calls.append((method, path, headers["Host"]))

        def getresponse(self):
            return RedirectResponse()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(dialogue_ollama.http.client, "HTTPConnection", RedirectConnection)
    with pytest.raises(PermissionError, match="redirects"):
        dialogue_ollama._post_loopback_json(
            "http://127.0.0.1:11434/v1", b"{}", timeout_seconds=1.0,
            maximum_bytes=1024,
        )
    assert calls[-1] == "closed"


def test_ollama_is_not_selected_without_explicit_environment_configuration(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_DIALOGUE_PROVIDER", raising=False)
    monkeypatch.delenv("COGNITIVEWORLD_OLLAMA_MODEL", raising=False)
    assert OllamaDialogueResponseCandidateProvider.from_environment() is None


def test_ollama_provider_failure_does_not_invent_a_reply(monkeypatch):
    monkeypatch.setenv("COGNITIVEWORLD_DIALOGUE_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(
        dialogue_ollama, "_post_loopback_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("local model timed out")),
    )
    service, _, _, _, history, _ = make_dialogue()
    result = service.submit(DialogueRequest("ollama-offline", "listener", "Hello."))
    assert result.status == "response_generation_failed"
    assert result.reply_event_id is None
    assert [event.type for event in history.get_events()] == ["dialogue_input"]


@pytest.mark.skipif(
    os.environ.get("COGNITIVEWORLD_RUN_OLLAMA_INTEGRATION") != "1",
    reason="explicit opt-in required for the real local Ollama integration",
)
def test_live_ollama_dialogue_candidate_reaches_player_gateway():
    service, _, _, _, history, _ = make_dialogue(provider=RequestInterpretation())
    assert isinstance(service.response_candidate_provider, OllamaDialogueResponseCandidateProvider)
    result = service.submit(DialogueRequest(
        "ollama-live-synthetic", "listener",
        "Could you help me think through what to do about the rain?",
    ))
    assert result.status == "reply_delivered"
    assert result.reply_delivered
    assert result.decision_candidate_id
    assert [event.type for event in history.get_events()] == ["dialogue_input", "dialogue_reply"]
    assert service.presentation.gateway.messages_for("player")[-1].source_event_ids == (
        result.reply_event_id,
    )
