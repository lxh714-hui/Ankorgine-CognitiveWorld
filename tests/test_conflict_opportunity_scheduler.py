"""Owner-scoped production checks for conflict/opportunity scheduling."""

from dataclasses import replace
import json

import pytest

from cognitive_world.cognition.runtime import CognitionState
from cognitive_world.decision import (
    ActionCandidate,
    ConflictOpportunityCandidate,
    DeterministicSituationAssessmentPolicy,
    SchedulerEvidenceRef,
    SituationAssessment,
)
from cognitive_world.decision.context import DecisionContext
from cognitive_world.decision.autonomous import ObservedAffordance, SituationFact, SituationGoal
from cognitive_world.runtime.conflict_opportunity import (
    ConflictOpportunityProviderContext,
    ConflictOpportunityScheduler,
)
from test_autonomous_agent_decision import _assessment
from test_autonomous_world_runner import _production_world, _action


def _situation(*, with_affordance=True, goals=None, conflicts=()):
    base = _assessment(DecisionContext(cognition_state=CognitionState("agent-a")))
    fact = SituationFact(
        "percept:door-observed", "event:door-observed", "environment",
        "door_open", "false", "fact:door-observed",
    )
    goal_rows = goals or (SituationGoal("goal-a", "open the passage", 0.8, 0.8, False),)
    affordances = (
        (ObservedAffordance(
            "environment-interaction", "object:door", "location:hall", "test a method",
            (), (fact.percept_id, fact.source_event_id),
        ),)
        if with_affordance else ()
    )
    return replace(
        base, observed_facts=(fact,), goals=goal_rows,
        goal_conflicts=tuple(conflicts), affordances=affordances,
    )


def _candidate(*, owner="agent-a", goal="goal-a", target="object:door", refs=("percept:door-observed", "event:door-observed"), candidate_id="candidate-a"):
    return ActionCandidate(
        candidate_id, owner, goal, "try a method", target, "a previously unlisted method",
        (), (), (), (), "possible progress only if independently resolved", (),
        None, None, 0.5, tuple(refs), "scheduler-test",
    )


def test_runtime_scheduler_changes_existing_evaluation_and_event_tree_trace():
    runner, world, history, _ = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    })

    report = runner.run(1)

    action = _action(report, "agent-a")
    record = runner.runtime.last_agent_turn_results[0]
    proposal = record.execution.proposal
    findings = record.scheduler_findings
    assert findings
    assert all(item.owner_id == "agent-a" for item in findings)
    opportunity = next(item for item in findings if item.kind == "opportunity")
    assert opportunity.source_refs
    assert {item.reference_type for item in opportunity.source_refs} >= {"goal", "percept"}
    trace = proposal.metadata["decision_trace"]
    linked = next(item for item in trace if item["candidate_id"] in opportunity.candidate_ids)
    assert dict(linked["factors"])["scheduler_relevance"] > 0
    assert opportunity.finding_id in linked["scheduler_finding_ids"]
    branch = next(item for item in record.event_tree_snapshot.branches if item.candidate_id == linked["candidate_id"])
    assert opportunity.finding_id in branch.scheduler_finding_ids
    assert action.status == "success"
    assert world.environment["door:archive"].is_open
    assert any(event.has_trusted_source("resolution") for event in history.get_events())
    assert runner.runtime.agent_decision.conflict_opportunity_scheduler is None


def test_discovery_is_owner_local_source_bound_and_does_not_claim_world_truth():
    situation = _situation()
    candidate = _candidate()
    scheduler = ConflictOpportunityScheduler()

    findings = scheduler.discover(situation, (candidate,), simulation_tick=4)

    opportunity = next(item for item in findings if item.kind == "opportunity")
    assert isinstance(opportunity, ConflictOpportunityCandidate)
    assert opportunity.owner_id == situation.owner_id
    assert opportunity.source_refs == (
        SchedulerEvidenceRef("event", "event:door-observed"),
        SchedulerEvidenceRef("goal", "goal-a"),
        SchedulerEvidenceRef("percept", "percept:door-observed"),
    )
    assert any("unconfirmed" in item.casefold() or "not" in item.casefold() for item in opportunity.uncertainties)
    assert scheduler.current_for("agent-b", 4) == ()
    with pytest.raises(PermissionError):
        scheduler.discover(situation, (_candidate(owner="agent-b"),), simulation_tick=4)


