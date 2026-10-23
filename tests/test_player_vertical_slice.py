import pytest
from threading import Event, Lock, Thread

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.no_result import NoResultState
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.player import PlayerActionRequest, PlayerActionService
from cognitive_world.player.input_understanding import (
    InputUnderstandingStatus, PlayerInputAssessment, PlayerInputRequest,
)
from cognitive_world.player.narrative_fallback import (
    NarrativeFallbackContext, NoResultReason, NoResultState,
    OllamaNarrativeFallbackProvider,
)
from cognitive_world.presentation.gateway import InMemoryChatOutputGateway
from cognitive_world.presentation.perspective import PerspectiveResolver
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding, RuntimeContext


def live_player(*, door_id="door-1", actor_id="actor-1", room_id="room-1", door_state=None,
                narrative_fallback_provider=None, input_understanding_provider=None):
    world = WorldState()
    world.load_environment_data(
        door_id, door_state or DoorState(door_id, room_id, False, False, True),
    )
    world.load_entity(Entity(actor_id, "character", sensory_capabilities=("sight",),
                             physical_capabilities=("manual_manipulation",)))
    world.load_location(actor_id, room_id)
    agents = AgentRegistry()
    agents.register(RuntimeAgent(actor_id, f"character:{actor_id}"))
    observations = ObservationStore()
    history = EventHistory()
    clock = SimulationClock(1)
    context = RuntimeContext(
        clock, world, history, agent_registry=agents, observation_store=observations,
        player_session=PlayerSessionBinding("session-1", "player-1", PlayerMode.ROLEPLAY, actor_id),
    )
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock,
                               agent_registry=agents, observation_store=observations)
    processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id=f"initial:{door_id}", event_type="environment_state_observed",
        timestamp="", simulation_tick=clock.current_time,
        changes=[{"environment_id": door_id}],
    ))
    output = InMemoryChatOutputGateway(context)
    service = PlayerActionService(
        context, processor, ActionPipeline(),
        ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world), world_state=world),
        output, world_id="world-1",
        narrative_fallback_provider=narrative_fallback_provider,
        input_understanding_provider=input_understanding_provider,
    )
    return service, world, history, observations, output


def request(request_id="request-1", method="push the closed door", target="door-1"):
    return PlayerActionRequest(request_id, "session-1", "world-1", method, method, target)


def input_request(request_id="input-1", text="Could you deal with this?"):
    return PlayerInputRequest(request_id, "session-1", "world-1", text)


def test_player_request_uses_real_resolution_event_observation_and_presentation():
    service, world, history, observations, output = live_player()
    assert service.available_targets() == ("door-1",)
    assert world.environment["door-1"].is_open is False
    before = len(history.get_events())
    result = service.submit(request())
    assert result.status == "resolved"
    assert result.messages and "门打开了" in result.messages[0]
    assert "door-1" not in result.messages[0] and "door_open" not in result.messages[0]
    assert world.environment["door-1"].is_open is True
    assert len(history.get_events()) == before + 1
    event = history.get_events()[-1]
    assert event.has_trusted_source("resolution")
    assert any(item.source_event_id == event.id and item.has_trusted_provenance()
               for item in observations.get_by_observer("actor-1"))
    assert output.messages_for("player-1")[0].source_event_ids == (event.id,)
    assert service.submit(request()) == result
    assert len(history.get_events()) == before + 1


def test_repeating_a_satisfied_action_reports_existing_state_without_claiming_a_change():
    service, world, history, _, output = live_player()
    first = service.submit(request("open-once"))
    assert first.status == "resolved"
    opened_state = world.environment["door-1"]
    before_events = len(history.get_events())

    repeated = service.submit(request("open-again"))

    assert repeated.status == "goal_already_satisfied"
    assert world.environment["door-1"] == opened_state
    assert len(history.get_events()) == before_events + 1
    event = history.get_events()[-1]
    assert event.changes[0]["success"] is False
    assert event.metadata["action_result_kind"] == "goal_already_satisfied"
    feedback = output.action_feedback_for("player-1")
    assert len(feedback) == 1
    assert feedback[0].content == "目标当前已经满足。"
    assert "door-1" not in feedback[0].content
    assert "door_open" not in feedback[0].content


def test_confirmed_failed_action_has_safe_feedback_and_no_world_change():
    locked = DoorState("door-1", "room-1", False, True, True)
    service, world, history, _, output = live_player(door_state=locked)
    before = world.environment["door-1"]

    result = service.submit(request("locked-attempt"))

    assert result.status == "failed"
    assert world.environment["door-1"] == before
    assert history.get_events()[-1].changes[0]["success"] is False
    assert output.action_feedback_for("player-1")[0].content == "这次行动没有达到预期效果。"
    rendered = output.action_feedback_for("player-1")[0].content
    assert "door-1" not in rendered and "door_open" not in rendered


def test_success_without_player_visible_fact_is_not_reported_as_a_visible_change():
    from cognitive_world.core.action_result import ActionResultKind
    from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine

    class CompletedWithoutVisibleEffect(ResolutionEngine):
        def _adjudicate(self, attempt):
            return ResolutionDecision(
                True, "confirmed execution", result_kind=ActionResultKind.STATE_CHANGED,
            )

    service, world, history, _, output = live_player()
    service.resolution_flow.resolution_engine = CompletedWithoutVisibleEffect()
    before = world.environment["door-1"]

    result = service.submit(request("no-visible-effect"))

    assert result.status == "executed_no_observable_change"
    assert world.environment["door-1"] == before
    assert history.get_events()[-1].changes[0]["success"] is True
    assert output.action_feedback_for("player-1")[0].result_kind is ActionResultKind.EXECUTED_NO_OBSERVABLE_CHANGE
    assert output.action_feedback_for("player-1")[0].content == "行动已裁定完成，但当前没有可展示的已确认变化。"


@pytest.mark.parametrize("raw_input", [False, True])
@pytest.mark.parametrize("delivered_before_error", [False, True])
@pytest.mark.parametrize("runtime_bound", [False, True])
def test_committed_player_request_retries_presentation_without_repeating_action(
    monkeypatch, raw_input, delivered_before_error, runtime_bound,
):
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        ),
    ])
    service, world, history, observations, output = live_player(
        input_understanding_provider=understanding,
    )
    if runtime_bound:
        from cognitive_world.runtime.runtime import SimulationRuntime

        runtime = SimulationRuntime(
            service.context, event_processor=service.processor,
            allow_environment_provider_discovery=False,
        )
        runtime.start()
    submit = service.submit_input if raw_input else service.submit
    pending = input_request(text="Open the door.") if raw_input else request()
    original_send = output.send

    def interrupted_send(batch):
        if delivered_before_error:
            original_send(batch)
        raise ConnectionError("test transport disconnected")

    monkeypatch.setattr(output, "send", interrupted_send)
    with pytest.raises(ConnectionError, match="test transport disconnected"):
        submit(pending)
    assert world.environment["door-1"].is_open is True
    assert len(history.get_events()) == 2
    committed = history.get_events()[-1]
    before_world = _world_snapshot(world)
    before_observations = observations.get_by_observer("actor-1")
    assert len(output.messages_for("player-1")) == int(delivered_before_error)
    changed = (
        input_request(text="Close the door.") if raw_input
        else request(method="pull the closed door")
    )
    with pytest.raises(PermissionError, match="request identity reused with changed content"):
        submit(changed)

    monkeypatch.setattr(output, "send", original_send)
    def unexpected_dispatch(*args, **kwargs):
        raise AssertionError("completed Event delivery must not re-enter world processing")

    monkeypatch.setattr(service.processor, "dispatch_with_evidence", unexpected_dispatch)
    result = submit(pending)
    assert result.status == "resolved"
    assert result.messages
    assert submit(pending) == result
    assert _world_snapshot(world) == before_world
    assert history.get_events()[-1].id == committed.id
    assert len(history.get_events()) == 2
    assert observations.get_by_observer("actor-1") == before_observations
    assert len(output.messages_for("player-1")) == 1
    assert len(understanding.calls) == int(raw_input)


def test_unresolved_and_rejected_requests_never_write_world():
    service, world, history, _, output = live_player()
    before = len(history.get_events())
    result = service.submit(request(method="try an unknown mechanism"))
    assert result.status == "unresolved"
    assert len(history.get_events()) == before
    assert world.environment["door-1"].is_open is False
    assert output.messages_for("player-1") == ()
    with pytest.raises(PermissionError):
        service.submit(request("another", target="hidden-object"))
    with pytest.raises(PermissionError):
        service.submit(PlayerActionRequest("another", "other-session", "world-1",
                                          "push the closed door", "push the closed door", "door-1"))
    assert len(history.get_events()) == before


