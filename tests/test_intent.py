from cognitive_world.decision.intent import Intent


def test_intent_can_be_created():
    intent = Intent(id="intent_001", actor="entity_001", goal="enter_room")

    assert isinstance(intent, Intent)


def test_intent_saves_fields():
    context = {"location": "room_001", "conditions": ["door_closed"]}
    metadata = {"source": "input", "details": {"confidence": 0.8}}
    intent = Intent(
        id="intent_001",
        actor="entity_001",
        goal="enter_room",
        context=context,
        metadata=metadata,
    )

    assert intent.id == "intent_001"
    assert intent.actor == "entity_001"
    assert intent.goal == "enter_room"
    assert intent.context == context
    assert intent.metadata == metadata
