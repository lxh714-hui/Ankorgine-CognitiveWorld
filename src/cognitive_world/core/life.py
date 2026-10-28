"""Closed canonical life-state value; not an operation or write capability."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LifeState:
    """Explicit LifeState/v1. Missing state remains unsupported."""

    version: int
    value: str

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported LifeState version")
        if type(self.value) is not str or self.value not in ("alive", "dead"):
            raise ValueError("unsupported life-state value")
