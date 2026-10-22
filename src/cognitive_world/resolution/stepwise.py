"""Bounded one-step-at-a-time execution for open-ended plans."""

from dataclasses import dataclass, field, replace
from enum import Enum
from collections.abc import Mapping
import hmac
import secrets
import math

from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.observation import Observation
from cognitive_world.observation.observable import FactScalar, ObservableFact
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import ActionInterpreter
from cognitive_world.resolution.provider_budget import provider_call_scope, provider_calls_used
from cognitive_world.runtime.clock import SimulationTime
from cognitive_world.safety.governance import SafetyInput, UniversalSafetyGovernance


MAX_PLAN_STEPS = 5
_PROGRESS_KEY = secrets.token_bytes(32)


class StepProgressStatus(str, Enum):
    READY = "ready"
    WAITING_FOR_OBSERVATION = "waiting_for_observation"
    COMPLETE = "complete"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class PlannedStep:
    method: str
    target: str | None = None
    condition: tuple[str, FactScalar, str | None] | None = None


@dataclass(frozen=True)
class StepwiseProgress:
    """Caller-carried immutable plan progress, never an authority to write."""

    proposal_id: str
    actor_id: str
    steps: tuple[PlannedStep, ...]
    next_step_index: int = 0
    completed_event_ids: tuple[str, ...] = ()
    last_event_id: str | None = None
    status: StepProgressStatus = StepProgressStatus.READY
    provider_calls_used: int = 0
    integrity_token: str = field(default="", repr=False, compare=False)
    runtime_binding: tuple[int, int, int] = field(default=(0, 0, 0), repr=False)
    proposal_fingerprint: str = field(default="", repr=False)


def _progress_payload(progress: StepwiseProgress) -> bytes:
    return repr((
        progress.proposal_id,
        progress.actor_id,
        progress.steps,
        progress.next_step_index,
        progress.completed_event_ids,
        progress.last_event_id,
        progress.status.value,
        progress.provider_calls_used,
        progress.runtime_binding,
        progress.proposal_fingerprint,
    )).encode("utf-8")


def _seal_progress(progress: StepwiseProgress) -> StepwiseProgress:
    token = hmac.digest(_PROGRESS_KEY, _progress_payload(progress), "sha256").hex()
    return replace(progress, integrity_token=token)