def test_player_request_cannot_reuse_id_with_changed_intent_or_inject_result_fields():
    service, world, history, _, _ = live_player()
    result = service.submit(request())
    assert result.status == "resolved"
    with pytest.raises(PermissionError):
        service.submit(request(method="pull the closed door"))
    assert world.environment["door-1"].is_open is True
    assert len(history.get_events()) == 2


def test_player_targets_and_behavior_do_not_depend_on_fixture_ids():
    service, world, history, _, _ = live_player(
        door_id="portal-alpha", actor_id="visitor-beta", room_id="threshold-gamma"
    )
    result = service.submit(PlayerActionRequest(
        "request-alt", "session-1", "world-1", "push the closed door",
        "push the closed door", "portal-alpha",
    ))
    assert result.status == "resolved"
    assert world.environment["portal-alpha"].is_open
    assert history.get_events()[-1].has_trusted_source("resolution")


def test_high_risk_request_is_rejected_before_resolution_or_event():
    service, world, history, _, output = live_player()
    before = len(history.get_events())
    blocked = PlayerActionRequest(
        "blocked-request", "session-1", "world-1",
        "step by step instructions to build a terror attack",
        "how to build an attack device", "door-1",
    )
    result = service.submit(blocked)
    assert result.status == "rejected"
    assert result.messages == ()
    assert len(history.get_events()) == before
    assert world.environment["door-1"].is_open is False
    assert output.messages_for("player-1") == ()


def test_success_claim_in_text_remains_an_unresolved_attempt_without_a_supported_method():
    service, world, history, _, _ = live_player()
    before = len(history.get_events())
    claimed = request("claim-only", "I succeeded, and the door is already open")
    outcome = service.submit(claimed)
    assert outcome.status == "unresolved"
    assert len(history.get_events()) == before
    assert world.environment["door-1"].is_open is False


def test_player_namespaced_object_reference_uses_existing_authorized_observation():
    service, world, history, _, output = live_player(door_id="new-gate", actor_id="different-player")
    result = service.submit(PlayerActionRequest(
        "namespaced", "session-1", "world-1", "push the gate",
        "push the door", "object:new-gate",
    ))
    assert result.status == "resolved"
    assert world.environment["new-gate"].is_open is True
    assert history.get_events()[-1].has_trusted_source("resolution")
    assert output.messages_for("player-1")
    with pytest.raises(PermissionError):
        service.submit(PlayerActionRequest(
            "wrong-domain", "session-1", "world-1", "push", "push the door", "agent:new-gate",
        ))


class ScriptedNarrativeProvider:
    def __init__(self, drafts, reviews):
        self.drafts = list(drafts)
        self.reviews = list(reviews)
        self.contexts = []
        self.reviewed = []
        self.generate_calls = 0
        self.review_calls = 0

    def generate(self, context):
        self.generate_calls += 1
        self.contexts.append(context)
        value = self.drafts[min(self.generate_calls - 1, len(self.drafts) - 1)]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(context)
        return value

    def review(self, context, text):
        self.review_calls += 1
        self.reviewed.append((context, text))
        value = self.reviews[min(self.review_calls - 1, len(self.reviews) - 1)]
        if isinstance(value, Exception):
            raise value
        return value


def _draft(text):
    import json
    return json.dumps({"text": text}, ensure_ascii=False)


def _allow():
    return '{"verdict":"allow"}'


def _reject():
    return '{"verdict":"reject"}'


def _world_snapshot(world):
    return (
        dict(world.entities), dict(world.locations), dict(world.relationships),
        dict(world.facts), dict(world.environment),
    )


