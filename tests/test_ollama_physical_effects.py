"""Untrusted semantic physical suggestions through the real causal boundary."""

import json
import os

import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution import (
    ActionInterpreter, ActionResolutionFlow, EffectParticipant,
    MethodBasedResolutionEngine, OllamaPhysicalEffectSuggestionProvider,
    PhysicalEffectSuggestion, SuggestedPhysicalChange,
    SupportedPhysicalEffectTranslator, CompositeCausalAssessmentPolicy,
)
from cognitive_world.runtime.clock import SimulationClock


def _case(*, method="rotate the hinged panel inward", target="object:door-one", extras=()):
    world = WorldState()
    world.load_environment_data("door-one", DoorState("door-one", "room-one", False, False, True))
    world.load_entity(Entity(
        "actor-one", "character", sensory_capabilities=("sight",),
        physical_capabilities=("manual_manipulation",),
    ))
    world.load_location("actor-one", "room-one")
    proposal = ActionProposal(
        "proposal-one", "actor-one", "interact with the panel",
        [target, *extras], {"method": method},
    )
    attempt = ActionInterpreter().interpret(proposal, actor_id="actor-one")
    return world, attempt


def _model_response(*, participants=None, changes=None, extra=None):
    if participants is None:
        participants = [
            {"reference": "agent:actor-one", "relation": "original actor and direct cause"},
            {"reference": "object:door-one", "relation": "possible affected object"},
        ]
    if changes is None:
        changes = [{
            "effect_type": "door_state_changed", "affected_refs": ["object:door-one"],
            "required_conditions": [], "unknown_conditions": [], "participants": participants,
        }]
    else:
        for change in changes:
            change.setdefault("participants", participants)
    payload = {"participants": participants, "changes": changes}
    if extra:
        payload.update(extra)
    return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()


def _provider(monkeypatch, response):
    from cognitive_world.dialogue import ollama

    calls = []

    def transport(base_url, body, *, timeout_seconds, maximum_bytes):
        calls.append(json.loads(body))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(ollama, "_post_loopback_json", transport)
    return OllamaPhysicalEffectSuggestionProvider("http://127.0.0.1:11434/v1", "local-model"), calls


def test_open_language_suggestion_is_rechecked_and_committed_by_existing_event_chain(monkeypatch):
    world, base = _case()
    attempt = Attempt(
        base.attempt_id, base.agent_id, base.action_proposal_id, base.action_type,
        base.target_refs, base.parameters, base.metadata, initiator_id="requester-one",
    )
    provider, calls = _provider(monkeypatch, _model_response())
    clock = SimulationClock(4)
    history = EventHistory()
    observations = ObservationStore()
    registry = AgentRegistry()
    registry.register(RuntimeAgent("actor-one"))
    flow = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world, effect_suggestion_provider=provider),
        world_state=world,
    )

    result, event = flow.execute_with_result(attempt, simulation_tick=clock.capture())

    assert len(calls) == 1
    assert calls[0]["messages"][1]["content"].find("rotate the hinged panel") >= 0
    assert "world_state" not in calls[0]["messages"][1]["content"]
    assert result.confirmed and result.success and event is not None
    assert world.environment["door-one"].is_open is False
    assert event.cause == attempt.attempt_id
    assert event.metadata["initiator_id"] == "requester-one"
    assert event.metadata["attempt_fingerprint"] == attempt.content_fingerprint()
    assert event.metadata["physical_effect_provenance"][0]["proposed_participants"]
    assert all(
        item["status"] == "model_proposed_unverified"
        for item in event.metadata["physical_effect_provenance"][0]["proposed_participants"]
    )
    processor = EventProcessor(
        world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
    )
    processor.dispatch_with_evidence(event)
    assert world.environment["door-one"].is_open is True
    assert observations.get_by_observer("actor-one")[0].source_event_id == event.id
    processor.dispatch_with_evidence(event)
    assert len(history.get_events()) == 1


