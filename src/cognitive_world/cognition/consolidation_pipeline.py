"""Coordinate importance evaluation and a non-accepting decision boundary."""

from copy import deepcopy
from dataclasses import dataclass, field

from cognitive_world.cognition.importance import ImportanceScore
from cognitive_world.cognition.importance_evaluator import ImportanceEvaluator
from cognitive_world.cognition.memory_decision import MemoryDecision
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.short_term_memory import ShortTermMemory


@dataclass
class MemoryConsolidationPipeline:
    """Pass short-term experience through evaluation without storing Memory."""

    importance_evaluator: ImportanceEvaluator = field(
        default_factory=ImportanceEvaluator
    )

    def consolidate(self, short_term_memory: ShortTermMemory) -> MemoryDecision:
        """Evaluate experience and create a pending, non-accepted decision."""
        if not isinstance(short_term_memory, ShortTermMemory):
            raise TypeError("short_term_memory must be a ShortTermMemory")

        proposal = MemoryProposal(
            id=(
                f"memory-proposal:{short_term_memory.owner_id}:"
                f"{short_term_memory.source_event_id}"
            ),
            source_event_id=short_term_memory.source_event_id,
            owner_id=short_term_memory.owner_id,
            memory_type="experience",
            content=deepcopy(short_term_memory.content),
            importance=0.0,
            metadata=deepcopy(short_term_memory.metadata),
        )
        score = self.importance_evaluator.evaluate(short_term_memory)
        if not isinstance(score, ImportanceScore):
            raise TypeError("ImportanceEvaluator.evaluate must return ImportanceScore")

        return MemoryDecision(
            proposal_id=proposal.id,
            accepted=False,
            importance=score.score,
            memory_type=proposal.memory_type,
            proposal=deepcopy(proposal),
            metadata={
                "source_event_id": proposal.source_event_id,
                "reason": score.reason,
                "evaluation_metadata": deepcopy(score.metadata),
            },
        )
