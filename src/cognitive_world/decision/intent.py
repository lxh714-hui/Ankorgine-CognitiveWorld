"""Intent data model for the decision layer."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Intent:
    """A purpose that an actor wants to achieve, independent of method."""

    id: str
    actor: str
    goal: str
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
