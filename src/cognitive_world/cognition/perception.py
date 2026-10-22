"""Initial perception records and Observation conversion boundary."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.observation.observation import Observation


@dataclass
class Percept:
    """Represent structured input perceived from an Observation, not a fact."""

    percept_id: str
    observer_id: str
    source_observation_id: str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PerceptionProcessor:
    """Convert an Observation into an isolated, initial Percept record."""

    def process(self, observation: Observation, *, observer_id: str) -> Percept:
        """Convert a verified Observation for its explicitly bound subject."""
        if not isinstance(observation, Observation):
            raise TypeError("observation must be an Observation")
        if observation.observer_id != observer_id:
            raise PermissionError("Observation belongs to a different observer")
        if not observation.has_trusted_provenance():
            raise PermissionError("Observation has no valid trusted provenance")

        return Percept(
            percept_id=f"percept:{observation.observation_id}",
            observer_id=observation.observer_id,
            source_observation_id=observation.observation_id,
            content=deepcopy(observation.content),
            metadata=deepcopy(observation.metadata),
        )
