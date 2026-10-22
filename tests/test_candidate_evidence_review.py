"""Local fake-provider checks; no live model transport or world authority."""
import json

from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.autonomous import ActionCandidate, DeterministicSituationAssessmentPolicy
from cognitive_world.decision.context import DecisionContext
from cognitive_world.decision.evidence_review import EvidenceAwareEvaluationPolicy
from cognitive_world.resolution.evidence import AuthorizedStateQuery
from test_authorized_state_query import runtime_with_observations


class LocalProvider:
    def __init__(self):
        self.seen = []

    def propose_query(self, candidate, *, max_output_chars):
        return json.dumps({"reference": candidate.target, "predicate": "door_open"})

    def review_evidence(self, candidate, evidence, *, max_output_chars):
        self.seen.append((candidate.candidate_id, evidence))
        return json.dumps({
            "cited_fact_ids": [item.fact_id for item in evidence] if candidate.method == "inspect" else [],
            "missing_conditions": [] if evidence and candidate.method == "inspect" else ["basis unknown"],
            "conflicting_fact_ids": [], "assessment": "tentative",
        })


class Candidates:
    def generate(self, situation):
        return tuple(ActionCandidate(
            candidate_id=name, owner_id=situation.owner_id, goal_id=None,
            intent="inspect", target="object:door-west", method=method,
            tools=(), required_capabilities=(), preconditions=(), steps=(),
            expected_result="unknown", uncertainties=(), estimated_risk=None,
            estimated_cost=None, commitment=0.5, source_refs=(), strategy="local fake",
        ) for name, method in (("informed", "inspect"), ("uncertain", "other")))


def test_authorized_evidence_changes_existing_candidate_ranking_without_world_effect():
    runtime = runtime_with_observations()
    observations = runtime.observation_store.get_by_observer("viewer")
    cognition = CognitiveRuntime().process("viewer", observations)
    context = DecisionContext(cognition_state=cognition, percepts=tuple(cognition.percepts))
    situation = DeterministicSituationAssessmentPolicy().assess(context)
    provider = LocalProvider()
    policy = EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime), 3, provider)
    candidates = Candidates().generate(situation)
    evaluated = policy.evaluate(situation, candidates)
    assert evaluated[0].score > evaluated[1].score
    assert len(provider.seen) == 2
    assert all(item.source_event_id == "observed:door-west" for _, batch in provider.seen for item in batch)
    decision = AgentDecision(candidate_policy=Candidates(), evaluation_policy=policy)
    proposed = decision.propose(context)
    assert proposed.metadata["selected_candidate_id"] == "informed"
    assert runtime.world_state.environment["door-west"].is_open is False
    assert len(runtime.event_history.get_events()) == 2


def test_store_observation_without_l1_does_not_reach_local_candidate_provider():
    runtime = runtime_with_observations()
    context = DecisionContext(cognition_state=CognitiveRuntime().process("viewer", ()))
    provider = LocalProvider()
    policy = EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime), 3, provider)
    decision = AgentDecision(candidate_policy=Candidates(), evaluation_policy=policy)
    decision.propose(context)
    assert provider.seen == []


def test_runtime_composes_owner_bound_evidence_review_into_real_decision_and_resolution():
    from test_autonomous_world_runner import _production_world, _action

    runner, world, history, observations = _production_world({
        "agent-a": ("goal-a", "open the archive door"),
        "agent-b": ("goal-b", "open the archive door"),
    })
    provider = LocalProvider()
    runner.runtime.evidence_review_provider = provider
    report = runner.run(1)
    local = _action(report, "agent-a")
    remote = _action(report, "agent-b")
    assert local.proposal is not None and local.proposal.candidates
    reviewed = [candidate for candidate in local.proposal.candidates
                if candidate.target == "door:archive"]
    assert reviewed
    assert any("bounded_observed_evidence_review" in dict(item.factors) for item in reviewed)
    assert all(item.observer_id == "agent-a" for _, batch in provider.seen for item in batch)
    assert remote.proposal is not None
    assert all("bounded_observed_evidence_review" not in dict(item.factors)
               for item in remote.proposal.candidates)
    assert local.event_committed and world.environment["door:archive"].is_open
    assert any(event.has_trusted_source("resolution") for event in history.get_events())
    assert runner.runtime.agent_decision.evaluation_policy.__class__.__name__ == "DeterministicActionEvaluationPolicy"


def test_runtime_default_is_local_and_never_needs_an_external_provider():
    from test_autonomous_world_runner import _production_world, _action

    runner, world, _, _ = _production_world({"agent-a": ("goal-a", "open the archive door")})
    assert runner.runtime.evidence_review_provider is None
    action = _action(runner.run(1), "agent-a")
    assert any("bounded_observed_evidence_review" in dict(item.factors)
               for item in action.proposal.candidates if item.target == "door:archive")
    assert action.event_committed and world.environment["door:archive"].is_open
