import pytest

from cognitive_world.cognition import Memory, MemoryStore


def make_memory(
    memory_id: str,
    owner_id: str,
    content: dict,
    metadata: dict | None = None,
) -> Memory:
    return Memory(
        id=memory_id,
        owner_id=owner_id,
        type="experience",
        content=content,
        importance=0.7,
        source_event=f"event_{memory_id}",
        metadata={} if metadata is None else metadata,
    )


def test_memory_store_saves_and_gets_memory_by_id():
    store = MemoryStore()
    memory = make_memory("memory_001", "owner_001", {"detail": [1]})

    store._commit_memory(memory)

    assert store.get_memory("memory_001") == memory
    assert store.get_memory("missing") is None


def test_memory_store_queries_by_owner_and_returns_all():
    store = MemoryStore()
    first = make_memory("memory_001", "owner_001", {"detail": "first"})
    second = make_memory("memory_002", "owner_001", {"detail": "second"})
    other = make_memory("memory_003", "owner_002", {"detail": "other"})
    for memory in (first, second, other):
        store._commit_memory(memory)

    assert store.get_memories_by_owner("owner_001") == (first, second)
    assert store.get_all_memories() == (first, second, other)


def test_memory_store_isolates_input_and_read_objects():
    store = MemoryStore()
    source = make_memory(
        "memory_001",
        "owner_001",
        {"nested": {"values": [1]}},
        {"extension": ["original"]},
    )
    store._commit_memory(source)

    source.content["nested"]["values"].append(2)
    source.metadata["extension"].append("external")
    retrieved = store.get_memory("memory_001")
    retrieved.content["nested"]["values"].append(3)
    retrieved.metadata["extension"].append("read")

    assert store.get_memory("memory_001").content == {
        "nested": {"values": [1]}
    }
    assert store.get_memory("memory_001").metadata == {"extension": ["original"]}

    with pytest.raises(TypeError):
        store.memories["memory_002"] = make_memory("memory_002", "owner_001", {})
