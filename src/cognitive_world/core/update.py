"""Generic world state update request model."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorldUpdate:
    """A state change request produced from an Event by an EventHandler."""

    target_id: str
    operation: str
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
