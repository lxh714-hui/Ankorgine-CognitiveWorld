"""Authoritative traversable connection stored in WorldState.environment."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PassageState:
    """A known connection between two locations; absence means unknown."""

    passage_id: str
    source_location_id: str
    destination_location_id: str
    traversable: bool

    def __post_init__(self) -> None:
        for name in ("passage_id", "source_location_id", "destination_location_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.traversable) is not bool:
            raise TypeError("traversable must be bool")
