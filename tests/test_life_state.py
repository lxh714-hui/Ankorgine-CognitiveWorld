"""Canonical life-state value compatibility; operation acceptance is separate."""

import pytest
from cognitive_world.core.entity import Entity
from cognitive_world.core.life import LifeState
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.core.world_state import WorldState


@pytest.mark.parametrize("value", ["alive", "dead"])
def test_explicit_life_state_initialization_and_codec(value):
    entity = Entity("subject", "character", state={"life": LifeState(1, value)})
    world = WorldState()
    world.load_entity(entity)
    codec = PersistedValueCodec()
    assert codec.loads(codec.dumps(entity)) == entity
    assert world.get_entity("subject").state["life"] == LifeState(1, value)


@pytest.mark.parametrize("version,value", [(True, "alive"), (2, "alive"), (1, True), (1, "unknown")])
def test_invalid_life_state_is_rejected(version, value):
    with pytest.raises(ValueError):
        LifeState(version, value)


def test_missing_life_state_keeps_legacy_entity_bytes():
    codec = PersistedValueCodec()
    entity = Entity("legacy", "character")
    payload = codec.dumps(entity)
    assert b"LifeState" not in payload
    assert codec.dumps(codec.loads(payload)) == payload
    assert "life" not in codec.loads(payload).state


@pytest.mark.parametrize("value", [True, "alive", {"version": 1, "value": "alive"}])
def test_untyped_life_state_is_not_authority(value):
    with pytest.raises(ValueError):
        Entity("subject", "character", state={"life": value})


def test_life_codec_rejects_unknown_version_fields_and_type():
    codec = PersistedValueCodec()
    record = codec.encode(LifeState(1, "alive"))
    for bad in (
        {**record, "fields": {"version": 2, "value": "alive"}},
        {**record, "fields": {**record["fields"], "authorized": True}},
        {**record, "$record": "unregistered.LifeState"},
    ):
        with pytest.raises(ValueError):
            codec.decode(bad)
