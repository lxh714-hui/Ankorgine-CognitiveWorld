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
    live_resolution_origin: tuple[object, ...] | None = None


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

    def _issue_source_receipt(
        self, source: str, *, live_resolution_origin: tuple[object, ...] | None = None
    ) -> None:
        if source not in {"resolution", "system"}:
            raise ValueError("unsupported Event source")
        if live_resolution_origin is not None and (
            source != "resolution" or type(live_resolution_origin) is not tuple
            or len(live_resolution_origin) != 7
            or type(live_resolution_origin[0]) is not int or live_resolution_origin[0] != 1
            or any(value is not None and type(value) not in {str, int}
                   for value in live_resolution_origin)
        ):
            raise ValueError("invalid live Resolution origin")
        self._source_receipt = _EventSourceReceipt(
            _EVENT_SOURCE_SEAL, source, self._source_snapshot(), live_resolution_origin
        )

    def _trusted_live_resolution_origin(self) -> tuple[object, ...] | None:
        if not self.has_trusted_source("resolution"):
            return None
        return self._source_receipt.live_resolution_origin

    def has_trusted_source(self, source: str | None = None) -> bool:
        receipt = self._source_receipt
        return (
            isinstance(receipt, _EventSourceReceipt)
            and receipt.seal is _EVENT_SOURCE_SEAL
            and receipt.snapshot == self._source_snapshot()
            and (source is None or receipt.source == source)
        )
