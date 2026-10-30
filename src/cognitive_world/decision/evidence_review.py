"""Optional, local candidate evidence review over the existing evaluation policy.

The proposal source is injected by a trusted host. This module never calls a
network transport, creates Events, or decides objective causal success.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
import json

from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.autonomous import (
    ActionCandidate, ActionEvaluationPolicy, CandidateEvaluation,
    DeterministicActionEvaluationPolicy, SituationAssessment,
)
from cognitive_world.resolution.causal import ActionInterpreter
from cognitive_world.resolution.evidence import (
    AuthorizedQuerySession, AuthorizedStateQuery, CausalEvidenceAnalysis,
    ObservedStateEvidence, StateQueryProposal,
)


class LocalEvidenceReviewProvider(Protocol):
    """Host-supplied local adapter. No network implementation is registered."""

    def propose_query(self, candidate: ActionCandidate, *, max_output_chars: int) -> str: ...
    def review_evidence(self, candidate: ActionCandidate,
                        evidence: tuple[ObservedStateEvidence, ...], *, max_output_chars: int) -> str: ...


@dataclass(frozen=True)
class DeterministicLocalEvidenceReviewProvider:
    """Default local query/analysis; never contacts a model or infers success."""

    def propose_query(self, candidate: ActionCandidate, *, max_output_chars: int) -> str:
        return json.dumps({"reference": candidate.target}) if candidate.target else '{"done":true}'

    def review_evidence(self, candidate: ActionCandidate,
                        evidence: tuple[ObservedStateEvidence, ...], *, max_output_chars: int) -> str:
        return json.dumps({
            "cited_fact_ids": [item.fact_id for item in evidence],
            "missing_conditions": [] if evidence else ["no authorized observed state for this target"],
            "conflicting_fact_ids": [],
            "assessment": "observed evidence is not a causal result",
        })


def _binding(value: object) -> str:
    """Decision-local immutable fingerprint of complete candidate/evidence values."""
    return sha256(repr(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceReviewSnapshot:
    owner_id: str
    candidate_id: str
    candidate_binding: str
    evidence_binding: str
    provider_identity: str
    provider_version: int
    status: str
    analysis: CausalEvidenceAnalysis | None
    _integrity: str = ""

    def validate(self, owner, candidate, evidence, provider):
        if (self.owner_id != owner or self.candidate_id != candidate.candidate_id
                or self.candidate_binding != _binding(candidate)
                or self.evidence_binding != _binding(evidence)
                or type(provider) is not DeterministicLocalEvidenceReviewProvider
                or self.provider_identity != "deterministic-local-evidence-review"
                or self.provider_version != 1
                or self.status not in ("analysis", "no_adjustment")
                or (self.status == "analysis") != (type(self.analysis) is CausalEvidenceAnalysis)
                or self._integrity != _binding((self.owner_id, self.candidate_id,
                    self.candidate_binding, self.evidence_binding, self.provider_identity,
                    self.provider_version, self.status, self.analysis))
                or (self.analysis is not None and not set(
                    (*self.analysis.cited_fact_ids, *self.analysis.conflicting_fact_ids)
                    ).issubset({item.fact_id for item in evidence}))):
            raise PermissionError("incompatible evidence review snapshot")


@dataclass(frozen=True)
class EvidenceAwareEvaluationPolicy:
    """Refine subjective rankings; the ordinary Resolution remains authoritative."""

    query_service: AuthorizedStateQuery
    simulation_tick: int
    provider: LocalEvidenceReviewProvider
    base_policy: ActionEvaluationPolicy = DeterministicActionEvaluationPolicy()

    def evaluate_with_reference(self, situation, candidates):
        """Evaluate once and reuse decision-local validated evidence for the reference."""
        if type(self.provider) is not DeterministicLocalEvidenceReviewProvider:
            raise PermissionError("reference policy requires a compatible evidence provider")
        if type(self.base_policy) is not DeterministicActionEvaluationPolicy:
            raise PermissionError("reference policy requires a compatible base evaluator")
        if situation.owner_id != self.query_service.observer_id:
            raise PermissionError("candidate owner differs from query observer")
        actual = self.base_policy.evaluate(situation, candidates)
        reference = self.base_policy.evaluate_reference(situation, candidates)
        actual_out, reference_out, snapshots = [], [], []
        def provider_call(method, *args, **kwargs):
            try:
                return method(*args, **kwargs)
            except Exception as exc:
                raise RuntimeError("reference evidence provider failed") from exc
        for candidate, a, r in zip(candidates, actual, reference, strict=True):
            if candidate.owner_id != situation.owner_id:
                raise PermissionError("cross-owner candidate review")
            evidence = ()
            analysis = None
            status = "no_adjustment"
            if candidate.target is not None:
                proposal = ActionProposal(f"evidence-review:{candidate.candidate_id}", candidate.owner_id,
                    candidate.intent, [candidate.target], {"method": candidate.method})
                attempt = ActionInterpreter().interpret(proposal, actor_id=candidate.owner_id)
                session = AuthorizedQuerySession(self.query_service, attempt, simulation_tick=self.simulation_tick)
                try:
                    raw = provider_call(self.provider.propose_query, candidate, max_output_chars=2048)
                    query = StateQueryProposal.from_model(raw)
                    if query is not None:
                        session.query(query)
                    consumed = {fact.fact_id for fact in situation.observed_facts if fact.fact_id is not None}
                    evidence = tuple(item for item in session.evidence if item.fact_id in consumed)
                    if evidence:
                        raw = provider_call(self.provider.review_evidence, candidate, evidence, max_output_chars=2048)
                        analysis = CausalEvidenceAnalysis.from_model(raw, evidence)
                        status = "analysis"
                except PermissionError:
                    raise
                except (OSError, TimeoutError) as exc:
                    raise RuntimeError("reference evidence provider failed") from exc
                except (TypeError, ValueError) as exc:
                    raise ValueError("reference evidence validation failed") from exc
            snapshot = EvidenceReviewSnapshot(situation.owner_id, candidate.candidate_id,
                _binding(candidate), _binding(evidence), "deterministic-local-evidence-review", 1,
                status, analysis)
            object.__setattr__(snapshot, "_integrity", _binding((snapshot.owner_id,
                snapshot.candidate_id, snapshot.candidate_binding, snapshot.evidence_binding,
                snapshot.provider_identity, snapshot.provider_version, snapshot.status, snapshot.analysis)))
            snapshot.validate(situation.owner_id, candidate, evidence, self.provider)
            snapshots.append(snapshot)
            def apply(item):
                if analysis is None:
                    return item
                change = min(0.05, 0.01 * len(analysis.cited_fact_ids))
                change -= min(0.05, 0.01 * len(analysis.missing_conditions))
                change -= min(0.05, 0.02 * len(analysis.conflicting_fact_ids))
                return CandidateEvaluation(item.candidate_id, item.score + change,
                    (*item.factors, ("bounded_observed_evidence_review", change)),
                    tuple(dict.fromkeys((*item.uncertainty, *analysis.missing_conditions))))
            actual_out.append(apply(a))
            reference_out.append(apply(r))
        return tuple(actual_out), tuple(reference_out), tuple(snapshots)

    def evaluate(self, situation: SituationAssessment,
                 candidates: tuple[ActionCandidate, ...]) -> tuple[CandidateEvaluation, ...]:
        base = self.base_policy.evaluate(situation, candidates)
        if situation.owner_id != self.query_service.observer_id:
            raise PermissionError("candidate owner differs from query observer")
        updated: list[CandidateEvaluation] = []
        for candidate, current in zip(candidates, base, strict=True):
            if candidate.owner_id != situation.owner_id:
                raise PermissionError("cross-owner candidate review")
            if candidate.target is None:
                updated.append(current)
                continue
            proposal = ActionProposal(
                f"evidence-review:{candidate.candidate_id}", candidate.owner_id,
                candidate.intent, [candidate.target], {"method": candidate.method},
            )
            attempt = ActionInterpreter().interpret(proposal, actor_id=candidate.owner_id)
            session = AuthorizedQuerySession(self.query_service, attempt,
                                             simulation_tick=self.simulation_tick)
            try:
                raw_query = self.provider.propose_query(candidate, max_output_chars=2048)
                query = StateQueryProposal.from_model(raw_query)
                if query is not None:
                    session.query(query)
                consumed_facts = {fact.fact_id for fact in situation.observed_facts
                                  if fact.fact_id is not None}
                visible_evidence = tuple(item for item in session.evidence
                                         if item.fact_id in consumed_facts)
                if len(visible_evidence) != len(session.evidence):
                    updated.append(current)
                    continue
                raw_analysis = self.provider.review_evidence(
                    candidate, visible_evidence, max_output_chars=2048,
                )
                analysis = CausalEvidenceAnalysis.from_model(raw_analysis, visible_evidence)
            except PermissionError:
                raise
            except (TypeError, ValueError, OSError, TimeoutError):
                updated.append(current)
                continue
            # The model's analysis remains a subjective ranking input. Even a
            # cited observation cannot confirm a candidate's expected effect.
            change = min(0.05, 0.01 * len(analysis.cited_fact_ids))
            change -= min(0.05, 0.01 * len(analysis.missing_conditions))
            change -= min(0.05, 0.02 * len(analysis.conflicting_fact_ids))
            factors = (*current.factors, ("bounded_observed_evidence_review", change))
            updated.append(CandidateEvaluation(
                current.candidate_id, current.score + change, factors,
                tuple(dict.fromkeys((*current.uncertainty, *analysis.missing_conditions))),
            ))
        return tuple(updated)
