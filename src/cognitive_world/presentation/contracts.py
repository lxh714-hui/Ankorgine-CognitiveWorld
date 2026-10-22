"""Closed presentation data contracts and process-local misuse receipts."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.runtime.context import PlayerMode
from cognitive_world.core.action_result import ActionResultKind


class _PresentationSeal:
    def __deepcopy__(self, memo: dict[int, Any]) -> "_PresentationSeal":
        return self


_PRESENTATION_SEAL = _PresentationSeal()


@dataclass(frozen=True)
class _Receipt:
    seal: object = field(repr=False, compare=False)
    snapshot: tuple[Any, ...] = field(repr=False)
    authority_snapshot: tuple[Any, ...] = field(repr=False)


@dataclass(frozen=True)
class PerspectiveContext:
    """Resolver-issued perspective; direct construction is not authorization."""

    recipient_id: str
    observer_id: str
    visible_scopes: frozenset[str]
    session_id: str
    mode: PlayerMode
    character_id: str | None = None
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.recipient_id, self.observer_id, self.session_id
        )):
            raise ValueError("recipient, observer, and session IDs are required")
        if not isinstance(self.mode, PlayerMode):
            raise TypeError("mode must be a PlayerMode")
        scopes = frozenset(self.visible_scopes)
        if not scopes or any(not isinstance(scope, str) or not scope for scope in scopes):
            raise ValueError("visible_scopes must contain non-empty strings")
        object.__setattr__(self, "visible_scopes", scopes)

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.recipient_id,
            self.observer_id,
            tuple(sorted(self.visible_scopes)),
            self.session_id,
            self.mode,
            self.character_id,
        )

    def has_trusted_resolution(self) -> bool:
        receipt = self._receipt
        return (
            isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
        )


@dataclass(frozen=True)
class VisibleInput:
    """A typed fact from a trusted, observer-authorized Observation."""

    recipient_id: str
    observer_id: str
    session_id: str
    source_event_id: str
    source_fact_id: str
    source_observation_id: str
    scope: str
    fact_type: str
    predicate: str
    value: str | int | float | bool | None | tuple[str | int | float | bool | None, ...]
    subject_ref: str | None = None
    location_id: str | None = None
    source_event_changed_state: bool = False
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.recipient_id,
            self.observer_id,
            self.session_id,
            self.source_event_id,
            self.source_fact_id,
            self.source_observation_id,
            self.scope,
            self.fact_type,
            self.predicate,
            deepcopy(self.value),
            self.subject_ref,
            self.location_id,
            self.source_event_changed_state,
        )

    def has_filter_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            perspective.has_trusted_resolution()
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and receipt.authority_snapshot == perspective._snapshot()
        )


@dataclass(frozen=True)
class PlayerVisibleMessage:
    """Closed player-facing message; construction alone grants no authority."""

    recipient_id: str
    observer_id: str
    session_id: str
    source_event_ids: tuple[str, ...]
    source_fact_ids: tuple[str, ...]
    visibility_scope: str
    content: str
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        object.__setattr__(self, "source_fact_ids", tuple(self.source_fact_ids))

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.recipient_id,
            self.observer_id,
            self.session_id,
            self.source_event_ids,
            self.source_fact_ids,
            self.visibility_scope,
            self.content,
        )

    def has_composition_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            perspective.has_trusted_resolution()
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and bool(receipt.authority_snapshot)
            and receipt.authority_snapshot[0] == perspective._snapshot()
        )


@dataclass(frozen=True)
class PlayerActionFeedbackMessage:
    """Bounded wording for a Resolution result, separate from fact messages."""

    request_id: str
    recipient_id: str
    observer_id: str
    session_id: str
    source_event_id: str
    result_kind: ActionResultKind
    content: str
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def _snapshot(self) -> tuple[Any, ...]:
        return (self.request_id, self.recipient_id, self.observer_id,
                self.session_id, self.source_event_id, self.result_kind, self.content)

    def has_feedback_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            perspective.has_trusted_resolution()
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and len(receipt.authority_snapshot) == 2
            and receipt.authority_snapshot[0] == perspective._snapshot()
            and receipt.authority_snapshot[1] == (self.source_event_id, self.result_kind)
        )


@dataclass(frozen=True)
class NoResultNarrativeMessage:
    """Display-only wording for a no-result state; it carries no Event/fact refs."""

    request_id: str
    recipient_id: str
    observer_id: str
    session_id: str
    no_result_reason: str
    input_fingerprint: str
    content: str
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.request_id, self.recipient_id, self.observer_id, self.session_id,
            self.no_result_reason, self.input_fingerprint, self.content,
        )

    def has_narrative_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            perspective.has_trusted_resolution()
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and len(receipt.authority_snapshot) == 2
            and receipt.authority_snapshot[0] == perspective._snapshot()
            and receipt.authority_snapshot[1] == (
                self.request_id, self.no_result_reason, self.input_fingerprint,
            )
        )


@dataclass(frozen=True)
class PlayerClarificationMessage:
    """A display-only question tied to a trusted clarification result."""

    request_id: str
    recipient_id: str
    observer_id: str
    session_id: str
    no_result_reason: str
    input_fingerprint: str
    missing_information: tuple[str, ...]
    question: str
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_information", tuple(self.missing_information))

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.request_id, self.recipient_id, self.observer_id, self.session_id,
            self.no_result_reason, self.input_fingerprint,
            self.missing_information, self.question,
        )

    def has_clarification_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            perspective.has_trusted_resolution()
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and len(receipt.authority_snapshot) == 2
            and receipt.authority_snapshot[0] == perspective._snapshot()
            and receipt.authority_snapshot[1] == (
                self.request_id, self.no_result_reason, self.input_fingerprint,
            )
        )


@dataclass(frozen=True)
class ReadOnlyObservationResult:
    """Request-scoped display of previously authorized facts; no new Event."""

    request_id: str
    batch: "ValidatedMessageBatch"
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def _snapshot(self) -> tuple[Any, ...]:
        return self.request_id, self.batch._snapshot()

    def has_result_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            bool(self.request_id) and len(self.request_id) <= 128
            and self.batch.has_validator_receipt(perspective)
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and receipt.authority_snapshot == perspective._snapshot()
        )

@dataclass(frozen=True)
class ValidatedMessageBatch:
    """Validator-issued batch accepted by the ChatOutputGateway."""

    session_id: str
    recipient_id: str
    observer_id: str
    messages: tuple[PlayerVisibleMessage, ...]
    _receipt: _Receipt | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.session_id,
            self.recipient_id,
            self.observer_id,
            tuple(message._snapshot() for message in self.messages),
        )

    def has_validator_receipt(self, perspective: PerspectiveContext) -> bool:
        receipt = self._receipt
        return (
            perspective.has_trusted_resolution()
            and isinstance(receipt, _Receipt)
            and receipt.seal is _PRESENTATION_SEAL
            and receipt.snapshot == self._snapshot()
            and bool(receipt.authority_snapshot)
            and receipt.authority_snapshot[0] == perspective._snapshot()
        )
