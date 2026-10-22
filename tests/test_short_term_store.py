import pytest

from cognitive_world.cognition import (
    Memory,
    ShortTermMemory,
    ShortTermMemoryStore,
)


def make_experience(experience_id, owner_id, content, metadata=None):
    return ShortTermMemory(
        id=experience_id,
        owner_id=owner_id,
        source_event_id=f"event_{experience_id}",
        content=content,
        timestamp="2026-10-14T10:00:00Z",
        metadata={} if metadata is None else metadata,
    )


def test_short_term_store_adds_and_gets_experience():
    store = ShortTermMemoryStore()
    experience = make_experience("short_001", "owner_001", {"detail": "recent"})

    store.add_experience(experience)

    assert store.get_experience(experience.id) == experience
    assert store.get_experience("missing") is None


def test_short_term_store_queries_owner_and_all_experiences():
    store = ShortTermMemoryStore()
    first = make_experience("short_001", "owner_001", {"detail": "first"})
    second = make_experience("short_002", "owner_001", {"detail": "second"})
    other = make_experience("short_003", "owner_002", {"detail": "other"})
    for experience in (first, second, other):
        store.add_experience(experience)

    assert store.get_by_owner("owner_001") == (first, second)
    assert store.get_all() == (first, second, other)


def test_short_term_store_isolates_input_and_read_objects():
    store = ShortTermMemoryStore()
    source = make_experience(
        "short_001",
        "owner_001",
        {"nested": {"values": [1]}},
        {"extension": ["original"]},
    )
    store.add_experience(source)

    source.content["nested"]["values"].append(2)
    source.metadata["extension"].append("external")
    retrieved = store.get_experience(source.id)
    retrieved.content["nested"]["values"].append(3)
    retrieved.metadata["extension"].append("read")

    assert store.get_experience(source.id).content == {
        "nested": {"values": [1]}
    }
    assert store.get_experience(source.id).metadata == {"extension": ["original"]}


def test_short_term_store_rejects_long_term_memory():
    store = ShortTermMemoryStore()
    memory = Memory(
        id="memory_001",
        owner_id="owner_001",
        type="experience",
        content={"detail": "long-term"},
        importance=0.8,
        source_event="event_001",
    )

    with pytest.raises(TypeError, match="experience must be a ShortTermMemory"):
        store.add_experience(memory)
