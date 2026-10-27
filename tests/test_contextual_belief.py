"""Contextual cognition changes actual choices, independently of BehaviorFeedback."""

from copy import deepcopy
from dataclasses import replace
import pytest
from test_consumed_physical_feedback import Host, Choices, Scores, NoReview
from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import Belief
from cognitive_world.cognition.causal_review import (
    CognitiveReview,
    BeliefRevisionSuggestion,
)
from cognitive_world.decision import AgentDecision
from cognitive_world.decision.contextual_belief import ContextualBeliefRule

RULE = ContextualBeliefRule(
    1, "action_result", "interaction_out_of_reach", True, -0.25, 2
)


class CopyEvidence:
    """Deterministic provider of proposals; never selects an action or writes state."""

    def review(self, request):
        evidence = request.evidence[-1]
        return CognitiveReview(
            "Retain the exact contextual evidence",
            "No generalization",
            BeliefRevisionSuggestion(
                "context",
                deepcopy(evidence.content),
                1.0,
                "This observation only",
                (evidence.observation_id,),
            ),
        )


def setup():
    h = Host()
    rt = h.runtime
    with rt.write_fence.operation():
        h.cognition.add_belief(Belief("context", h.owner, "Unknown", confidence=1.0))
        h.cognition.add_belief(
            Belief("unrelated", h.owner, "A separate commitment", confidence=0.5)
        )
    original = rt.cognition_context_provider

    def provide(agent):
        c = original(agent)
        if agent.agent_id != h.owner:
            return c
        return CognitionContext.from_character(
            Character(
                c.character_id,
                agent.agent_id,
                agent.agent_id,
                belief_ids=["context", "unrelated"],
                goal_ids=list(agent.goal_ids),
            ),
            h.cognition,
            h.memory,
            observation_store=rt.context.observation_store,
        )

    rt.cognition_context_provider = provide
    rt.agent_action_loop.agent_turn.contextual_belief_rules = (RULE,)
    return h


def prepare(h):
    rt = h.runtime
    with rt.write_fence.operation():
        return rt.agent_action_loop.agent_turn.prepare_decision_context(
            rt.context.agent_registry.get(h.owner),
            rt.cognition_context_provider(rt.context.agent_registry.get(h.owner)),
            simulation_tick=rt.context.clock.capture(),
        )[0]


def decision(h):
    # Deliberately no BehaviorFeedback: all A/B inputs other than Belief are held fixed.
    return AgentDecision(
        candidate_policy=Choices(h.target, h.route),
        evaluation_policy=Scores(),
        review_policy=NoReview(),
    )


