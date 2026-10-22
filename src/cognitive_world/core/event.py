"""Core event data model."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


class _EventSourceSeal:
    def __deepcopy__(self, memo: dict[int, object]) -> "_EventSourceSeal":
        return self


_EVENT_SOURCE_SEAL = _EventSourceSeal()


@dataclass(frozen=True)
class _EventSourceReceipt:
    seal: object
    source: str
    snapshot: tuple[object, ...]


@dataclass
class Event:
    """A record of a confirmed change that happened in the world."""

    id: str
    type: str
    timestamp: str
    participants: list[str] = field(default_factory=list)
    cause: str = ""
    changes: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    simulation_tick: int | None = None
    dialogue_payload: object | None = None
    _source_receipt: _EventSourceReceipt | None = field(default=None, repr=False, compare=False, init=False)
    _runtime_write_permit: RuntimeWritePermit | None = field(
        default=None, repr=False, compare=False, init=False
    )

    def __post_init__(self) -> None:
        self._runtime_write_permit = RuntimeWriteFence.bind_current_permit()
        if self.simulation_tick is not None and (
            isinstance(self.simulation_tick, bool)
            or not isinstance(self.simulation_tick, int)
            or self.simulation_tick < 0
        ):
            raise ValueError("simulation_tick must be a non-negative integer or None")

    def _source_snapshot(self) -> tuple[object, ...]:
        return (
            self.id,
            self.type,
            self.timestamp,
            deepcopy(self.participants),
            self.cause,
            deepcopy(self.changes),
            deepcopy(self.metadata),
            self.simulation_tick,
            deepcopy(self.dialogue_payload),
        )

    def _issue_source_receipt(self, source: str) -> None:
        if source not in {"resolution", "system"}:
            raise ValueError("unsupported Event source")
        self._source_receipt = _EventSourceReceipt(
            _EVENT_SOURCE_SEAL, source, self._source_snapshot()
        )

    def has_trusted_source(self, source: str | None = None) -> bool:
        receipt = self._source_receipt
        return (
            isinstance(receipt, _EventSourceReceipt)
            and receipt.seal is _EVENT_SOURCE_SEAL
            and receipt.snapshot == self._source_snapshot()
            and (source is None or receipt.source == source)
        )
