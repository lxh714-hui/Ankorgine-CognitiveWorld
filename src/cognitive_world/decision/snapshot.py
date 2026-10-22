"""Deeply immutable value snapshots for DecisionContext."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class FrozenMapping(Mapping[Any, Any]):
    """Small immutable mapping backed by recursively frozen key/value pairs."""

    _items: tuple[tuple[Any, Any], ...]

    def __getitem__(self, key: Any) -> Any:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[Any]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __deepcopy__(self, memo: dict[int, Any]) -> "FrozenMapping":
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self.items()) == dict(other.items())


@dataclass(frozen=True)
class FrozenRecordSnapshot:
    """Read-only attribute view of one copied cognition record."""

    record_type: str
    _fields: FrozenMapping

    def __post_init__(self) -> None:
        if not isinstance(self.record_type, str) or not isinstance(self._fields, Mapping):
            raise TypeError("FrozenRecordSnapshot requires a type label and field mapping")
        # Keep the invariant true even when a caller constructs this public
        # value directly: its field mapping must not retain mutable references.
        object.__setattr__(self, "_fields", freeze_value(self._fields))

    def __getattr__(self, name: str) -> Any:
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(name) from None

    def __deepcopy__(self, memo: dict[int, Any]) -> "FrozenRecordSnapshot":
        return self


def freeze_value(value: Any) -> Any:
    """Copy supported record values into immutable Python value shapes."""
    # Snapshots produced here are already recursively immutable. Returning
    # them directly makes freezing idempotent and, crucially, preserves their
    # private field map instead of treating the snapshot as an ordinary record
    # whose public ``record_type`` is its only visible attribute.
    if isinstance(value, FrozenRecordSnapshot):
        return value
    if value is None or isinstance(value, (str, bytes, int, float, bool, Enum)):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(
            tuple((freeze_value(key), freeze_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_value(item) for item in value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return FrozenRecordSnapshot(
            record_type=f"{type(value).__module__}.{type(value).__qualname__}",
            _fields=FrozenMapping(
                tuple(
                    (name, freeze_value(item))
                    for name, item in attributes.items()
                    if not name.startswith("_")
                )
            ),
        )
    raise TypeError(f"unsupported mutable DecisionContext value: {type(value).__name__}")
