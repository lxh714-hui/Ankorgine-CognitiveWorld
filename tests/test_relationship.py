from cognitive_world.core.relationship import Relationship


def test_relationship_saves_entity_ids():
    source_id = "entity_001"
    target_id = "entity_002"
    relationship = Relationship(source=source_id, target=target_id)

    assert relationship.source == source_id
    assert relationship.target == target_id


def test_relationship_saves_arbitrary_attributes():
    attributes = {"trust": 0.75, "context": {"since": "event_001"}}
    relationship = Relationship(
        source="entity_001",
        target="entity_002",
        attributes=attributes,
    )

    assert relationship.attributes == attributes
