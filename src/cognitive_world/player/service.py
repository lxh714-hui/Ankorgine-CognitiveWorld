"""Host-bound player input through the existing world authorities.

Raw text interpretation produces only an untrusted action candidate or a typed
no-result. Candidate targets are still checked against authorized observations.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from contextlib import nullcontext
from hashlib import sha256
import json
from threading import Event, RLock
from time import monotonic
from uuid import uuid4

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.core.door import DoorState
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.passage import PassageState
from cognitive_world.core.action_result import ActionResultKind
from cognitive_world.core.event import Event
from cognitive_world.core.no_result import _issue_no_result_state
from cognitive_world.core.world_state import WorldStateSlot, WorldStateSlotRead
from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event.history import EventProcessingStatus
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.observation.store import ObservationStore
from cognitive_world.presentation.gateway import ChatOutputGateway
from cognitive_world.presentation.contracts import (
    NoResultNarrativeMessage, PlayerClarificationMessage,
)
from cognitive_world.presentation.perspective import PerspectiveResolver
from cognitive_world.presentation.pipeline import PresentationPipeline
from cognitive_world.presentation.visibility import VisibilityFilter
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.runtime.context import PlayerMode, RuntimeContext
from cognitive_world.safety.governance import SafetyInput, UniversalSafetyGovernance
from .task_context import (
    PlayerTaskAborted, active_player_task, check_active_player_task,
)
from .narrative_fallback import (
    NarrativeFallbackContext,
    NarrativeFallbackProvider,
    NarrativeFallbackService,
    NoResultReason,
    NoResultState,
)
from .input_understanding import (
    AuthorizedTargetCandidate, InputUnderstandingStatus, OllamaPlayerInputUnderstandingProvider,
    PlayerInputAssessment, PlayerInputRequest, PlayerInputUnderstandingProvider,
)
from .input_diagnostics import emit as emit_input_diagnostic, enabled as input_diagnostics_enabled


@dataclass(frozen=True)
class PlayerActionRequest:
    request_id: str
    session_id: str
    world_id: str
    intent: str
    method: str
    target_ref: str | None = None

    def __post_init__(self) -> None:
        for value in (self.request_id, self.session_id, self.world_id, self.intent, self.method):
            if not isinstance(value, str) or not value or len(value) > 1024:
                raise ValueError("player request fields must be bounded non-empty text")
        if self.target_ref is not None and (
            not isinstance(self.target_ref, str) or not self.target_ref or len(self.target_ref) > 1024
        ):
            raise ValueError("target_ref must be a bounded non-empty reference")


@dataclass(frozen=True)
class PlayerActionOutcome:
    request_id: str
    status: str
    messages: tuple[str, ...] = ()
    narrative_fallback: NoResultNarrativeMessage | None = None
    recovery_action: str | None = None
    no_result_state: NoResultState | None = None
    clarification: PlayerClarificationMessage | None = None


@dataclass(frozen=True)
class _PendingClarification:
    original: PlayerInputRequest
    assessment: PlayerInputAssessment
    session_id: str
    runtime_session_id: str
    restore_generation: int
    deadline: float
    candidates: tuple[tuple[AuthorizedTargetCandidate, str], ...]
    context_reads: tuple[WorldStateSlotRead, ...]
    original_cancellation: Event | None = None


class PlayerActionService:
    """One host-created service for one trusted roleplay session and world."""

    def __init__(self, context: RuntimeContext, processor: EventProcessor,
                 action_pipeline: ActionPipeline, resolution_flow: ActionResolutionFlow,
                 output: ChatOutputGateway, *, world_id: str,
                 narrative_fallback_provider: NarrativeFallbackProvider | None = None,
                 input_understanding_provider: PlayerInputUnderstandingProvider | None = None) -> None:
        if not isinstance(context, RuntimeContext) or not isinstance(processor, EventProcessor):
            raise TypeError("canonical RuntimeContext and EventProcessor required")
        if not isinstance(world_id, str) or not world_id:
            raise ValueError("world_id required")
        if (processor.world_state is not context.world_state
                or processor.event_history is not context.event_history
                or processor.simulation_clock is not context.clock
                or processor.agent_registry is not context.agent_registry
                or processor.observation_store is not context.observation_store):
            raise ValueError("player boundary requires the runtime's authorities")
        if not isinstance(context.agent_registry, AgentRegistry) or not isinstance(
                context.observation_store, ObservationStore):
            raise ValueError("registered actors and observations required")
        if not isinstance(context.safety_governance, UniversalSafetyGovernance):
            raise ValueError("shared safety governance required")
        if not isinstance(action_pipeline, ActionPipeline) or not isinstance(resolution_flow, ActionResolutionFlow):
            raise TypeError("existing action and resolution flows required")
        action_pipeline.bind_safety_governance(context.safety_governance)
        resolution_flow.world_state = context.world_state
        resolution_flow.bind_safety_governance(context.safety_governance)
        self.context, self.processor = context, processor
        self.action_pipeline, self.resolution_flow = action_pipeline, resolution_flow
        resolution_flow.action_expectations = processor.action_expectations
        resolution_flow.expectation_origin = "player"
        self.presentation = PresentationPipeline.for_runtime(context, output)
        self.world_id = world_id
        self._requests: dict[str, tuple[str, object | None, PlayerActionOutcome | None]] = {}
        self._request_lock = RLock()
        self.narrative_fallback = NarrativeFallbackService(narrative_fallback_provider)
        self.input_understanding_provider = input_understanding_provider
        self._fallback_diagnostics: dict[str, str] = {}
        self._pending_clarification: _PendingClarification | None = None

    def fallback_diagnostic(self, request_id: str) -> str | None:
        """Return an internal non-text failure code; never includes provider output/errors."""
        return self._fallback_diagnostics.get(request_id)

    def _diagnose_action_event(self, request_id: str, event: Event,
                               before_location: str | None, batch=None,
                               track_location: bool = False) -> None:
        if not input_diagnostics_enabled():
            return
        try:
            effect = event.changes[1] if len(event.changes) > 1 else None
            effect_type = effect.get("effect_type") if isinstance(effect, dict) else None
            effect_type = effect_type if effect_type in {
                "actor_location_changed", "door_state_changed",
            } else ("other" if effect_type is not None else None)
            evidence = self.context.event_history.get_processing_evidence(event.id)
            arrivals = set() if evidence is None else {
                fact.fact_id for fact in evidence.observable_facts
                if fact.fact_type == "movement" and fact.predicate == "actor_arrived"
            }
            observed = {
                item.content.fact_id
                for item in self.context.observation_store.get_by_observer(self._actor())
                if item.source_event_id == event.id and item.has_trusted_provenance()
            }
            fields = dict(
                effect_type=effect_type,
                event_processed=(self.context.event_history.get_processing_status(event.id)
                                 is EventProcessingStatus.COMPLETE),
                arrival_fact_emitted=bool(arrivals),
                arrival_observation_authorized=bool(arrivals & observed),
            )
            if track_location or effect_type == "actor_location_changed":
                after_location = self.context.world_state.locations.get(self._actor())
                fields.update(location_before=before_location, location_after=after_location,
                              location_changed=before_location != after_location)
            if batch is not None:
                displayed = {fact_id for message in batch.messages
                             for fact_id in message.source_fact_ids}
                fields.update(arrival_observation_used_by_presentation=bool(arrivals & observed & displayed),
                              confirmed_message_count=len(batch.messages))
            emit_input_diagnostic(request_id, "presentation" if batch is not None else "event_processing",
                                  **fields)
        except Exception:
            pass

    def cancel_pending_clarification(self, original_request_id: str, *, session_id: str) -> bool:
        """Cancel one unconsumed, process-local clarification without a world write."""
        with self._request_lock:
            pending = self._pending_clarification
            if (pending is None or pending.original.request_id != original_request_id
                    or pending.session_id != session_id):
                return False
            self._pending_clarification = None
            return True

    def _check_task_binding(self) -> None:
        check_active_player_task()
        binding = active_player_task()
        if binding is None:
            return
        session = self.context.player_session
        try:
            actor = self._actor()
        except Exception as exc:
            raise PlayerTaskAborted("stale") from exc
        if (session is None or session.session_id != binding.player_session_id
                or actor != binding.actor_id):
            raise PlayerTaskAborted("stale")

    def _actor(self) -> str:
        session = self.context.player_session
        perspective = PerspectiveResolver(self.context).resolve()
        if session is None or session.mode is not PlayerMode.ROLEPLAY:
            raise PermissionError("player actions require a host-bound roleplay session")
        if perspective.observer_id != session.controlled_agent_id:
            raise PermissionError("player actor does not match the resolved perspective")
        return perspective.observer_id

    def available_targets(self) -> tuple[str, ...]:
        """Only expose references from this session's intact, visible observations."""
        actor = self._actor()
        history = self.context.event_history
        observations = self.context.observation_store
        assert observations is not None
        perspective = PerspectiveResolver(self.context).resolve()
        visibility = VisibilityFilter(history, observations)
        targets: set[str] = set()
        for observation in observations.get_by_observer(actor):
            if not observation.has_trusted_provenance():
                continue
            event = history.get_event(observation.source_event_id)
            evidence = history.get_processing_evidence(observation.source_event_id)
            if event is None or evidence is None:
                continue
            for visible in visibility.filter(event, evidence, perspective):
                if (visible.source_observation_id == observation.observation_id
                        and visible.scope == "environment"
                        and visible.fact_type == "environment_state"
                        and visible.subject_ref):
                    targets.add(visible.subject_ref)
        return tuple(sorted(targets))

    def _current_visible_environment(self) -> tuple:
        """Read only this observer's intact, presently local environment facts."""
        actor = self._actor()
        perspective = PerspectiveResolver(self.context).resolve()
        visibility = VisibilityFilter(self.context.event_history, self.context.observation_store)
        actor_location = self.context.world_state.locations.get(actor)
        fence = self.processor.write_fence
        latest = {}
        for observation in self.context.observation_store.get_by_observer(actor):
            if not observation.has_trusted_provenance():
                continue
            runtime_binding = observation.trusted_source_runtime_binding()
            if (runtime_binding is not None and fence is not None
                    and runtime_binding != (fence.session_id, fence.restore_generation)):
                continue
            event = self.context.event_history.get_event(observation.source_event_id)
            evidence = self.context.event_history.get_processing_evidence(observation.source_event_id)
            if event is None or evidence is None:
                continue
            for item in visibility.filter(event, evidence, perspective):
                if (item.source_observation_id == observation.observation_id
                        and item.scope == "environment" and item.location_id == actor_location):
                    latest[(item.subject_ref, item.predicate)] = item
        return tuple(latest.values())

    def _request_candidates(self) -> tuple[tuple[AuthorizedTargetCandidate, str], ...]:
        descriptions = {}
        kinds = {}
        for item in self._current_visible_environment():
            if item.fact_type != "environment_state" or not item.subject_ref:
                continue
            rendered = self.presentation.composer._render(item)
            if rendered is None:
                continue
            descriptions.setdefault(item.subject_ref, []).append(rendered)
            if item.predicate in {"door_open", "door_locked"}:
                kinds[item.subject_ref] = "door"
            elif item.predicate == "passage_destination":
                kinds[item.subject_ref] = "passage"
        candidates = []
        for index, (reference, parts) in enumerate(sorted(descriptions.items()), 1):
            kind = kinds.get(reference, "environment_object")
            methods = self.resolution_flow.supported_attempt_methods(kind)
            candidates.append((
                AuthorizedTargetCandidate(
                    f"candidate-{index}", " ".join(parts)[:240], kind, methods,
                ),
                reference,
            ))
        return tuple(candidates)

    @staticmethod
    def _candidate_identities(pairs: tuple) -> dict:
        """Compare authorized identities and meaning, never regenerated ordinals."""
        return {reference: (candidate.description, candidate.kind, candidate.supported_methods)
                for candidate, reference in pairs}

    def _clarification_context(self, pairs: tuple) -> tuple[WorldStateSlotRead, ...]:
        # Only read the actor's location and already Observation-authorized targets.
        # These existing slot receipts are validity checks, not permanent grants.
        slots = (WorldStateSlot("locations", self._actor()),) + tuple(
            WorldStateSlot("environment", reference) for _, reference in pairs
        )
        return tuple(self.context.world_state.read_state_slot(
            slot, event_history=self.context.event_history,
        ) for slot in slots)

    def _clarification_context_valid(self, reads: tuple[WorldStateSlotRead, ...]) -> bool:
        return bool(reads) and reads[0].slot.record_id == self._actor() and all(
            # A slot receipt checks continuity only. Observation remains the
            # authority; this does not upgrade an unknown slot origin to fact.
            read.present
            and self.context.world_state.verify_state_slot_read(
                read, event_history=self.context.event_history,
            ) for read in reads
        )

    @staticmethod
    def _digest(request: PlayerActionRequest) -> str:
        payload = (request.session_id, request.world_id, request.intent, request.method, request.target_ref)
        return sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _request_scope(self):
        # A synchronous host call starts one operation before Proposal creation.
        # Background tasks must retain their own capability, never replace it.
        fence = self.processor.write_fence
        if (self.processor.action_expectations is not None and fence is not None
                and RuntimeWriteFence.current_permit() is None
                and active_player_task() is None):
            return fence.operation()
        return nullcontext()

    def submit(self, request: PlayerActionRequest) -> PlayerActionOutcome:
        if not isinstance(request, PlayerActionRequest):
            raise TypeError("PlayerActionRequest required")
        with self._request_lock, self._request_scope():
            self._check_task_binding()
            return self._submit_action(request, self._digest(request))

    def _resume_event_delivery(
        self, request_id: str, digest: str, event: Event,
    ) -> PlayerActionOutcome:
        """Resume the recorded Event, never reinterpret or repeat its Attempt.

        Completed action processing does not rerun the action. Passage arrivals
        may complete missing local observation Events before delivery; current
        Presentation authorization still applies. Incomplete action processing
        retains EventProcessor recovery checks. Keep the pending entry intact
        if any stage fails again.
        """
        if self.context.event_history.get_processing_status(event.id) is not EventProcessingStatus.COMPLETE:
            self.processor.dispatch_with_evidence(event)
        batch = self.presentation.publish_event(event.id)
        self._observe_arrival_environment(event)
        feedback = self.presentation.publish_action_feedback(
            event.id, request_id, has_visible_result=bool(batch.messages),
        )
        status = self._status_for_event(event, feedback)
        result = PlayerActionOutcome(
            request_id, status, tuple(m.content for m in batch.messages),
        )
        self._requests[request_id] = (digest, event, result)
        return result

    def _observe_arrival_environment(self, event: Event) -> None:
        """Issue local typed mechanism observations after a committed passage move."""
        if (event.type != "resolution" or not event.has_trusted_source("resolution")
                or self.context.event_history.get_processing_status(event.id)
                    is not EventProcessingStatus.COMPLETE
                or len(event.changes) != 2 or not isinstance(event.changes[1], dict)):
            return
        effect = event.changes[1]
        actor = self._actor()
        destination = effect.get("destination_location")
        if (effect.get("effect_type") != "actor_location_changed"
                or effect.get("actor_id") != actor
                or not isinstance(destination, str)
                or self.context.world_state.locations.get(actor) != destination):
            return
        for mechanism_id, mechanism in self.context.world_state.environment.items():
            location = (mechanism.interaction_location_id if isinstance(mechanism, DoorState)
                        else mechanism.source_location_id if isinstance(mechanism, PassageState)
                        else None)
            if location != destination:
                continue
            observation_id = "arrival-observation:" + sha256(
                (event.id + "\0" + mechanism_id).encode("utf-8")
            ).hexdigest()[:32]
            recorded = self.context.event_history.get_event(observation_id)
            if recorded is None:
                observed = SystemEventFactory().create(
                    event_id=observation_id, event_type="environment_state_observed",
                    timestamp=str(self.context.clock.current_time),
                    simulation_tick=self.context.clock.current_time,
                    changes=[{"environment_id": mechanism_id}],
                )
                self.processor.dispatch_with_evidence(observed)
            elif (recorded.type != "environment_state_observed"
                  or not recorded.has_trusted_source("system")
                  or recorded.changes != [{"environment_id": mechanism_id}]
                  or self.context.event_history.get_processing_status(observation_id)
                      is not EventProcessingStatus.COMPLETE):
                raise RuntimeError("destination observation is incomplete or conflicting")
            self.presentation.publish_event(observation_id)

    def _submit_action(
        self, request: PlayerActionRequest, digest: str, *, preclaimed: bool = False,
        clarification: _PendingClarification | None = None,
    ) -> PlayerActionOutcome:
        self._check_task_binding()
        actor = self._actor()
        session = self.context.player_session
        if request.session_id != session.session_id or request.world_id != self.world_id:
            raise PermissionError("player request does not match the host session and world")
        existing = None if preclaimed else self._requests.get(request.request_id)
        if existing is not None:
            if existing[0] != digest:
                raise PermissionError("request identity reused with changed content")
            if existing[2] is not None:
                return existing[2]
            if existing[1] is None:
                raise RuntimeError("request processing is incomplete; do not replay its attempt")
            return self._resume_event_delivery(request.request_id, digest, existing[1])

        if request.target_ref is not None:
            address = InteractionReference.parse(request.target_ref)
            if address.namespace != "object" or address.identifier not in self.available_targets():
                raise PermissionError("target was not authorized by the player's observations")
        self._requests[request.request_id] = (digest, None, None)
        try:
            self.context.safety_governance.require_action_allowed(SafetyInput(
                actor_id=actor, source="player_input", intent=request.intent,
                method=request.method,
                target_refs=() if request.target_ref is None else (request.target_ref,),
            ))
            proposal = ActionProposal(
                proposal_id=f"player-proposal:{uuid4().hex}", agent_id=actor,
                action_type=request.intent,
                target_refs=[] if request.target_ref is None else [request.target_ref],
                parameters={"method": request.method},
            )
            if self.processor.action_expectations is not None:
                from cognitive_world.cognition.action_expectation_source import _PLAYER_ENTRY_AUTHORITY
                self.processor.action_expectations.issue_player_source(proposal,authority=_PLAYER_ENTRY_AUTHORITY)
            attempt = self.action_pipeline.create_attempt(proposal)
            before_location = None
            track_location = False
            if input_diagnostics_enabled():
                try:
                    before_location = self.context.world_state.locations.get(actor)
                    target = (self.context.world_state.environment.get(
                        InteractionReference.parse(request.target_ref).identifier)
                        if request.target_ref is not None else None)
                    kind = ("passage" if isinstance(target, PassageState) else
                            "door" if isinstance(target, DoorState) else None)
                    track_location = kind == "passage"
                    offered = self.resolution_flow.supported_attempt_methods(kind) if kind else ()
                    emit_input_diagnostic(request.request_id, "attempt_prepared",
                                          attempt_created=True, selected_mechanism_kind=kind,
                                          permitted_method=(request.method if request.method in offered else None),
                                          location_before=(before_location if kind == "passage" else None))
                except Exception:
                    pass
            b3_options = ({"action_proposal": proposal}
                          if self.resolution_flow.action_expectations is not None else {})
            resolution, event = self.resolution_flow.execute_with_result(
                attempt, **b3_options, action_proposal_id=proposal.proposal_id,
                simulation_tick=self.context.clock.capture(),
            )
            if input_diagnostics_enabled():
                try:
                    effect = event.changes[1] if event is not None and len(event.changes) > 1 else None
                    effect_type = effect.get("effect_type") if isinstance(effect, dict) else None
                    emit_input_diagnostic(request.request_id, "resolution",
                                          formal_event_created=event is not None,
                                          effect_type=(effect_type if effect_type in {
                                              "actor_location_changed", "door_state_changed",
                                          } else ("other" if effect_type is not None else None)))
                except Exception:
                    pass
            self._check_task_binding()
            if event is None:
                state = _issue_no_result_state(
                    request.request_id, NoResultReason.UNRESOLVED_ATTEMPT, digest,
                )
                narrative_context = NarrativeFallbackContext(
                    state, request.intent, request.method, digest,
                )
                run = self.narrative_fallback.render(narrative_context)
                if run.failure_code is not None:
                    suffix = "" if run.exception_type is None else ":" + run.exception_type
                    self._fallback_diagnostics[request.request_id] = run.failure_code + suffix
                narrative = None
                recovery_action = None
                if run.text is not None:
                    try:
                        self._check_task_binding()
                        narrative = self.presentation.publish_narrative_fallback(
                            state, run.text,
                        )
                    except Exception as exc:
                        self._fallback_diagnostics[request.request_id] = (
                            "presentation_rejected:" + type(exc).__name__
                        )
                        recovery_action = "clarify_or_retry"
                else:
                    recovery_action = "clarify_or_retry"
                result = PlayerActionOutcome(
                    request.request_id, "unresolved", narrative_fallback=narrative,
                    recovery_action=recovery_action, no_result_state=state,
                )
                self._requests[request.request_id] = (digest, None, result)
                return result
            self._requests[request.request_id] = (digest, event, None)
            self._check_task_binding()
            # Recheck the original question at the existing final-write lock.
            # snapshot_scope does not acquire a replacement operation permit.
            scope = (self.processor.write_fence.snapshot_scope()
                     if clarification is not None else nullcontext())
            with scope:
                if clarification is not None and (
                        monotonic() >= clarification.deadline
                        or not self._clarification_context_valid(clarification.context_reads)
                        or self._candidate_identities(clarification.candidates)
                            != self._candidate_identities(self._request_candidates())):
                    return self._complete_input_result(request.request_id, digest,
                        PlayerActionOutcome(request.request_id, "clarification_expired"))
                self.processor.dispatch_with_evidence(event)
            self._diagnose_action_event(request.request_id, event, before_location,
                                        track_location=track_location)
            batch = self.presentation.publish_event(event.id)
            self._diagnose_action_event(request.request_id, event, before_location, batch,
                                        track_location=track_location)
            self._observe_arrival_environment(event)
            feedback = self.presentation.publish_action_feedback(
                event.id, request.request_id, has_visible_result=bool(batch.messages),
            )
            result = PlayerActionOutcome(
                request.request_id,
                self._status_for_event(event, feedback),
                tuple(m.content for m in batch.messages),
            )
            self._requests[request.request_id] = (digest, event, result)
            return result
        except PermissionError:
            if self._requests[request.request_id][1] is None:
                result = PlayerActionOutcome(request.request_id, "rejected")
                self._requests[request.request_id] = (digest, None, result)
                return result
            raise

    @staticmethod
    def _status_for_event(event: Event, feedback) -> str:
        if feedback is not None:
            if feedback.result_kind is ActionResultKind.GOAL_ALREADY_SATISFIED:
                return "goal_already_satisfied"
            if feedback.result_kind is ActionResultKind.EXECUTED_NO_OBSERVABLE_CHANGE:
                return "executed_no_observable_change"
            if feedback.result_kind is ActionResultKind.ACTION_FAILED:
                return "failed"
        return "resolved" if event.changes[0]["success"] is True else "failed"

    @staticmethod
    def _input_digest(request: PlayerInputRequest) -> str:
        payload = ("player-input/v1", request.session_id, request.world_id, request.text,
                   request.clarification_id, request.new_request)
        return sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _complete_input_result(
        self, request_id: str, digest: str, outcome: PlayerActionOutcome,
    ) -> PlayerActionOutcome:
        self._check_task_binding()
        self._requests[request_id] = (digest, None, outcome)
        return outcome

    def _input_failure(
        self, request: PlayerInputRequest, digest: str, reason_code: str,
    ) -> PlayerActionOutcome:
        self._check_task_binding()
        state = _issue_no_result_state(
            request.request_id, NoResultReason.NPC_REASONING_UNAVAILABLE, digest,
        )
        self._fallback_diagnostics[request.request_id] = reason_code
        emit_input_diagnostic(request.request_id, "input_stopped",
                              reason_code=reason_code.split(":", 1)[0],
                              attempt_created=False, formal_event_created=False)
        return self._complete_input_result(request.request_id, digest, PlayerActionOutcome(
            request.request_id, "reasoning_unavailable", recovery_action="clarify_or_retry",
            no_result_state=state,
        ))

    def submit_input(self, request: PlayerInputRequest) -> PlayerActionOutcome:
        """Interpret raw input, then route only an authorized action candidate to the existing path."""
        with self._request_lock, self._request_scope():
            return self._submit_input_locked(request)

    def _submit_input_locked(self, request: PlayerInputRequest) -> PlayerActionOutcome:
        if not isinstance(request, PlayerInputRequest):
            raise TypeError("PlayerInputRequest required")
        self._check_task_binding()
        actor = self._actor()
        session = self.context.player_session
        if request.session_id != session.session_id or request.world_id != self.world_id:
            raise PermissionError("player request does not match the host session and world")
        digest = self._input_digest(request)
        existing = self._requests.get(request.request_id)
        if existing is not None:
            if existing[0] != digest:
                raise PermissionError("request identity reused with changed content")
            if existing[2] is not None:
                return existing[2]
            if existing[1] is not None:
                return self._resume_event_delivery(request.request_id, digest, existing[1])
            raise RuntimeError("request processing is incomplete; do not replay its interpretation")
        self._requests[request.request_id] = (digest, None, None)
        pending = self._pending_clarification
        if request.clarification_id is not None:
            if pending is None or pending.original.request_id != request.clarification_id:
                return self._complete_input_result(request.request_id, digest,
                    PlayerActionOutcome(request.request_id, "clarification_expired"))
        elif pending is not None and not request.new_request:
            return self._complete_input_result(request.request_id, digest,
                PlayerActionOutcome(request.request_id, "clarification_expired"))
        if request.new_request:
            self._pending_clarification = None

        try:
            self.context.safety_governance.require_action_allowed(SafetyInput(
                actor_id=actor,
                source="player_input",
                intent=request.text,
                method="unparsed player input",
            ))
        except PermissionError:
            return self._complete_input_result(
                request.request_id, digest,
                PlayerActionOutcome(request.request_id, "rejected"),
            )
        except Exception as exc:
            self._check_task_binding()
            return self._input_failure(
                request, digest, "raw_input_safety_failed:" + type(exc).__name__,
            )

        try:
            provider = self.input_understanding_provider
            if provider is None:
                provider = OllamaPlayerInputUnderstandingProvider.from_environment()
        except Exception as exc:
            self._check_task_binding()
            return self._input_failure(
                request, digest, "input_provider_configuration_failed:" + type(exc).__name__,
            )
        if provider is None:
            self._check_task_binding()
            return self._input_failure(request, digest, "input_provider_unavailable")
        binding = active_player_task()
        admission_targets = (
            self.available_targets() if binding is None else binding.authorized_targets
        )
        candidate_pairs = self._request_candidates()
        context_reads = self._clarification_context(candidate_pairs)
        candidates = tuple(item for item, _ in candidate_pairs)
        candidate_refs = {item.handle: reference for item, reference in candidate_pairs}
        using_candidates = callable(getattr(provider, "understand_candidates", None))
        pending = self._pending_clarification
        fence = self.processor.write_fence
        original_generation = fence.restore_generation if fence is not None else None
        if pending is not None:
            if (fence is None or pending.session_id != session.session_id
                    or pending.runtime_session_id != fence.session_id
                    or pending.restore_generation != fence.restore_generation
                    or (pending.original_cancellation is not None
                        and pending.original_cancellation.is_set())
                    or monotonic() >= pending.deadline
                    or not self._clarification_context_valid(pending.context_reads)
                    or self._candidate_identities(pending.candidates)
                        != self._candidate_identities(candidate_pairs)):
                self._pending_clarification = None
                return self._complete_input_result(request.request_id, digest,
                    PlayerActionOutcome(request.request_id, "clarification_expired"))
            # Preserve the exact option handles and canonical identities shown
            # with the original question, despite current enumeration order.
            candidate_pairs = pending.candidates
            context_reads = pending.context_reads
            candidates = tuple(item for item, _ in candidate_pairs)
            candidate_refs = {item.handle: reference for item, reference in candidate_pairs}
        provider_returned = False
        try:
            emit_input_diagnostic(request.request_id, "provider_invocation",
                                  provider_invoked=True, candidate_count=len(candidates),
                                  candidate_mechanism_kinds=sorted({item.kind for item in candidates}),
                                  continuation=pending is not None)
            candidate_interpreter = getattr(provider, "understand_candidates", None)
            resolver = getattr(provider, "resolve_clarification", None)
            if pending is not None and callable(resolver):
                prior = pending.assessment
                # The interpreter must bind a clarification answer to the
                # original request and select a currently offered method.
                # Do not turn a number or yes/no answer directly into an
                # executable action in the service layer.
                assessment = resolver(request, original=pending.original,
                                      prior=prior, candidates=candidates)
                self._check_task_binding()
                if assessment.status is InputUnderstandingStatus.INDEPENDENT_REQUEST:
                    self._pending_clarification = None
                    pending = None
                    candidate_pairs = self._request_candidates()
                    context_reads = self._clarification_context(candidate_pairs)
                    candidates = tuple(item for item, _ in candidate_pairs)
                    candidate_refs = {item.handle: reference for item, reference in candidate_pairs}
                    assessment = candidate_interpreter(request, candidates=candidates)
                elif assessment.status in {InputUnderstandingStatus.ACTION,
                                           InputUnderstandingStatus.OBSERVE}:
                    selected = assessment.target_ref or prior.resolved_target_handle
                    if prior.answer_mode == "choice":
                        ordinal = request.text.strip()
                        expected = (prior.option_handles[int(ordinal) - 1]
                                    if ordinal.isdecimal()
                                    and 1 <= int(ordinal) <= len(prior.option_handles)
                                    else None)
                        if (selected not in prior.option_handles
                                or (ordinal.isdecimal() and selected != expected)):
                            self._pending_clarification = None
                            return self._input_failure(request, digest, "clarification_choice_invalid")
                    assessment = replace(
                        assessment, intent=prior.intent,
                        target_ref=assessment.target_ref or prior.resolved_target_handle,
                    )
                    self._pending_clarification = None
                elif assessment.status is InputUnderstandingStatus.CANCELLED:
                    self._pending_clarification = None
                elif assessment.status is InputUnderstandingStatus.CLARIFICATION_REQUIRED:
                    self._pending_clarification = None
            elif pending is not None:
                self._pending_clarification = None
                return self._input_failure(request, digest, "clarification_provider_unavailable")
            elif callable(candidate_interpreter):
                assessment = candidate_interpreter(request, candidates=candidates)
            else:
                assessment = provider.understand(request, authorized_targets=admission_targets)
            provider_returned = True
            if not isinstance(assessment, PlayerInputAssessment):
                raise TypeError("input provider returned an untyped assessment")
            if using_candidates and assessment.target_ref is not None:
                reference = candidate_refs.get(assessment.target_ref)
                if reference is None:
                    raise PermissionError("input provider proposed an unknown candidate")
                assessment = replace(assessment, target_ref=reference)
            selected_kind = next((item.kind for item, reference in candidate_pairs
                                  if reference == assessment.target_ref), None)
            emit_input_diagnostic(request.request_id, "interpretation",
                                  structured_response="accepted",
                                  status=assessment.status.value,
                                  selected_mechanism_kind=selected_kind,
                                  clarification_requested=(assessment.status is InputUnderstandingStatus.CLARIFICATION_REQUIRED),
                                  clarification_answer_mode=(assessment.answer_mode if assessment.status is InputUnderstandingStatus.CLARIFICATION_REQUIRED else None),
                                  clarification_option_count=len(assessment.option_handles),
                                  clarification_available=("unknown" if assessment.status is InputUnderstandingStatus.UNPARSEABLE else None),
                                  unparseable_reason=("provider_unspecified" if assessment.status is InputUnderstandingStatus.UNPARSEABLE else None),
                                  stopped_before_attempt=(assessment.status is not InputUnderstandingStatus.ACTION))
        except PlayerTaskAborted:
            raise
        except Exception as exc:
            emit_input_diagnostic(request.request_id, "interpretation",
                                  structured_response=("rejected" if provider_returned else "unavailable"),
                                  provider_returned=provider_returned,
                                  failure_type=type(exc).__name__,
                                  stopped_before_attempt=True)
            self._check_task_binding()
            return self._input_failure(
                request, digest, "input_understanding_failed:" + type(exc).__name__,
            )
        self._check_task_binding()

        if pending is not None and (
                monotonic() >= pending.deadline
                or not self._clarification_context_valid(context_reads)
                or self._candidate_identities(candidate_pairs)
                    != self._candidate_identities(self._request_candidates())):
            self._pending_clarification = None
            return self._complete_input_result(request.request_id, digest,
                PlayerActionOutcome(request.request_id, "clarification_expired"))

        if assessment.status is InputUnderstandingStatus.CANCELLED:
            return self._complete_input_result(request.request_id, digest,
                PlayerActionOutcome(request.request_id, "clarification_cancelled"))

        if (using_candidates and assessment.status in {
                InputUnderstandingStatus.ACTION, InputUnderstandingStatus.OBSERVE}
                and assessment.target_ref is not None
                and self._candidate_identities(candidate_pairs)
                    != self._candidate_identities(self._request_candidates())):
            return self._complete_input_result(request.request_id, digest,
                PlayerActionOutcome(request.request_id, "target_unavailable"))

        if (using_candidates and assessment.status is InputUnderstandingStatus.ACTION
                and assessment.target_ref is not None):
            offered = next((candidate.supported_methods for candidate, reference in candidate_pairs
                            if reference == assessment.target_ref), ())
            if assessment.method not in offered:
                return self._input_failure(request, digest, "action_method_not_offered")

        if assessment.status is InputUnderstandingStatus.OBSERVE:
            visible = self._current_visible_environment()
            if assessment.target_ref is not None:
                current_refs = {reference for _, reference in self._request_candidates()}
                if assessment.target_ref not in current_refs:
                    return self._complete_input_result(request.request_id, digest,
                        PlayerActionOutcome(request.request_id, "target_unavailable"))
                visible = tuple(item for item in visible if item.subject_ref == assessment.target_ref)
            if not visible:
                return self._complete_input_result(request.request_id, digest,
                    PlayerActionOutcome(request.request_id, "observation_empty"))
            try:
                scope = fence.snapshot_scope() if fence is not None and binding is not None else nullcontext()
                with scope:
                    self._check_task_binding()
                    result = self.presentation.publish_observation_result(request.request_id, visible)
            except PlayerTaskAborted:
                raise
            except Exception as exc:
                self._fallback_diagnostics[request.request_id] = (
                    "observation_delivery_failed:" + type(exc).__name__
                )
                return self._complete_input_result(request.request_id, digest,
                    PlayerActionOutcome(request.request_id, "reasoning_unavailable"))
            return self._complete_input_result(request.request_id, digest,
                PlayerActionOutcome(request.request_id, "observed",
                                    tuple(item.content for item in result.batch.messages)))

        if assessment.status is InputUnderstandingStatus.UNPARSEABLE:
            state = _issue_no_result_state(
                request.request_id, NoResultReason.UNPARSEABLE_INPUT, digest,
            )
            context = NarrativeFallbackContext(
                state, "", "", digest, input_text=request.text,
            )
            run = self.narrative_fallback.render(context)
            if run.failure_code is not None:
                suffix = "" if run.exception_type is None else ":" + run.exception_type
                self._fallback_diagnostics[request.request_id] = run.failure_code + suffix
            narrative = None
            recovery_action = "clarify_or_retry"
            if run.text is not None:
                try:
                    self._check_task_binding()
                    narrative = self.presentation.publish_narrative_fallback(state, run.text)
                    recovery_action = None
                except PlayerTaskAborted:
                    raise
                except Exception as exc:
                    self._fallback_diagnostics[request.request_id] = (
                        "presentation_rejected:" + type(exc).__name__
                    )
            outcome = PlayerActionOutcome(
                request.request_id, "unparseable", narrative_fallback=narrative,
                recovery_action=recovery_action, no_result_state=state,
            )
            return self._complete_input_result(request.request_id, digest, outcome)

        if assessment.status is InputUnderstandingStatus.CLARIFICATION_REQUIRED:
            if using_candidates and (
                any(handle not in candidate_refs for handle in assessment.option_handles)
                or (assessment.resolved_target_handle is not None
                    and assessment.resolved_target_handle not in candidate_refs)
            ):
                return self._input_failure(request, digest, "clarification_option_invalid")
            state = _issue_no_result_state(
                request.request_id, NoResultReason.CLARIFICATION_REQUIRED, digest,
            )
            clarification = None
            recovery_action = None
            question = assessment.clarification_question
            if assessment.answer_mode == "choice":
                descriptions = {candidate.handle: candidate.description for candidate in candidates}
                if any(handle not in descriptions for handle in assessment.option_handles):
                    return self._input_failure(request, digest, "clarification_option_invalid")
                options = " ".join(
                    f"{index}. {descriptions[handle]}"
                    for index, handle in enumerate(assessment.option_handles, 1)
                )
                question = f"请选择一个当前可见的对象：{options}"
            try:
                self._check_task_binding()
                clarification = self.presentation.publish_clarification(
                    state, assessment.missing_information, question,
                )
            except PlayerTaskAborted:
                raise
            except Exception as exc:
                self._fallback_diagnostics[request.request_id] = (
                    "clarification_delivery_failed:" + type(exc).__name__
                )
                recovery_action = "clarify_or_retry"
            outcome = PlayerActionOutcome(
                request.request_id, "clarification_required",
                recovery_action=recovery_action, no_result_state=state,
                clarification=clarification,
            )
            completed = self._complete_input_result(request.request_id, digest, outcome)
            if (fence is not None and clarification is not None
                    and fence.restore_generation == original_generation
                    and self._clarification_context_valid(context_reads)
                    and self._candidate_identities(candidate_pairs)
                        == self._candidate_identities(self._request_candidates())):
                self._pending_clarification = _PendingClarification(
                    request, assessment, session.session_id, fence.session_id,
                    original_generation, monotonic() + 120.0,
                    candidate_pairs, context_reads,
                    None if binding is None else binding.cancellation,
                )
            return completed

        try:
            if assessment.target_ref is not None:
                address = InteractionReference.parse(assessment.target_ref)
                current_authorized = self.available_targets()
                authorized_identifiers = set()
                for reference in admission_targets:
                    try:
                        parsed = InteractionReference.parse(reference)
                    except ValueError:
                        continue
                    if parsed.namespace == "object":
                        authorized_identifiers.add(parsed.identifier)
                current_identifiers = set()
                for reference in current_authorized:
                    try:
                        parsed = InteractionReference.parse(reference)
                    except ValueError:
                        continue
                    if parsed.namespace == "object":
                        current_identifiers.add(parsed.identifier)
                if (address.namespace != "object"
                        or (assessment.target_ref not in admission_targets
                            and address.identifier not in authorized_identifiers)
                        or (assessment.target_ref not in current_authorized
                            and address.identifier not in current_identifiers)):
                    return self._input_failure(request, digest, "input_target_not_authorized")
            action_request = PlayerActionRequest(
                request.request_id, request.session_id, request.world_id,
                assessment.intent, assessment.method, assessment.target_ref,
            )
        except Exception as exc:
            return self._input_failure(
                request, digest, "input_assessment_invalid:" + type(exc).__name__,
            )
        self._check_task_binding()
        return self._submit_action(action_request, digest, preclaimed=True, clarification=pending)

    def has_completed_event_for_request(self, request_id: str, digest: str) -> bool:
        """Check canonical EventHistory for a committed request without exposing its Event."""
        with self._request_lock:
            entry = self._requests.get(request_id)
            return bool(
                entry is not None and entry[0] == digest and isinstance(entry[1], Event)
                and self.context.event_history.get_processing_status(entry[1].id)
                is EventProcessingStatus.COMPLETE
            )

    def retry_input_presentation(self, request: PlayerInputRequest) -> PlayerActionOutcome:
        """Redeliver a completed input action without interpreting or dispatching it again."""
        if not isinstance(request, PlayerInputRequest):
            raise TypeError("PlayerInputRequest required")
        with self._request_lock:
            return self._retry_input_presentation_locked(request)

    def _retry_input_presentation_in_runtime_snapshot(
        self, request: PlayerInputRequest,
    ) -> PlayerActionOutcome:
        """Retry under the original permit, preserving request-lock/fence order."""
        if not isinstance(request, PlayerInputRequest):
            raise TypeError("PlayerInputRequest required")
        with self._request_lock:
            fence = self.processor.write_fence
            if fence is None:
                raise PermissionError("Runtime-bound presentation retry is unavailable")
            with fence.snapshot_scope():
                return self._retry_input_presentation_locked(request)

    def _retry_input_presentation_locked(
        self, request: PlayerInputRequest,
    ) -> PlayerActionOutcome:
        digest = self._input_digest(request)
        entry = self._requests.get(request.request_id)
        if entry is None or entry[0] != digest or not isinstance(entry[1], Event):
            raise PermissionError("request has no matching committed Event to present")
        if self.context.event_history.get_processing_status(entry[1].id) is not EventProcessingStatus.COMPLETE:
            raise PermissionError("request Event is not canonically complete")
        return self._resume_event_delivery(request.request_id, digest, entry[1])
