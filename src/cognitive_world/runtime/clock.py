"""Independent simulation time tracking."""

from dataclasses import dataclass


_SIMULATION_TIME_SEAL = object()


@dataclass(frozen=True)
class SimulationTime:
    """Process-local captured time issued by a SimulationClock instance."""

    tick: int
    _seal: object

    def is_clock_issued(self) -> bool:
        return self._seal is _SIMULATION_TIME_SEAL


@dataclass
class SimulationClock:
    """A minimal integer clock for tracking simulation time."""

    current_time: int = 0

    def tick(self) -> int:
        """Advance simulation time by one unit and return the new time."""
        return self.advance(1)

    def advance(self, amount: int) -> int:
        """Advance simulation time by the given number of units."""
        self.current_time += amount
        return self.current_time

    def capture(self) -> SimulationTime:
        """Capture the current authoritative time for a Runtime consumer."""
        if isinstance(self.current_time, bool) or not isinstance(self.current_time, int) or self.current_time < 0:
            raise ValueError("simulation clock must contain a non-negative integer")
        return SimulationTime(self.current_time, _SIMULATION_TIME_SEAL)
