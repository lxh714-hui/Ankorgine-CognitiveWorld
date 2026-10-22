"""Canonical Event-backed candidate model for the Memory lifecycle."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


@dataclass
class MemoryProposal:
    """A candidate memory associated with its source Event.

    This is the single candidate representation used before decision. Legacy
    ``MemoryCandidate`` imports resolve to this model.
    """

    id: str
    source_event_id: str
    owner_id: str
    memory_type: str
    content: Any
    importance: float
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    logical_record_id: str | None = None
    supersedes_record_id: str | None = None
    _runtime_write_permit: RuntimeWritePermit | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_runtime_write_permit" and name in self.__dict__:
            raise AttributeError("Memory proposal runtime origin is immutable")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        # Capture provenance when the candidate is created. A delayed proposal
        # cannot be reissued as current merely by constructing a new request.
        object.__setattr__(
            self, "_runtime_write_permit", RuntimeWriteFence.bind_current_permit()
        )
        self.content = deepcopy(self.content)
        self.metadata = deepcopy(self.metadata)
        if self.logical_record_id is None:
            self.logical_record_id = f"memory:{self.id}"
        if not isinstance(self.logical_record_id, str) or not self.logical_record_id:
            raise ValueError("logical_record_id must be non-empty")
        if self.supersedes_record_id is not None and (
            not isinstance(self.supersedes_record_id, str) or not self.supersedes_record_id
        ):
            raise ValueError("supersedes_record_id must be non-empty or None")

    @property
    def runtime_write_permit(self) -> RuntimeWritePermit | None:
        return self._runtime_write_permit

    @property
    def source_event_ids(self) -> list[str]:
        """Compatibility view for callers that used the plural candidate field."""
        return [self.source_event_id]
