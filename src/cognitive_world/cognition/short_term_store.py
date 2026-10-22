"""Isolated storage for recent cognitive experience records."""

from copy import deepcopy
from dataclasses import dataclass, field

from cognitive_world.cognition.short_term_memory import ShortTermMemory


@dataclass
class ShortTermMemoryStore:
    """Save and query ShortTermMemory without forming long-term Memory."""

    _experiences: dict[str, ShortTermMemory] = field(default_factory=dict, repr=False)

    def add_experience(self, experience: ShortTermMemory) -> None:
        """Store an isolated ShortTermMemory record by identifier."""
        if not isinstance(experience, ShortTermMemory):
            raise TypeError("experience must be a ShortTermMemory")
        self._experiences[experience.id] = deepcopy(experience)

    def get_experience(self, experience_id: str) -> ShortTermMemory | None:
        """Return an isolated experience by identifier, if present."""
        experience = self._experiences.get(experience_id)
        return deepcopy(experience) if experience is not None else None

    def get_by_owner(self, owner_id: str) -> tuple[ShortTermMemory, ...]:
        """Return isolated experiences belonging to an owner, in insertion order."""
        return tuple(
            deepcopy(experience)
            for experience in self._experiences.values()
            if experience.owner_id == owner_id
        )

    def get_all(self) -> tuple[ShortTermMemory, ...]:
        """Return isolated copies of all stored experiences in insertion order."""
        return tuple(deepcopy(list(self._experiences.values())))