def test_multiple_participants_and_changes_are_representable_but_not_confirmed(monkeypatch):
    world, base = _case(
        method="I throw the stone; it may strike the other person",
        extras=("object:stone-one", "agent:recipient-one"),
    )
    world.load_entity(Entity("stone-one", "tool", owner_id="actor-one"))
    world.load_entity(Entity("recipient-one", "character"))
    attempt = Attempt(
        base.attempt_id, base.agent_id, base.action_proposal_id, base.action_type,
        base.target_refs, base.parameters, base.metadata, initiator_id="requester-one",
    )
    participants = [
        {"reference": "agent:actor-one", "relation": "original actor"},
        {"reference": "object:stone-one", "relation": "direct physical cause"},
        {"reference": "agent:recipient-one", "relation": "potential recipient"},
        {"reference": "object:stone-one", "relation": "moving participant"},
    ]
    changes = [
        {"effect_type": "object_motion", "affected_refs": ["object:stone-one"],
         "required_conditions": ["stone is actually held"], "unknown_conditions": ["trajectory not known"],
         "participants": [
             {"reference": "agent:actor-one", "relation": "original actor"},
             {"reference": "object:stone-one", "relation": "direct cause"},
         ]},
        {"effect_type": "physiological_effect", "affected_refs": ["agent:recipient-one"],
         "required_conditions": ["collision must be established"],
         "unknown_conditions": ["injury severity not established"],
         "participants": [
             {"reference": "object:stone-one", "relation": "potential cause"},
             {"reference": "agent:recipient-one", "relation": "possible recipient"},
         ]},
    ]
    provider, _ = _provider(monkeypatch, _model_response(participants=participants, changes=changes))
    from cognitive_world.resolution.interaction_context import InteractionStateAggregator

    clock = SimulationClock(2)
    context = InteractionStateAggregator().aggregate(attempt, world, clock.capture()).physical
    suggestion = provider.suggest_effects(attempt, context)
    assert suggestion.actor_id == "actor-one"
    assert suggestion.initiator_id == "requester-one"
    assert suggestion.participants[1].reference == suggestion.participants[3].reference
    assert suggestion.changes[0].participants[1].relation == "direct cause"
    assert suggestion.changes[1].participants[1].relation == "possible recipient"
    assert suggestion.changes[0].affected_refs != suggestion.changes[1].affected_refs
    result = MethodBasedResolutionEngine(
        world_state=world, simulation_time=clock.capture(), effect_suggestion_provider=provider,
    ).resolve(attempt)
    assert not result.confirmed and result.outcome == "unresolved"
    assert world.environment["door-one"].is_open is False


def test_confirmed_collision_fact_does_not_authorize_unproved_injury(monkeypatch):
    world, attempt = _case(
        method="the moving object collided; injury is only possible",
        extras=("object:stone-one", "agent:recipient-one"),
    )
    world.load_fact("collision-record", {
        "source": "object:stone-one", "recipient": "agent:recipient-one",
    })
    changes = [
        {"effect_type": "collision", "affected_refs": ["object:stone-one"],
         "required_conditions": ["impact evidence"], "unknown_conditions": [],
         "participants": [
             {"reference": "object:stone-one", "relation": "possible direct cause"},
             {"reference": "agent:recipient-one", "relation": "possible contact target"},
         ]},
        {"effect_type": "physiological_effect", "affected_refs": ["agent:recipient-one"],
         "required_conditions": ["confirmed collision"],
         "unknown_conditions": ["injury severity is not established"],
         "participants": [
             {"reference": "object:stone-one", "relation": "possible cause"},
             {"reference": "agent:recipient-one", "relation": "potential recipient"},
         ]},
    ]
    provider, _ = _provider(monkeypatch, _model_response(changes=changes))
    clock = SimulationClock(3)
    result, event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world, effect_suggestion_provider=provider),
        world_state=world,
    ).execute_with_result(attempt, simulation_tick=clock.capture())
    assert world.facts["collision-record"]["source"] == "object:stone-one"
    assert not result.confirmed and result.outcome == "unresolved" and event is None
    assert world.environment["door-one"].is_open is False


@pytest.mark.parametrize("response", [
    _model_response(participants=[{"reference": "agent:unknown", "relation": "direct cause"}]),
    _model_response(extra={"event": "forged"}),
    TimeoutError("local model unavailable"),
])
def test_unverified_model_identity_authority_or_timeout_cannot_confirm(monkeypatch, response):
    world, attempt = _case()
    provider, _ = _provider(monkeypatch, response)
    clock = SimulationClock(3)
    result, event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world, effect_suggestion_provider=provider),
        world_state=world,
    ).execute_with_result(attempt, simulation_tick=clock.capture())
    assert not result.confirmed and result.outcome == "unresolved" and event is None
    assert world.environment["door-one"].is_open is False


def test_stale_suggestion_and_unknown_target_remain_unresolved():
    world, attempt = _case()
    clock = SimulationClock(5)

    class StaleProvider:
        def suggest_effects(self, current, context):
            return PhysicalEffectSuggestion(
                current.attempt_id, "0" * 64, current.agent_id, current.initiator_id,
                current.target, context.simulation_tick, context.source_refs,
                (EffectParticipant("agent:actor-one", "actor"),),
                (SuggestedPhysicalChange("door_state_changed", ("object:door-one",)),),
            )

    result = MethodBasedResolutionEngine(
        world_state=world, simulation_time=clock.capture(),
        effect_suggestion_provider=StaleProvider(),
    ).resolve(attempt)
    assert result.outcome == "unresolved" and not result.confirmed
    unknown = Attempt(
        "attempt-unknown", "actor-one", "proposal-unknown", "interact",
        ["object:missing"], {"method": "rotate the unknown panel"},
    )
    result = MethodBasedResolutionEngine(
        world_state=world, simulation_time=clock.capture(),
        effect_suggestion_provider=StaleProvider(),
    ).resolve(unknown)
    assert result.outcome == "unresolved" and not result.confirmed


