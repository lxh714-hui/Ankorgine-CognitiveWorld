"""Optional, local candidate evidence review over the existing evaluation policy.

The proposal source is injected by a trusted host. This module never calls a
network transport, creates Events, or decides objective causal success.
"""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class EvidenceAwareEvaluationPolicy:
    """Refine subjective rankings; the ordinary Resolution remains authoritative."""

    query_service: AuthorizedStateQuery
    simulation_tick: int
    provider: LocalEvidenceReviewProvider
    base_policy: ActionEvaluationPolicy = DeterministicActionEvaluationPolicy()

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