def test_goal_tension_is_subjective_and_repeated_discovery_is_deduplicated():
    goals = (
        SituationGoal("goal-a", "keep the archive sealed", 0.7, 0.7, False),
        SituationGoal("goal-b", "open the archive", 0.8, 0.9, False),
    )
    situation = _situation(with_affordance=False, goals=goals, conflicts=(("goal-a", "goal-b"),))
    scheduler = ConflictOpportunityScheduler()

    first = scheduler.discover(situation, (), simulation_tick=1)
    repeated = scheduler.discover(situation, (), simulation_tick=1)
    later = scheduler.discover(situation, (), simulation_tick=2)

    assert len(first) == len(repeated) == len(later) == 1
    assert first[0].finding_id == repeated[0].finding_id == later[0].finding_id
    assert first[0].sightings == repeated[0].sightings == 1
    assert later[0].sightings == 2
    assert "not an objective world conflict" in first[0].uncertainties[0]
    assert not any(item.kind == "opportunity" for item in first)


def test_unknown_evidence_does_not_create_opportunity_and_budget_limits_findings():
    situation = _situation(with_affordance=False, goals=(
        SituationGoal("goal-a", "a", 0.4, 0.4, False),
        SituationGoal("goal-b", "b", 0.9, 0.9, False),
        SituationGoal("goal-c", "c", 0.8, 0.8, False),
    ), conflicts=(("goal-a", "goal-b"), ("goal-b", "goal-c")))
    scheduler = ConflictOpportunityScheduler(maximum_findings_per_turn=1)

    findings = scheduler.discover(situation, (), simulation_tick=1)

    assert len(findings) == 1
    assert findings[0].goal_ids == ("goal-b", "goal-c")
    assert all(item.kind != "opportunity" for item in findings)


def test_findings_become_dormant_only_after_bounded_missed_evaluations():
    situation = _situation(with_affordance=False, goals=(
        SituationGoal("goal-a", "a", 0.8, 0.8, False),
        SituationGoal("goal-b", "b", 0.7, 0.7, False),
    ), conflicts=(("goal-a", "goal-b"),))
    scheduler = ConflictOpportunityScheduler()
    first = scheduler.discover(situation, (), simulation_tick=1)[0]

    scheduler.discover(replace(situation, goal_conflicts=()), (), simulation_tick=2)
    still_active = next(item for item in scheduler.tracked_for("agent-a") if item.finding_id == first.finding_id)
    scheduler.discover(replace(situation, goal_conflicts=()), (), simulation_tick=3)
    dormant = next(item for item in scheduler.tracked_for("agent-a") if item.finding_id == first.finding_id)

    assert still_active.lifecycle == "active"
    assert dormant.lifecycle == "dormant"
    assert scheduler.tracked_for("agent-b") == ()


class _FakeAnalyzer:
    def __init__(self, source_ref):
        self.source_ref = source_ref
        self.seen = []

    def analyze(self, context: ConflictOpportunityProviderContext, *, max_candidates, max_output_chars):
        self.seen.append(context)
        assert max_candidates <= 8
        assert max_output_chars <= 12_000
        return json.dumps({
            "schema_version": 1,
            "findings": [{
                "kind": "opportunity", "goal_ids": ["goal-a"],
                "target_refs": ["object:door"], "candidate_ids": ["candidate-a"],
                "source_refs": [self.source_ref], "importance": 0.6,
                "relevance": 0.7, "uncertainties": [],
            }],
        })


class _ContextBoundRuntimeAnalyzer:
    def __init__(self):
        self.calls = 0

    def analyze(self, context, *, max_candidates, max_output_chars):
        self.calls += 1
        candidate_id, goal_id, target, _intent, candidate_sources = context.candidates[0]
        source_ref = next(
            reference for reference in context.allowed_source_refs
            if reference.split(":", 1)[1] in candidate_sources
        )
        return json.dumps({
            "schema_version": 1,
            "findings": [{
                "kind": "opportunity", "goal_ids": [goal_id],
                "target_refs": [target], "candidate_ids": [candidate_id],
                "source_refs": [source_ref], "importance": 1.0,
                "relevance": 1.0, "uncertainties": [],
            }],
        })


