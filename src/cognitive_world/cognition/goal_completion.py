"""Narrow completion from an explicit state or actor-action evidence condition.

No planner, world writer, result ledger or free-text goal interpretation lives here.
Conditions are data in existing Goal metadata; authority comes from existing B3
history bindings, authorized L1 consumption and the cognitive write boundary.
"""
from dataclasses import asdict, dataclass
import json
import math

from cognitive_world.core.interaction import InteractionReference

COMPLETION_KEY = "cognitive_world.goal_completion"


@dataclass(frozen=True)
class GoalCompletionCondition:
    target_ref: str
    fact_type: str
    predicate: str
    subject_ref: str
    expected_value: str | bool | int | float
    version: int = 1
    completion_kind: str = "actor_action"

    def __post_init__(self):
        if type(self.version) is not int or self.version not in (1, 2):
            raise ValueError("unsupported Goal completion condition version")
        if (self.completion_kind not in ("actor_action", "state")
                or (self.version == 1 and self.completion_kind != "actor_action")):
            raise ValueError("unsupported Goal completion semantics")
        # State commitments concern state evidence, never another actor's private result.
        if self.completion_kind == "state" and self.fact_type != "environment_state":
            raise ValueError("state completion requires typed environment-state evidence")
        if self.version == 2 and InteractionReference.parse(self.target_ref).identifier != self.subject_ref:
            raise ValueError("completion target and fact subject must match")
        for value in (self.target_ref, self.fact_type, self.predicate, self.subject_ref):
            if not isinstance(value, str) or not value or len(value) > 1024:
                raise ValueError("completion references must be bounded explicit identities")
        InteractionReference.parse(self.target_ref)
        value = self.expected_value
        if (type(value) not in (str, bool, int, float)
                or (type(value) is float and not math.isfinite(value))
                or (type(value) is str and len(value) > 1024)):
            raise ValueError("completion requires a known finite typed scalar")

    def as_value(self):
        value = asdict(self)
        if self.version == 1:
            value.pop("completion_kind")
        return value

    @classmethod
    def from_value(cls, value):
        fields = {"target_ref", "fact_type", "predicate", "subject_ref", "expected_value", "version"}
        if type(value) is dict and value.get("version") == 2:
            fields.add("completion_kind")
        if type(value) is not dict or set(value) != fields:
            raise ValueError("unsupported Goal completion condition shape")
        return cls(**value)


@dataclass(frozen=True)
class GoalCompletionOutcome:
    owner_id: str
    goal_id: str
    event_id: str
    status: str


