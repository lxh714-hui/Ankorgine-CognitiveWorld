"""Validate exact authorized inputs and issue a gateway-only message batch."""

from dataclasses import dataclass

from cognitive_world.presentation.composer import MinimalComposer
from cognitive_world.presentation.contracts import (
    _PRESENTATION_SEAL,
    _Receipt,
    PerspectiveContext,
    PlayerVisibleMessage,
    ValidatedMessageBatch,
    VisibleInput,
)
from cognitive_world.presentation.visibility import VisibilityFilter


@dataclass
class PresentationValidator:
    visibility_filter: VisibilityFilter
    composer: MinimalComposer

    def validate_and_issue(
        self,
        messages: tuple[PlayerVisibleMessage, ...],
        inputs: tuple[VisibleInput, ...],
        perspective: PerspectiveContext,
    ) -> ValidatedMessageBatch:
        if not perspective.has_trusted_resolution():
            raise PermissionError("message validation requires a trusted perspective")
        if not isinstance(messages, tuple) or not isinstance(inputs, tuple):
            raise TypeError("messages and authorized inputs must be tuples")
        if len(messages) != len(inputs):
            raise ValueError("each message must map to exactly one authorized fact")

        for message, visible in zip(messages, inputs, strict=True):
            self.visibility_filter.validate_input(visible, perspective)
            expected = self.composer._render(visible)
            if (
                not isinstance(message, PlayerVisibleMessage)
                or not message.has_composition_receipt(perspective)
                or message.recipient_id != perspective.recipient_id
                or message.observer_id != perspective.observer_id
                or message.session_id != perspective.session_id
                or message.source_event_ids != (visible.source_event_id,)
                or message.source_fact_ids != (visible.source_fact_id,)
                or message.visibility_scope != visible.scope
                or message.content != expected
            ):
                raise PermissionError("message does not match its authorized fact input")

            receipt = message._receipt
            if (
                receipt is None
                or receipt.authority_snapshot
                != (perspective._snapshot(), (visible._snapshot(),))
            ):
                raise PermissionError("message composition receipt does not match input")

        batch = ValidatedMessageBatch(
            session_id=perspective.session_id,
            recipient_id=perspective.recipient_id,
            observer_id=perspective.observer_id,
            messages=messages,
        )
        object.__setattr__(
            batch,
            "_receipt",
            _Receipt(
                _PRESENTATION_SEAL,
                batch._snapshot(),
                (
                    perspective._snapshot(),
                    tuple(item._snapshot() for item in inputs),
                ),
            ),
        )
        return batch
