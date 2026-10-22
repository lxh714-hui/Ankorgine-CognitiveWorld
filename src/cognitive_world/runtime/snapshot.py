"""Snapshot data for runtime lifecycle state."""

from dataclasses import dataclass


@dataclass
class RuntimeSnapshot:
    """Describe the runtime clock and lifecycle state only."""

    simulation_time: int
    running: bool
