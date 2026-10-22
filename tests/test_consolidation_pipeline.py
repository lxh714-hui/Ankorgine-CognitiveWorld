from copy import deepcopy

import pytest

from cognitive_world.cognition import (
    ImportanceEvaluator,
    ImportanceScore,
    MemoryConsolidationPipeline,
    MemoryStore,
    Personality,
    ShortTermMemory,
)
from cognitive_world.core.world_state import WorldState


class FixedImportanceEvaluator(ImportanceEvaluator):
    def __init__(self, score):
        self.score = score
        self.received = None

    def evaluate(self, short_term_memory: ShortTermMemory) -> ImportanceScore:
        self.received = short_term_memory
        return self.score


def test_pipeline_coordinates_evaluator_and_creates_pending_decision():
    experience = ShortTermMemory(
        id="short_001",
        owner_id="owner_001",
        source_event_id="event_001",
        content={"details": ["recent"]},
        timestamp="t1",
    )
    score = ImportanceScore(
        target_id=experience.id,
        score=0.74,
        reason="caller-provided assessment",
        metadata={"review": ["manual"]},
    )
    evaluator = FixedImportanceEvaluator(score)
    pipeline = MemoryConsolidationPipeline(evaluator)

    decision = pipeline.consolidate(experience)

    assert evaluator.received is experience
    assert decision.proposal_id == "memory-proposal:owner_001:event_001"
    assert decision.proposal_id != experience.id
    assert decision.proposal.id == decision.proposal_id
    assert decision.proposal.source_event_id == experience.source_event_id
    assert decision.accepted is False
    assert decision.importance == score.score
    assert decision.memory_type == "experience"
    assert decision.metadata == {
        "source_event_id": experience.source_event_id,
        "reason": score.reason,
        "evaluation_metadata": score.metadata,
    }


def test_pipeline_does_not_write_memory_or_modify_world_cognition_or_input():
    experience = ShortTermMemory(
        id="short_001",
        owner_id="owner_001",
        source_event_id="event_001",
        content={"nested": ["original"]},
        timestamp="t1",
        metadata={"extension": ["original"]},
    )
    original = deepcopy(experience)
    evaluator = FixedImportanceEvaluator(
        ImportanceScore(
            target_id=experience.id,
            score=0.5,
            reason="assessment",
        )
    )
    memory_store = MemoryStore()
    personality = Personality(id="personality_001", traits={"steady": True})
    world_state = WorldState()

    MemoryConsolidationPipeline(evaluator).consolidate(experience)

    assert experience == original
    assert memory_store.get_all_memories() == ()
    assert personality.traits == {"steady": True}
    assert dict(world_state.facts) == {}


def test_pipeline_rejects_non_short_term_memory_input():
    pipeline = MemoryConsolidationPipeline(FixedImportanceEvaluator(None))

    with pytest.raises(TypeError, match="short_term_memory must be a ShortTermMemory"):
        pipeline.consolidate(object())
