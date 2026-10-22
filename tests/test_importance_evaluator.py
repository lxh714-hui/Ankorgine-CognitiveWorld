from typing import get_type_hints

import pytest

from cognitive_world.cognition import (
    ImportanceEvaluator,
    ImportanceScore,
    MemoryStore,
    Personality,
    ShortTermMemory,
)
from cognitive_world.cognition.short_term_store import ShortTermMemoryStore
from cognitive_world.core.world_state import WorldState


def test_importance_evaluator_interface_is_typed():
    hints = get_type_hints(ImportanceEvaluator.evaluate)

    assert callable(ImportanceEvaluator().evaluate)
    assert hints["short_term_memory"] is ShortTermMemory
    assert hints["return"] is ImportanceScore


def test_unimplemented_evaluation_has_no_side_effects():
    experience = ShortTermMemory(
        id="short_001",
        owner_id="owner_001",
        source_event_id="event_001",
        content={"details": ["recent"]},
        timestamp="t1",
    )
    experience_store = ShortTermMemoryStore()
    experience_store.add_experience(experience)
    memory_store = MemoryStore()
    personality = Personality(id="personality_001", traits={"steady": True})
    world_state = WorldState()
    evaluator = ImportanceEvaluator()

    with pytest.raises(NotImplementedError):
        evaluator.evaluate(experience)

    assert experience_store.get_experience(experience.id) == experience
    assert memory_store.get_all_memories() == ()
    assert personality.traits == {"steady": True}
    assert dict(world_state.facts) == {}
