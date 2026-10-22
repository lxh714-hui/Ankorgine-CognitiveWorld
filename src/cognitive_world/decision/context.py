"""Immutable, owner-scoped cognition snapshot supplied to an Agent decision."""

from dataclasses import dataclass, field
from typing import Any

from cognitive_world.decision.snapshot import FrozenMapping, freeze_value


@dataclass(frozen=True)
class DecisionContext:
    """A deep immutable view of one Agent's five-layer decision inputs.

    The constructor accepts detached records from existing authoritative
    boundaries, verifies ownership, and exposes only recursively frozen
    snapshots. It contains no Store or WorldState references.
    """

    cognition_state: Any
    personality: Any = None
    self_model: Any = None
    goals: tuple[Any, ...] = field(default_factory=tuple)
    beliefs: tuple[Any, ...] = field(default_factory=tuple)
    metadata: Any = field(default_factory=dict)
    percepts: tuple[Any, ...] = field(default_factory=tuple)
    working_memory: Any = None
    long_term_memories: tuple[Any, ...] = field(default_factory=tuple)
    emotion: Any = None
    metacognitive_feedback: Any = None
    motivation_assessment: Any = None
    decision_modulation: Any = None

    def __post_init__(self) -> None:
        raw_state = self.cognition_state
        owner_id = getattr(raw_state, "agent_id", None)
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("DecisionContext requires a cognition owner")

        records = {
            "personality": self.personality,
            "self_model": self.self_model,
            "emotion": self.emotion,
            "working_memory": self.working_memory,
            "metacognitive_feedback": self.metacognitive_feedback,
            "motivation_assessment": self.motivation_assessment,
            "decision_modulation": self.decision_modulation,
        }
        for name, record in records.items():
            if record is not None and getattr(record, "owner_id", None) != owner_id:
                raise PermissionError(f"{name} does not belong to DecisionContext owner")
        for name, sequence in (
            ("beliefs", self.beliefs),
            ("goals", self.goals),
            ("long_term_memories", self.long_term_memories),
        ):
            if any(getattr(record, "owner_id", None) != owner_id for record in sequence):
                raise PermissionError(f"{name} contains a record owned by another Agent")
        if any(getattr(percept, "observer_id", None) != owner_id for percept in self.percepts):
            raise PermissionError("percepts contain a record for another Agent")

        for name in (
            "cognition_state",
            "personality",
            "self_model",
            "goals",
            "beliefs",
            "metadata",
            "percepts",
            "working_memory",
            "long_term_memories",
            "emotion",
            "metacognitive_feedback",
            "motivation_assessment",
            "decision_modulation",
        ):
            object.__setattr__(self, name, freeze_value(getattr(self, name)))

        if not isinstance(self.metadata, FrozenMapping):
            raise TypeError("DecisionContext metadata must freeze to a mapping")