def test_unresolved_player_attempt_gets_dynamic_narrative_without_world_or_event_changes(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider(
        [lambda context: _draft(
            f"“{context.method}”还没有足够线索，下一步需要更具体的尝试。"
        )], [_allow()],
    )
    service, world, history, observations, output = live_player(
        narrative_fallback_provider=provider,
    )
    before_world = _world_snapshot(world)
    before_events = history.get_events()
    before_observations = observations.get_by_observer("actor-1")

    outcome = service.submit(request(method="try an unknown mechanism"))

    assert outcome.status == "unresolved"
    assert outcome.messages == ()
    assert outcome.narrative_fallback is not None
    assert outcome.narrative_fallback.content == "“try an unknown mechanism”还没有足够线索，下一步需要更具体的尝试。"
    assert outcome.narrative_fallback.no_result_reason == NoResultReason.UNRESOLVED_ATTEMPT.value
    assert outcome.no_result_state is not None
    assert outcome.no_result_state.reason is NoResultReason.UNRESOLVED_ATTEMPT
    assert not hasattr(outcome.narrative_fallback, "source_event_ids")
    assert not hasattr(outcome.narrative_fallback, "source_fact_ids")
    assert outcome.narrative_fallback.has_narrative_receipt(PerspectiveResolver(service.context).resolve())
    assert output.narrative_fallbacks_for("player-1") == (outcome.narrative_fallback,)
    assert output.messages_for("player-1") == ()
    with pytest.raises(TypeError, match="ValidatedMessageBatch"):
        output.send(outcome.narrative_fallback)
    assert provider.generate_calls == provider.review_calls == 1
    assert provider.contexts[0].state.reason is NoResultReason.UNRESOLVED_ATTEMPT
    assert provider.contexts[0].intent == "try an unknown mechanism"
    assert set(provider.contexts[0].__dict__) == {
        "state", "intent", "method", "input_fingerprint", "input_text",
    }
    assert not hasattr(service.context, "memory_store")
    assert not hasattr(service.context, "belief_store")
    assert not hasattr(service.context, "goal_store")
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert observations.get_by_observer("actor-1") == before_observations


@pytest.mark.parametrize("claim", [
    "你在桌上发现了一把钥匙。",
    "门应声打开，你把钥匙收进口袋。",
    "一个陌生人从门后走出来，向你点头。",
    "守卫此刻信任你，并决定帮助你。",
])
def test_narrative_reviewer_rejects_unverified_world_or_cognition_claims(claim, monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider([_draft(claim), _draft(claim)], [_reject(), _reject()])
    service, world, history, _, output = live_player(narrative_fallback_provider=provider)
    before_world, before_events = _world_snapshot(world), history.get_events()

    outcome = service.submit(request(method="try an unknown mechanism"))

    assert outcome.status == "unresolved"
    assert outcome.narrative_fallback is None
    assert outcome.recovery_action == "clarify_or_retry"
    assert "reject" not in " ".join(outcome.messages).casefold()
    assert output.narrative_fallbacks_for("player-1") == ()
    assert provider.generate_calls == 2 and provider.review_calls == 2
    assert service.fallback_diagnostic(request().request_id) == "narrative_rejected"
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events


@pytest.mark.parametrize("bad_draft", ["", "not-json", '{"text":""}', '{"text":"ok","event":"fake"}'])
def test_invalid_narrative_output_has_bounded_retry_and_recovery_signal(bad_draft, monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider([bad_draft, bad_draft], [])
    service, world, history, _, output = live_player(narrative_fallback_provider=provider)
    before_world, before_events = _world_snapshot(world), history.get_events()

    outcome = service.submit(request(method="try an unknown mechanism"))

    assert outcome.narrative_fallback is None
    assert outcome.recovery_action == "clarify_or_retry"
    assert provider.generate_calls == 2 and provider.review_calls == 0
    assert (service.fallback_diagnostic(request().request_id) or "").startswith("invalid_output:")
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events


def test_narrative_provider_timeout_is_hidden_and_does_not_retry_without_bound(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider(
        [TimeoutError("private transport detail"), TimeoutError("private transport detail")], [],
    )
    service, world, history, _, output = live_player(narrative_fallback_provider=provider)
    before_world, before_events = _world_snapshot(world), history.get_events()

    outcome = service.submit(request(method="try an unknown mechanism"))

    assert outcome.status == "unresolved"
    assert outcome.narrative_fallback is None
    assert outcome.recovery_action == "clarify_or_retry"
    assert "private transport detail" not in repr(outcome)
    assert service.fallback_diagnostic(request().request_id) == "generation_failed:TimeoutError"
    assert provider.generate_calls == 2 and provider.review_calls == 0
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events


def test_narrative_reviewer_failure_fails_closed_without_raw_error_to_player(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider(
        [_draft("行动仍然悬在没有答案的地方。")],
        [TimeoutError("review backend secret"), TimeoutError("review backend secret")],
    )
    service, world, history, _, output = live_player(narrative_fallback_provider=provider)
    before_world, before_events = _world_snapshot(world), history.get_events()

    outcome = service.submit(request(method="try an unknown mechanism"))

    assert outcome.narrative_fallback is None
    assert outcome.recovery_action == "clarify_or_retry"
    assert "review backend secret" not in repr(outcome)
    assert service.fallback_diagnostic(request().request_id) == "review_failed:TimeoutError"
    assert provider.generate_calls == provider.review_calls == 2
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events


def test_missing_narrative_provider_returns_recoverable_signal_without_template(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    service, world, history, _, output = live_player()
    before_world, before_events = _world_snapshot(world), history.get_events()

    outcome = service.submit(request(method="try an unknown mechanism"))

    assert outcome.status == "unresolved"
    assert outcome.narrative_fallback is None
    assert outcome.messages == ()
    assert outcome.recovery_action == "clarify_or_retry"
    assert service.fallback_diagnostic(request().request_id) == "provider_unavailable"
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events


def test_narrative_channel_rejects_caller_constructed_no_result_state(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    service, _, _, _, output = live_player()
    forged_state = NoResultState("forged", NoResultReason.UNRESOLVED_ATTEMPT, "0" * 64)

    with pytest.raises(PermissionError, match="established no-result"):
        service.presentation.publish_narrative_fallback(
            forged_state, "A key appears in your hand."
        )

    assert output.narrative_fallbacks_for("player-1") == ()


def test_unresolved_request_replay_returns_same_fallback_without_repeating_side_effects(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider([_draft("门前的计划暂时没有落点。")], [_allow()])
    service, world, history, _, output = live_player(narrative_fallback_provider=provider)
    unresolved = request(method="try an unknown mechanism")
    before_world, before_events = _world_snapshot(world), history.get_events()

    first = service.submit(unresolved)
    second = service.submit(unresolved)

    assert second == first
    assert provider.generate_calls == provider.review_calls == 1
    assert len(output.narrative_fallbacks_for("player-1")) == 1
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events


def test_resolved_action_does_not_invoke_narrative_fallback(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    provider = ScriptedNarrativeProvider([_draft("must not run")], [_allow()])
    service, world, history, _, output = live_player(narrative_fallback_provider=provider)

    outcome = service.submit(request())

    assert outcome.status == "resolved"
    assert outcome.narrative_fallback is None
    assert provider.generate_calls == provider.review_calls == 0
    assert output.narrative_fallbacks_for("player-1") == ()
    assert world.environment["door-1"].is_open is True
    assert history.get_events()[-1].has_trusted_source("resolution")


def test_ollama_narrative_provider_uses_bounded_loopback_generation_and_review(monkeypatch):
    import json

    calls = []

    def fake_post(url, body, *, timeout_seconds, maximum_bytes):
        request_body = json.loads(body.decode("utf-8"))
        calls.append((url, request_body, timeout_seconds, maximum_bytes))
        content = ('{"text":"你的尝试停在尚未验证的门前。"}' if len(calls) == 1
                   else '{"verdict":"allow"}')
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    monkeypatch.setattr(
        "cognitive_world.player.narrative_fallback._post_loopback_json", fake_post,
    )
    provider = OllamaNarrativeFallbackProvider("http://127.0.0.1:11434/v1", "local-test")
    context = NarrativeFallbackContext(
        NoResultState("provider-test", NoResultReason.UNRESOLVED_ATTEMPT, "0" * 64),
        "try the sealed door", "push gently", "0" * 64,
    )

    generated = provider.generate(context)
    reviewed = provider.review(context, "你的尝试停在尚未验证的门前。")

    assert json.loads(generated)["text"] == "你的尝试停在尚未验证的门前。"
    assert json.loads(reviewed)["verdict"] == "allow"
    assert len(calls) == 2
    assert all(call[0] == "http://127.0.0.1:11434/v1" for call in calls)
    assert all(call[2] <= 10.0 and call[3] <= 8_000 for call in calls)
    assert calls[0][1]["messages"][0]["role"] == "system"
    assert "candidate_text" in calls[1][1]["messages"][1]["content"]

    with pytest.raises(ValueError, match="loopback"):
        OllamaNarrativeFallbackProvider("https://remote.example/v1", "local-test")


class ScriptedInputUnderstandingProvider:
    def __init__(self, assessments):
        self.assessments = list(assessments)
        self.calls = []

    def understand(self, request, *, authorized_targets):
        self.calls.append((request, authorized_targets))
        value = self.assessments[min(len(self.calls) - 1, len(self.assessments) - 1)]
        if isinstance(value, Exception):
            raise value
        return value


def test_unparseable_player_input_has_no_proposal_or_world_effect_and_uses_dynamic_fallback(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    narrative = ScriptedNarrativeProvider(
        [lambda context: _draft(f"“{context.input_text}”暂时没有形成可执行的意思。")],
        [_allow()],
    )
    service, world, history, observations, output = live_player(
        narrative_fallback_provider=narrative,
        input_understanding_provider=understanding,
    )
    from cognitive_world.decision.action_proposal import ActionProposal as ProposalType
    proposals = []
    monkeypatch.setattr(
        "cognitive_world.player.service.ActionProposal",
        lambda **kwargs: proposals.append(kwargs) or ProposalType(**kwargs),
    )
    before_world = _world_snapshot(world)
    before_events = history.get_events()
    before_observations = observations.get_by_observer("actor-1")
    attempted = []
    original_create_attempt = service.action_pipeline.create_attempt
    service.action_pipeline.create_attempt = lambda proposal: (
        attempted.append(proposal) or original_create_attempt(proposal)
    )

    outcome = service.submit_input(input_request(text="[unparseable noise]"))

    assert outcome.status == "unparseable"
    assert not hasattr(outcome, "action_proposal")
    assert outcome.narrative_fallback is not None
    assert outcome.narrative_fallback.content == "“[unparseable noise]”暂时没有形成可执行的意思。"
    assert outcome.no_result_state.reason is NoResultReason.UNPARSEABLE_INPUT
    assert outcome.clarification is None
    assert attempted == []
    assert proposals == []
    assert len(understanding.calls) == 1
    assert narrative.generate_calls == narrative.review_calls == 1
    assert output.messages_for("player-1") == ()
    assert len(output.narrative_fallbacks_for("player-1")) == 1
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert observations.get_by_observer("actor-1") == before_observations
    assert not hasattr(service.context, "memory_store")


def test_critical_missing_information_gets_targeted_clarification_then_reenters_normal_action_flow(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.CLARIFICATION_REQUIRED,
            intent="open the door", method="push it",
            missing_information=("target",),
            clarification_question="你说的“它”是哪个已看见的物体？",
        ),
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the door", target_ref="door-1",
        ),
    ])
    narrative = ScriptedNarrativeProvider([_draft("unused")], [_allow()])
    service, world, history, observations, output = live_player(
        input_understanding_provider=understanding,
        narrative_fallback_provider=narrative,
    )
    from cognitive_world.decision.action_proposal import ActionProposal as ProposalType
    proposals = []
    monkeypatch.setattr(
        "cognitive_world.player.service.ActionProposal",
        lambda **kwargs: proposals.append(kwargs) or ProposalType(**kwargs),
    )
    before_world = _world_snapshot(world)
    before_events = history.get_events()
    before_observations = observations.get_by_observer("actor-1")
    attempted = []
    original_create_attempt = service.action_pipeline.create_attempt
    service.action_pipeline.create_attempt = lambda proposal: (
        attempted.append(proposal) or original_create_attempt(proposal)
    )

    clarification = service.submit_input(input_request("clarify-1", "Open it."))

    assert clarification.status == "clarification_required"
    assert not hasattr(clarification, "action_proposal")
    assert clarification.no_result_state.reason is NoResultReason.CLARIFICATION_REQUIRED
    assert clarification.clarification.question == "你说的“它”是哪个已看见的物体？"
    assert clarification.clarification.missing_information == ("target",)
    assert output.clarifications_for("player-1") == (clarification.clarification,)
    assert output.messages_for("player-1") == ()
    assert attempted == []
    assert proposals == []
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert observations.get_by_observer("actor-1") == before_observations
    assert not hasattr(service.context, "memory_store")

    resolved = service.submit_input(input_request("clarify-2", "The visible door. Push it."))

    assert resolved.status == "resolved"
    assert resolved.clarification is None
    assert len(attempted) == 1
    assert attempted[0].target_refs == ["door-1"]
    assert world.environment["door-1"].is_open is True
    assert len(history.get_events()) == len(before_events) + 1
    assert history.get_events()[-1].has_trusted_source("resolution")
    assert len(understanding.calls) == 2
    assert output.narrative_fallbacks_for("player-1") == ()
    assert narrative.generate_calls == narrative.review_calls == 0
    event_count = len(history.get_events())
    replay = service.submit_input(input_request("clarify-2", "The visible door. Push it."))
    assert replay == resolved
    assert len(understanding.calls) == 2
    assert len(attempted) == 1
    assert len(history.get_events()) == event_count


def test_input_interpreter_cannot_authorize_unobserved_target_or_turn_it_into_an_action(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open object", method="turn the handle", target_ref="hidden-door",
        ),
    ])
    service, world, history, _, output = live_player(
        input_understanding_provider=understanding,
    )
    before_world, before_events = _world_snapshot(world), history.get_events()
    attempted = []
    original_create_attempt = service.action_pipeline.create_attempt
    service.action_pipeline.create_attempt = lambda proposal: (
        attempted.append(proposal) or original_create_attempt(proposal)
    )

    outcome = service.submit_input(input_request(text="Open the hidden door."))

    assert outcome.status == "reasoning_unavailable"
    assert not hasattr(outcome, "action_proposal")
    assert attempted == []
    assert "hidden-door" not in repr(outcome)
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert output.messages_for("player-1") == ()


def test_input_understanding_failure_is_not_mislabeled_as_unparseable_and_can_recover(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    understanding = ScriptedInputUnderstandingProvider([
        TimeoutError("private parser transport detail"),
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push it", target_ref="door-1",
        ),
    ])
    narrative = ScriptedNarrativeProvider(
        [_draft("unused" )], [_allow()],
    )
    service, world, history, _, output = live_player(
        narrative_fallback_provider=narrative,
        input_understanding_provider=understanding,
    )
    before_world, before_events = _world_snapshot(world), history.get_events()

    failed = service.submit_input(input_request("model-failure", "Open it."))

    assert failed.status == "reasoning_unavailable"
    assert not hasattr(failed, "action_proposal")
    assert failed.no_result_state.reason is NoResultReason.NPC_REASONING_UNAVAILABLE
    assert failed.recovery_action == "clarify_or_retry"
    assert "private parser transport detail" not in repr(failed)
    assert narrative.generate_calls == narrative.review_calls == 0
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events

    recovered = service.submit_input(input_request("model-recovery", "Open the visible door."))
    assert recovered.status == "resolved"
    assert world.environment["door-1"].is_open is True
    assert len(understanding.calls) == 2
    assert output.narrative_fallbacks_for("player-1") == ()


def test_input_request_replay_is_idempotent_and_changed_content_conflicts():
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    service, world, history, _, _ = live_player(
        input_understanding_provider=understanding,
    )
    before_events = history.get_events()
    raw = input_request("same-input", "some unintelligible input")

    first = service.submit_input(raw)
    second = service.submit_input(raw)

    assert first == second
    assert len(understanding.calls) == 1
    assert history.get_events() == before_events
    assert world.environment["door-1"].is_open is False
    with pytest.raises(PermissionError, match="reused with changed content"):
        service.submit_input(input_request("same-input", "open the door"))


def test_unparseable_input_without_narrative_provider_returns_recoverable_signal(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    monkeypatch.delenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER", raising=False)
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    service, world, history, observations, output = live_player(
        input_understanding_provider=understanding,
    )
    before_world = _world_snapshot(world)
    before_events = history.get_events()
    before_observations = observations.get_by_observer("actor-1")

    outcome = service.submit_input(input_request("no-narrator", "unintelligible words"))

    assert outcome.status == "unparseable"
    assert outcome.narrative_fallback is None
    assert outcome.recovery_action == "clarify_or_retry"
    assert outcome.no_result_state.reason is NoResultReason.UNPARSEABLE_INPUT
    assert service.fallback_diagnostic("no-narrator") == "provider_unavailable"
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert observations.get_by_observer("actor-1") == before_observations


def test_input_diagnostics_are_disabled_by_default(monkeypatch, caplog):
    monkeypatch.delenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", raising=False)
    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    service, _, _, _, _ = live_player(input_understanding_provider=provider)
    assert service.submit_input(input_request("quiet-diagnostic", "private input")).status == "unparseable"
    assert not any("CW_INPUT_DIAGNOSTIC" in record.getMessage() for record in caplog.records)


def test_unparseable_diagnostic_records_unknown_reason_without_input_text(monkeypatch, caplog):
    import json

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    before = _world_snapshot(world), history.get_events()
    outcome = service.submit_input(input_request("unparseable-diagnostic", "吃掉苹果 PRIVATE_MARKER"))
    records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
               for item in caplog.records if "CW_INPUT_DIAGNOSTIC " in item.getMessage()]

    assert outcome.status == "unparseable"
    assert (_world_snapshot(world), history.get_events()) == before
    assert any(item["stage"] == "provider_invocation" and item["provider_invoked"] is True
               for item in records)
    assert any(item["stage"] == "interpretation" and item["status"] == "unparseable"
               and item["structured_response"] == "accepted"
               and item["unparseable_reason"] == "provider_unspecified"
               and item["clarification_available"] == "unknown"
               and item["stopped_before_attempt"] is True for item in records)
    assert all(item["request_id"] == "unparseable-diagnostic" for item in records)
    assert "PRIVATE_MARKER" not in " ".join(item.getMessage() for item in caplog.records)


def test_input_diagnostic_logger_failure_cannot_change_action_or_duplicate_event(monkeypatch):
    import cognitive_world.player.input_diagnostics as diagnostics

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    def failed_log(*args, **kwargs):
        raise RuntimeError("diagnostic sink unavailable")
    monkeypatch.setattr(diagnostics._LOGGER, "warning", failed_log)
    service, world, history, _, _ = live_player()
    before_events = len(history.get_events())
    result = service.submit(request("diagnostic-sink-failed"))

    assert result.status == "resolved"
    assert world.environment["door-1"].is_open is True
    assert len(history.get_events()) == before_events + 1
    assert service.submit(request("diagnostic-sink-failed")) == result
    assert len(history.get_events()) == before_events + 1


def test_input_diagnostics_distinguish_provider_rejection_from_unparseable(monkeypatch, caplog):
    import json

    class InvalidProvider:
        def understand_candidates(self, request, *, candidates):
            raise ValueError("PRIVATE_MODEL_RESPONSE")

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    service, world, history, _, _ = live_player(input_understanding_provider=InvalidProvider())
    before = _world_snapshot(world), history.get_events()
    result = service.submit_input(input_request("invalid-provider-diagnostic", "PRIVATE_INPUT"))
    records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
               for item in caplog.records if "CW_INPUT_DIAGNOSTIC " in item.getMessage()]

    assert result.status == "reasoning_unavailable"
    assert (_world_snapshot(world), history.get_events()) == before
    assert any(item["stage"] == "interpretation" and item["structured_response"] == "unavailable"
               and item["provider_returned"] is False
               and item["failure_type"] == "ValueError" for item in records)
    assert any(item["stage"] == "input_stopped" and not item["attempt_created"]
               and not item["formal_event_created"] for item in records)
    assert "PRIVATE_INPUT" not in " ".join(item.getMessage() for item in caplog.records)
    assert "PRIVATE_MODEL_RESPONSE" not in " ".join(item.getMessage() for item in caplog.records)


def test_input_diagnostics_identify_rejected_candidate_without_world_write(monkeypatch, caplog):
    import json

    class InvalidCandidateProvider:
        def understand_candidates(self, request, *, candidates):
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION, "open the door",
                                         "push the closed door", "not-an-offered-handle")

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    service, world, history, _, _ = live_player(input_understanding_provider=InvalidCandidateProvider())
    before = _world_snapshot(world), history.get_events()
    result = service.submit_input(input_request("bad-candidate-diagnostic", "open door"))
    records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
               for item in caplog.records if "CW_INPUT_DIAGNOSTIC " in item.getMessage()]

    assert result.status == "reasoning_unavailable"
    assert (_world_snapshot(world), history.get_events()) == before
    assert any(item["stage"] == "interpretation" and item["structured_response"] == "rejected"
               and item["provider_returned"] is True
               and item["failure_type"] == "PermissionError" for item in records)
    assert all("not-an-offered-handle" not in item.getMessage() for item in caplog.records)


@pytest.mark.parametrize("drafts,reviews,diagnostic", [
    ([TimeoutError("private generation detail"), TimeoutError("private generation detail")],
     [], "generation_failed:TimeoutError"),
    (["", ""], [], "invalid_output:JSONDecodeError"),
    ([_draft("暂时没有可确认的结果。"), _draft("暂时没有可确认的结果。")],
     [_reject(), _reject()], "narrative_rejected"),
])
def test_unparseable_input_fallback_failure_is_bounded_and_has_no_side_effects(
    monkeypatch, drafts, reviews, diagnostic,
):
    monkeypatch.delenv("COGNITIVEWORLD_NARRATIVE_FALLBACK_PROVIDER", raising=False)
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    narrative = ScriptedNarrativeProvider(drafts, reviews)
    service, world, history, observations, output = live_player(
        input_understanding_provider=understanding,
        narrative_fallback_provider=narrative,
    )
    before_world = _world_snapshot(world)
    before_events = history.get_events()
    before_observations = observations.get_by_observer("actor-1")

    outcome = service.submit_input(input_request("fallback-failure", "unparseable input"))

    assert outcome.status == "unparseable"
    assert outcome.narrative_fallback is None
    assert outcome.recovery_action == "clarify_or_retry"
    assert outcome.no_result_state.reason is NoResultReason.UNPARSEABLE_INPUT
    assert service.fallback_diagnostic("fallback-failure") == diagnostic
    assert narrative.generate_calls == 2
    assert narrative.review_calls == (0 if reviews == [] else 2)
    assert "private generation detail" not in repr(outcome)
    assert output.messages_for("player-1") == ()
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert observations.get_by_observer("actor-1") == before_observations


def test_ollama_input_interpreter_returns_only_closed_assessment_and_visible_targets(monkeypatch):
    import json

    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    calls = []

    def fake_post(url, body, *, timeout_seconds, maximum_bytes):
        payload = json.loads(body.decode("utf-8"))
        calls.append((url, payload, timeout_seconds, maximum_bytes))
        return json.dumps({"choices": [{"message": {"content": json.dumps({
            "status": "clarification_required",
            "intent": "open the door",
            "method": "push it",
            "missing_information": ["target"],
            "clarification_question": "Which visible object did you mean?",
        })}}]}).encode("utf-8")

    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json", fake_post)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    result = provider.understand(input_request(text="Open it."), authorized_targets=("door-1",))

    assert result.status is InputUnderstandingStatus.CLARIFICATION_REQUIRED
    assert result.missing_information == ("target",)
    assert len(calls) == 1
    assert calls[0][1]["temperature"] == 0
    assert calls[0][2] <= 10.0 and calls[0][3] <= 8_000
    user_payload = json.loads(calls[0][1]["messages"][1]["content"])
    assert user_payload == {
        "player_input": "Open it.", "authorized_targets": ["door-1"],
    }

    with pytest.raises(ValueError, match="loopback"):
        OllamaPlayerInputUnderstandingProvider("https://remote.example/v1", "local-test")


@pytest.mark.parametrize("payload,stage,code", [
    (b"\xff", "response_decode", "invalid_utf8"),
    (b"PRIVATE_BAD_ENVELOPE", "response_envelope", "invalid_json"),
    (b"{}", "response_envelope", "content_missing"),
    (b'{"choices":[{"message":{"content":"PRIVATE_BAD_CONTENT"}}]}',
     "response_content", "invalid_json"),
    (b'{"choices":[{"message":{"content":"{\\"status\\":\\"unknown\\"}"}}]}',
     "schema_validation", "status_invalid"),
    (b'{"choices":[{"message":{"content":"{\\"status\\":\\"action\\"}"}}]}',
     "schema_validation", "targeted_shape_invalid"),
    (b'{"choices":[{"message":{"content":"{\\"status\\":\\"observe\\",\\"intent\\":null,\\"method\\":null,\\"target_ref\\":null}"}}]}',
     "schema_validation", "assessment_fields_invalid"),
])
def test_ollama_input_failure_diagnostics_identify_stage_without_response_body(
    monkeypatch, caplog, payload, stage, code,
):
    import json
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json",
                        lambda *args, **kwargs: payload)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    with pytest.raises(ValueError):
        provider.understand_candidates(input_request("wire-failure", "PRIVATE_INPUT"), candidates=())
    records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
               for item in caplog.records if "CW_INPUT_DIAGNOSTIC " in item.getMessage()]
    assert records == [{"schema": "desktop-input-diagnostic/v1", "request_id": "wire-failure",
                        "stage": "provider_failure", "failure_stage": stage, "failure_code": code}]
    assert "PRIVATE_INPUT" not in caplog.text
    assert "PRIVATE_BAD" not in caplog.text


