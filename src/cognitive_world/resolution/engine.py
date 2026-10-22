"""Placeholder interface for resolving an Attempt."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.decision.attempt import Attempt
from cognitive_world.core.action_result import ActionResultKind
from cognitive_world.resolution.result import ResolutionResult


@dataclass(frozen=True)
class ResolutionDecision:
    """Rule-evaluation output that is not trusted until issued by this engine."""

    success: bool
    outcome: str
    event_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    world_effects: tuple[dict[str, Any], ...] = ()
    result_kind: ActionResultKind | None = None


@dataclass
class ResolutionEngine:
    """Own the controlled result-confirmation boundary for an Attempt."""

    def resolve(self, attempt: Attempt) -> ResolutionResult:
        """Evaluate an attempt and issue a result snapshot, or remain unresolved.

        Subclasses may implement ``_adjudicate``. Constructing a public
        ResolutionResult with ``confirmed=True`` does not issue confirmation.
        """
        if not isinstance(attempt, Attempt):
            raise TypeError("attempt must be an Attempt")
        decision = self._adjudicate(attempt)
        if decision is None:
            return ResolutionResult(
                resolution_id=f"resolution:{attempt.attempt_id}",
                attempt_id=attempt.attempt_id,
                success=False,
                outcome="unresolved",
                confirmed=False,
            )
        if not isinstance(decision, ResolutionDecision):
            raise TypeError("_adjudicate must return ResolutionDecision or None")
        return ResolutionResult._issue_confirmed(
            resolution_id=f"resolution:{attempt.attempt_id}",
            attempt_id=attempt.attempt_id,
            success=decision.success,
            outcome=decision.outcome,
            event_ids=list(decision.event_ids),
            metadata=deepcopy(decision.metadata),
            world_effects=deepcopy(decision.world_effects),
            attempt_snapshot=attempt._resolution_snapshot(),
            result_kind=decision.result_kind,
        )

    def _adjudicate(self, attempt: Attempt) -> ResolutionDecision | None:
        """Return None until an explicit, trusted rule strategy is installed."""
        return None
