"""Agent data model linking an Entity to cognition records."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Agent:
    """A data record for an Entity with cognition-related references."""

    id: str
    entity_id: str
    cognition_ids: list[str] = field(default_factory=list)
    goal_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
