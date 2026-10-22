"""Data model for an importance evaluation result."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportanceScore:
    """Record an importance score and its explanation for a target object."""

    target_id: str
    score: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
