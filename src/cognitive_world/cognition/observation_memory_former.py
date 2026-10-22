"""Create candidate memories from information already observed by a subject."""

from copy import deepcopy
from dataclasses import dataclass

from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.observation.observation import Observation


@dataclass
class ObservationMemoryFormer:
    """Convert an Observation into a non-persisted MemoryProposal."""

    def create(self, observation: Observation) -> MemoryProposal:
        """Return a proposal that preserves the Observation's source and content."""
        if not isinstance(observation, Observation):
            raise TypeError("observation must be an Observation")

        return MemoryProposal(
            id=f"observation-memory-proposal:{observation.observation_id}",
            source_event_id=observation.source_event_id,
            owner_id=observation.observer_id,
            memory_type="observation",
            content=deepcopy(observation.content),
            importance=0.0,
            metadata={
                **deepcopy(observation.metadata),
                "source": "observation",
                "source_observation_id": observation.observation_id,
            },
        )
