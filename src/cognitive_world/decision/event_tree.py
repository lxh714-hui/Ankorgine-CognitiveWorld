"""Bounded, non-authoritative exploration of decision candidates.

This slice deliberately records candidate alternatives only. It does not
simulate effects, clone WorldState, or create hypothetical Events.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from typing import Protocol

from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.autonomous import ActionCandidate, MAX_CANDIDATES


MAX_EVENT_TREE_BRANCHES = 4
MAX_EVENT_TREE_PROPOSALS = 2
MAX_EVENT_TREE_PROVIDER_CALLS = 2


@dataclass(frozen=True)
class EventTreeBranch:
    """One possible action branch, not a prediction or confirmed result."""

    node_id: str
    parent_id: str
    candidate_id: str
    owner_id: str
    intent: str
    target: str | None
    method: str
    goal_id: str | None
    source_refs: tuple[str, ...]
    subjective_score: float | None
    evaluation_factors: tuple[tuple[str, float], ...]
    uncertainties: tuple[str, ...]
    selected_by_decision: bool
    assessed: bool
    scheduler_finding_ids: tuple[str, ...] = ()
    candidate_source: str | None = None
    expansion_status: str = "unexplored"
    expansion_reason: str | None = None


@dataclass(frozen=True)
class EventTreePruning:
    """A proposed alternative omitted from the materialized tree, with its basis."""

    candidate_id: str
    parent_id: str
    source_refs: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class EventTreeSnapshot:
    """Immutable per-turn candidate tree projection for runtime diagnostics."""

    tree_id: str
    owner_id: str
    root_id: str
    branches: tuple[EventTreeBranch, ...]
    branch_budget: int
    pruned_candidate_ids: tuple[str, ...]
    pending_candidate_count: int
    source_proposal_id: str = ""
    simulation_tick: int | None = None
    pruning: tuple[EventTreePruning, ...] = ()
    provider_calls_used: int = 0
    provider_call_budget: int = MAX_EVENT_TREE_PROVIDER_CALLS

    @property
    def semantics(self) -> str:
        return "candidate_exploration_only"


@dataclass(frozen=True)
class EventTreeBranchProposalContext:
    """Minimal authorized references supplied to an optional branch provider."""

    tree_id: str
    owner_id: str
    parent_id: str
    authorized_source_refs: tuple[str, ...]
    authorized_targets: tuple[str, ...]
    authorized_goal_ids: tuple[str, ...]
    remaining_branch_budget: int
    remaining_provider_calls: int = 0


class EventTreeBranchProposalProvider(Protocol):
    """Optional host-injected proposer; implementations never receive WorldState."""

    def propose_branches(
        self, context: EventTreeBranchProposalContext
    ) -> tuple[ActionCandidate, ...]: ...


@dataclass(frozen=True)
class _CandidateRecord:
    candidate_id: str
    goal_id: str | None
    intent: str
    target: str | None
    method: str
    source_refs: tuple[str, ...]
    score: float
    factors: tuple[tuple[str, float], ...]
    uncertainty: tuple[str, ...]
    scheduler_finding_ids: tuple[str, ...]
    candidate_source: str | None


class EventTreeExplorer:
    """Lazily materialize a bounded tree over a decision's evaluated options."""

    def __init__(
        self,
        proposal: ActionProposal,
        *,
        branch_budget: int = MAX_EVENT_TREE_BRANCHES,
        simulation_tick: int | None = None,
        provider_call_budget: int = MAX_EVENT_TREE_PROVIDER_CALLS,
        scheduler_finding_ids: tuple[str, ...] | None = None,
    ) -> None:
        if not isinstance(proposal, ActionProposal):
            raise TypeError("EventTreeExplorer requires an ActionProposal")
        if (
            isinstance(branch_budget, bool)
            or not isinstance(branch_budget, int)
            or not 1 <= branch_budget <= MAX_EVENT_TREE_BRANCHES
        ):
            raise ValueError("branch_budget is outside the trusted per-turn bound")
        if simulation_tick is not None and (
            isinstance(simulation_tick, bool) or not isinstance(simulation_tick, int)
            or simulation_tick < 0
        ):
            raise ValueError("simulation_tick must be a trusted non-negative integer")
        if (
            isinstance(provider_call_budget, bool)
            or not isinstance(provider_call_budget, int)
            or not 0 <= provider_call_budget <= MAX_EVENT_TREE_PROVIDER_CALLS
        ):
            raise ValueError("provider_call_budget exceeds the trusted per-turn bound")
        self._proposal = proposal
        self._simulation_tick = simulation_tick
        self._provider_call_budget = provider_call_budget
        self._provider_calls_used = 0
        self._owner_id = proposal.agent_id
        self._tree_id = f"event-tree:{proposal.proposal_id}"
        self._root_id = f"{self._tree_id}:root"
        self._branch_budget = branch_budget
        self._selected_id = proposal.metadata.get("selected_candidate_id")
        trace = proposal.metadata.get("decision_trace", ())
        self._candidates = self._validated_trace(trace)
        if scheduler_finding_ids is not None:
            if not isinstance(scheduler_finding_ids, tuple) or any(
                not isinstance(item, str) or not item for item in scheduler_finding_ids
            ):
                raise ValueError("scheduler finding IDs are malformed")
            allowed_findings = set(scheduler_finding_ids)
            if any(
                not set(item.scheduler_finding_ids).issubset(allowed_findings)
                for item in self._candidates
            ):
                raise PermissionError("decision trace cites an unissued scheduler finding")
        candidate_ids = {item.candidate_id for item in self._candidates}
        if self._selected_id is not None and self._selected_id not in candidate_ids:
            raise ValueError("selected candidate is absent from the decision trace")
        self._pending = list(self._candidates)
        self._branches: list[EventTreeBranch] = []
        self._pruned: list[str] = []
        self._pruning: list[EventTreePruning] = []
        self._expanded_parents: set[str] = set()
        self._provider_semantics: set[tuple[object, ...]] = set()

    @classmethod
    def from_proposal(
        cls,
        proposal: ActionProposal,
        *,
        branch_budget: int = MAX_EVENT_TREE_BRANCHES,
        simulation_tick: int | None = None,
        provider_call_budget: int = MAX_EVENT_TREE_PROVIDER_CALLS,
        scheduler_finding_ids: tuple[str, ...] | None = None,
    ) -> "EventTreeExplorer":
        return cls(
            proposal, branch_budget=branch_budget,
            simulation_tick=simulation_tick,
            provider_call_budget=provider_call_budget,
            scheduler_finding_ids=scheduler_finding_ids,
        )

    @staticmethod
    def _validated_trace(trace: object) -> tuple[_CandidateRecord, ...]:
        if not isinstance(trace, (tuple, list)) or len(trace) > MAX_CANDIDATES:
            raise ValueError("decision trace is malformed or exceeds the candidate bound")
        records: list[_CandidateRecord] = []
        seen: set[str] = set()
        for item in trace:
            if not isinstance(item, Mapping):
                raise TypeError("decision trace entries must be mappings")
            candidate_id = item.get("candidate_id")
            intent = item.get("intent")
            method = item.get("method")
            target = item.get("target")
            goal_id = item.get("goal_id")
            score = item.get("score")
            if (
                not isinstance(candidate_id, str) or not candidate_id
                or candidate_id in seen
                or not isinstance(intent, str) or not intent
                or not isinstance(method, str) or not method
                or (target is not None and not isinstance(target, str))
                or (goal_id is not None and not isinstance(goal_id, str))
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
            ):
                raise ValueError("decision trace contains an invalid candidate record")
            refs = item.get("source_refs", ())
            factors = item.get("factors", ())
            uncertainty = item.get("uncertainty", ())
            scheduler_finding_ids = item.get("scheduler_finding_ids", ())
            candidate_source = item.get("candidate_source")
            if candidate_source is not None and (
                not isinstance(candidate_source, str) or not candidate_source
            ):
                raise ValueError("candidate generation source is malformed")
            if not isinstance(refs, (tuple, list)) or any(
                not isinstance(ref, str) or not ref for ref in refs
            ):
                raise ValueError("candidate source references are malformed")
            if not isinstance(factors, (tuple, list)):
                raise ValueError("candidate evaluation factors are malformed")
            normalized_factors: list[tuple[str, float]] = []
            for factor in factors:
                if (
                    not isinstance(factor, (tuple, list)) or len(factor) != 2
                    or not isinstance(factor[0], str)
                    or isinstance(factor[1], bool)
                    or not isinstance(factor[1], (int, float))
                    or not math.isfinite(float(factor[1]))
                ):
                    raise ValueError("candidate evaluation factor is malformed")
                normalized_factors.append((factor[0], float(factor[1])))
            if not isinstance(uncertainty, (tuple, list)) or any(
                not isinstance(value, str) for value in uncertainty
            ):
                raise ValueError("candidate uncertainty is malformed")
            if not isinstance(scheduler_finding_ids, (tuple, list)) or len(scheduler_finding_ids) > 8 or any(
                not isinstance(value, str) or not value for value in scheduler_finding_ids
            ):
                raise ValueError("scheduler finding references are malformed")
            seen.add(candidate_id)
            records.append(_CandidateRecord(
                candidate_id, goal_id, intent, target, method,
                tuple(refs), float(score), tuple(normalized_factors), tuple(uncertainty),
                tuple(scheduler_finding_ids),
                candidate_source,
            ))
        return tuple(sorted(records, key=lambda row: (-row.score, row.candidate_id)))

    @property
    def remaining_branch_budget(self) -> int:
        return self._branch_budget - len(self._branches)

    def expand(self, count: int = 1) -> tuple[EventTreeBranch, ...]:
        """Materialize up to ``count`` candidate children without resolving them."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("expansion count must be a non-negative integer")
        amount = min(count, self.remaining_branch_budget, len(self._pending))
        added: list[EventTreeBranch] = []
        for _ in range(amount):
            candidate = self._pending.pop(0)
            branch = EventTreeBranch(
                node_id=f"{self._tree_id}:candidate:{candidate.candidate_id}",
                parent_id=self._root_id,
                candidate_id=candidate.candidate_id,
                owner_id=self._owner_id,
                intent=candidate.intent,
                target=candidate.target,
                method=candidate.method,
                goal_id=candidate.goal_id,
                source_refs=candidate.source_refs,
                subjective_score=candidate.score,
                evaluation_factors=candidate.factors,
                uncertainties=candidate.uncertainty,
                selected_by_decision=candidate.candidate_id == self._selected_id,
                assessed=True,
                scheduler_finding_ids=candidate.scheduler_finding_ids,
                candidate_source=candidate.candidate_source,
            )
            self._branches.append(branch)
            added.append(branch)
        if self.remaining_branch_budget == 0:
            for item in self._pending:
                self._pruned.append(item.candidate_id)
                self._pruning.append(EventTreePruning(
                    item.candidate_id, self._root_id, item.source_refs,
                    "global_branch_budget",
                ))
            self._pending.clear()
        return tuple(added)

    def _set_expansion_state(self, node_id: str, status: str, reason: str | None) -> None:
        for index, branch in enumerate(self._branches):
            if branch.node_id == node_id:
                self._branches[index] = replace(
                    branch, expansion_status=status, expansion_reason=reason,
                )
                return

    @staticmethod
    def _semantic_key(candidate: ActionCandidate) -> tuple[object, ...]:
        return (
            candidate.goal_id, candidate.intent, candidate.target,
            candidate.method, candidate.tools, candidate.required_capabilities,
            candidate.preconditions, candidate.steps, candidate.expected_result,
            tuple(sorted(candidate.source_refs)),
        )

    def expand_with_provider(
        self,
        parent_id: str,
        provider: EventTreeBranchProposalProvider,
    ) -> tuple[EventTreeBranch, ...]:
        """Accept bounded unassessed branches from an explicit local/host provider.

        Provider output remains hypothetical. It cannot add evidence references,
        goals, targets, authority, or world effects outside this decision trace.
        """
        parent = next((branch for branch in self._branches if branch.node_id == parent_id), None)
        if parent is None:
            raise ValueError("provider expansion requires an existing branch parent")
        if parent_id in self._expanded_parents:
            return ()
        remaining = self.remaining_branch_budget
        if remaining <= 0:
            self._set_expansion_state(parent_id, "pruned", "global_branch_budget")
            return ()
        if self._provider_calls_used >= self._provider_call_budget:
            self._set_expansion_state(parent_id, "pruned", "provider_call_budget")
            return ()
        allowed_refs = tuple(sorted({ref for row in self._candidates for ref in row.source_refs}))
        allowed_targets = tuple(sorted({row.target for row in self._candidates if row.target is not None}))
        allowed_goals = tuple(sorted({row.goal_id for row in self._candidates if row.goal_id is not None}))
        context = EventTreeBranchProposalContext(
            self._tree_id, self._owner_id, parent.node_id,
            allowed_refs, allowed_targets, allowed_goals,
            min(remaining, MAX_EVENT_TREE_PROPOSALS),
            self._provider_call_budget - self._provider_calls_used,
        )
        self._expanded_parents.add(parent_id)
        self._provider_calls_used += 1
        try:
            proposals = provider.propose_branches(context)
            if not isinstance(proposals, tuple) or len(proposals) > context.remaining_branch_budget:
                raise ValueError("branch provider exceeded its output budget")
            added: list[EventTreeBranch] = []
            duplicates: list[EventTreePruning] = []
            known_ids = {row.candidate_id for row in self._candidates}
            known_ids.update(branch.candidate_id for branch in self._branches)
            known_semantics = set(self._provider_semantics)
            for candidate in proposals:
                if not isinstance(candidate, ActionCandidate):
                    raise TypeError("branch provider must return existing ActionCandidate values")
                if candidate.owner_id != self._owner_id:
                    raise PermissionError("branch candidate belongs to another Agent")
                if candidate.goal_id is not None and candidate.goal_id not in allowed_goals:
                    raise PermissionError("branch candidate uses an ungrounded Goal")
                if candidate.target is not None and candidate.target not in allowed_targets:
                    raise PermissionError("branch candidate uses an ungrounded target")
                if not set(candidate.source_refs).issubset(allowed_refs):
                    raise PermissionError("branch candidate cites unauthorized evidence")
                key = self._semantic_key(candidate)
                if candidate.candidate_id in known_ids or key in known_semantics:
                    duplicates.append(EventTreePruning(
                        candidate.candidate_id, parent_id, candidate.source_refs,
                        "duplicate_candidate",
                    ))
                    continue
                known_ids.add(candidate.candidate_id)
                known_semantics.add(key)
                added.append(EventTreeBranch(
                    node_id=f"{self._tree_id}:candidate:{candidate.candidate_id}",
                    parent_id=parent.node_id,
                    candidate_id=candidate.candidate_id,
                    owner_id=self._owner_id,
                    intent=candidate.intent,
                    target=candidate.target,
                    method=candidate.method,
                    goal_id=candidate.goal_id,
                    source_refs=candidate.source_refs,
                    subjective_score=None,
                    evaluation_factors=(),
                    uncertainties=candidate.uncertainties,
                    selected_by_decision=False,
                    assessed=False,
                    candidate_source=candidate.strategy,
                ))
        except Exception:
            self._set_expansion_state(parent_id, "blocked", "provider_error")
            raise
        self._branches.extend(added)
        added_ids = {branch.candidate_id for branch in added}
        self._provider_semantics.update(
            self._semantic_key(candidate) for candidate in proposals
            if candidate.candidate_id in added_ids
        )
        self._pruning.extend(duplicates)
        self._pruned.extend(item.candidate_id for item in duplicates)
        self._set_expansion_state(parent_id, "expanded", None)
        return tuple(added)

    def snapshot(self) -> EventTreeSnapshot:
        return EventTreeSnapshot(
            tree_id=self._tree_id,
            owner_id=self._owner_id,
            root_id=self._root_id,
            branches=tuple(self._branches),
            branch_budget=self._branch_budget,
            pruned_candidate_ids=tuple(self._pruned),
            pending_candidate_count=len(self._pending),
            source_proposal_id=self._proposal.proposal_id,
            simulation_tick=self._simulation_tick,
            pruning=tuple(self._pruning),
            provider_calls_used=self._provider_calls_used,
            provider_call_budget=self._provider_call_budget,
        )