@pytest.mark.parametrize("failure,expected_code,expected_status", [
    (ValueError("Ollama response exceeded the transport bound"), "response_too_large", None),
    (ValueError("PRIVATE_TRANSPORT_DETAIL"), "transport_validation_failed", None),
    (ConnectionError("Ollama returned HTTP 400"), "http_error", 400),
    (TimeoutError("PRIVATE_TIMEOUT"), "timeout", None),
])
def test_ollama_input_transport_diagnostics_keep_original_failure_and_safe_http_status(
    monkeypatch, caplog, failure, expected_code, expected_status,
):
    import json
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    def failing_post(*args, **kwargs):
        raise failure
    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json",
                        failing_post)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    with pytest.raises(type(failure)):
        provider.understand_candidates(input_request("transport-failure", "PRIVATE_INPUT"), candidates=())
    records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
               for item in caplog.records if "CW_INPUT_DIAGNOSTIC " in item.getMessage()]
    assert len(records) == 1
    assert records[0]["failure_stage"] == "http_transport"
    assert records[0]["failure_code"] == expected_code
    assert records[0].get("http_status") == expected_status
    assert "PRIVATE_INPUT" not in caplog.text
    assert "PRIVATE_TRANSPORT_DETAIL" not in caplog.text
    assert "PRIVATE_TIMEOUT" not in caplog.text