class ConsumedResultGoalCompletion:
    """Stateless opt-in adapter over the existing signed result and Goal paths."""

    def __init__(self, runtime):
        from cognitive_world.cognition.validation import CognitiveUpdateValidator
        if runtime.event_processor.persistence_trust is None:
            raise PermissionError("Goal result completion requires signed canonical history")
        self.runtime = runtime
        self.validator = CognitiveUpdateValidator()

    def _verified_context(self, context, cognitive_runtime):
        from cognitive_world.cognition.action_expectation import verify_records
        rt = self.runtime
        actor = rt.context.agent_registry.get(context.owner_id)
        if actor is None or actor.character_id != context.character_id:
            raise PermissionError("Goal completion owner is not registered")
        canonical = rt.cognition_context_provider(actor)
        if (canonical.cognition_container is not context.cognition_container
                or canonical.memory_store is not context.memory_store
                or cognitive_runtime is not rt.agent_action_loop.agent_turn.cognitive_runtime
                or getattr(cognitive_runtime, "_history_context", None) is None
                or cognitive_runtime._history_context.history is not rt.context.event_history):
            raise PermissionError("Goal completion must use the canonical cognition and history")
        memories = context.memory_store.get_all_memories()
        verify_records(memories, history=rt.context.event_history,
            trust=rt.event_processor.persistence_trust,
            checkpoint_tick=rt.context.clock.current_time, lineage=rt.memory_revision_lineage)
        return actor, {m.id: m.content for m in memories}

    def after_l1(self, context, cognitive_runtime):
        from cognitive_world.cognition.action_expectation import ActionResultAssociation, ActionExpectationRecord
        rt = self.runtime
        with rt.write_fence.commit_scope():
            actor, records = self._verified_context(context, cognitive_runtime)
            outcomes = []
            for record in records.values():
                if type(record) is not ActionResultAssociation or record.owner_id != actor.agent_id:
                    continue
                expected = records.get(record.expectation_id)
                if type(expected) is not ActionExpectationRecord or expected.origin != "npc":
                    continue
                goal_id = json.loads(expected.attempt_json)[5].get("goal_id")
                if goal_id not in actor.goal_ids:
                    continue
                goal = context.cognition_container.goal_store.get_owned(actor.agent_id, goal_id)
                if goal is None or COMPLETION_KEY not in goal.metadata:
                    continue
                outcomes.append(self._review(context, cognitive_runtime, goal, record.event_id, records))
            # State commitments require this owner's authorized consumed fact,
            # independently of who caused it or whether they had a B3 expectation.
            for goal in context.get_goals():
                try:
                    condition = GoalCompletionCondition.from_value(goal.metadata.get(COMPLETION_KEY))
                except (TypeError, ValueError):
                    continue
                if condition.completion_kind != "state" or goal.goal_id not in actor.goal_ids:
                    continue
                for event_id in dict.fromkeys(o.source_event_id for o in context.get_observations()):
                    outcome = self._review(context, cognitive_runtime, goal, event_id, records)
                    outcomes.append(outcome)
                    if outcome.status in ("completed", "already_completed", "inactive"):
                        break
            return tuple(outcomes)

    def review(self, context, cognitive_runtime, *, goal_id, event_id):
        """Recheck a specific formal result; no action or L1 processing is retried."""
        with self.runtime.write_fence.commit_scope():
            actor, records = self._verified_context(context, cognitive_runtime)
            if goal_id not in actor.goal_ids:
                raise PermissionError("Goal is not linked to this owner")
            goal = context.cognition_container.goal_store.get_owned(actor.agent_id, goal_id)
            if goal is None:
                raise PermissionError("canonical Goal is absent")
            return self._review(context, cognitive_runtime, goal, event_id, records)

    def _review(self, context, cognitive_runtime, goal, event_id, records):
        from cognitive_world.cognition.action_expectation import ActionResultAssociation, ActionExpectationRecord
        from cognitive_world.cognition.goal_update import GoalUpdater
        from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
        rt = self.runtime

        def result(status):
            return GoalCompletionOutcome(goal.owner_id, goal.goal_id, event_id, status)

        if COMPLETION_KEY not in goal.metadata:
            return result("not_configured")
        try:
            condition = GoalCompletionCondition.from_value(goal.metadata[COMPLETION_KEY])
        except (TypeError, ValueError):
            return result("unsupported_condition")
        event = rt.context.event_history.get_event(event_id)
        if event is None:
            return result("uncommitted")
        if goal.status == "completed" and event_id in goal.source_refs:
            return result("already_completed")
        if goal.status != "active":
            return result("inactive")
        if condition.completion_kind == "actor_action":
            associations = [r for r in records.values()
                            if type(r) is ActionResultAssociation and r.event_id == event_id
                            and r.owner_id == goal.owner_id]
            if len(associations) != 1:
                return result("unresolved_result")
            expected = records.get(associations[0].expectation_id)
            if type(expected) is not ActionExpectationRecord or expected.origin != "npc":
                return result("unbound_goal")
            snapshot = json.loads(expected.attempt_json)
            if (snapshot[5].get("goal_id") != goal.goal_id
                    or snapshot[4] != [condition.target_ref]):
                return result("unbound_goal")
            summary = event.changes[0] if event.changes else {}
            if not isinstance(summary, dict) or type(summary.get("success")) is not bool:
                return result("unresolved_result")
            if not summary["success"]:
                return result("action_failed")
        elif event.has_trusted_source("resolution"):
            summary = event.changes[0] if event.changes else {}
            if not isinstance(summary, dict) or summary.get("success") is not True:
                return result("action_failed")
        evidence = rt.context.event_history.get_processing_evidence(event_id)
        if evidence is None or not evidence.has_trusted_source(event):
            return result("unresolved_result")
        facts = [f for f in evidence.observable_facts
                 if f.has_trusted_source(event) and f.fact_type == condition.fact_type
                 and f.predicate == condition.predicate and f.subject_ref == condition.subject_ref]
        if len(facts) != 1:
            return result("success_condition_unresolved")
        fact = facts[0]
        if condition.completion_kind == "state":
            # Historical intake is not evidence that an old state still holds.
            # Use canonical processing order (not ticks, which may tie), and
            # require the owner's consumed fact to be the current projection.
            latest = None
            for candidate in rt.context.event_history.get_events():
                processed = rt.context.event_history.get_processing_evidence(candidate.id)
                if processed is None or not processed.has_trusted_source(candidate):
                    return result("unresolved_result")
                if any(f.has_trusted_source(candidate) and f.fact_type == condition.fact_type
                        and f.predicate == condition.predicate and f.subject_ref == condition.subject_ref
                        for f in processed.observable_facts):
                    latest = candidate.id
            if latest != event_id:
                return result("superseded_state_evidence")
        consumed = next((o for o in context.get_observations()
                         if o.observer_id == goal.owner_id and o.source_event_id == event_id
                         and o.has_trusted_provenance() and o.content == fact
                         and cognitive_runtime.has_consumed_observation(
                             goal.owner_id, o, source_event_id=event_id)), None)
        if consumed is None:
            return result("awaiting_consumption")
        if type(fact.value) is not type(condition.expected_value) or fact.value != condition.expected_value:
            return result("success_condition_unmet")
        sources = list(dict.fromkeys([*goal.source_refs, event_id]))
        proposal = GoalUpdater().propose_update(goal, {
            "new_state": "completed", "operation": "complete",
            "reason": "Owner consumed the Goal-bound authoritative result.",
            "source_refs": sources, "evidence_refs": [consumed.observation_id, event_id],
        })
        validation = self.validator.validate(proposal, {
            "agent_id": goal.owner_id, "authorized_source_refs": tuple(sources)})
        if not validation.accepted:
            return result("governance_rejected")
        container = context.cognition_container
        try:
            CognitiveUpdateApplier(container.belief_store, container.goal_store,
                container.self_model_store, write_fence=rt.write_fence).apply(proposal, validation)
        except BaseException:
            # An uncertain Goal write must not be retried as a second action
            # or captured as an unambiguously consistent cognitive checkpoint.
            rt.write_fence.mark_recovery_required()
            raise
        return result("completed")