def test_governed_revision_changes_actual_action_without_feedback_and_later_corrects():
    h = setup()
    rt = h.runtime
    old = h.cognition.get_belief("context")
    unrelated = h.cognition.get_belief("unrelated")
    goals = h.cognition.goal_store.get_all()
    failure = h.advance()
    assert failure.event_committed and not failure.execution.resolution.success
    assert h.cognition.get_belief("context") == old  # delivery is not revision
    turn = rt.agent_action_loop.agent_turn
    turn.cognitive_review_provider = CopyEvidence()
    context = prepare(h)
    revised = h.cognition.get_belief("context")
    assert revised != old and revised.content["predicate"] == "interaction_out_of_reach"
    assert len(context.contextual_beliefs) == 1
    assert context.contextual_beliefs[0].source_event_id == failure.execution.event.id
    assert (
        h.cognition.get_belief("unrelated") == unrelated
        and h.cognition.goal_store.get_all() == goals
    )
    assert decision(h).propose(context).action_type == "Move"
    counterfactual = replace(context, beliefs=(old, unrelated), contextual_beliefs=())
    assert decision(h).propose(counterfactual).action_type == "Open"
    again = prepare(h)
    assert h.cognition.get_belief("context") == revised  # no duplicate revision
    assert len(again.contextual_beliefs) == 1
    # Same real AgentTurn/action loop, but no feedback ranking adapter.
    with rt.write_fence.operation():
        execution = rt.agent_action_loop.run_turn_with_result(
            rt.context.agent_registry.get(h.owner),
            rt.cognition_context_provider(rt.context.agent_registry.get(h.owner)),
            decision(h),
            simulation_tick=rt.context.clock.capture(),
        )
        assert execution.proposal.action_type == "Move"
        rt.event_processor.dispatch_with_evidence(execution.event)
    assert rt.context.world_state.get_location(h.owner).endswith(":target")
    after = prepare(h)
    assert not after.contextual_beliefs
    assert h.cognition.get_belief("context").content["predicate"] == "actor_arrived"
    with rt.write_fence.operation():
        execution = rt.agent_action_loop.run_turn_with_result(
            rt.context.agent_registry.get(h.owner),
            rt.cognition_context_provider(rt.context.agent_registry.get(h.owner)),
            decision(h),
            simulation_tick=rt.context.clock.capture(),
        )
        assert execution.proposal.action_type == "Open" and execution.resolution.success
        rt.event_processor.dispatch_with_evidence(execution.event)
    prepare(h)
    assert h.cognition.get_belief("context").content["predicate"] == "door_open"
    assert h.cognition.get_belief("context").content["value"] is True
    assert (
        h.cognition.get_belief("unrelated") == unrelated
        and h.cognition.goal_store.get_all() == goals
    )


def learned():
    h = setup()
    h.advance()
    h.runtime.agent_action_loop.agent_turn.cognitive_review_provider = CopyEvidence()
    return h, prepare(h)


@pytest.mark.parametrize("change", ["target", "operation", "method", "tools"])
def test_exact_matching_does_not_affect_other_candidates(change):
    from cognitive_world.decision.autonomous import (
        DeterministicSituationAssessmentPolicy,
    )
    from cognitive_world.decision.contextual_belief import adjust_evaluations

    h, context = learned()
    situation = DeterministicSituationAssessmentPolicy().assess(context)
    candidates = Choices(h.target, h.route).generate(situation)
    selected = next(c for c in candidates if c.intent == "Open")
    changed = replace(
        selected,
        **{
            "target": {"target": "object:" + h.route},
            "operation": {"intent": "Other"},
            "method": {"method": "another method"},
            "tools": {"tools": ("another-tool",)},
        }[change],
    )
    baseline = Scores().evaluate(situation, (changed,))
    assert adjust_evaluations(situation, (changed,), baseline) == baseline


def test_stale_frontier_age_and_ambiguous_policy_defer():
    h, context = learned()
    rt = h.runtime
    rt.context.clock.tick()
    rt.context.clock.tick()
    rt.context.clock.tick()
    assert not prepare(h).contextual_beliefs
    h, context = learned()
    h.runtime.agent_action_loop.agent_turn.contextual_belief_rules = (RULE, RULE)
    assert not prepare(h).contextual_beliefs


def test_missing_history_and_wrong_owner_do_not_revise():
    h = setup()
    h.advance()
    turn = h.runtime.agent_action_loop.agent_turn
    from cognitive_world.cognition.runtime import CognitiveRuntime

    turn.cognitive_runtime = (
        CognitiveRuntime()
    )  # supported unbound compatibility intake defers
    turn.cognitive_review_provider = CopyEvidence()
    old = h.cognition.get_belief("context")
    with pytest.raises(PermissionError, match="canonical history"):
        prepare(h)
    assert h.cognition.get_belief("context") == old
    assert not turn.cognitive_runtime._l1_consumption_receipts


@pytest.mark.parametrize(
    "kwargs",
    [{"version": 2}, {"value": 1}, {"adjustment": float("nan")}, {"max_age_ticks": -1}],
)
def test_unknown_or_malformed_rules_fail_closed(kwargs):
    with pytest.raises(ValueError):
        replace(RULE, **kwargs)


