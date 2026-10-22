"""Resolution result data model for the resolution boundary."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.core.action_result import ActionResultKind


class _ResolutionSeal:
    def __deepcopy__(self, memo: dict[int, object]) -> "_ResolutionSeal":
        return self


_RESOLUTION_SEAL = _ResolutionSeal()


@dataclass(init=False)
class ResolutionResult:
    """Record the result associated with an Attempt and its Event references."""

    resolution_id: str
    attempt_id: str
    success: bool
    outcome: str
    result_kind: ActionResultKind | None
    confirmed: bool
    _event_ids: list[str] = field(repr=False)
    _metadata: dict[str, Any] = field(repr=False)
    _world_effects: list[dict[str, Any]] = field(repr=False)
    _attempt_snapshot: tuple[Any, ...] | None = field(default=None, repr=False)
    _confirmation_snapshot: object | None = field(default=None, repr=False)

    def __init__(
        self,
        resolution_id: str,
        attempt_id: str,
        success: bool,
        outcome: str,
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        confirmed: bool = False,
        world_effects: list[dict[str, Any]] | None = None,
        _attempt_snapshot: tuple[Any, ...] | None = None,
        result_kind: ActionResultKind | None = None,
    ) -> None:
        self.resolution_id = resolution_id
        self.attempt_id = attempt_id
        self.success = success
        self.outcome = outcome
        if result_kind is not None and not isinstance(result_kind, ActionResultKind):
            raise TypeError("result_kind must be an ActionResultKind")
        self.result_kind = result_kind
        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be a bool")
        self.confirmed = confirmed
        self._event_ids = deepcopy(event_ids if event_ids is not None else [])
        self._metadata = deepcopy(metadata if metadata is not None else {})
        self._world_effects = deepcopy(world_effects if world_effects is not None else [])
        self._attempt_snapshot = deepcopy(_attempt_snapshot)
        self._confirmation_snapshot = None

    @classmethod
    def _issue_confirmed(
        cls,
        *,
        resolution_id: str,
        attempt_id: str,
        success: bool,
        outcome: str,
        event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        world_effects: list[dict[str, Any]] | None = None,
        attempt_snapshot: tuple[Any, ...] | None = None,
        result_kind: ActionResultKind | None = None,
    ) -> "ResolutionResult":
        """Issue an immutable-by-verification result snapshot for ResolutionEngine."""
        result = cls(
            resolution_id=resolution_id,
            attempt_id=attempt_id,
            success=success,
            outcome=outcome,
            event_ids=event_ids,
            metadata=metadata,
            confirmed=True,
            world_effects=world_effects,
            _attempt_snapshot=attempt_snapshot,
            result_kind=result_kind,
        )
        result._confirmation_snapshot = (_RESOLUTION_SEAL, result._snapshot())
        return result

    def _snapshot(self) -> tuple[object, ...]:
        return (
            self.resolution_id,
            self.attempt_id,
            self.success,
            self.outcome,
            self.result_kind,
            self.confirmed,
            deepcopy(self._event_ids),
            deepcopy(self._metadata),
            deepcopy(self._world_effects),
            deepcopy(self._attempt_snapshot),
        )

    def _has_valid_confirmation(self, attempt_id: Any = None) -> bool:
        snapshot = self._confirmation_snapshot
        expected_attempt_id = None
        attempt_matches = True
        if isinstance(attempt_id, str):
            expected_attempt_id = attempt_id
        elif attempt_id is not None:
            expected_attempt_id = getattr(attempt_id, "attempt_id", None)
            snapshot_method = getattr(attempt_id, "_resolution_snapshot", None)
            attempt_matches = callable(snapshot_method) and snapshot_method() == self._attempt_snapshot
        return (
            self.confirmed is True
            and isinstance(snapshot, tuple)
            and len(snapshot) == 2
            and snapshot[0] is _RESOLUTION_SEAL
            and snapshot[1] == self._snapshot()
            and (expected_attempt_id is None or self.attempt_id == expected_attempt_id)
            and attempt_matches
            and (self._attempt_snapshot is not None or attempt_id is None or isinstance(attempt_id, str))
        )

    @property
    def event_ids(self) -> list[str]:
        """Return an isolated copy of the referenced Events."""
        return deepcopy(self._event_ids)

    @property
    def metadata(self) -> dict[str, Any]:
        """Return an isolated copy of the extensible result metadata."""
        return deepcopy(self._metadata)

    @property
    def world_effects(self) -> list[dict[str, Any]]:
        """Return a copy of effects adjudicated by the trusted Resolution policy."""
        return deepcopy(self._world_effects)
