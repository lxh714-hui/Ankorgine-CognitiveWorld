"""Deterministic prose templates over typed, authorized observable facts."""

from dataclasses import dataclass

from cognitive_world.presentation.contracts import (
    _PRESENTATION_SEAL,
    _Receipt,
    PerspectiveContext,
    PlayerVisibleMessage,
    VisibleInput,
)
from cognitive_world.core.action_result import ActionResultKind


@dataclass(frozen=True)
class MinimalComposer:
    """Render the currently supported room-light fact without inference."""

    def compose(
        self,
        inputs: tuple[VisibleInput, ...],
        perspective: PerspectiveContext,
    ) -> tuple[PlayerVisibleMessage, ...]:
        if not perspective.has_trusted_resolution():
            raise PermissionError("composer requires a resolver-issued perspective")
        if not isinstance(inputs, tuple) or any(
            not isinstance(item, VisibleInput)
            or not item.has_filter_receipt(perspective)
            for item in inputs
        ):
            raise TypeError("composer accepts only authorized VisibleInput records")

        messages: list[PlayerVisibleMessage] = []
        for item in inputs:
            text = self._render(item)
            if text is None:
                raise PermissionError("composer received an unsupported fact")
            message = PlayerVisibleMessage(
                recipient_id=item.recipient_id,
                observer_id=item.observer_id,
                session_id=item.session_id,
                source_event_ids=(item.source_event_id,),
                source_fact_ids=(item.source_fact_id,),
                visibility_scope=item.scope,
                content=text,
            )
            object.__setattr__(
                message,
                "_receipt",
                _Receipt(
                    _PRESENTATION_SEAL,
                    message._snapshot(),
                    (perspective._snapshot(), (item._snapshot(),)),
                ),
            )
            messages.append(message)
        return tuple(messages)

    @staticmethod
    def _render(item: VisibleInput) -> str | None:
        if (
            item.scope == "dialogue"
            and item.fact_type == "social_output"
            and item.predicate == "utterance_delivered"
            and isinstance(item.value, str)
        ):
            # The fact is that the NPC said this; its claims are not world truth.
            return item.value
        if (
            item.scope == "environment"
            and item.fact_type == "environment_state"
            and item.predicate == "room_light_on"
            and item.value is True
        ):
            return "房间里的灯亮了。"
        if item.scope == "environment" and item.fact_type == "environment_state" and item.subject_ref:
            if item.predicate == "door_open" and type(item.value) is bool:
                if item.value and item.source_event_changed_state:
                    return "眼前的门打开了。"
                return "眼前的门开着。" if item.value else "眼前的门关着。"
            if item.predicate == "door_locked" and item.value is True:
                return "眼前的门锁着。"
            if item.predicate == "passage_destination" and isinstance(item.value, str):
                # A destination reference is an internal location identity, not a display name.
                return "这里有一条通道。"
        return None

    @staticmethod
    def action_feedback(kind: ActionResultKind) -> str:
        """Render only finite Resolution semantics, never free-form explanations."""
        if kind is ActionResultKind.GOAL_ALREADY_SATISFIED:
            return "目标当前已经满足。"
        if kind is ActionResultKind.ACTION_FAILED:
            return "这次行动没有达到预期效果。"
        if kind is ActionResultKind.EXECUTED_NO_OBSERVABLE_CHANGE:
            return "行动已裁定完成，但当前没有可展示的已确认变化。"
        if kind is ActionResultKind.INSUFFICIENT_INFORMATION:
            return "还缺少足够信息，暂时无法确认结果。"
        if kind is ActionResultKind.UNSUPPORTED_ACTION:
            return "当前规则不支持这项行动。"
        raise ValueError("state changes are presented through authorized fact messages")
