"""Closed reach configuration. Sharing coordinates does not share disclosure policy."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class InteractionRangePolicy:
    version: int
    maximum_distance_m: float

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported interaction range version")
        if (type(self.maximum_distance_m) not in (int, float)
                or not math.isfinite(self.maximum_distance_m)
                or not 0 <= self.maximum_distance_m <= 1_000_000):
            raise ValueError("interaction distance must be finite bounded metres")