def test_malformed_ollama_candidate_response_stops_before_attempt_and_event(monkeypatch, caplog):
    import json
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    payload = json.dumps({"choices": [{"message": {"content": json.dumps({
        "status": "action", "intent": "open the door",
    })}}]}).encode()
    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json",
                        lambda *args, **kwargs: payload)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    before = _world_snapshot(world), history.get_events()
    result = service.submit_input(input_request("malformed-wire", "PRIVATE_INPUT"))
    records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
               for item in caplog.records if "CW_INPUT_DIAGNOSTIC " in item.getMessage()]

    assert result.status == "reasoning_unavailable"
    assert service.fallback_diagnostic("malformed-wire") == "input_understanding_failed:ValueError"
    assert (_world_snapshot(world), history.get_events()) == before
    assert any(item["stage"] == "provider_failure"
               and item["failure_stage"] == "schema_validation"
               and item["failure_code"] == "targeted_shape_invalid" for item in records)
    assert any(item["stage"] == "interpretation" and item["provider_returned"] is False
               and item["structured_response"] == "unavailable" for item in records)
    assert any(item["stage"] == "input_stopped" and not item["attempt_created"]
               and not item["formal_event_created"] for item in records)
    assert "PRIVATE_INPUT" not in caplog.text


def test_ollama_provider_failure_diagnostics_remain_off_by_default(monkeypatch, caplog):
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    monkeypatch.delenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", raising=False)
    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json",
                        lambda *args, **kwargs: b"not-json")
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    with pytest.raises(ValueError):
        provider.understand_candidates(input_request("quiet-wire-failure", "PRIVATE_INPUT"),
                                       candidates=())
    assert "CW_INPUT_DIAGNOSTIC" not in caplog.text