def test_open_semantic_effect_reports_missing_transition_without_world_write():
    from cognitive_world.resolution.interaction_context import InteractionStateAggregator

    world, attempt = _case(method="alter the panel surface in an unfamiliar way")
    clock = SimulationClock(8)
    context = InteractionStateAggregator().aggregate(attempt, world, clock.capture()).physical
    suggestion = PhysicalEffectSuggestion(
        attempt.attempt_id, attempt.content_fingerprint(), attempt.agent_id,
        attempt.initiator_id, attempt.target, context.simulation_tick, context.source_refs,
        (EffectParticipant("agent:actor-one", "original actor"),
         EffectParticipant("object:door-one", "possible affected entity")),
        (SuggestedPhysicalChange("surface_structure_altered", ("object:door-one",)),),
    )
    translation = SupportedPhysicalEffectTranslator().translate(
        suggestion, attempt, context, CompositeCausalAssessmentPolicy(),
    )
    assert translation.assessment is None
    assert translation.missing_contracts == ("state_transition_unsupported:surface_structure_altered",)
    assert world.environment["door-one"].is_open is False

    class OpenSuggestionProvider:
        def suggest_effects(self, current, view):
            assert suggestion.is_bound_to(current, view)
            return suggestion

    result, event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world, effect_suggestion_provider=OpenSuggestionProvider()),
        world_state=world,
    ).execute_with_result(attempt, simulation_tick=clock.capture())
    assert result.outcome == "unresolved" and not result.confirmed and event is None
    assert world.environment["door-one"].is_open is False


def test_multi_entity_suggestion_reports_uninstalled_transition_boundary():
    from cognitive_world.resolution.interaction_context import InteractionStateAggregator

    world, attempt = _case(extras=("object:stone-one", "agent:recipient-one"))
    world.load_entity(Entity("stone-one", "tool", owner_id="actor-one"))
    world.load_entity(Entity("recipient-one", "character"))
    clock = SimulationClock(9)
    context = InteractionStateAggregator().aggregate(attempt, world, clock.capture()).physical
    suggestion = PhysicalEffectSuggestion(
        attempt.attempt_id, attempt.content_fingerprint(), attempt.agent_id,
        attempt.initiator_id, attempt.target, context.simulation_tick, context.source_refs,
        (EffectParticipant("agent:actor-one", "origin"),
         EffectParticipant("object:stone-one", "direct cause"),
         EffectParticipant("agent:recipient-one", "possible recipient")),
        (SuggestedPhysicalChange("motion", ("object:stone-one",)),
         SuggestedPhysicalChange("injury", ("agent:recipient-one",))),
    )
    translation = SupportedPhysicalEffectTranslator().translate(
        suggestion, attempt, context, CompositeCausalAssessmentPolicy(),
    )
    assert translation.assessment is None
    assert translation.missing_contracts == ("multi_effect_transition_not_installed",)
    assert world.environment["door-one"].is_open is False


@pytest.mark.skipif(
    os.environ.get("COGNITIVEWORLD_RUN_OLLAMA_PHYSICAL_INTEGRATION") != "1",
    reason="explicit local Ollama physical-effect integration opt-in required",
)
def test_real_local_ollama_proposes_only_a_candidate():
    world, attempt = _case()
    clock = SimulationClock(6)
    from cognitive_world.resolution.interaction_context import InteractionStateAggregator

    context = InteractionStateAggregator().aggregate(attempt, world, clock.capture()).physical
    provider = OllamaPhysicalEffectSuggestionProvider.from_environment()
    assert provider is not None
    suggestion = provider.suggest_effects(attempt, context)
    assert suggestion.is_bound_to(attempt, context)
    assert suggestion.changes
    participant_refs = {
        item.reference
        for item in suggestion.participants
    } | {
        item.reference for change in suggestion.changes for item in change.participants
    }
    assert participant_refs <= set(context.grounded_refs)
    assert f"agent:{attempt.agent_id}" in participant_refs
    assert attempt.target in participant_refs
    assert suggestion.actor_id == attempt.agent_id
    assert suggestion.initiator_id == attempt.initiator_id
    assert world.environment["door-one"].is_open is False

    result, event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world, effect_suggestion_provider=provider),
        world_state=world,
    ).execute_with_result(attempt, simulation_tick=clock.capture())
    assert result.confirmed and result.success and event is not None
    assert world.environment["door-one"].is_open is False
    processor = EventProcessor(
        world_state=world, event_history=EventHistory(), simulation_clock=clock,
    )
    processor.dispatch_with_evidence(event)
    assert world.environment["door-one"].is_open is True
