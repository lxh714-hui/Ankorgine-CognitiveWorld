from cognitive_world.cognition import SelfModel, SelfModelStore
import pytest


def test_self_model_creation_and_identity_fields():
    self_model = SelfModel(
        owner_id="agent-1",
        identity={"role": "traveler", "self_concept": ["curious"]},
        capabilities={"languages": ["common"], "navigation": True},
        limitations={"mobility": "limited"},
        self_beliefs=[{"claim": "I am cautious", "confidence": 0.8}],
        metadata={"revision": 2},
    )

    assert self_model.owner_id == "agent-1"
    assert self_model.identity == {
        "role": "traveler",
        "self_concept": ["curious"],
    }
    assert self_model.capabilities["languages"] == ["common"]
    assert self_model.limitations == {"mobility": "limited"}
    assert self_model.self_beliefs[0]["confidence"] == 0.8


def test_self_model_store_isolates_agents():
    store = SelfModelStore()
    store.add(SelfModel("agent-1", identity={"name": "one"}))
    store.add(SelfModel("agent-2", identity={"name": "two"}))

    assert store.get("agent-1").identity == {"name": "one"}
    assert store.get("agent-2").identity == {"name": "two"}
    assert store.get("missing") is None


def test_self_model_store_deep_copies_add_get_and_update_values():
    store = SelfModelStore()
    source = SelfModel(
        "agent-1",
        identity={"descriptors": ["initial"]},
        capabilities={"skill": {"levels": [1]}},
        limitations={"resources": ["initial"]},
        self_beliefs=[{"claim": ["initial"]}],
        metadata={"extensions": ["initial"]},
    )
    store.add(source)
    source.identity["descriptors"].append("source change")
    source.capabilities["skill"]["levels"].append(2)

    stored = store.get("agent-1")
    assert stored.identity == {"descriptors": ["initial"]}
    assert stored.capabilities == {"skill": {"levels": [1]}}

    stored.limitations["resources"].append("read change")
    stored.self_beliefs[0]["claim"].append("read change")
    stored.metadata["extensions"].append("read change")
    assert store.get("agent-1").limitations == {"resources": ["initial"]}
    assert store.get("agent-1").self_beliefs == [{"claim": ["initial"]}]
    assert store.get("agent-1").metadata == {"extensions": ["initial"]}

    replacement = SelfModel("agent-1", identity={"descriptors": ["initial"]}, capabilities={"skill": {"levels": [1]}}, limitations={"resources": ["initial"]}, self_beliefs=[{"claim": ["initial"]}], metadata={"extensions": ["initial"]})
    with pytest.raises(PermissionError):
        store.update(replacement)


def test_self_model_storage_has_no_world_event_or_other_cognition_dependencies():
    store = SelfModelStore()
    store.add(SelfModel("agent-1", identity="self"))

    assert store.get("agent-1").identity == "self"
    assert not hasattr(store, "world_state")
    assert not hasattr(store, "event_history")
    assert not hasattr(store, "memory_store")
    assert not hasattr(store, "personality_store")
