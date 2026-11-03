from dataclasses import replace

import pytest

from cognitive_world.core.entity import Entity
from cognitive_world.core.physical import PhysicalRelation, validate_physical_world
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.core.world_state import WorldState
from cognitive_world.items.containment import effective_location


def scene():
    entities = {x: Entity(x, "object", physical_capabilities=("container",))
                for x in ("bag", "bottle", "key", "coin")}
    entities.update({x: Entity(x, "location") for x in ("room", "elsewhere")})
    locations = dict(bag="room", bottle="bag", key="bottle", coin="bag")
    relations = {(a, b): PhysicalRelation(2, a, b, ("contained_in",))
                 for a, b in (("bottle", "bag"), ("key", "bottle"), ("coin", "bag"))}
    return entities, locations, relations


def test_nested_multiple_contents_move_without_rewriting_descendants():
    e, l, r = scene()
    validate_physical_world(e, l, r)
    w = WorldState()
    for x in e.values(): w.load_entity(x)
    for x, y in l.items(): w.load_location(x, y)
    for relation in r.values(): w.load_relationship(relation)
    assert effective_location(w, "key") == "room"
    # Initialization only: runtime movement must still pass EventProcessor.
    w.load_location("bag", "elsewhere")
    assert effective_location(w, "key") == "elsewhere"
    assert w.get_location("key") == "bottle"


@pytest.mark.parametrize("defect", ["parent", "location", "capability", "missing", "cycle", "self"])
def test_invalid_containment_fails_closed(defect):
    e, l, r = scene()
    with pytest.raises((ValueError, TypeError)):
        if defect == "parent":
            r[("key", "bag")] = PhysicalRelation(2, "key", "bag", ("contained_in",))
        elif defect == "location": l["key"] = "room"
        elif defect == "capability": e["bag"] = replace(e["bag"], physical_capabilities=())
        elif defect == "missing": del e["bottle"]
        elif defect == "self": PhysicalRelation(2, "bag", "bag", ("contained_in",))
        elif defect == "cycle":
            l["bag"] = "key"
            r[("bag", "key")] = PhysicalRelation(2, "bag", "key", ("contained_in",))
        validate_physical_world(e, l, r)


def test_relation_versions_keep_legacy_bytes_and_explicit_v2_roundtrip():
    codec = PersistedValueCodec()
    old = PhysicalRelation(1, "item", "holder", ("held_by",))
    encoded = codec.dumps(old)
    assert encoded == (b'{"$record":"cognitive_world.core.physical:PhysicalRelation",'
                       b'"fields":{"kinds":{"$tuple":["held_by"]},"source":"item",'
                       b'"target":"holder","version":1}}')
    assert codec.dumps(codec.loads(encoded)) == encoded
    with pytest.raises(ValueError): PhysicalRelation(1, "item", "bag", ("contained_in",))
    new = PhysicalRelation(2, "item", "bag", ("contained_in",))
    assert codec.loads(codec.dumps(new)) == new
