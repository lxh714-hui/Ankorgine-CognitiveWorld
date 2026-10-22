"""Owner-scoped, non-authoritative conflict/opportunity scheduling.

The scheduler consumes the same frozen SituationAssessment and ActionCandidate
batch used by AgentDecision. Its lifecycle records are process-local attention
state, not WorldState, EventHistory, cognition, or an alternate planner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Protocol

from cognitive_world.decision.autonomous import (
    ActionCandidate,
    ConflictOpportunityCandidate,
    SchedulerEvidenceRef,
    SituationAssessment,
)


MAX_FINDINGS_PER_TURN = 8
MAX_TRACKED_FINDINGS = 256
MAX_PROVIDER_OUTPUT_CHARS = 12_000
MAX_PROVIDER_CANDIDATES = 8
MAX_MISSED_TURNS_BEFORE_DORMANT = 2
MAX_CROSS_AGENT_GOAL_PROJECTIONS = 512


@dataclass(frozen=True)
class CrossAgentGoalProjection:
    """Runtime-issued minimum projection of one canonical resource demand.

    It contains no Goal prose or priority. The slot receipt grounds the
    referenced resource in the current authoritative WorldState.
    """

    owner_id: str
    goal_id: str
    goal_revision: str
    resource_ref: str
    scope_ref: str | None
    exclusive_use: bool
    simulation_tick: int
    resource_slot_read: object

    def __post_init__(self) -> None:
        for name in ("owner_id", "goal_id", "goal_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if not self.resource_ref.startswith("object:") or not self.resource_ref.removeprefix("object:"):
            raise ValueError("resource_ref must be an object namespace reference")
        if self.scope_ref is not None and (not isinstance(self.scope_ref, str) or not self.scope_ref):
            raise ValueError("scope_ref must be non-empty or None")
        if type(self.exclusive_use) is not bool:
            raise TypeError("exclusive_use must be bool")
        if isinstance(self.simulation_tick, bool) or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0:
            raise ValueError("simulation_tick must be non-negative")


def goal_resource_revision(goal: object) -> str:
    """Fingerprint only the active identity and structured demand semantics."""
    demands = tuple(
        sorted((item.resource_ref, item.scope_ref, item.exclusive_use)
               for item in getattr(goal, "resource_demands", ()))
    )
    material = json.dumps(
        (getattr(goal, "owner_id", None), getattr(goal, "goal_id", None),
         getattr(goal, "status", None), demands),
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConflictOpportunityProviderContext:
    """Narrow owner-local context for an explicitly injected analyzer.

    This excludes Memory, Beliefs, Emotion, Personality, WorldState, and other
    Agents' cognition. Host configuration remains responsible for data-scope
    approval before connecting any external transport.
    """

    observed_facts: tuple[tuple[str, str, str, str, str], ...]
    goals: tuple[tuple[str, str, float, bool, tuple[str, ...]], ...]
    affordances: tuple[tuple[str, str, str, tuple[str, ...]], ...]
    candidates: tuple[tuple[str, str | None, str | None, str, tuple[str, ...]], ...]
    allowed_source_refs: tuple[str, ...]
    allowed_goal_ids: tuple[str, ...]
    allowed_target_refs: tuple[str, ...]
    allowed_candidate_ids: tuple[str, ...]
    max_output_chars: int


class ConflictOpportunityAnalysisProvider(Protocol):
    """Optional model/local analysis adapter; output is untrusted structured data."""

    def analyze(
        self,
        context: ConflictOpportunityProviderContext,
        *,
        max_candidates: int,
        max_output_chars: int,
    ) -> str: ...


@dataclass
class _TrackedFinding:
    value: ConflictOpportunityCandidate
    last_evaluated_tick: int
    missed_turns: int = 0


class ConflictOpportunityScheduler:
    """Discover, deduplicate, rank, and track owner-local attention candidates."""

    def __init__(
        self,
        *,
        provider: ConflictOpportunityAnalysisProvider | None = None,
        maximum_findings_per_turn: int = MAX_FINDINGS_PER_TURN,
    ) -> None:
        if (
            isinstance(maximum_findings_per_turn, bool)
            or not isinstance(maximum_findings_per_turn, int)
            or not 1 <= maximum_findings_per_turn <= MAX_FINDINGS_PER_TURN
        ):
            raise ValueError("scheduler finding budget exceeds the trusted bound")
        if provider is not None and not callable(getattr(provider, "analyze", None)):
            raise TypeError("scheduler provider must expose analyze(context, ...)")
        self.provider = provider
        self.maximum_findings_per_turn = maximum_findings_per_turn
        self._tracked: dict[tuple[str, str], _TrackedFinding] = {}
        self._latest_tick: dict[str, int] = {}
        self._turn_results: dict[tuple[str, int], tuple[ConflictOpportunityCandidate, ...]] = {}
        self._provider_errors: dict[tuple[str, int], str] = {}
        self._cross_agent_goal_projections: tuple[CrossAgentGoalProjection, ...] = ()
        self._cross_agent_world_state: object | None = None
        self._cross_agent_event_history: object | None = None
        self._cross_agent_tick: int | None = None

    def bind_cross_agent_goal_projections(
        self,
        projections: tuple[CrossAgentGoalProjection, ...],
        *,
        world_state: object,
        event_history: object,
        simulation_tick: int,
    ) -> None:
        """Bind one Runtime-built, bounded projection for this simulation tick."""
        if not isinstance(projections, tuple) or len(projections) > MAX_CROSS_AGENT_GOAL_PROJECTIONS:
            raise ValueError("cross-agent Goal projection is malformed or over budget")
        if isinstance(simulation_tick, bool) or not isinstance(simulation_tick, int) or simulation_tick < 0:
            raise ValueError("simulation_tick must be non-negative")
        from cognitive_world.core.world_state import WorldState, WorldStateSlotRead

        if not isinstance(world_state, WorldState):
            raise TypeError("cross-agent Goal projection requires canonical WorldState")
        accepted = []
        seen = set()
        for item in projections:
            if not isinstance(item, CrossAgentGoalProjection) or item.simulation_tick != simulation_tick:
                raise ValueError("cross-agent Goal projection is stale or malformed")
            if item in seen:
                continue
            seen.add(item)
            read = item.resource_slot_read
            identifier = item.resource_ref.removeprefix("object:")
            if (
                not isinstance(read, WorldStateSlotRead)
                or read.slot.collection != "entities"
                or read.slot.record_id != identifier
                or read.slot.path != ("type",)
                or not read.present
                or not isinstance(read.value, str)
                or not read.value
                or read.origin_kind not in {"event", "initialization"}
                or not world_state.verify_state_slot_read(read, event_history=event_history)
            ):
                # An ungrounded resource is not promoted to a conflict.
                continue
            accepted.append(item)
        self._cross_agent_goal_projections = tuple(accepted)
        self._cross_agent_world_state = world_state
        self._cross_agent_event_history = event_history
        self._cross_agent_tick = simulation_tick

    @staticmethod
    def _unit(value: float) -> float:
        if not math.isfinite(float(value)):
            return 0.0
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _finding_id(
        owner_id: str,
        kind: str,
        goal_ids: tuple[str, ...],
        target_refs: tuple[str, ...],
    ) -> str:
        material = json.dumps(
            (owner_id, kind, tuple(sorted(goal_ids)), tuple(sorted(target_refs))),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return "scheduler-finding:" + hashlib.sha256(material).hexdigest()[:24]

    @staticmethod
    def _source_sets(
        situation: SituationAssessment,
    ) -> tuple[set[str], set[str], set[str]]:
        percepts = {item.percept_id for item in situation.observed_facts if item.percept_id}
        events = {item.source_event_id for item in situation.observed_facts if item.source_event_id}
        goals = {item.goal_id for item in situation.goals}
        owner_local_sources = (
            percepts
            | events
            | {ref for belief in situation.beliefs for ref in belief.source_refs}
            | {memory.source_event_id for memory in situation.memories}
        )
        for item in situation.goals:
            if any(ref not in owner_local_sources for ref in item.source_refs):
                raise PermissionError("Goal source reference is outside the current owner view")
        for affordance in situation.affordances:
            if any(ref not in percepts | events for ref in affordance.source_refs):
                raise PermissionError("affordance source is outside the current owner view")
        return percepts, events, goals

    def discover(
        self,
        situation: SituationAssessment,
        candidates: tuple[ActionCandidate, ...],
        *,
        simulation_tick: int,
    ) -> tuple[ConflictOpportunityCandidate, ...]:
        """Return current bounded findings and update only scheduler lifecycle state."""
        if not isinstance(situation, SituationAssessment):
            raise TypeError("scheduler requires owner-scoped SituationAssessment")
        if (
            isinstance(simulation_tick, bool)
            or not isinstance(simulation_tick, int)
            or simulation_tick < 0
        ):
            raise ValueError("scheduler requires a non-negative trusted simulation tick")
        owner = situation.owner_id
        previous_tick = self._latest_tick.get(owner, simulation_tick)
        if simulation_tick < previous_tick:
            raise ValueError("scheduler simulation time moved backwards")
        if not isinstance(candidates, tuple) or len(candidates) > 6:
            raise ValueError("scheduler candidate input is malformed or over budget")
        percept_refs, event_refs, goal_ids = self._source_sets(situation)
        candidate_ids: set[str] = set()
        by_goal: dict[str, list[ActionCandidate]] = {}
        affordances_by_target = {item.target_ref: item for item in situation.affordances}
        for candidate in candidates:
            if not isinstance(candidate, ActionCandidate) or candidate.owner_id != owner:
                raise PermissionError("scheduler candidate is not owned by the current Agent")
            if candidate.candidate_id in candidate_ids:
                raise ValueError("scheduler candidate IDs must be unique")
            candidate_ids.add(candidate.candidate_id)
            if candidate.goal_id is not None:
                if candidate.goal_id not in goal_ids:
                    raise PermissionError("scheduler candidate references an unavailable Goal")
                by_goal.setdefault(candidate.goal_id, []).append(candidate)
            if not set(candidate.source_refs).issubset(percept_refs | event_refs | {
                ref for goal in situation.goals for ref in goal.source_refs
            } | {ref for belief in situation.beliefs for ref in belief.source_refs}
            | {memory.source_event_id for memory in situation.memories}):
                raise PermissionError("scheduler candidate cites evidence outside the owner view")

        raw: dict[str, ConflictOpportunityCandidate] = {}
        for finding in self._cross_agent_findings(owner, candidates, simulation_tick):
            raw[finding.finding_id] = finding
        goals = {item.goal_id: item for item in situation.goals}

        # Structured owner-local Goal tension; this is not a world conflict or
        # a claim about another Agent's intention.
        for left, right in situation.goal_conflicts:
            if left not in goals or right not in goals or left == right:
                continue
            goal_ids_pair = tuple(sorted((left, right)))
            refs = tuple(SchedulerEvidenceRef("goal", item) for item in goal_ids_pair)
            related = tuple(sorted({
                candidate.candidate_id
                for goal_id in goal_ids_pair
                for candidate in by_goal.get(goal_id, ())
            }))
            importance = max(
                self._unit(goals[left].motivation_score),
                self._unit(goals[right].motivation_score),
            )
            finding = self._make_finding(
                owner, "conflict", goal_ids_pair, (), related, refs,
                importance, 1.0,
                ("This is an owner-local goal tension, not an objective world conflict.",),
                simulation_tick,
            )
            raw[finding.finding_id] = finding

        # An opportunity is emitted only when an existing candidate's goal,
        # target, and cited observation source all match an observed affordance.
        for candidate in candidates:
            affordance = affordances_by_target.get(candidate.target or "")
            goal = goals.get(candidate.goal_id or "")
            if affordance is None or goal is None or goal.blocked:
                continue
            if not affordance.source_refs or not set(affordance.source_refs).issubset(candidate.source_refs):
                continue
            refs = [SchedulerEvidenceRef("goal", goal.goal_id)]
            refs.extend(
                SchedulerEvidenceRef("percept" if ref in percept_refs else "event", ref)
                for ref in affordance.source_refs
            )
            finding = self._make_finding(
                owner, "opportunity", (goal.goal_id,), (affordance.target_ref,),
                (candidate.candidate_id,), tuple(refs),
                self._unit(goal.motivation_score), 1.0,
                tuple(dict.fromkeys((
                    *candidate.uncertainties,
                    "The observed affordance does not confirm the candidate's expected result.",
                ))), simulation_tick,
            )
            raw[finding.finding_id] = finding

        provider_error = None
        if self.provider is not None:
            try:
                for finding in self._provider_findings(situation, candidates, simulation_tick):
                    existing = raw.get(finding.finding_id)
                    raw[finding.finding_id] = finding if existing is None else self._merge(existing, finding)
            except Exception as error:
                # A failed optional analyzer cannot erase deterministic findings
                # or authorize an action.
                provider_error = type(error).__name__

        ranked = sorted(raw.values(), key=lambda item: (-item.importance, -item.relevance, item.finding_id))
        considered = ranked[:MAX_TRACKED_FINDINGS]
        selected = considered[: self.maximum_findings_per_turn]
        considered_ids = {item.finding_id for item in considered}
        self._advance_owner_lifecycle(owner, simulation_tick, considered_ids)
        tracked_considered = {
            item.finding_id: self._upsert(item, simulation_tick)
            for item in considered
        }
        tracked = tuple(tracked_considered[item.finding_id] for item in selected)
        tracked = tuple(sorted(tracked, key=lambda item: (-item.importance, -item.relevance, item.finding_id)))
        self._latest_tick[owner] = simulation_tick
        self._turn_results[(owner, simulation_tick)] = tracked
        if provider_error is not None:
            self._provider_errors[(owner, simulation_tick)] = provider_error
        else:
            self._provider_errors.pop((owner, simulation_tick), None)
        # These are per-turn diagnostics only; lifecycle history lives in the
        # bounded _tracked map. Retain the current result, not an unbounded log.
        for key in tuple(self._turn_results):
            if key[0] == owner and key[1] != simulation_tick:
                self._turn_results.pop(key, None)
        for key in tuple(self._provider_errors):
            if key[0] == owner and key[1] != simulation_tick:
                self._provider_errors.pop(key, None)
        self._trim_lifecycle(owner)
        return tracked

    def _cross_agent_findings(
        self,
        owner: str,
        candidates: tuple[ActionCandidate, ...],
        tick: int,
    ) -> tuple[ConflictOpportunityCandidate, ...]:
        if tick != self._cross_agent_tick or self._cross_agent_world_state is None:
            return ()
        world_state = self._cross_agent_world_state
        rows = tuple(
            item for item in self._cross_agent_goal_projections
            if item.simulation_tick == tick
            and world_state.verify_state_slot_read(
                item.resource_slot_read, event_history=self._cross_agent_event_history
            )
        )
        own_rows = tuple(item for item in rows if item.owner_id == owner)
        output = []
        for own in own_rows:
            partners = tuple(
                item for item in rows
                if item.owner_id != owner and item.resource_ref == own.resource_ref
            )
            for partner in partners:
                if own.exclusive_use and partner.exclusive_use:
                    if own.scope_ref is not None and own.scope_ref == partner.scope_ref:
                        kind = "supported_conflict"
                        relevance = 0.6
                        uncertainty = ("Canonical active Goals require exclusive use of the same grounded resource in the same declared scope; "
                                       "this system-level attention item does not establish that this Agent observed another Goal, "
                                       "that any Agent is aware of the comparison, or that an action/world conflict occurred.")
                    else:
                        kind = "potential_conflict"
                        relevance = 0.3
                        uncertainty = ("Both Goals declare exclusive use, but a shared applicable scope is not verified; "
                                       "this system-level attention item does not establish that this Agent observed another Goal.")
                elif own.exclusive_use or partner.exclusive_use:
                    kind = "potential_conflict"
                    relevance = 0.25
                    uncertainty = ("The resource is shared and exclusivity or scope requirements are incomplete; "
                                   "this system-level attention item does not establish that this Agent observed another Goal.")
                else:
                    kind = "shared_target_only"
                    relevance = 0.0
                    uncertainty = ("Goals share a grounded target; no competitive constraint is established, and this does not establish "
                                   "that this Agent observed another Goal.")
                participant_key = tuple(sorted((
                    (own.owner_id, own.goal_id, own.goal_revision),
                    (partner.owner_id, partner.goal_id, partner.goal_revision),
                )))
                issue_material = json.dumps(
                    (participant_key, own.resource_ref, own.scope_ref,
                     partner.scope_ref, kind,
                     own.resource_slot_read.value_fingerprint,
                     own.resource_slot_read.source_event_id),
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
                issue_id = hashlib.sha256(issue_material).hexdigest()[:24]
                finding_id = "cross-goal:" + hashlib.sha256(
                    f"{owner}:{issue_id}".encode("utf-8")
                ).hexdigest()[:24]
                own_candidates = tuple(sorted(
                    item.candidate_id for item in candidates
                    if item.goal_id == own.goal_id
                ))
                slot_material = json.dumps(
                    (own.resource_slot_read.slot.to_record(),
                     own.resource_slot_read.value_fingerprint,
                     own.resource_slot_read.origin_kind),
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
                slot_ref = hashlib.sha256(slot_material).hexdigest()
                source_refs = (
                    SchedulerEvidenceRef("goal", own.goal_id),
                    SchedulerEvidenceRef("goal_revision", own.goal_revision),
                    SchedulerEvidenceRef("world_slot", slot_ref),
                )
                output.append(ConflictOpportunityCandidate(
                    finding_id=finding_id,
                    owner_id=owner,
                    kind=kind,
                    goal_ids=(own.goal_id,),
                    target_refs=(own.resource_ref,),
                    candidate_ids=own_candidates,
                    source_refs=source_refs,
                    importance=1.0,
                    relevance=relevance,
                    uncertainties=(uncertainty,),
                    first_seen_tick=tick,
                    last_seen_tick=tick,
                    sightings=1,
                    revision=1,
                    lifecycle="active",
                ))
        # A Goal may have more than one matching partner; deduplicate the same
        # owner-facing issue without putting partner IDs into its projection.
        unique = {item.finding_id: item for item in output}
        return tuple(unique[key] for key in sorted(unique))

    def _make_finding(
        self,
        owner: str,
        kind: str,
        goals: tuple[str, ...],
        targets: tuple[str, ...],
        candidate_ids: tuple[str, ...],
        refs: tuple[SchedulerEvidenceRef, ...],
        importance: float,
        relevance: float,
        uncertainties: tuple[str, ...],
        tick: int,
    ) -> ConflictOpportunityCandidate:
        finding_id = self._finding_id(owner, kind, goals, targets)
        return ConflictOpportunityCandidate(
            finding_id, owner, kind, tuple(sorted(set(goals))),
            tuple(sorted(set(targets))), tuple(sorted(set(candidate_ids))),
            tuple(sorted(set(refs), key=lambda item: (item.reference_type, item.reference_id))),
            self._unit(importance), self._unit(relevance), tuple(dict.fromkeys(uncertainties)),
            tick, tick, 1, 1, "active",
        )

    @staticmethod
    def _merge(
        left: ConflictOpportunityCandidate,
        right: ConflictOpportunityCandidate,
    ) -> ConflictOpportunityCandidate:
        return replace(
            left,
            candidate_ids=tuple(sorted(set(left.candidate_ids) | set(right.candidate_ids))),
            source_refs=tuple(sorted(set(left.source_refs) | set(right.source_refs), key=lambda item: (item.reference_type, item.reference_id))),
            importance=max(left.importance, right.importance),
            relevance=max(left.relevance, right.relevance),
            uncertainties=tuple(dict.fromkeys((*left.uncertainties, *right.uncertainties))),
        )

    def _provider_findings(
        self,
        situation: SituationAssessment,
        candidates: tuple[ActionCandidate, ...],
        tick: int,
    ) -> tuple[ConflictOpportunityCandidate, ...]:
        provider = self.provider
        if provider is None:
            return ()
        percepts, events, goal_ids = self._source_sets(situation)
        known_refs = tuple(sorted({*(f"percept:{item}" for item in percepts), *(f"event:{item}" for item in events)}))
        context = ConflictOpportunityProviderContext(
            tuple((fact.fact_id or fact.percept_id, fact.source_event_id, fact.fact_type, fact.predicate, fact.value)
                  for fact in situation.observed_facts),
            tuple((goal.goal_id, goal.description, self._unit(goal.motivation_score), goal.blocked, goal.source_refs)
                  for goal in situation.goals),
            tuple((item.target_ref, item.location_id, item.domain, item.source_refs)
                  for item in situation.affordances),
            tuple((item.candidate_id, item.goal_id, item.target, item.intent, item.source_refs)
                  for item in candidates),
            known_refs,
            tuple(sorted(goal_ids)),
            tuple(sorted(item.target_ref for item in situation.affordances)),
            tuple(sorted(item.candidate_id for item in candidates)),
            MAX_PROVIDER_OUTPUT_CHARS,
        )
        raw = provider.analyze(
            context,
            max_candidates=min(MAX_PROVIDER_CANDIDATES, self.maximum_findings_per_turn),
            max_output_chars=MAX_PROVIDER_OUTPUT_CHARS,
        )
        if not isinstance(raw, str) or len(raw) > MAX_PROVIDER_OUTPUT_CHARS:
            raise ValueError("scheduler provider output exceeds its bound")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "findings"} or payload["schema_version"] != 1:
            raise ValueError("scheduler provider returned an invalid root schema")
        rows = payload["findings"]
        if not isinstance(rows, list) or len(rows) > min(MAX_PROVIDER_CANDIDATES, self.maximum_findings_per_turn):
            raise ValueError("scheduler provider exceeded finding count budget")
        goal_set = set(goal_ids)
        target_set = set(context.allowed_target_refs)
        candidate_set = set(context.allowed_candidate_ids)
        candidate_by_id = {item.candidate_id: item for item in candidates}
        reference_map = {f"percept:{ref}": SchedulerEvidenceRef("percept", ref) for ref in percepts}
        reference_map.update({f"event:{ref}": SchedulerEvidenceRef("event", ref) for ref in events})
        goals = {item.goal_id: item for item in situation.goals}
        results = []
        expected = {"kind", "goal_ids", "target_refs", "candidate_ids", "source_refs", "importance", "relevance", "uncertainties"}
        for row in rows:
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError("scheduler provider finding has unknown or missing fields")
            if row["kind"] not in {"conflict", "opportunity"}:
                raise ValueError("scheduler provider finding kind is unsupported")
            for key in ("goal_ids", "target_refs", "candidate_ids", "source_refs", "uncertainties"):
                if not isinstance(row[key], list) or len(row[key]) > 16 or any(not isinstance(item, str) or not item for item in row[key]):
                    raise ValueError(f"scheduler provider {key} is malformed")
            if not set(row["goal_ids"]).issubset(goal_set):
                raise PermissionError("scheduler provider referenced an unavailable owner Goal")
            if not set(row["target_refs"]).issubset(target_set):
                raise PermissionError("scheduler provider referenced an unobserved target")
            if not set(row["candidate_ids"]).issubset(candidate_set):
                raise PermissionError("scheduler provider referenced an unknown candidate")
            if not row["source_refs"] or not set(row["source_refs"]).issubset(reference_map):
                raise PermissionError("scheduler provider cited an unauthorized source")
            for candidate_id in row["candidate_ids"]:
                candidate = candidate_by_id[candidate_id]
                if row["goal_ids"] and candidate.goal_id not in row["goal_ids"]:
                    raise PermissionError("scheduler provider mismatched candidate and Goal")
                if row["target_refs"] and candidate.target not in row["target_refs"]:
                    raise PermissionError("scheduler provider mismatched candidate and target")
                candidate_sources = set(candidate.source_refs)
                cited_evidence = {
                    reference_map[ref].reference_id
                    for ref in row["source_refs"]
                }
                if not cited_evidence.issubset(candidate_sources | set(row["goal_ids"])):
                    raise PermissionError("scheduler provider linked a candidate to unrelated evidence")
            for key in ("importance", "relevance"):
                value = row[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
                    raise ValueError(f"scheduler provider {key} is outside [0,1]")
            results.append(self._make_finding(
                situation.owner_id, row["kind"], tuple(row["goal_ids"]),
                tuple(row["target_refs"]), tuple(row["candidate_ids"]),
                tuple(reference_map[ref] for ref in row["source_refs"]),
                float(row["importance"]), float(row["relevance"]),
                tuple(dict.fromkeys((
                    *row["uncertainties"],
                    "Provider proposal is an unverified interpretation.",
                ))), tick,
            ))
        return tuple(results)

    def _advance_owner_lifecycle(self, owner: str, tick: int, present: set[str]) -> None:
        for (record_owner, _), record in self._tracked.items():
            if record_owner != owner or record.value.finding_id in present:
                continue
            if record.last_evaluated_tick >= tick:
                continue
            missed = record.missed_turns + 1
            lifecycle = "dormant" if missed >= MAX_MISSED_TURNS_BEFORE_DORMANT else "active"
            record.value = replace(record.value, lifecycle=lifecycle)
            record.missed_turns = missed
            record.last_evaluated_tick = tick

    def _upsert(
        self,
        finding: ConflictOpportunityCandidate,
        tick: int,
    ) -> ConflictOpportunityCandidate:
        key = (finding.owner_id, finding.finding_id)
        prior = self._tracked.get(key)
        if prior is None:
            self._tracked[key] = _TrackedFinding(finding, tick)
            return finding
        old = prior.value
        sightings = old.sightings + (1 if old.last_seen_tick < tick else 0)
        changed = any((
            old.kind != finding.kind,
            old.goal_ids != finding.goal_ids,
            old.target_refs != finding.target_refs,
            old.candidate_ids != finding.candidate_ids,
            old.source_refs != finding.source_refs,
            old.importance != finding.importance,
            old.relevance != finding.relevance,
            old.uncertainties != finding.uncertainties,
            old.lifecycle != "active",
        ))
        updated = replace(
            finding,
            first_seen_tick=old.first_seen_tick,
            last_seen_tick=max(old.last_seen_tick, tick),
            sightings=sightings,
            revision=old.revision + (1 if changed else 0),
            lifecycle="active",
        )
        prior.value = updated
        prior.last_evaluated_tick = tick
        prior.missed_turns = 0
        return updated

    def _trim_lifecycle(self, owner: str) -> None:
        owned = [(key, value) for key, value in self._tracked.items() if key[0] == owner]
        if len(owned) <= MAX_TRACKED_FINDINGS:
            return
        eviction_order = sorted(
            owned,
            key=lambda item: (
                item[1].value.lifecycle != "dormant",
                item[1].value.importance,
                item[1].value.relevance,
                item[1].value.last_seen_tick,
                item[0][1],
            ),
        )
        for key, _ in eviction_order[: len(owned) - MAX_TRACKED_FINDINGS]:
            self._tracked.pop(key, None)

    def current_for(self, owner_id: str, simulation_tick: int) -> tuple[ConflictOpportunityCandidate, ...]:
        """Return only this owner's findings produced for the requested turn."""
        return self._turn_results.get((owner_id, simulation_tick), ())

    def tracked_for(self, owner_id: str) -> tuple[ConflictOpportunityCandidate, ...]:
        """Return isolated lifecycle values for diagnostics/tests of that owner."""
        return tuple(
            record.value for (owner, _), record in sorted(self._tracked.items())
            if owner == owner_id
        )

    def provider_error_for(self, owner_id: str, simulation_tick: int) -> str | None:
        """Return a non-sensitive provider failure category for diagnostics."""
        return self._provider_errors.get((owner_id, simulation_tick))
