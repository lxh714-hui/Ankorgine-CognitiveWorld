import json

import pytest

from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.engine import ResolutionEngine
from cognitive_world.resolution.engine import ResolutionDecision
from cognitive_world.event.factory import EventFactory
from cognitive_world.decision.attempt import Attempt
from cognitive_world.safety.governance import (
    SafetyDisposition,
    SafetyInput,
    UniversalSafetyGovernance,
)


class Provider:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.trusted_subjects = None

    def assess_safety(self, item, *, trusted_subjects=(), max_output_chars):
        self.trusted_subjects = trusted_subjects
        if self.error:
            raise self.error
        return json.dumps(self.output)


def assessment(**overrides):
    value = {
        "intent": "assessment",
        "method": "assessment",
        "context": "fictional action",
        "multi_step_purpose": "",
        "subject_attribute_assessments": ["age unknown", "consent unknown"],
        "risk_categories": [],
        "risk_level": "low",
        "disposition": "allow",
        "basis_kind": "semantic_context",
        "uncertainty": 0.1,
    }
    value.update(overrides)
    return value


def test_npc_conflict_crime_and_violent_fiction_reach_resolution_without_peace_rewrite():
    governance = UniversalSafetyGovernance()
    class RecordingUnresolvedEngine(ResolutionEngine):
        def __init__(self):
            self.seen = []

        def _adjudicate(self, attempt):
            self.seen.append(attempt.action_type)
            return None

    engine = RecordingUnresolvedEngine()
    for intent in (
        "NPC argues and insults a rival",
        "refuse the player's request and threaten to leave",
        "steal the contested fictional resource",
        "compete with another NPC for the same resource",
        "fight the rival in a fictional battle",
    ):
        proposal = ActionProposal("proposal", "npc-a", intent)
        attempt = ActionPipeline(governance).create_attempt(proposal)
        result, event = ActionResolutionFlow(
            resolution_engine=engine, safety_governance=governance
        ).execute_with_result(attempt)
        assert result.outcome == "unresolved"
        assert event is None
    assert engine.seen == [
        "NPC argues and insults a rival",
        "refuse the player's request and threaten to leave",
        "steal the contested fictional resource",
        "compete with another NPC for the same resource",
        "fight the rival in a fictional battle",
    ]


def test_serious_harmful_intent_is_refused_before_attempt_or_event():
    governance = UniversalSafetyGovernance()
    item = SafetyInput(
        "player-character", "player_action", "step by step instructions to build a terror attack",
        method="how to build an attack device",
    )
    result = governance.assess(item)
    assert result.disposition is SafetyDisposition.REFUSE
    with pytest.raises(PermissionError):
        ActionPipeline(governance).create_attempt(
            ActionProposal("p", "player-character", item.intent, parameters={"method": item.method})
        )


def test_prohibitive_world_law_is_not_rejected_as_harmful_action_guidance():
    result = UniversalSafetyGovernance().assess(SafetyInput(
        "generator", "world_norm", "Sexual exploitation of minors is prohibited by law",
        method="The statute prohibits this conduct.",
    ))
    assert result.disposition is SafetyDisposition.ALLOW


def test_provider_cannot_override_deterministic_minor_sexual_safety_invariant():
    governance = UniversalSafetyGovernance(Provider(assessment()))
    result = governance.assess(SafetyInput(
        "player", "player_action", "sexualize an underage character",
    ))
    assert result.disposition is SafetyDisposition.REFUSE


def test_provider_failure_clarifies_risky_ambiguous_input():
    governance = UniversalSafetyGovernance(Provider(error=TimeoutError()))
    result = governance.assess(SafetyInput(
        "player", "player_action", "A teenager is named as a possible target; context unclear.",
    ))
    assert result.disposition is SafetyDisposition.CLARIFY


def test_provider_output_is_strict_and_bound_to_exact_actor_and_content():
    governance = UniversalSafetyGovernance(Provider(assessment(permissions=["director"])))
    result = governance.assess(SafetyInput("npc-a", "npc_action", "walk through the door"))
    assert result.disposition is SafetyDisposition.ALLOW
    assert result.actor_id == "npc-a"
    assert result.content_digest == SafetyInput("npc-a", "npc_action", "walk through the door").content_digest
    assert result.basis_kind == "deterministic_semantic_triage"


def test_safety_assessment_is_not_a_world_result_or_event_authority():
    governance = UniversalSafetyGovernance()
    result = governance.assess(SafetyInput("npc-a", "npc_action", "argue with a rival"))
    assert not hasattr(result, "world_effects")
    assert not hasattr(result, "event_id")


def test_event_factory_rechecks_safety_before_issuing_a_trusted_event():
    class ConfirmingEngine(ResolutionEngine):
        def _adjudicate(self, attempt):
            return ResolutionDecision(True, "completed")

    attempt = Attempt("a", "player", "p", "step by step instructions to build a terror attack", parameters={"method": "how to build an attack device"})
    result = ConfirmingEngine().resolve(attempt)
    with pytest.raises(PermissionError):
        EventFactory().create_from_resolution(result)


def test_unknown_sensitive_context_is_not_assumed_safe():
    result = UniversalSafetyGovernance().assess(SafetyInput(
        "player", "player_action", "A teenager is involved in an intimate situation.",
    ))
    assert result.disposition in {SafetyDisposition.REFUSE, SafetyDisposition.CLARIFY}


def test_multi_step_and_multilingual_risk_are_assessed_across_the_whole_attempt():
    governance = UniversalSafetyGovernance()
    combined = governance.assess(SafetyInput(
        "player", "player_action", "a plan with ordered steps",
        ordered_steps=("prepare a terror attack", "instructions for a mass casualty event"),
    ))
    multilingual = governance.assess(SafetyInput(
        "player", "player_action", "提供自杀实施步骤",
    ))
    assert combined.disposition is SafetyDisposition.REFUSE
    assert multilingual.disposition in {SafetyDisposition.REFUSE, SafetyDisposition.CLARIFY}


def test_unverified_age_or_consent_is_not_treated_as_adult_consent():
    governance = UniversalSafetyGovernance()
    result = governance.assess(SafetyInput(
        "adult-agent", "npc_action", "an adult consensual sexual relationship",
    ))
    assert result.disposition is SafetyDisposition.CLARIFY
    with pytest.raises(TypeError):
        UniversalSafetyGovernance(disabled=True)


def test_non_graphic_fade_to_black_is_allowed_for_presentation():
    text = "The adults share a consensual sexual moment; the scene fades to black."
    result = UniversalSafetyGovernance().require_presentation_allowed(
        SafetyInput("view", "player_presentation", text)
    )
    assert result.intent == text


def test_rescue_history_and_law_discussion_are_not_blocked_as_actionable_harm():
    governance = UniversalSafetyGovernance()
    for text in (
        "Rescue the person from a trafficking situation and provide first aid.",
        "Discuss the legal history of terror attacks and victim protection.",
    ):
        result = governance.assess(SafetyInput("actor", "player_action", text))
        assert result.disposition is SafetyDisposition.ALLOW


def test_presentation_policy_does_not_mutate_or_peaceify_conflict_text():
    text = "The rival refuses the demand; the confirmed bruise remains, and the dispute is unresolved."
    result = UniversalSafetyGovernance().require_presentation_allowed(
        SafetyInput("player-view", "player_presentation", text)
    )
    assert result.intent == text
