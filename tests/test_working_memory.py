from cognitive_world.cognition import (
    MemoryStore,
    WorkingMemory,
    WorkingMemoryStore,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory


def test_working_memory_can_be_created_with_percept_references():
    memory = WorkingMemory(
        owner_id="agent_001",
        percept_ids=["percept_001", "percept_002"],
        focus={"target": "door_001"},
        context={"recent": ["hallway", "locked door"]},
        metadata={"mode": "active"},
    )

    assert memory.owner_id == "agent_001"
    assert memory.percept_ids == ["percept_001", "percept_002"]
    assert memory.focus == {"target": "door_001"}
    assert memory.context == {"recent": ["hallway", "locked door"]}


def test_working_memory_store_keeps_owners_isolated():
    store = WorkingMemoryStore()
    first = WorkingMemory("agent_001", percept_ids=["percept_001"])
    second = WorkingMemory("agent_002", percept_ids=["percept_002"])
    store.add(first)
    store.add(second)

    assert store.get("agent_001").percept_ids == ["percept_001"]
    assert store.get("agent_002").percept_ids == ["percept_002"]


def test_store_isolates_input_output_and_update_data():
    store = WorkingMemoryStore()
    initial = WorkingMemory(
        owner_id="agent_001",
        percept_ids=["percept_001"],
        focus={"nested": ["initial"]},
        context={"nested": {"value": "initial"}},
    )
    store.add(initial)
    initial.percept_ids.append("external")
    initial.focus["nested"].append("external")

    returned = store.get("agent_001")
    returned.percept_ids.append("returned")
    returned.context["nested"]["value"] = "returned"

    assert store.get("agent_001").percept_ids == ["percept_001"]
    assert store.get("agent_001").focus == {"nested": ["initial"]}
    assert store.get("agent_001").context == {"nested": {"value": "initial"}}

    replacement = WorkingMemory("agent_001", percept_ids=["percept_002"])
    store.update(replacement)
    replacement.percept_ids.append("external after update")
    assert store.get("agent_001").percept_ids == ["percept_002"]


def test_working_memory_store_has_no_world_event_or_long_term_memory_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("event_001", "fact", "t1"))
    memory_store = MemoryStore()
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()
    before_memories = memory_store.get_all_memories()
    store = WorkingMemoryStore()

    store.add(WorkingMemory("agent_001", percept_ids=["percept_001"]))
    store.update(WorkingMemory("agent_001", percept_ids=["percept_002"]))
    store.get("agent_001")

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
    assert memory_store.get_all_memories() == before_memories
