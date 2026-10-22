"""Isolated storage for Observation records."""

from copy import deepcopy
from dataclasses import dataclass, field

from cognitive_world.observation.observation import Observation


@dataclass
class ObservationStore:
    """Save and query observations without interpreting their contents."""

    _observations: dict[str, Observation] = field(default_factory=dict, repr=False)

    def add(self, observation: Observation) -> None:
        """Store an isolated copy of an observation by its identifier."""
        if not isinstance(observation, Observation):
            raise TypeError("observation must be an Observation")
        self._observations[observation.observation_id] = deepcopy(observation)

    def get(self, observation_id: str) -> Observation | None:
        """Return an isolated observation copy, if it exists."""
        observation = self._observations.get(observation_id)
        return deepcopy(observation) if observation is not None else None

    def get_by_observer(self, observer_id: str) -> tuple[Observation, ...]:
        """Return isolated copies of observations for an observer."""
        return tuple(
            deepcopy(observation)
            for observation in self._observations.values()
            if observation.observer_id == observer_id
        )

    def all(self) -> tuple[Observation, ...]:
        """Return isolated copies of all observations in insertion order."""
        return tuple(deepcopy(list(self._observations.values())))
