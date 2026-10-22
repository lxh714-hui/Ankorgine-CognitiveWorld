from cognitive_world.cognition import MemoryWriteRequest


def test_memory_write_request_preserves_fields():
    content = {"record": {"items": ["confirmed"]}}
    metadata = {"source": {"review": "approved"}}
    request = MemoryWriteRequest(
        memory_id="memory_001",
        owner_id="owner_001",
        source_event_id="event_001",
        content=content,
        memory_type="experience",
        importance=0.8,
        metadata=metadata,
    )

    assert request.memory_id == "memory_001"
    assert request.owner_id == "owner_001"
    assert request.source_event_id == "event_001"
    assert request.content == content
    assert request.memory_type == "experience"
    assert request.importance == 0.8
    assert request.metadata == metadata