@pytest.mark.parametrize("variant", ["wrong_owner", "invalid_provenance"])
def test_bad_delivery_does_not_authorize_a_revision(variant):
    from cognitive_world.observation.store import ObservationStore

    h = setup()
    failure = h.advance()
    rt = h.runtime
    original = rt.cognition_context_provider(rt.context.agent_registry.get(h.owner))
    (observation,) = [
        o
        for o in rt.context.observation_store.get_by_observer(h.owner)
        if o.source_event_id == failure.execution.event.id
    ]
    invalid = (
        replace(observation, observer_id="another-owner")
        if variant == "wrong_owner"
        else replace(observation, content=replace(observation.content, value=False))
    )
    isolated = ObservationStore()
    isolated.add(invalid)
    context = CognitionContext.from_character(
        Character(
            original.character_id,
            h.owner,
            h.owner,
            belief_ids=["context", "unrelated"],
            goal_ids=list(rt.context.agent_registry.get(h.owner).goal_ids),
        ),
        h.cognition,
        h.memory,
        observation_store=isolated,
    )
    turn = rt.agent_action_loop.agent_turn
    turn.cognitive_review_provider = CopyEvidence()
    before = h.cognition.get_belief("context")
    with rt.write_fence.operation():
        decision_context, state = turn.prepare_decision_context(
            rt.context.agent_registry.get(h.owner),
            context,
            simulation_tick=rt.context.clock.capture(),
        )
    assert not decision_context.contextual_beliefs and not state.percept_ids
    assert h.cognition.get_belief("context") == before
    assert (
        h.owner,
        invalid.observation_id,
    ) not in turn.cognitive_runtime._l1_consumption_receipts
    if variant == "wrong_owner":
        assert (
            not context.get_observations()
        )  # rejected by the real owner-scoped input boundary


def test_uncommitted_failure_cannot_revise_and_integer_is_not_boolean_evidence():
    h = setup()
    rt = h.runtime
    prepare(h)  # consume only existing initial observations
    before = h.cognition.get_belief("context")
    with rt.write_fence.operation():
        pending = rt.agent_action_loop.run_turn_with_result(
            rt.context.agent_registry.get(h.owner),
            rt.cognition_context_provider(rt.context.agent_registry.get(h.owner)),
            decision(h),
            simulation_tick=rt.context.clock.capture(),
        )
    assert not pending.resolution.success and pending.event is not None
    assert rt.context.event_history.get_event(pending.event.id) is None
    rt.agent_action_loop.agent_turn.cognitive_review_provider = CopyEvidence()
    assert not prepare(h).contextual_beliefs
    assert h.cognition.get_belief("context") == before
    h, context = learned()

    # A provider may propose an integer, but it cannot gain Boolean matching semantics.
    class NumericSuggestion:
        def review(self, request):
            evidence = request.evidence[-1]
            content = dict(evidence.content, value=1)
            return CognitiveReview(
                "Not a Boolean judgment",
                "Unsupported matching",
                BeliefRevisionSuggestion(
                    "context",
                    content,
                    1.0,
                    "Typed mismatch",
                    (evidence.observation_id,),
                ),
            )

    other = setup()
    other.advance()
    other.runtime.agent_action_loop.agent_turn.cognitive_review_provider = (
        NumericSuggestion()
    )
    assert not prepare(other).contextual_beliefs