def test_candidate_interpreter_method_must_match_installed_causal_adapter_offer(monkeypatch):
    import json
    from cognitive_world.player.input_understanding import (
        AuthorizedTargetCandidate, OllamaPlayerInputUnderstandingProvider,
    )

    calls = []
    response = {"status": "action", "intent": "open", "method": "open it",
                "target_ref": "candidate-1"}

    def fake_post(url, body, *, timeout_seconds, maximum_bytes):
        calls.append(json.loads(body.decode("utf-8")))
        return json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()

    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json", fake_post)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    request = PlayerInputRequest("candidate-method", "session-1", "world-1", "打开门")
    candidate = AuthorizedTargetCandidate(
        "candidate-1", "门处于关闭状态", "door", ("push the door", "pull the door"),
    )

    with pytest.raises(PermissionError, match="method not offered"):
        provider.understand_candidates(request, candidates=(candidate,))
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert sent["candidates"][0]["supported_methods"] == ["push the door", "pull the door"]

    response["method"] = "push the door"
    result = provider.understand_candidates(request, candidates=(candidate,))
    assert result.method == "push the door"


def test_candidate_without_installed_operation_cannot_become_executable(monkeypatch):
    import json
    from cognitive_world.player.input_understanding import (
        AuthorizedTargetCandidate, OllamaPlayerInputUnderstandingProvider,
    )

    def fake_post(url, body, *, timeout_seconds, maximum_bytes):
        value = {"status": "action", "intent": "change", "method": "change it",
                 "target_ref": "candidate-1"}
        return json.dumps({"choices": [{"message": {"content": json.dumps(value)}}]}).encode()

    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json", fake_post)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "local-test")
    request = PlayerInputRequest("unsupported-method", "session-1", "world-1", "change it")
    candidate = AuthorizedTargetCandidate("candidate-1", "observed item", "object", ())
    with pytest.raises(PermissionError, match="method not offered"):
        provider.understand_candidates(request, candidates=(candidate,))


@pytest.mark.parametrize("response", [
    {"status": "observe", "intent": "inspect", "method": None},
    {"status": "observe", "intent": None, "method": None, "target_ref": None},
    {"status": "observe", "intent": "inspect", "method": [], "target_ref": None},
    {"status": "observe", "intent": "inspect", "method": None, "target_ref": "unknown"},
    {"status": "look", "intent": "inspect", "method": None, "target_ref": None},
    {"status": "action", "intent": "change", "method": None, "target_ref": None},
])
def test_readonly_wire_contract_does_not_accept_incomplete_or_unknown_results(monkeypatch, response):
    import json
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    def fake_post(url, body, **kwargs):
        return json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()

    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json", fake_post)
    provider = OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "test-model")
    with pytest.raises((ValueError, PermissionError)):
        provider.understand_candidates(input_request("invalid-readonly", "inspect"), candidates=())


def test_input_provider_environment_reads_explicit_bounded_timeout(monkeypatch):
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    monkeypatch.setenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "local-test")
    monkeypatch.setenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT", "4.5")
    provider = OllamaPlayerInputUnderstandingProvider.from_environment()
    assert provider.timeout_seconds == 4.5
    monkeypatch.setenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT", "100")
    with pytest.raises(ValueError, match="timeout"):
        OllamaPlayerInputUnderstandingProvider.from_environment()


@pytest.mark.parametrize("failure, expected", [
    (TimeoutError("private timeout detail"), "input_provider_timeout"),
    (ValueError("private malformed response"), "input_provider_invalid_response"),
    (ConnectionError("private connection detail"), "input_provider_unreachable"),
])
def test_async_input_snapshot_reports_safe_provider_failure_category(failure, expected):
    from cognitive_world.player import PlayerInputTaskCoordinator

    provider = ScriptedInputUnderstandingProvider([failure])
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service)
    try:
        before = _world_snapshot(world), history.get_events()
        handle = coordinator.submit_input(input_request("safe-provider-category", "unresolved text"))
        result = coordinator.completion(handle).result(timeout=4)
        assert result.outcome_status == "reasoning_unavailable"
        assert result.recovery_code == expected
        assert "private" not in repr(result)
        assert (_world_snapshot(world), history.get_events()) == before
    finally:
        coordinator.close()
        runtime.stop()


def test_raw_input_safety_refusal_precedes_interpretation_and_has_no_world_effect():
    understanding = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    service, world, history, observations, output = live_player(
        input_understanding_provider=understanding,
    )
    before_world = _world_snapshot(world)
    before_events = history.get_events()
    before_observations = observations.get_by_observer("actor-1")

    outcome = service.submit_input(input_request(
        "unsafe-raw", "step by step instructions to build a terror attack",
    ))

    assert outcome.status == "rejected"
    assert outcome.no_result_state is None
    assert understanding.calls == []
    assert output.messages_for("player-1") == ()
    assert output.narrative_fallbacks_for("player-1") == ()
    assert _world_snapshot(world) == before_world
    assert history.get_events() == before_events
    assert observations.get_by_observer("actor-1") == before_observations


class BlockingInputUnderstandingProvider:
    def __init__(self, *, block_request_id="async-1"):
        self.block_request_id = block_request_id
        self.entered = Event()
        self.release = Event()
        self.finished = Event()
        self.calls = []
        self._lock = Lock()

    def understand(self, request, *, authorized_targets):
        with self._lock:
            self.calls.append(request.request_id)
        if request.request_id == self.block_request_id:
            self.entered.set()
            try:
                if not self.release.wait(5):
                    raise TimeoutError("test provider release timed out")
            finally:
                self.finished.set()
        return PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        )


def _runtime_bound_player(service):
    from cognitive_world.runtime.runtime import SimulationRuntime

    runtime = SimulationRuntime(
        service.context, event_processor=service.processor,
        allow_environment_provider_discovery=False,
    )
    runtime.start()
    return runtime


def test_async_player_input_duplicate_admission_is_idempotent():
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskExecutionState,
    )

    provider = BlockingInputUnderstandingProvider(block_request_id="async-idempotent")
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service)
    try:
        request_value = input_request("async-idempotent", "Open the door.")
        before = len(history.get_events())
        first = coordinator.submit_input(request_value)
        duplicate = coordinator.submit_input(request_value)
        assert duplicate == first
        assert provider.entered.wait(2)
        abandoned_view = coordinator.completion(first)
        assert not abandoned_view.done()
        assert abandoned_view.cancel() is True
        assert len(history.get_events()) == before
        provider.release.set()
        completed = coordinator.completion(first).result(timeout=4)
        assert completed.execution is PlayerTaskExecutionState.COMPLETED
        assert completed.outcome_status == "resolved"
        assert len(provider.calls) == 1
        assert len(history.get_events()) == before + 1
        assert world.environment["door-1"].is_open is True
        with pytest.raises(PermissionError, match="changed content"):
            coordinator.submit_input(input_request("async-idempotent", "Close the door."))
    finally:
        provider.release.set()
        coordinator.close()
        runtime.stop()


def test_async_player_input_serializes_same_runtime_admission_order():
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskExecutionState,
    )

    provider = BlockingInputUnderstandingProvider(block_request_id="async-first")
    service, _, history, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service, timeout_seconds=4)
    try:
        before = len(history.get_events())
        first = coordinator.submit_input(input_request("async-first", "Open it."))
        assert provider.entered.wait(2)
        second = coordinator.submit_input(input_request("async-second", "Open it too."))
        assert provider.calls == ["async-first"]
        provider.release.set()
        first_result = coordinator.completion(first).result(timeout=4)
        second_result = coordinator.completion(second).result(timeout=4)
        assert first_result.execution is PlayerTaskExecutionState.COMPLETED
        assert second_result.execution is PlayerTaskExecutionState.COMPLETED
        assert provider.calls == ["async-first", "async-second"]
        assert len(history.get_events()) == before + 2
    finally:
        provider.release.set()
        coordinator.close()
        runtime.stop()


def test_async_player_input_captures_target_authorization_when_worker_starts():
    from cognitive_world.player import PlayerInputTaskCoordinator, PlayerTaskExecutionState

    provider = BlockingInputUnderstandingProvider(block_request_id="async-auth-first")
    provider.authorizations = []

    def understand(request_value, *, authorized_targets):
        provider.calls.append(request_value.request_id)
        provider.authorizations.append(tuple(authorized_targets))
        if request_value.request_id == "async-auth-first":
            provider.entered.set()
            try:
                assert provider.release.wait(4)
            finally:
                provider.finished.set()
            return PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE)
        return PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE)

    provider.understand = understand
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    allowed = {"door-1"}
    service.available_targets = lambda: tuple(sorted(allowed))
    coordinator = PlayerInputTaskCoordinator(service, timeout_seconds=4)
    try:
        before = history.get_events()
        first = coordinator.submit_input(input_request("async-auth-first", "Unclear input."))
        assert provider.entered.wait(2)
        second = coordinator.submit_input(input_request("async-auth-second", "Open the late door."))
        allowed.add("late-door")
        provider.release.set()
        first_result = coordinator.completion(first).result(timeout=3)
        second_result = coordinator.completion(second).result(timeout=3)
        assert first_result.execution is PlayerTaskExecutionState.COMPLETED
        assert second_result.execution is PlayerTaskExecutionState.COMPLETED
        assert provider.authorizations == [("door-1",), ("door-1", "late-door")]
        assert second_result.outcome_status == "unparseable"
        assert world.environment["door-1"].is_open is False
        assert history.get_events() == before
    finally:
        provider.release.set()
        coordinator.close()
        runtime.stop()


