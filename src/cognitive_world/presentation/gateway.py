"""The sole player-chat output interface and in-memory implementation."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol

from cognitive_world.presentation.contracts import (
    NoResultNarrativeMessage, PlayerActionFeedbackMessage, PlayerClarificationMessage, ReadOnlyObservationResult,
    ValidatedMessageBatch,
)
from cognitive_world.presentation.perspective import PerspectiveResolver
from cognitive_world.runtime.context import RuntimeContext


class ChatOutputGateway(Protocol):
    """Accept fact-backed batches and a separately typed no-result aside."""

    def send(self, batch: ValidatedMessageBatch) -> None:
        """Deliver a validated batch to its bound active player session."""
        ...

    def send_narrative_fallback(self, message: NoResultNarrativeMessage) -> None:
        """Deliver display-only no-result wording, never an Event or fact."""
        ...

    def send_clarification(self, message: PlayerClarificationMessage) -> None:
        """Deliver a typed clarification question without fact provenance."""
        ...

    def send_observation_result(self, result: ReadOnlyObservationResult) -> None:
        """Deliver a read-only query of already authorized facts, without a new Event."""
        ...

    def send_action_feedback(self, message: PlayerActionFeedbackMessage) -> None:
        """Deliver a typed summary of a completed Resolution, not a fact."""
        ...


@dataclass
class InMemoryChatOutputGateway:
    """Production-callable prototype sink; a future UI can replace its storage."""

    runtime_context: RuntimeContext
    _batches: list[ValidatedMessageBatch] = field(default_factory=list, repr=False)
    _narrative_fallbacks: list[NoResultNarrativeMessage] = field(default_factory=list, repr=False)
    _clarifications: list[PlayerClarificationMessage] = field(default_factory=list, repr=False)
    _observation_results: list[ReadOnlyObservationResult] = field(default_factory=list, repr=False)
    _action_feedback: list[PlayerActionFeedbackMessage] = field(default_factory=list, repr=False)
    _last_error_code: str | None = field(default=None, init=False, repr=False)

    def send(self, batch: ValidatedMessageBatch) -> None:
        if not isinstance(batch, ValidatedMessageBatch):
            self._last_error_code = "invalid_batch_type"
            raise TypeError("ChatOutputGateway accepts only ValidatedMessageBatch")
        try:
            perspective = PerspectiveResolver(self.runtime_context).resolve()
            if not batch.has_validator_receipt(perspective):
                raise PermissionError("message batch is not validator-issued or was modified")
            if (
                batch.session_id != perspective.session_id
                or batch.recipient_id != perspective.recipient_id
                or batch.observer_id != perspective.observer_id
                or any(
                    message.session_id != perspective.session_id
                    or message.recipient_id != perspective.recipient_id
                    or message.observer_id != perspective.observer_id
                    or not message.has_composition_receipt(perspective)
                    for message in batch.messages
                )
            ):
                raise PermissionError("output target does not match the active session")
        except Exception:
            self._last_error_code = "authorization_rejected"
            raise
        # A retry after an uncertain caller failure must not append the same
        # authorized output twice in this in-process adapter.
        key = (batch.session_id, batch.recipient_id, tuple(
            event_id for message in batch.messages for event_id in message.source_event_ids
        ))
        for existing in self._batches:
            existing_key = (existing.session_id, existing.recipient_id, tuple(
                event_id for message in existing.messages for event_id in message.source_event_ids
            ))
            if existing_key == key:
                if existing._snapshot() != batch._snapshot():
                    self._last_error_code = "conflicting_delivery"
                    raise PermissionError("an Event was already delivered with different content")
                self._last_error_code = None
                return
        self._batches.append(deepcopy(batch))
        self._last_error_code = None

    def messages_for(self, recipient_id: str) -> tuple:
        """Return isolated messages delivered to the given recipient."""
        return tuple(
            deepcopy(message)
            for batch in self._batches
            if batch.recipient_id == recipient_id
            for message in batch.messages
        )

    def send_narrative_fallback(self, message: NoResultNarrativeMessage) -> None:
        """Store a distinct display-only channel, isolated from Event messages."""
        if not isinstance(message, NoResultNarrativeMessage):
            self._last_error_code = "invalid_narrative_type"
            raise TypeError("narrative channel accepts only NoResultNarrativeMessage")
        try:
            perspective = PerspectiveResolver(self.runtime_context).resolve()
            if (not message.has_narrative_receipt(perspective)
                    or message.session_id != perspective.session_id
                    or message.recipient_id != perspective.recipient_id
                    or message.observer_id != perspective.observer_id):
                raise PermissionError("narrative fallback is not issued for the active session")
        except Exception:
            self._last_error_code = "narrative_authorization_rejected"
            raise
        for existing in self._narrative_fallbacks:
            if (existing.session_id, existing.request_id) == (message.session_id, message.request_id):
                if existing._snapshot() != message._snapshot():
                    self._last_error_code = "conflicting_narrative_delivery"
                    raise PermissionError("request already has different narrative fallback content")
                self._last_error_code = None
                return
        self._narrative_fallbacks.append(deepcopy(message))
        self._last_error_code = None

    def narrative_fallbacks_for(self, recipient_id: str) -> tuple[NoResultNarrativeMessage, ...]:
        """Return isolated no-result asides; never mix them into Event messages."""
        return tuple(
            deepcopy(message) for message in self._narrative_fallbacks
            if message.recipient_id == recipient_id
        )

    def send_clarification(self, message: PlayerClarificationMessage) -> None:
        if not isinstance(message, PlayerClarificationMessage):
            self._last_error_code = "invalid_clarification_type"
            raise TypeError("clarification channel accepts only PlayerClarificationMessage")
        try:
            perspective = PerspectiveResolver(self.runtime_context).resolve()
            if (not message.has_clarification_receipt(perspective)
                    or message.session_id != perspective.session_id
                    or message.recipient_id != perspective.recipient_id
                    or message.observer_id != perspective.observer_id):
                raise PermissionError("clarification is not issued for the active session")
        except Exception:
            self._last_error_code = "clarification_authorization_rejected"
            raise
        for existing in self._clarifications:
            if (existing.session_id, existing.request_id) == (message.session_id, message.request_id):
                if existing._snapshot() != message._snapshot():
                    self._last_error_code = "conflicting_clarification_delivery"
                    raise PermissionError("request already has different clarification content")
                self._last_error_code = None
                return
        self._clarifications.append(deepcopy(message))
        self._last_error_code = None

    def clarifications_for(self, recipient_id: str) -> tuple[PlayerClarificationMessage, ...]:
        return tuple(
            deepcopy(message) for message in self._clarifications
            if message.recipient_id == recipient_id
        )

    def send_observation_result(self, result: ReadOnlyObservationResult) -> None:
        perspective = PerspectiveResolver(self.runtime_context).resolve()
        if (not isinstance(result, ReadOnlyObservationResult)
                or not result.has_result_receipt(perspective)):
            raise PermissionError("read-only observation requires a validated result")
        batch = result.batch
        if (batch.session_id != perspective.session_id or batch.recipient_id != perspective.recipient_id
                or batch.observer_id != perspective.observer_id
                or any(not message.has_composition_receipt(perspective)
                       for message in batch.messages)):
            raise PermissionError("observation result belongs to another session")
        for prior in self._observation_results:
            if prior.request_id == result.request_id:
                if prior._snapshot() != result._snapshot():
                    raise PermissionError("observation result identity reused with changed facts")
                return
        self._observation_results.append(deepcopy(result))

    def observation_results_for(self, recipient_id: str) -> tuple[ReadOnlyObservationResult, ...]:
        return tuple(deepcopy(result) for result in self._observation_results
                     if result.batch.recipient_id == recipient_id)

    def send_action_feedback(self, message: PlayerActionFeedbackMessage) -> None:
        if not isinstance(message, PlayerActionFeedbackMessage):
            self._last_error_code = "invalid_action_feedback_type"
            raise TypeError("action feedback channel accepts only PlayerActionFeedbackMessage")
        try:
            perspective = PerspectiveResolver(self.runtime_context).resolve()
            if (not message.has_feedback_receipt(perspective)
                    or message.session_id != perspective.session_id
                    or message.recipient_id != perspective.recipient_id
                    or message.observer_id != perspective.observer_id):
                raise PermissionError("action feedback is not issued for the active session")
        except Exception:
            self._last_error_code = "action_feedback_authorization_rejected"
            raise
        for existing in self._action_feedback:
            if (existing.session_id, existing.request_id) == (message.session_id, message.request_id):
                if existing._snapshot() != message._snapshot():
                    raise PermissionError("request already has different action feedback")
                self._last_error_code = None
                return
        self._action_feedback.append(deepcopy(message))
        self._last_error_code = None

    def action_feedback_for(self, recipient_id: str) -> tuple[PlayerActionFeedbackMessage, ...]:
        return tuple(deepcopy(message) for message in self._action_feedback
                     if message.recipient_id == recipient_id)

    @property
    def last_error_code(self) -> str | None:
        """Expose only a non-sensitive status label for host diagnostics."""
        return self._last_error_code
