from cognitive_world.core.entity import Entity


def test_entity_can_be_created():
    entity = Entity(id="entity_001", type="object")

    assert isinstance(entity, Entity)


def test_entity_saves_id_and_type():
    entity = Entity(id="entity_001", type="object")

    assert entity.id == "entity_001"
    assert entity.type == "object"


def test_entity_saves_attributes_and_state():
    attributes = {"color": "blue"}
    state = {"active": True}
    entity = Entity(
        id="entity_001",
        type="object",
        attributes=attributes,
        state=state,
    )

    assert entity.attributes == attributes
    assert entity.state == state
