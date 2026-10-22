"""Trusted Event-to-chat orchestration using the existing Presentation module."""

from dataclasses import dataclass

from cognitive_world.core.no_result import NoResultState
from cognitive_world.core.action_result import ActionResultKind
from cognitive_world.event.history import EventProcessingStatus
from cognitive_world.presentation.composer import MinimalComposer
from cognitive_world.presentation.contracts import (
    _PRESENTATION_SEAL, _Receipt, NoResultNarrativeMessage, PlayerClarificationMessage,
    PlayerActionFeedbackMessage, ReadOnlyObservationResult, ValidatedMessageBatch,
)
from cognitive_world.presentation.gateway import ChatOutputGateway
from cognitive_world.presentation.perspective import PerspectiveResolver
from cognitive_world.presentation.validator import PresentationValidator
from cognitive_world.presentation.visibility import VisibilityFilter
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.safety.governance import SafetyInput, UniversalSafetyGovernance


_NO_RESULT_REASONS = frozenset({
    "unparseable_input", "clarification_required", "unresolved_attempt",
    "npc_reasoning_unavailable", "technical_failure", "candidates_rejected",
    "retries_exhausted",
})
_MAX_NARRATIVE_CHARS = 640


@dataclass
class PresentationPipeline:
    """Resolve a host-bound view, validate facts, and send through one Gateway."""

    runtime_context: RuntimeContext
    visibility_filter: VisibilityFilter
    composer: MinimalComposer
    validator: PresentationValidator
    gateway: ChatOutputGateway
    safety_governance: UniversalSafetyGovernance | None = None

    def __post_init__(self) -> None:
        if self.safety_governance is None:
            self.safety_governance = self.runtime_context.safety_governance
        elif self.safety_governance is not self.runtime_context.safety_governance:
            raise ValueError("PresentationPipeline must share RuntimeContext safety governance")

    @classmethod
    def for_runtime(
        cls,
        runtime_context: RuntimeContext,
        gateway: ChatOutputGateway,
        composer: MinimalComposer | None = None,
    ) -> "PresentationPipeline":
        """Wire the existing Runtime stores into the trusted Presentation path."""
        if runtime_context.observation_store is None:
            raise ValueError("RuntimeContext must provide the ObservationStore")
        selected_composer = composer or MinimalComposer()
        visibility_filter = VisibilityFilter(
            runtime_context.event_history,
            runtime_context.observation_store,
        )
        validator = PresentationValidator(visibility_filter, selected_composer)
        return cls(
            runtime_context,
            visibility_filter,
            selected_composer,
            validator,
            gateway,
            runtime_context.safety_governance,
        )

    def publish_event(self, event_id: str) -> ValidatedMessageBatch:
        """Publish only Event facts already observed by the trusted view Agent."""
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id must be a non-empty string")
        history = self.runtime_context.event_history
        event = history.get_event(event_id)
        evidence = history.get_processing_evidence(event_id)
        if (
            event is None
            or not event.has_trusted_source()
            or evidence is None
            or not evidence.has_trusted_source(event)
        ):
            raise PermissionError("Event has no trusted recorded processing evidence")

        perspective = PerspectiveResolver(self.runtime_context).resolve()
        authorized_inputs = self.visibility_filter.filter(event, evidence, perspective)
        messages = self.composer.compose(authorized_inputs, perspective)
        batch = self.validator.validate_and_issue(
            messages,
            authorized_inputs,
            perspective,
        )
        for message in batch.messages:
            if not isinstance(self.safety_governance, UniversalSafetyGovernance):
                raise RuntimeError("PresentationPipeline has no valid safety governance")
            self.safety_governance.require_presentation_allowed(SafetyInput(
                actor_id=perspective.observer_id,
                source="player_presentation",
                intent=message.content,
                target_refs=message.source_fact_ids,
                context="authorized, already-composed player-visible summary",
            ))
        self.gateway.send(batch)
        return batch

    def publish_action_feedback(
        self, event_id: str, request_id: str, *, has_visible_result: bool,
    ) -> PlayerActionFeedbackMessage | None:
        """Project a finite result code from a completed Resolution Event."""
        if (not isinstance(event_id, str) or not event_id
                or not isinstance(request_id, str) or not request_id
                or type(has_visible_result) is not bool):
            raise ValueError("action feedback request is invalid")
        history = self.runtime_context.event_history
        event = history.get_event(event_id)
        evidence = history.get_processing_evidence(event_id)
        if (event is None or event.type != "resolution"
                or not event.has_trusted_source("resolution")
                or evidence is None or not evidence.has_trusted_source(event)
                or history.get_processing_status(event_id) is not EventProcessingStatus.COMPLETE):
            raise PermissionError("action feedback requires a completed trusted Resolution Event")
        try:
            kind = ActionResultKind(event.metadata.get("action_result_kind"))
        except (TypeError, ValueError):
            return None
        success = bool(event.changes and isinstance(event.changes[0], dict)
                       and event.changes[0].get("success") is True)
        if kind is ActionResultKind.STATE_CHANGED:
            if not success:
                raise PermissionError("state-change feedback conflicts with the Resolution Event")
            if has_visible_result:
                return None
            kind = ActionResultKind.EXECUTED_NO_OBSERVABLE_CHANGE
        elif kind is ActionResultKind.GOAL_ALREADY_SATISFIED:
            if success:
                raise PermissionError("already-satisfied feedback conflicts with the Resolution Event")
        elif kind is ActionResultKind.ACTION_FAILED:
            if success:
                raise PermissionError("failure feedback conflicts with the Resolution Event")
        else:
            return None

        perspective = PerspectiveResolver(self.runtime_context).resolve()
        content = self.composer.action_feedback(kind)
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise RuntimeError("PresentationPipeline has no valid safety governance")
        self.safety_governance.require_presentation_allowed(SafetyInput(
            actor_id=perspective.observer_id,
            source="player_presentation",
            intent=content,
            target_refs=(),
            context="finite wording projected from a completed trusted Resolution result",
        ))
        message = PlayerActionFeedbackMessage(
            request_id, perspective.recipient_id, perspective.observer_id,
            perspective.session_id, event.id, kind, content,
        )
        object.__setattr__(message, "_receipt", _Receipt(
            _PRESENTATION_SEAL, message._snapshot(),
            (perspective._snapshot(), (event.id, kind)),
        ))
        sender = getattr(self.gateway, "send_action_feedback", None)
        if not callable(sender):
            raise TypeError("ChatOutputGateway does not support typed action feedback")
        sender(message)
        return message

    def publish_observation_result(
        self, request_id: str, inputs: tuple,
    ) -> ReadOnlyObservationResult:
        """Revalidate current observed facts and display them without issuing an Event."""
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ValueError("observation request identity is invalid")
        perspective = PerspectiveResolver(self.runtime_context).resolve()
        messages = self.composer.compose(inputs, perspective)
        batch = self.validator.validate_and_issue(messages, inputs, perspective)
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise RuntimeError("PresentationPipeline has no valid safety governance")
        for message in batch.messages:
            self.safety_governance.require_presentation_allowed(SafetyInput(
                actor_id=perspective.observer_id,
                source="player_presentation", intent=message.content,
                target_refs=message.source_fact_ids,
                context="current authorized read-only Observation summary",
            ))
        sender = getattr(self.gateway, "send_observation_result", None)
        if not callable(sender):
            raise TypeError("Gateway does not support read-only observation results")
        result = ReadOnlyObservationResult(request_id, batch)
        object.__setattr__(result, "_receipt", _Receipt(
            _PRESENTATION_SEAL, result._snapshot(), perspective._snapshot(),
        ))
        sender(result)
        return result

    def publish_narrative_fallback(
        self, state: NoResultState, content: str,
    ) -> NoResultNarrativeMessage:
        """Publish reviewed no-result wording on a channel without fact provenance."""
        if not isinstance(state, NoResultState) or not state.has_trusted_result_origin():
            raise PermissionError("narrative fallback requires an established no-result reason")
        request_id, no_result_reason = state.request_id, state.reason.value
        if no_result_reason not in _NO_RESULT_REASONS:
            raise PermissionError("narrative fallback reason is not supported")
        if (not isinstance(content, str) or not content.strip()
                or len(content) > _MAX_NARRATIVE_CHARS):
            raise ValueError("narrative fallback content is invalid")
        perspective = PerspectiveResolver(self.runtime_context).resolve()
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise RuntimeError("PresentationPipeline has no valid safety governance")
        self.safety_governance.require_presentation_allowed(SafetyInput(
            actor_id=perspective.observer_id,
            source="player_presentation",
            intent=content,
            context=("reviewed literary wording for an established no-result state; "
                     "not an Event, action result, observation, or cognition update"),
        ))
        message = NoResultNarrativeMessage(
            request_id, perspective.recipient_id, perspective.observer_id,
            perspective.session_id, no_result_reason, state.input_fingerprint, content.strip(),
        )
        object.__setattr__(
            message, "_receipt",
            _Receipt(
                _PRESENTATION_SEAL,
                message._snapshot(),
                (perspective._snapshot(), state._snapshot()),
            ),
        )
        sender = getattr(self.gateway, "send_narrative_fallback", None)
        if not callable(sender):
            raise TypeError("ChatOutputGateway does not support the no-result narrative channel")
        sender(message)
        return message

    def publish_clarification(
        self, state: NoResultState, missing_information: tuple[str, ...], question: str,
    ) -> PlayerClarificationMessage:
        """Publish a question only for a trusted clarification result."""
        if (not isinstance(state, NoResultState) or not state.has_trusted_result_origin()
                or state.reason.value != "clarification_required"):
            raise PermissionError("clarification requires an established clarification result")
        if (not isinstance(missing_information, tuple) or not missing_information
                or len(missing_information) > 4
                or any(not isinstance(item, str) or not item.strip() or len(item) > 120
                       for item in missing_information)):
            raise ValueError("clarification slots are invalid")
        if not isinstance(question, str) or not question.strip() or len(question) > 1_000:
            raise ValueError("clarification question is invalid")
        perspective = PerspectiveResolver(self.runtime_context).resolve()
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise RuntimeError("PresentationPipeline has no valid safety governance")
        self.safety_governance.require_presentation_allowed(SafetyInput(
            actor_id=perspective.observer_id,
            source="player_presentation",
            intent=question,
            context=("a model-proposed clarification question; it has no action, Event, "
                     "observation, or cognition authority"),
        ))
        message = PlayerClarificationMessage(
            state.request_id, perspective.recipient_id, perspective.observer_id,
            perspective.session_id, state.reason.value, state.input_fingerprint,
            missing_information, question.strip(),
        )
        object.__setattr__(message, "_receipt", _Receipt(
            _PRESENTATION_SEAL, message._snapshot(),
            (perspective._snapshot(), state._snapshot()),
        ))
        sender = getattr(self.gateway, "send_clarification", None)
        if not callable(sender):
            raise TypeError("ChatOutputGateway does not support the clarification channel")
        sender(message)
        return message
