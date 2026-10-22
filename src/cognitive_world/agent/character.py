"""Character data model for narrative identity references."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Character:
    """A data record linking an Agent to its cognition records."""

    id: str
    agent_id: str
    personality_id: str
    memory_ids: list[str] = field(default_factory=list)
    belief_ids: list[str] = field(default_factory=list)
    emotion_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    goal_ids: list[str] = field(default_factory=list)
