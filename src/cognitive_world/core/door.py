"""Typed door facts stored in the existing WorldState environment collection."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DoorState:
    """Authoritative door condition; ``interaction_location_id`` is exact contact space."""

    door_id: str
    interaction_location_id: str
    is_open: bool
    is_locked: bool
    hand_operable: bool
    key_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("door_id", "interaction_location_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if any(type(value) is not bool for value in (self.is_open, self.is_locked, self.hand_operable)):
            raise TypeError("door state flags must be bool values")
        if self.key_id is not None and (not isinstance(self.key_id, str) or not self.key_id):
            raise ValueError("key_id must be non-empty when provided")
