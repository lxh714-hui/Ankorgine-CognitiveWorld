"""Cognition-driven, proposal-only Agent decision boundary."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import math
from uuid import uuid4
from typing import Any

from cognitive_world.cognition.runtime import CognitionState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.context import DecisionContext
from cognitive_world.decision.behavior_feedback import BehaviorFeedback
from cognitive_world.decision.autonomous import (
    DEFAULT_ACTION_EVALUATION_POLICY,
    DEFAULT_CANDIDATE_GENERATION_POLICY,
    DEFAULT_DECISION_REVIEW_POLICY,
    DEFAULT_SITUATION_ASSESSMENT_POLICY,
    MAX_CANDIDATES,
    ActionCandidate,
    BoundedDecisionReviewPolicy,
    DeterministicActionEvaluationPolicy,
    DeterministicSituationAssessmentPolicy,
    ModelAssistedCandidatePolicy,
)


@dataclass
class AgentDecision:
    """Assess, generate, evaluate, review, and select one open-ended attempt.

    Direct legacy Mapping/CognitionState inputs retain the former placeholder
    behavior. The production AgentTurn path supplies the owner-scoped frozen
    DecisionContext and uses the autonomous strategy pipeline.
    """

    situation_policy: Any = field(default_factory=DeterministicSituationAssessmentPolicy)
    candidate_policy: Any = field(default_factory=ModelAssistedCandidatePolicy)
    evaluation_policy: Any = field(default_factory=DeterministicActionEvaluationPolicy)
    review_policy: Any = field(default_factory=BoundedDecisionReviewPolicy)
    conflict_opportunity_scheduler: Any = None
    simulation_tick: int | None = None
    behavior_feedback: BehaviorFeedback | None = None

    def has_custom_autonomous_policies(self) -> bool:
        """Report whether a caller supplied a non-default policy strategy."""
        defaults = (
            ("situation_policy", DEFAULT_SITUATION_ASSESSMENT_POLICY),
            ("candidate_policy", DEFAULT_CANDIDATE_GENERATION_POLICY),
            ("evaluation_policy", DEFAULT_ACTION_EVALUATION_POLICY),
            ("review_policy", DEFAULT_DECISION_REVIEW_POLICY),
        )
        return (
            getattr(self, "conflict_opportunity_scheduler", None) is not None
            or any(getattr(self, name, default) != default for name, default in defaults)
        )

    def propose(
        self, context: Mapping[str, Any] | CognitionState | DecisionContext
    ) -> ActionProposal:
        """Prefer DecisionContext while retaining legacy input compatibility.

        The decision boundary consumes snapshots only; it has no Store or
        WorldState reference and does not apply cognition changes.
        """
        if isinstance(context, DecisionContext):
            return self._propose_from_context(context)
        if isinstance(context, CognitionState):
            agent_id = context.agent_id
        elif isinstance(context, Mapping):
            agent_id = context.get("agent_id")
        else:
            raise TypeError(
                "context must be a DecisionContext, CognitionState, or mapping"
            )
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("context must contain a non-empty agent_id")

        return ActionProposal(
            proposal_id=f"action-proposal:{agent_id}:placeholder",
            agent_id=agent_id,
            action_type="unselected",
            metadata={"status": "placeholder"},
        )

    def propose_from_candidates(
        self, context: DecisionContext, candidates: tuple[ActionCandidate, ...]
    ) -> ActionProposal:
        """Use the existing owner, evaluation and review path for supplied choices."""
        if not isinstance(context, DecisionContext):
            raise TypeError("social candidates require a frozen DecisionContext")
        return self._propose_from_context(context, candidate_batch=candidates)

    def _propose_from_context(
        self,
        context: DecisionContext,
        *,
        candidate_batch: tuple[ActionCandidate, ...] | None = None,
    ) -> ActionProposal:
        situation_policy = getattr(
            self, "situation_policy", DEFAULT_SITUATION_ASSESSMENT_POLICY
        )
        candidate_policy = getattr(
            self, "candidate_policy", DEFAULT_CANDIDATE_GENERATION_POLICY
        )
        evaluation_policy = getattr(
            self, "evaluation_policy", DEFAULT_ACTION_EVALUATION_POLICY
        )
        review_policy = getattr(self, "review_policy", DEFAULT_DECISION_REVIEW_POLICY)

        situation = situation_policy.assess(context)
        if situation.owner_id != context.cognition_state.agent_id:
            raise PermissionError("situation assessment belongs to another Agent")
        generated = candidate_policy.generate(situation) if candidate_batch is None else candidate_batch
        if (
            isinstance(generated, tuple)
            and len(generated) == 2
            and isinstance(generated[1], str)
            and isinstance(generated[0], tuple)
        ):
            candidates, generation_mode = generated
        else:
            candidates = generated
            generation_mode = "replaceable_candidate_policy"
        if (
            not isinstance(candidates, tuple)
            or not candidates
            or len(candidates) > MAX_CANDIDATES
            or any(not isinstance(candidate, ActionCandidate) for candidate in candidates)
        ):
            raise ValueError("candidate policy returned an invalid or over-budget candidate batch")
        known_goals = {goal.goal_id for goal in situation.goals}
        authorized_sources = {
            reference
            for fact in situation.observed_facts
            for reference in (fact.percept_id, fact.source_event_id)
        }
        authorized_sources.update(memory.source_event_id for memory in situation.memories)
        authorized_sources.update(reference for belief in situation.beliefs for reference in belief.source_refs)
        candidate_ids: set[str] = set()
        for candidate in candidates:
            if candidate.owner_id != situation.owner_id:
                raise PermissionError("action candidate belongs to another Agent")
            if candidate.candidate_id in candidate_ids:
                raise ValueError("candidate IDs must be unique within one turn")
            candidate_ids.add(candidate.candidate_id)
            if candidate.goal_id is not None and candidate.goal_id not in known_goals:
                raise PermissionError("action candidate references a Goal outside the current context")
            if not set(candidate.source_refs).issubset(authorized_sources):
                raise PermissionError("candidate contains an unverified cognition trace reference")
            if len(candidate.steps) > 5:
                raise ValueError("candidate plan exceeds the per-turn step budget")

        scheduler = getattr(self, "conflict_opportunity_scheduler", None)
        if scheduler is not None:
            simulation_tick = getattr(self, "simulation_tick", None)
            if (
                isinstance(simulation_tick, bool)
                or not isinstance(simulation_tick, int)
                or simulation_tick < 0
            ):
                raise ValueError("Runtime-bound scheduler requires a trusted simulation tick")
            findings = scheduler.discover(
                situation, candidates, simulation_tick=simulation_tick
            )
            if not isinstance(findings, tuple):
                raise TypeError("scheduler must return an immutable finding tuple")
            # Scheduler findings are non-authoritative, owner-scoped assessment
            # inputs. They do not alter candidate generation or the proposal's
            # claimed outcome.
            if any(
                getattr(finding, "owner_id", None) != situation.owner_id
                for finding in findings
            ):
                raise PermissionError("scheduler returned a finding for another Agent")
            situation = replace(situation, scheduler_findings=findings)

        evaluations = evaluation_policy.evaluate(situation, candidates)
        if not isinstance(evaluations, tuple) or len(evaluations) != len(candidates):
            raise ValueError("evaluation policy returned an incomplete evaluation batch")
        if review_policy.should_review(situation, evaluations):
            evaluations = review_policy.reassess(situation, candidates, evaluations)
        feedback = getattr(self, "behavior_feedback", None)
        if feedback is not None:
            evaluations = feedback.adjust(
                situation, candidates, evaluations, tick=self.simulation_tick,
            )
        if not evaluations or any(
            isinstance(item.score, bool)
            or not isinstance(item.score, (int, float))
            or not math.isfinite(float(item.score))
            for item in evaluations
        ):
            raise ValueError("candidate evaluation contains no usable scores")
        evaluation_by_id = {item.candidate_id: item for item in evaluations}
        if set(evaluation_by_id) != candidate_ids:
            raise ValueError("candidate evaluations do not correspond to this candidate batch")
        selected = min(
            candidates,
            key=lambda candidate: (-float(evaluation_by_id[candidate.candidate_id].score), candidate.candidate_id),
        )
        from cognitive_world.cognition.action_expectation import capture_selection_time, bind_selection
        selection_tick = capture_selection_time()
        decision_trace = tuple(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_source": candidate.strategy,
                "goal_id": candidate.goal_id,
                "intent": candidate.intent,
                "target": candidate.target,
                "method": candidate.method,
                "required_capabilities": candidate.required_capabilities,
                # Retain the provenance already checked for this candidate so
                # speculative branches can cite, but never broaden, its basis.
                "source_refs": candidate.source_refs,
                "domain_payload": candidate.domain_payload,
                "score": float(evaluation_by_id[candidate.candidate_id].score),
                "factors": evaluation_by_id[candidate.candidate_id].factors,
                "uncertainty": evaluation_by_id[candidate.candidate_id].uncertainty,
                "scheduler_finding_ids": tuple(
                    finding.finding_id
                    for finding in situation.scheduler_findings
                    if candidate.candidate_id in finding.candidate_ids
                ),
            }
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    -float(evaluation_by_id[item.candidate_id].score), item.candidate_id
                ),
            )
        )
        proposal = ActionProposal(
            proposal_id=f"action-proposal:{situation.owner_id}:{uuid4().hex}",
            agent_id=situation.owner_id,
            # ActionProposal.action_type has always been an open string; use
            # the candidate's own intent rather than imposing an action enum.
            action_type=selected.intent,
            target_refs=[] if selected.target is None else [selected.target],
            parameters={
                "goal_id": selected.goal_id,
                "intent": selected.intent,
                "method": selected.method,
                "tools": selected.tools,
                "required_capabilities": selected.required_capabilities,
                "preconditions": selected.preconditions,
                "steps": selected.steps,
                "expected_result": selected.expected_result,
                "uncertainties": selected.uncertainties,
                "estimated_risk": selected.estimated_risk,
                "estimated_cost": selected.estimated_cost,
                "commitment": selected.commitment,
                "domain_payload": selected.domain_payload,
            },
            reasoning_refs=list(selected.source_refs),
            metadata={
                "candidate_id": selected.candidate_id,
                "candidate_source": selected.strategy,
                "generation_mode": generation_mode,
                "status": "attempt_proposed",
                # Bounded numeric/rule diagnostics for engineering reports;
                # this is not passed through the Presentation contract.
                "decision_trace": decision_trace,
                "selected_candidate_id": selected.candidate_id,
            },
        )
        return bind_selection(proposal, selection_tick, selected=selected)
