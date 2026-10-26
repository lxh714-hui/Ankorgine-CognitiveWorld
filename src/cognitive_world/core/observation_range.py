"""Closed one-dimensional observation-domain coordinates and disclosure limits.

These records are not global 3D geometry, collision shapes or a visibility solver.
"""
from dataclasses import dataclass
import math


def _version(value):
    if type(value) is not int or value != 1:
        raise ValueError("unsupported observation range contract version")


def _reference(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("invalid observation range reference")


def _distance(value):
    if type(value) not in (int, float) or abs(value) > 1_000_000 or not math.isfinite(value):
        raise ValueError("observation coordinate/limit is outside the finite supported domain")


@dataclass(frozen=True)
class ObservationZone:
    version: int
    frame_id: str
    offset_m: float

    def __post_init__(self):
        _version(self.version)
        _reference(self.frame_id)
        _distance(self.offset_m)


@dataclass(frozen=True)
class ObservationRangePolicy:
    version: int
    coarse_distance_m: float
    detail_distance_m: float
    detail_observers: tuple[str, ...]

    def __post_init__(self):
        _version(self.version)
        _distance(self.coarse_distance_m)
        _distance(self.detail_distance_m)
        if not 0 <= self.detail_distance_m <= self.coarse_distance_m:
            raise ValueError("observation limits must be ordered non-negative distances")
        if (not isinstance(self.detail_observers, tuple) or len(self.detail_observers) > 32
                or len(set(self.detail_observers)) != len(self.detail_observers)):
            raise ValueError("detail recipients must be bounded unique identities")
        for owner in self.detail_observers:
            _reference(owner)
