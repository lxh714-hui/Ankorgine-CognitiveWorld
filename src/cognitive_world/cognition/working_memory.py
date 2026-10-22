"""Current cognitive workspace data model and isolated storage."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkingMemory:
    """Represent the information an Agent is currently processing."""

    owner_id: str
    percept_ids: list[str] = field(default_factory=list)
    focus: Any = None
    context: Any = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkingMemoryStore:
    """Store one isolated WorkingMemory snapshot per Agent owner."""

    _memories: dict[str, WorkingMemory] = field(default_factory=dict, repr=False)

    def add(self, memory: WorkingMemory) -> None:
        """Add or replace the WorkingMemory snapshot for its owner."""
        if not isinstance(memory, WorkingMemory):
            raise TypeError("memory must be a WorkingMemory")
        self._memories[memory.owner_id] = deepcopy(memory)

    def get(self, owner_id: str) -> WorkingMemory | None:
        """Return an isolated WorkingMemory copy for an owner, if present."""
        memory = self._memories.get(owner_id)
        return deepcopy(memory) if memory is not None else None

    def update(self, memory: WorkingMemory) -> None:
        """Replace the stored snapshot for the WorkingMemory's owner."""
        if not isinstance(memory, WorkingMemory):
            raise TypeError("memory must be a WorkingMemory")
        self._memories[memory.owner_id] = deepcopy(memory)