def test_async_admission_returns_while_authorized_target_projection_is_blocked():
    from cognitive_world.player import PlayerInputTaskCoordinator, PlayerTaskExecutionState

    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE),
    ])
    service, _, _, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service, timeout_seconds=4)
    projection_entered = Event()
    release_projection = Event()
    original_targets = service.available_targets

    def blocked_targets():
        projection_entered.set()
        assert release_projection.wait(3)
        return original_targets()

    service.available_targets = blocked_targets
    accepted = Event()
    result = []

    def submit():
        result.append(coordinator.submit_input(input_request(
            "async-admission-before-projection", "Unclear input.",
        )))
        accepted.set()

    thread = Thread(target=submit, daemon=True)
    try:
        thread.start()
        assert accepted.wait(2)
        handle = result[0]
        assert projection_entered.wait(2)
        # Admission returned even though the authorized retrieval is still
        # blocked in the background worker.
        assert coordinator.get_status(handle).execution.value == "running"
        release_projection.set()
        completed = coordinator.completion(handle).result(timeout=3)
        assert completed.execution is PlayerTaskExecutionState.COMPLETED
        assert [call[0].request_id for call in provider.calls] == [
            "async-admission-before-projection",
        ]
    finally:
        release_projection.set()
        thread.join(timeout=2)
        coordinator.close()
        runtime.stop()


@pytest.mark.parametrize("termination", ["cancel", "timeout", "shutdown"])
def test_async_player_input_uncommitted_late_result_cannot_write(termination):
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskExecutionState,
    )

    provider = BlockingInputUnderstandingProvider(block_request_id=f"async-{termination}")
    service, world, history, _, output = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(
        service, timeout_seconds=0.1 if termination == "timeout" else 4,
    )
    try:
        before_world = _world_snapshot(world)
        before_events = history.get_events()
        handle = coordinator.submit_input(input_request(f"async-{termination}", "Open it."))
        assert provider.entered.wait(2)
        if termination == "cancel":
            assert coordinator.cancel(handle) is True
            expected = PlayerTaskExecutionState.CANCELLED
        elif termination == "timeout":
            expected = PlayerTaskExecutionState.EXPIRED
            assert coordinator.completion(handle).result(timeout=2).execution is expected
        else:
            coordinator.close()
            expected = PlayerTaskExecutionState.CANCELLED
            assert coordinator.completion(handle).result(timeout=2).execution is expected
        assert coordinator.get_status(handle).execution is expected
        provider.release.set()
        assert provider.finished.wait(2)
        assert _world_snapshot(world) == before_world
        assert history.get_events() == before_events
        assert output.messages_for("player-1") == ()
    finally:
        provider.release.set()
        coordinator.close()
        runtime.stop()


def test_async_player_input_restore_generation_invalidates_original_task_permit():
    from cognitive_world.player import PlayerInputTaskCoordinator, PlayerTaskExecutionState

    provider = BlockingInputUnderstandingProvider(block_request_id="async-old-generation")
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service, timeout_seconds=4)
    try:
        before = history.get_events()
        handle = coordinator.submit_input(input_request("async-old-generation", "Open it."))
        assert provider.entered.wait(2)
        runtime.freeze_writes()
        runtime.unfreeze_writes()
        provider.release.set()
        result = coordinator.completion(handle).result(timeout=3)
        assert result.execution is PlayerTaskExecutionState.STALE
        assert history.get_events() == before
        assert world.environment["door-1"].is_open is False
    finally:
        provider.release.set()
        coordinator.close()
        runtime.stop()


def test_old_async_task_cannot_write_into_a_new_runtime():
    from cognitive_world.player import PlayerInputTaskCoordinator, PlayerTaskExecutionState

    provider = BlockingInputUnderstandingProvider(block_request_id="async-old-task")
    old_service, old_world, old_history, _, _ = live_player(
        input_understanding_provider=provider,
    )
    old_runtime = _runtime_bound_player(old_service)
    coordinator = PlayerInputTaskCoordinator(old_service, timeout_seconds=4)
    new_service, new_world, new_history, _, _ = live_player()
    new_runtime = _runtime_bound_player(new_service)
    try:
        old_before = old_history.get_events()
        new_before = new_history.get_events()
        handle = coordinator.submit_input(input_request("async-old-task", "Open it."))
        assert provider.entered.wait(2)
        old_runtime.freeze_writes()
        provider.release.set()
        result = coordinator.completion(handle).result(timeout=3)
        assert result.execution is PlayerTaskExecutionState.STALE
        assert old_history.get_events() == old_before
        assert new_history.get_events() == new_before
        assert old_world.environment["door-1"].is_open is False
        assert new_world.environment["door-1"].is_open is False
    finally:
        provider.release.set()
        coordinator.close()
        old_runtime.stop()
        new_runtime.stop()


def test_async_player_presentation_retry_does_not_repeat_interpretation_or_event(monkeypatch):
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskDeliveryState,
        PlayerTaskExecutionState,
    )

    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        ),
    ])
    service, world, history, _, output = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service)
    original_send = output.send

    def fail_once(batch):
        output.send = original_send
        raise ConnectionError("controlled presentation interruption")

    monkeypatch.setattr(output, "send", fail_once)
    try:
        before = len(history.get_events())
        handle = coordinator.submit_input(input_request("async-delivery", "Open the door."))
        first = coordinator.completion(handle).result(timeout=4)
        assert first.execution is PlayerTaskExecutionState.COMPLETED
        assert first.delivery is PlayerTaskDeliveryState.RETRYABLE
        event_id = history.get_events()[-1].id
        before_world = _world_snapshot(world)

        def forbidden_replay(_event):
            raise AssertionError("presentation retry must not re-dispatch a committed Event")

        monkeypatch.setattr(service.processor, "dispatch_with_evidence", forbidden_replay)
        retried = coordinator.retry_presentation(handle).result(timeout=4)
        assert retried.execution is PlayerTaskExecutionState.COMPLETED
        assert retried.delivery is PlayerTaskDeliveryState.DELIVERED
        assert len(history.get_events()) == before + 1
        assert history.get_events()[-1].id == event_id
        assert _world_snapshot(world) == before_world
        assert len(provider.calls) == 1
        assert len(output.messages_for("player-1")) == 1
    finally:
        coordinator.close()
        runtime.stop()


def test_async_presentation_retry_is_serialized_with_runtime_generation_advance(monkeypatch):
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskDeliveryState,
        PlayerTaskExecutionState,
    )

    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        ),
    ])
    service, _, history, _, output = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service)
    original_send = output.send
    send_entered = Event()
    release_send = Event()
    generation_advanced = Event()
    freeze_thread = None

    def fail_first_send(batch):
        output.send = original_send
        raise ConnectionError("controlled initial presentation failure")

    monkeypatch.setattr(output, "send", fail_first_send)
    try:
        before_events = history.get_events()
        handle = coordinator.submit_input(input_request("async-delivery-generation", "Open the door."))
        failed_delivery = coordinator.completion(handle).result(timeout=4)
        assert failed_delivery.execution is PlayerTaskExecutionState.COMPLETED
        assert failed_delivery.delivery is PlayerTaskDeliveryState.RETRYABLE
        assert len(history.get_events()) == len(before_events) + 1

        def blocked_send(batch):
            send_entered.set()
            assert release_send.wait(3)
            original_send(batch)

        monkeypatch.setattr(output, "send", blocked_send)

        def advance_generation():
            runtime.freeze_writes()
            generation_advanced.set()
            runtime.unfreeze_writes()

        retry = coordinator.retry_presentation(handle)
        assert send_entered.wait(2)
        freeze_thread = Thread(target=advance_generation, daemon=True)
        freeze_thread.start()
        # The gateway is paused inside the original-permit read scope. A
        # generation change must wait until this one delivery linearizes.
        freeze_thread.join(timeout=0.05)
        assert freeze_thread.is_alive()
        assert not generation_advanced.is_set()

        release_send.set()
        retried = retry.result(timeout=4)
        freeze_thread.join(timeout=2)
        assert not freeze_thread.is_alive()
        assert generation_advanced.is_set()
        assert retried.execution is PlayerTaskExecutionState.COMPLETED
        assert retried.delivery is PlayerTaskDeliveryState.DELIVERED
        assert len(history.get_events()) == len(before_events) + 1
        assert len(provider.calls) == 1
        assert len(output.messages_for("player-1")) == 1
    finally:
        release_send.set()
        if freeze_thread is not None:
            freeze_thread.join(timeout=2)
        coordinator.close()
        runtime.stop()