def _validate_progress(progress: StepwiseProgress) -> bool:
    if not isinstance(progress, StepwiseProgress) or not progress.integrity_token:
        return False
    try:
        expected = hmac.digest(_PROGRESS_KEY, _progress_payload(progress), "sha256").hex()
        return hmac.compare_digest(progress.integrity_token, expected)
    except (AttributeError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class StepwiseStepResult:
    progress: StepwiseProgress
    attempt: Attempt | None
    event: Event | None
    outcome: str


@dataclass
class StepwisePlanExecutor:
    """Resolve and commit at most one planned method per call.

    A subsequent step requires an owner-scoped CognitionContext containing a
    trusted Observation of the preceding event. This keeps newly acquired
    knowledge on the existing Observation/Cognition path.
    """

    action_resolution_flow: ActionResolutionFlow
    event_processor: EventProcessor
    world_state: WorldState
    interpreter: ActionInterpreter = field(default_factory=ActionInterpreter)
    maximum_steps: int = MAX_PLAN_STEPS
    cognitive_runtime: CognitiveRuntime | None = None
    safety_governance: UniversalSafetyGovernance | None = None
    _provider_calls_by_proposal: dict[tuple[str, str], int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_steps <= MAX_PLAN_STEPS:
            raise ValueError("maximum_steps must be within the trusted plan bound")
        if self.safety_governance is None:
            self.safety_governance = self.action_resolution_flow.safety_governance
        elif self.safety_governance is not self.action_resolution_flow.safety_governance:
            raise ValueError("StepwisePlanExecutor must share ActionResolutionFlow safety governance")
        self.action_resolution_flow.world_state = self.world_state
        self.action_resolution_flow.event_history = self.event_processor.event_history
        self.event_processor.world_state = self.world_state
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise RuntimeError("StepwisePlanExecutor has no valid safety governance")
        self.safety_governance.bind_world_state(self.world_state)

    def advance(
        self,
        proposal: ActionProposal,
        *,
        progress: StepwiseProgress | None = None,
        cognition_context: CognitionContext | None = None,
        simulation_tick: SimulationTime | None = None,
    ) -> StepwiseStepResult:
        if not isinstance(proposal, ActionProposal):
            raise TypeError("proposal must be an ActionProposal")
        if progress is not None and not _validate_progress(progress):
            raise PermissionError("step progress was not issued intact by this executor")
        if progress is not None and progress.runtime_binding != self._runtime_binding():
            raise PermissionError("step progress belongs to a different runtime state")
        proposal_key = (proposal.agent_id, proposal.proposal_id)
        used_before = max(
            0 if progress is None else progress.provider_calls_used,
            self._provider_calls_by_proposal.get(proposal_key, 0),
        )
        if not 0 <= used_before <= 1:
            raise ValueError("plan provider-call budget is invalid")
        with provider_call_scope(1 - used_before):
            try:
                result = self._advance(
                    proposal,
                    progress=progress,
                    cognition_context=cognition_context,
                    simulation_tick=simulation_tick,
                )
            finally:
                used_now = provider_calls_used()
                used_total = used_before + used_now
                if used_total:
                    self._provider_calls_by_proposal[proposal_key] = used_total
        updated_progress = _seal_progress(
            replace(
                result.progress,
                provider_calls_used=self._provider_calls_by_proposal.get(proposal_key, 0),
                runtime_binding=self._runtime_binding(),
            )
        )
        return StepwiseStepResult(updated_progress, result.attempt, result.event, result.outcome)

    def _runtime_binding(self) -> tuple[int, int, int]:
        return (id(self), id(self.world_state), id(self.event_processor.event_history))

    def _advance(
        self,
        proposal: ActionProposal,
        *,
        progress: StepwiseProgress | None = None,
        cognition_context: CognitionContext | None = None,
        simulation_tick: SimulationTime | None = None,
    ) -> StepwiseStepResult:
        if not isinstance(proposal, ActionProposal):
            raise TypeError("proposal must be an ActionProposal")
        proposal_fingerprint = self.interpreter.proposal_fingerprint(
            proposal, actor_id=proposal.agent_id
        )
        raw_steps = proposal.parameters.get("steps", ())
        if not isinstance(raw_steps, (tuple, list)) or not raw_steps:
            raise ValueError("stepwise execution requires non-empty ordered steps")
        normalized: list[PlannedStep] = []
        for index, raw_step in enumerate(raw_steps):
            if isinstance(raw_step, str):
                method = raw_step
                target = proposal.target_refs[index] if index < len(proposal.target_refs) else proposal.target_refs[0] if proposal.target_refs else None
                condition = None
            elif isinstance(raw_step, Mapping) and set(raw_step).issubset({"method", "target", "condition"}) and "method" in raw_step:
                method = raw_step["method"]
                target = raw_step.get("target")
                raw_condition = raw_step.get("condition")
                condition = None
                if raw_condition is not None:
                    if not isinstance(raw_condition, Mapping) or set(raw_condition) - {"predicate", "value", "subject_ref"} or "predicate" not in raw_condition or "value" not in raw_condition:
                        raise ValueError("step condition must contain a predicate and scalar value")
                    predicate = raw_condition["predicate"]
                    value = raw_condition["value"]
                    subject_ref = raw_condition.get("subject_ref")
                    if not isinstance(predicate, str) or not predicate or not (
                        value is None or isinstance(value, (str, int, bool))
                        or isinstance(value, float) and math.isfinite(value)
                    ):
                        raise ValueError("step condition is outside the supported observable-fact contract")
                    if subject_ref is not None and (not isinstance(subject_ref, str) or not subject_ref):
                        raise ValueError("condition subject_ref must be non-empty text")
                    condition = (predicate, value, subject_ref)
            else:
                raise ValueError("step must be text or a bounded method/target mapping")
            if not isinstance(method, str) or not method.strip():
                raise ValueError("step method must be non-empty text")
            if target is not None and (not isinstance(target, str) or not target):
                raise ValueError("step target must be non-empty text when present")
            normalized.append(PlannedStep(" ".join(method.split()), target, condition))
        steps = tuple(normalized)
        if len(steps) > self.maximum_steps:
            raise ValueError("plan exceeds the trusted step budget")
        for step in steps:
            if not isinstance(self.safety_governance, UniversalSafetyGovernance):
                raise RuntimeError("StepwisePlanExecutor has no valid safety governance")
            self.safety_governance.require_action_allowed(SafetyInput(
                actor_id=proposal.agent_id,
                source="stepwise_action_step",
                intent=proposal.action_type,
                target_refs=() if step.target is None else (step.target,),
                method=step.method,
                ordered_steps=(step.method,),
            ))
        if progress is None:
            progress = StepwiseProgress(
                proposal.proposal_id,
                proposal.agent_id,
                steps,
                proposal_fingerprint=proposal_fingerprint,
            )
        if (
            progress.proposal_id != proposal.proposal_id
            or progress.actor_id != proposal.agent_id
            or progress.steps != steps
            or progress.proposal_fingerprint != proposal_fingerprint
        ):
            raise PermissionError("step progress does not match this proposal and actor")
        if progress.status in {StepProgressStatus.COMPLETE, StepProgressStatus.FAILED, StepProgressStatus.UNRESOLVED}:
            raise ValueError("plan is not in a resumable state")
        if progress.last_event_id is not None:
            if not isinstance(cognition_context, CognitionContext) or cognition_context.owner_id != proposal.agent_id:
                raise PermissionError("a subsequent step requires the actor's refreshed CognitionContext")
            history = self.event_processor.event_history
            prior_event = history.get_event(progress.last_event_id) if history is not None else None
            if prior_event is None or not prior_event.has_trusted_source():
                raise PermissionError("the previous step Event is absent from trusted EventHistory")
            observations = cognition_context.get_observations()
            prior_observations = tuple(
                item
                for item in observations
                if isinstance(item, Observation)
                and item.observer_id == proposal.agent_id
                and item.source_event_id == progress.last_event_id
                and item.has_trusted_provenance()
                and isinstance(item.content, ObservableFact)
                and item.content.has_trusted_source(prior_event)
            )
            if not prior_observations:
                raise PermissionError("the previous step must be observed through the trusted perception path")
            if self.cognitive_runtime is None:
                raise PermissionError("continuing a plan requires the Runtime's CognitiveRuntime")
            consumed = any(
                self.cognitive_runtime.has_consumed_observation(
                    proposal.agent_id,
                    item,
                    source_event_id=progress.last_event_id,
                )
                for item in prior_observations
            )
            if not consumed:
                self.cognitive_runtime.process(proposal.agent_id, observations)
                consumed = any(
                    self.cognitive_runtime.has_consumed_observation(
                        proposal.agent_id,
                        item,
                        source_event_id=progress.last_event_id,
                    )
                    for item in prior_observations
                )
            if not consumed:
                raise PermissionError("the prior step Observation was not consumed by L1 Perception")
        index = progress.next_step_index
        if index >= len(steps):
            raise ValueError("all plan steps have already completed")
        planned_step = steps[index]
        if planned_step.condition is not None:
            if not isinstance(cognition_context, CognitionContext) or cognition_context.owner_id != proposal.agent_id:
                raise PermissionError("conditional steps require the actor's owner-scoped CognitionContext")
            predicate, expected_value, subject_ref = planned_step.condition
            matching = []
            for observation in cognition_context.get_observations():
                if not isinstance(observation, Observation) or observation.observer_id != proposal.agent_id or not observation.has_trusted_provenance():
                    continue
                source_event = self.event_processor.event_history.get_event(observation.source_event_id) if self.event_processor.event_history is not None else None
                fact = observation.content
                if (
                    source_event is not None
                    and isinstance(fact, ObservableFact)
                    and fact.has_trusted_source(source_event)
                    and fact.source_event_id == observation.source_event_id
                    and fact.predicate == predicate
                    and (subject_ref is None or fact.subject_ref == subject_ref)
                ):
                    matching.append(fact.value == expected_value)
            if True not in matching:
                stopped = StepwiseProgress(
                    progress.proposal_id, progress.actor_id, progress.steps,
                    index, progress.completed_event_ids, progress.last_event_id,
                    StepProgressStatus.UNRESOLVED if not matching else StepProgressStatus.FAILED,
                    proposal_fingerprint=progress.proposal_fingerprint,
                )
                return StepwiseStepResult(stopped, None, None, "condition_unresolved" if not matching else "condition_not_met")

        params = dict(proposal.parameters)
        params.pop("steps", None)
        method, target = planned_step.method, planned_step.target
        params["method"] = method
        step_proposal = ActionProposal(
            proposal_id=f"{proposal.proposal_id}:step:{index}",
            agent_id=proposal.agent_id,
            action_type=proposal.action_type,
            target_refs=[target] if target is not None else proposal.target_refs,
            parameters=params,
            reasoning_refs=proposal.reasoning_refs,
            metadata=proposal.metadata,
        )
        attempt_id = f"attempt:{proposal.proposal_id}:step:{index}"
        attempt = self.interpreter.interpret(
            step_proposal,
            actor_id=proposal.agent_id,
            attempt_id=attempt_id,
        )
        event_id = f"event:resolution:{attempt.attempt_id}"
        history = self.event_processor.event_history
        existing = history.get_event(event_id) if history is not None else None
        if existing is not None:
            if (
                not existing.has_trusted_source("resolution")
                or existing.metadata.get("attempt_id") != attempt.attempt_id
                or existing.metadata.get("action_proposal_id") != step_proposal.proposal_id
                or existing.metadata.get("attempt_fingerprint") != attempt.content_fingerprint()
            ):
                raise PermissionError("an existing Event does not match this controlled plan step")
            history_status = history.get_processing_status(event_id)
            if history_status is not None and history_status.value != "complete" and self.event_processor.observation_store is not None:
                self.event_processor.dispatch_with_evidence(existing)
            first_change = existing.changes[0] if existing.changes else {}
            success = isinstance(first_change, Mapping) and first_change.get("success") is True
            completed_ids = progress.completed_event_ids
            if event_id not in completed_ids:
                completed_ids = (*completed_ids, event_id)
            next_index = index + 1
            status = (
                StepProgressStatus.COMPLETE
                if success and next_index == len(steps)
                else StepProgressStatus.WAITING_FOR_OBSERVATION
                if success
                else StepProgressStatus.FAILED
            )
            updated = StepwiseProgress(
                progress.proposal_id, progress.actor_id, progress.steps,
                next_index, completed_ids, event_id, status,
                proposal_fingerprint=progress.proposal_fingerprint,
            )
            return StepwiseStepResult(updated, attempt, existing, str(first_change.get("outcome", "unknown")) if isinstance(first_change, Mapping) else "unknown")
        result, event = self.action_resolution_flow.execute_with_result(
            attempt,
            action_proposal_id=step_proposal.proposal_id,
            simulation_tick=simulation_tick,
        )
        if event is None:
            stopped = StepwiseProgress(
                progress.proposal_id, progress.actor_id, progress.steps, index,
                progress.completed_event_ids, progress.last_event_id,
                StepProgressStatus.UNRESOLVED,
                proposal_fingerprint=progress.proposal_fingerprint,
            )
            return StepwiseStepResult(stopped, attempt, None, "unresolved")
        self.event_processor.dispatch_with_evidence(event)
        completed_ids = (*progress.completed_event_ids, event.id)
        next_index = index + 1
        status = (
            StepProgressStatus.COMPLETE
            if next_index == len(steps)
            else StepProgressStatus.WAITING_FOR_OBSERVATION
        ) if result.success else StepProgressStatus.FAILED
        updated = StepwiseProgress(
            progress.proposal_id,
            progress.actor_id,
            progress.steps,
            next_index,
            completed_ids,
            event.id,
            status,
            proposal_fingerprint=progress.proposal_fingerprint,
        )
        return StepwiseStepResult(updated, attempt, event, result.outcome)