def test_explicit_analyzer_runs_inside_runtime_candidate_dataflow_without_network():
    from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler

    runner, _world, _history, _ = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    })
    analyzer = _ContextBoundRuntimeAnalyzer()
    runner.runtime.conflict_opportunity_scheduler = ConflictOpportunityScheduler(provider=analyzer)

    report = runner.run(1)

    action = _action(report, "agent-a")
    record = runner.runtime.last_agent_turn_results[0]
    assert analyzer.calls == 1
    assert action.proposal is not None
    assert any(
        item.importance == 1.0
        and "Provider proposal is an unverified interpretation." in item.uncertainties
        for item in record.scheduler_findings
    )
    assert any(
        dict(candidate.factors)["scheduler_relevance"] == pytest.approx(0.12)
        for candidate in action.proposal.candidates
        if candidate.target == "door:archive"
    )


def test_optional_provider_is_narrow_validated_and_failure_preserves_local_path():
    situation = _situation()
    candidate = _candidate()
    provider = _FakeAnalyzer("percept:percept:door-observed")
    scheduler = ConflictOpportunityScheduler(provider=provider)
    findings = scheduler.discover(situation, (candidate,), simulation_tick=1)

    assert provider.seen
    assert not hasattr(provider.seen[0], "owner_id")
    assert not hasattr(provider.seen[0], "world_state")
    assert any(item.kind == "opportunity" for item in findings)
    assert any("unverified interpretation" in text for item in findings for text in item.uncertainties)

    invalid_provider = _FakeAnalyzer("event:forged")
    fallback = ConflictOpportunityScheduler(provider=invalid_provider)
    preserved = fallback.discover(situation, (candidate,), simulation_tick=1)
    assert any(item.kind == "opportunity" for item in preserved)
    assert fallback.provider_error_for("agent-a", 1) == "PermissionError"


def test_scheduler_provider_never_receives_owner_private_memory_or_beliefs():
    from cognitive_world.decision.autonomous import SituationBelief, SituationMemory

    situation = replace(
        _situation(),
        beliefs=(SituationBelief("belief-private", "private belief", 0.9, ("event:door-observed",)),),
        memories=(SituationMemory("memory-private", "private recollection", "event:door-observed"),),
    )
    provider = _FakeAnalyzer("percept:percept:door-observed")
    scheduler = ConflictOpportunityScheduler(provider=provider)

    scheduler.discover(situation, (_candidate(),), simulation_tick=1)

    context = provider.seen[0]
    assert all("private" not in repr(value) for value in (
        context.observed_facts, context.goals, context.affordances, context.candidates,
    ))
    assert not hasattr(context, "beliefs")
    assert not hasattr(context, "memories")


def test_scheduler_does_not_claim_authority_or_accept_unverified_sources():
    situation = _situation()
    scheduler = ConflictOpportunityScheduler()
    with pytest.raises(PermissionError):
        scheduler.discover(
            situation,
            (_candidate(refs=("event:not-observed",)),),
            simulation_tick=1,
        )
    assert scheduler.tracked_for("agent-a") == ()


def test_same_objective_for_two_owners_has_separate_lifecycle_records():
    scheduler = ConflictOpportunityScheduler()
    for owner in ("agent-a", "agent-b"):
        situation = replace(_situation(), owner_id=owner)
        result = scheduler.discover(
            situation,
            (_candidate(owner=owner),),
            simulation_tick=1,
        )
        assert all(item.owner_id == owner for item in result)

    left = scheduler.tracked_for("agent-a")
    right = scheduler.tracked_for("agent-b")
    assert len(left) == len(right) == 1
    assert left[0].finding_id != right[0].finding_id
    assert scheduler.current_for("agent-a", 1)[0].owner_id == "agent-a"
    assert scheduler.current_for("agent-b", 1)[0].owner_id == "agent-b"
