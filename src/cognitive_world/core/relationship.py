"""Core relationship data model."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Relationship:
    """A generic relationship between two entities."""

    source: str
    target: str
    attributes: dict[str, Any] = field(default_factory=dict)
