"""Boundary interface for evaluating short-term experience importance."""

from cognitive_world.cognition.importance import ImportanceScore
from cognitive_world.cognition.short_term_memory import ShortTermMemory


class ImportanceEvaluator:
    """Define evaluation without applying an importance policy."""

    def evaluate(self, short_term_memory: ShortTermMemory) -> ImportanceScore:
        """Return an importance result when an evaluation policy exists."""
        raise NotImplementedError("Importance evaluation is not implemented")
