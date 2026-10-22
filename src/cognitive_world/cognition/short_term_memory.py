"""Data model for a character's recent cognitive experience."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShortTermMemory:
    """Record a recent experience linked to its confirmed source Event."""

    id: str
    owner_id: str
    source_event_id: str
    content: Any
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)