def test_async_presentation_retry_is_rejected_after_runtime_generation_advance(monkeypatch):
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskDeliveryState,
        PlayerTaskExecutionState,
    )

    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        ),
    ])
    service, _, history, _, output = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service)
    original_send = output.send

    def fail_first_send(batch):
        output.send = original_send
        raise ConnectionError("controlled initial presentation failure")

    monkeypatch.setattr(output, "send", fail_first_send)
    try:
        before_events = len(history.get_events())
        handle = coordinator.submit_input(input_request("async-delivery-stale", "Open the door."))
        completed = coordinator.completion(handle).result(timeout=4)
        assert completed.delivery is PlayerTaskDeliveryState.RETRYABLE
        assert len(history.get_events()) == before_events + 1

        runtime.freeze_writes()
        runtime.unfreeze_writes()
        retry = coordinator.retry_presentation(handle).result(timeout=1)
        assert retry.execution is PlayerTaskExecutionState.COMPLETED
        assert retry.delivery is PlayerTaskDeliveryState.STALE
        assert retry.recovery_code == "runtime_generation_changed"
        assert len(history.get_events()) == before_events + 1
        assert len(provider.calls) == 1
        assert output.messages_for("player-1") == ()
    finally:
        coordinator.close()
        runtime.stop()


def test_async_presentation_retry_uses_service_then_runtime_lock_order(monkeypatch):
    from cognitive_world.player import PlayerInputTaskCoordinator, PlayerTaskDeliveryState

    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        ),
    ])
    service, _, _, _, output = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service)
    original_send = output.send
    resolution_entered = Event()
    release_resolution = Event()
    sync_finished = Event()
    retry_entered = Event()
    retry_result = []
    sync_errors = []

    def fail_first_send(batch):
        output.send = original_send
        raise ConnectionError("controlled initial presentation failure")

    monkeypatch.setattr(output, "send", fail_first_send)
    try:
        handle = coordinator.submit_input(input_request("async-lock-order", "Open the door."))
        assert coordinator.completion(handle).result(timeout=4).delivery is PlayerTaskDeliveryState.RETRYABLE

        def paused_resolution(*args, **kwargs):
            resolution_entered.set()
            assert release_resolution.wait(3)
            raise RuntimeError("controlled pre-commit stop")

        monkeypatch.setattr(service.resolution_flow, "execute_with_result", paused_resolution)

        def synchronous_request():
            try:
                with service.processor.write_fence.operation():
                    service.submit(PlayerActionRequest(
                        "sync-during-delivery", "session-1", "world-1",
                        "open the door", "push the closed door", "door-1",
                    ))
            except RuntimeError as exc:
                if str(exc) != "controlled pre-commit stop":
                    sync_errors.append(exc)
            except Exception as exc:
                sync_errors.append(exc)
            finally:
                sync_finished.set()

        sync_thread = Thread(target=synchronous_request, daemon=True)
        sync_thread.start()
        assert resolution_entered.wait(2)

        original_retry_scope = service._retry_input_presentation_in_runtime_snapshot

        def observe_retry_start(request):
            retry_entered.set()
            return original_retry_scope(request)

        monkeypatch.setattr(service, "_retry_input_presentation_in_runtime_snapshot", observe_retry_start)
        retry = coordinator.retry_presentation(handle)
        assert retry_entered.wait(2)
        release_resolution.set()
        assert sync_finished.wait(2)
        sync_thread.join(timeout=1)
        assert not sync_thread.is_alive()
        assert sync_errors == []
        retry_result.append(retry.result(timeout=3))
        assert retry_result[0].delivery is PlayerTaskDeliveryState.DELIVERED
        assert len(output.messages_for("player-1")) == 1
        assert len(provider.calls) == 1
    finally:
        release_resolution.set()
        coordinator.close()
        runtime.stop()


def test_async_close_resolves_queued_presentation_retry_as_pending_recovery(monkeypatch):
    from cognitive_world.player import (
        PlayerInputTaskCoordinator, PlayerTaskDeliveryState,
        PlayerTaskExecutionState,
    )

    class SecondRequestBlockingProvider:
        def __init__(self):
            self.entered = Event()
            self.release = Event()
            self.finished = Event()
            self.calls = []

        def understand(self, request_value, *, authorized_targets):
            self.calls.append(request_value.request_id)
            if request_value.request_id == "async-close-running":
                self.entered.set()
                try:
                    assert self.release.wait(3)
                finally:
                    self.finished.set()
            return PlayerInputAssessment(
                InputUnderstandingStatus.ACTION,
                intent="open the door", method="push the closed door", target_ref="door-1",
            )

    provider = SecondRequestBlockingProvider()
    service, world, history, _, output = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service, timeout_seconds=4)
    original_send = output.send

    def fail_first_send(batch):
        output.send = original_send
        raise ConnectionError("controlled initial presentation failure")

    monkeypatch.setattr(output, "send", fail_first_send)
    try:
        before_events = len(history.get_events())
        first = coordinator.submit_input(input_request("async-close-retryable", "Open it."))
        first_result = coordinator.completion(first).result(timeout=4)
        assert first_result.delivery is PlayerTaskDeliveryState.RETRYABLE
        committed_count = len(history.get_events())
        assert committed_count == before_events + 1

        second = coordinator.submit_input(input_request("async-close-running", "Open it again."))
        assert provider.entered.wait(2)
        retry = coordinator.retry_presentation(first)
        coordinator.close()

        # A queued delivery job cancelled by executor shutdown must still
        # complete its public future and expose the undelivered state.
        retry_result = retry.result(timeout=1)
        assert retry_result.execution is PlayerTaskExecutionState.COMPLETED
        assert retry_result.delivery is PlayerTaskDeliveryState.PENDING
        assert retry_result.recovery_code == "coordinator_closed"
        assert coordinator.get_status(second).execution is PlayerTaskExecutionState.CANCELLED

        provider.release.set()
        assert provider.finished.wait(2)
        assert len(history.get_events()) == committed_count
        assert world.environment["door-1"].is_open is True
        assert output.messages_for("player-1") == ()
    finally:
        provider.release.set()
        coordinator.close()
        runtime.stop()


def test_async_cancel_after_commit_boundary_is_too_late_and_does_not_rollback(monkeypatch):
    from cognitive_world.player import PlayerInputTaskCoordinator, PlayerTaskExecutionState

    provider = ScriptedInputUnderstandingProvider([
        PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the door", method="push the closed door", target_ref="door-1",
        ),
    ])
    service, world, history, _, _ = live_player(input_understanding_provider=provider)
    runtime = _runtime_bound_player(service)
    coordinator = PlayerInputTaskCoordinator(service, timeout_seconds=4)
    commit_entered = Event()
    commit_release = Event()
    original_process = service.processor.process_with_evidence

    def paused_commit(*args, **kwargs):
        commit_entered.set()
        assert commit_release.wait(3)
        return original_process(*args, **kwargs)

    monkeypatch.setattr(service.processor, "process_with_evidence", paused_commit)
    try:
        before = len(history.get_events())
        handle = coordinator.submit_input(input_request("async-commit-won", "Open the door."))
        assert commit_entered.wait(2)
        cancel_result = []
        cancel_thread = Thread(
            target=lambda: cancel_result.append(coordinator.cancel(handle)), daemon=True,
        )
        cancel_thread.start()
        commit_release.set()
        cancel_thread.join(2)
        assert not cancel_thread.is_alive()
        assert cancel_result == [False]
        result = coordinator.completion(handle).result(timeout=4)
        assert result.execution is PlayerTaskExecutionState.COMPLETED
        assert world.environment["door-1"].is_open is True
        assert len(history.get_events()) == before + 1
    finally:
        commit_release.set()
        coordinator.close()
        runtime.stop()
