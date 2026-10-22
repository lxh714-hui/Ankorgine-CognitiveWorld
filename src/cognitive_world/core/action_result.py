"""Finite semantic classifications for confirmed player action results."""

from enum import Enum


class ActionResultKind(str, Enum):
    """A typed interpretation of Resolution evidence, never an authority itself."""

    STATE_CHANGED = "state_changed"
    GOAL_ALREADY_SATISFIED = "goal_already_satisfied"
    EXECUTED_NO_OBSERVABLE_CHANGE = "executed_no_observable_change"
    ACTION_FAILED = "action_failed"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    UNSUPPORTED_ACTION = "unsupported_action"
