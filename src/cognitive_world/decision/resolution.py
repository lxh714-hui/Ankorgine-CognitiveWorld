"""Resolution data model for the decision layer."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Resolution:
    """A recorded outcome and effects for an Attempt."""

    id: str
    attempt_id: str
    outcome: str
    effects: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
