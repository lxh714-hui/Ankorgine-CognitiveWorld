from cognitive_world.cognition import Personality, PersonalityStore


def test_personality_creation_and_behavior_parameters():
    personality = Personality(
        owner_id="agent-1",
        traits={"trust_tendency": 0.7},
        preferences={"risk_preference": "cautious"},
        values={"value_bias": {"honesty": 0.9}},
        metadata={"decision_bias": {"novelty": -0.2}},
    )

    assert personality.owner_id == "agent-1"
    assert personality.traits == {"trust_tendency": 0.7}
    assert personality.preferences == {"risk_preference": "cautious"}
    assert personality.values == {"value_bias": {"honesty": 0.9}}
    assert personality.metadata == {"decision_bias": {"novelty": -0.2}}


def test_personality_store_isolates_agents():
    store = PersonalityStore()
    store.add(Personality("agent-1", traits={"patience": 0.8}))
    store.add(Personality("agent-2", traits={"patience": 0.2}))

    assert store.get("agent-1").traits == {"patience": 0.8}
    assert store.get("agent-2").traits == {"patience": 0.2}
    assert store.get("unknown-agent") is None


def test_personality_store_deep_copies_on_add_get_and_update():
    store = PersonalityStore()
    source = Personality(
        "agent-1",
        traits={"nested": ["original"]},
        preferences={"nested": {"choice": [1]}},
    )
    store.add(source)

    source.traits["nested"].append("outside")
    source.preferences["nested"]["choice"].append(2)
    stored_copy = store.get("agent-1")
    assert stored_copy.traits == {"nested": ["original"]}
    assert stored_copy.preferences == {"nested": {"choice": [1]}}

    stored_copy.traits["nested"].append("read mutation")
    stored_copy.preferences["nested"]["choice"].append(3)
    assert store.get("agent-1").traits == {"nested": ["original"]}
    assert store.get("agent-1").preferences == {"nested": {"choice": [1]}}

    updated = Personality("agent-1", traits={"updated": True})
    store.update(updated)
    updated.traits["updated"] = False
    assert store.get("agent-1").traits == {"updated": True}


def test_personality_store_has_no_world_event_or_other_cognition_dependencies():
    store = PersonalityStore()
    store.add(Personality("agent-1", traits={"risk": 0.4}))

    assert store.get("agent-1").traits == {"risk": 0.4}
    assert not hasattr(store, "world_state")
    assert not hasattr(store, "event_history")
    assert not hasattr(store, "memory_store")
    assert not hasattr(store, "belief_store")
    assert not hasattr(store, "goal_store")
