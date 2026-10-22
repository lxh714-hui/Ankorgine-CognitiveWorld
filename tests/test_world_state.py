import pytest

from cognitive_world.core.entity import Entity
from cognitive_world.core.relationship import Relationship
from cognitive_world.core.world_state import WorldState


def test_world_state_can_be_created():
    world_state = WorldState()

    assert len(world_state.entities) == 0
    assert len(world_state.relationships) == 0
    assert len(world_state.facts) == 0
    assert len(world_state.environment) == 0


def test_world_state_loads_and_gets_entity_without_external_reference_leaks():
    world_state = WorldState()
    entity = Entity(
        id="entity_001",
        type="object",
        attributes={"nested": {"label": "original"}},
    )

    world_state.load_entity(entity)
    entity.attributes["nested"]["label"] = "changed outside"

    stored = world_state.get_entity("entity_001")
    assert stored is not entity
    assert stored.attributes == {"nested": {"label": "original"}}

    stored.attributes["nested"]["label"] = "changed from read"
    assert world_state.get_entity("entity_001").attributes == {
        "nested": {"label": "original"}
    }

    listed = world_state.entities["entity_001"]
    listed.attributes["nested"]["label"] = "changed from mapping"
    assert world_state.get_entity("entity_001").attributes == {
        "nested": {"label": "original"}
    }


def test_world_state_loads_relationship_without_external_reference_leaks():
    world_state = WorldState()
    relationship = Relationship(
        source="entity_001",
        target="entity_002",
        attributes={"nested": {"value": 1}},
    )

    world_state.load_relationship(relationship)
    relationship.attributes["nested"]["value"] = 2

    stored = world_state.relationships[("entity_001", "entity_002")]
    assert stored is not relationship
    assert stored.attributes == {"nested": {"value": 1}}
    stored.attributes["nested"]["value"] = 3
    assert world_state.relationships[("entity_001", "entity_002")].attributes == {
        "nested": {"value": 1}
    }


def test_world_state_saves_facts_and_environment_data():
    world_state = WorldState()
    fact = {"nested": ["value"]}
    environment = {"conditions": {"level": 3}}

    world_state.load_fact("fact_key", fact)
    world_state.load_environment_data("environment_key", environment)

    fact["nested"].append("external mutation")
    environment["conditions"]["level"] = 99
    assert world_state.facts["fact_key"] == {"nested": ["value"]}
    assert world_state.environment["environment_key"] == {"conditions": {"level": 3}}

    with pytest.raises(TypeError):
        world_state.facts["new"] = "value"
