from cognitive_world.core.update import WorldUpdate


def test_world_update_can_be_created():
    update = WorldUpdate(target_id="entity_001", operation="change")

    assert isinstance(update, WorldUpdate)


def test_world_update_saves_fields_and_arbitrary_payload_and_metadata():
    payload = {"nested": ["value", {"number": 3}]}
    metadata = {"source": "event_handler", "details": ["recorded", 1]}
    update = WorldUpdate(
        target_id="entity_001",
        operation="change",
        payload=payload,
        metadata=metadata,
    )

    assert update.target_id == "entity_001"
    assert update.operation == "change"
    assert update.payload == payload
    assert update.metadata == metadata