def test_signed_restore_retains_belief_but_does_not_fabricate_consumption_or_views(
    tmp_path, monkeypatch
):
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from test_runtime_reconstruction import _dependency_manifest
    import cognitive_world.event.processor as processor_module

    h, context = learned()
    belief = h.cognition.get_belief("context")
    manager, saved = h.save(tmp_path / "saves")
    records = tuple(
        h.runtime.context.event_history.get_persistence_record(e.id).to_json_record()
        for e in h.runtime.context.event_history.get_events()
    )

    class Assembler:
        def assemble(self, inputs):
            self.host = Host(inputs=inputs, trust=h.trust)
            return self.host.runtime

    def forbid(*args, **kwargs):
        pytest.fail("restore must not sign old evidence")

    monkeypatch.setattr(processor_module, "make_persisted_event_record", forbid)
    assembly = Assembler()
    staged = manager.stage_restore(
        saved.save_id,
        timeline_id=saved.timeline_id,
        active_runtime=h.runtime,
        assembler=assembly,
        dependencies=_dependency_manifest(),
        new_timeline_id="contextual-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(h.runtime)).activate(staged)
    assert assembly.host.cognition.get_belief("context") == belief
    assert (
        tuple(
            child.context.event_history.get_persistence_record(e.id).to_json_record()
            for e in child.context.event_history.get_events()
        )
        == records
    )
    child.agent_action_loop.agent_turn.contextual_belief_rules = (RULE,)
    assert not prepare(assembly.host).contextual_beliefs
    assert (
        not child.agent_action_loop.agent_turn.cognitive_runtime._l1_consumption_receipts
    )


def test_governance_rejection_retains_belief_despite_actual_consumption():
    from cognitive_world.cognition.causal_review import CognitiveBeliefReview
    from cognitive_world.cognition.validation import ValidationResult

    h = setup()
    event = h.advance().execution.event
    old = h.cognition.get_belief("context")

    class Reject:
        def validate(self, proposal, context):
            return ValidationResult(False, "Host policy refused revision")

    turn = h.runtime.agent_action_loop.agent_turn
    turn.cognitive_belief_review = CognitiveBeliefReview(validator=Reject())
    turn.cognitive_review_provider = CopyEvidence()
    context = prepare(h)
    assert h.cognition.get_belief("context") == old and not context.contextual_beliefs
    (observation,) = [
        o
        for o in h.runtime.context.observation_store.get_by_observer(h.owner)
        if o.source_event_id == event.id
    ]
    assert turn.cognitive_runtime.has_consumed_observation(
        h.owner, observation, source_event_id=event.id
    )


def test_provider_projection_is_json_safe_and_omits_internal_binding_state(monkeypatch):
    import json
    import cognitive_world.decision.autonomous as module

    h, context = learned()
    situation = module.DeterministicSituationAssessmentPolicy().assess(context)
    captured = []

    # Return ordinary provider output, with only transport replaced.
    def transport(base, path, body, **kwargs):
        captured.append(json.loads(body))
        return json.dumps(
            {"choices": [{"message": {"content": '{"candidates":[]}'}}]}
        ).encode()

    monkeypatch.setattr(module, "post_provider_json", transport)
    module.OpenAICompatibleDecisionProvider(
        "http://127.0.0.1:11434/v1", "fixture"
    ).generate_candidates(situation, max_candidates=3, max_output_chars=1000)
    prompt = captured[0]["messages"][0]["content"]
    view = json.loads(prompt.split("Situation:\n", 1)[1])
    belief = next(b for b in view["subjective_beliefs"] if b["belief_id"] == "context")
    assert belief["contextual_judgment"]["value"] is True
    assert "belief_snapshot" not in prompt and "_seal" not in prompt


def test_actual_movement_invalidates_old_judgment_even_without_a_new_revision():
    h, context = learned()
    rt = h.runtime
    prior = h.cognition.get_belief("context")
    rt.agent_action_loop.agent_turn.cognitive_review_provider = None
    with rt.write_fence.operation():
        execution = rt.agent_action_loop.run_turn_with_result(
            rt.context.agent_registry.get(h.owner),
            rt.cognition_context_provider(rt.context.agent_registry.get(h.owner)),
            decision(h),
            simulation_tick=rt.context.clock.capture(),
        )
        assert execution.proposal.action_type == "Move"
        rt.event_processor.dispatch_with_evidence(execution.event)
    current = prepare(h)
    assert h.cognition.get_belief("context") == prior
    assert not current.contextual_beliefs
    assert decision(h).propose(current).action_type == "Open"
