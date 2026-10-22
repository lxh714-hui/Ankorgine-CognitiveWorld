from cognitive_world.cognition import ShortTermMemory


def test_short_term_memory_preserves_fields():
    content = {"experience": {"details": ["recent", 1]}}
    metadata = {"extension": ["value"]}
    experience = ShortTermMemory(
        id="short_001",
        owner_id="owner_001",
        source_event_id="event_001",
        content=content,
        timestamp="2026-10-14T10:00:00Z",
        metadata=metadata,
    )

    assert experience.id == "short_001"
    assert experience.owner_id == "owner_001"
    assert experience.source_event_id == "event_001"
    assert experience.content == content
    assert experience.timestamp == "2026-10-14T10:00:00Z"
    assert experience.metadata == metadata
