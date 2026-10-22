from cognitive_world.cognition import Belief, BeliefStore, MemoryStore
from cognitive_world.cognition import (
    BeliefChange,
    BeliefUpdateProposal,
    CognitiveUpdateApplier,
    CognitiveUpdateValidator,
    GoalStore,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory


def test_belief_stores_judgement_source_references_and_confidence():
    belief = Belief(
        belief_id="belief_001",
        owner_id="agent_001",
        content={"claim": "the bridge is unsafe"},
        source_refs=["percept_001", "event_001"],
        confidence=0.82,
        metadata={"basis": "visual evidence"},
    )

    assert belief.belief_id == "belief_001"
    assert belief.owner_id == "agent_001"
    assert belief.content == {"claim": "the bridge is unsafe"}
    assert belief.source_refs == ["percept_001", "event_001"]
    assert belief.confidence == 0.82


def test_belief_store_isolates_agents_and_mutable_data():
    store = BeliefStore()
    first = Belief("belief_001", "agent_001", {"claim": ["one"]}, ["p1"], 0.5)
    second = Belief("belief_002", "agent_002", {"claim": ["two"]}, ["p2"], 0.9)
    store.add(first)
    store.add(second)

    first.content["claim"].append("external")
    first.source_refs.append("external")
    returned = store.get("agent_001")
    returned.content["claim"].append("read")
    returned.metadata["extension"] = ["read"]

    assert store.get("agent_001").content == {"claim": ["one"]}
    assert store.get("agent_001").source_refs == ["p1"]
    assert store.get("agent_002").content == {"claim": ["two"]}


def test_belief_store_update_replaces_only_matching_owner():
    store = BeliefStore()
    store.add(Belief("belief_001", "agent_001", "old", ["p1"], 0.4))
    store.add(Belief("belief_002", "agent_002", "other", ["p2"], 0.6))
    proposal = BeliefUpdateProposal(
        owner_id="agent_001",
        belief_id="belief_001",
        change=BeliefChange("replace", "old", "updated", "test", ["p3"]),
        source_refs=["p3"],
        confidence=0.8,
    )
    validation = CognitiveUpdateValidator().validate(
        proposal, {"agent_id": "agent_001"}
    )

    CognitiveUpdateApplier(store, GoalStore()).apply(proposal, validation)

    assert store.get("agent_001").content == "updated"
    assert store.get("agent_001").belief_id == "belief_001"
    assert store.get("agent_002").content == "other"


def test_belief_storage_has_no_world_event_or_memory_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("event_001", "fact", "t1"))
    memory_store = MemoryStore()
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()
    before_memories = memory_store.get_all_memories()
    store = BeliefStore()

    store.add(Belief("belief_001", "agent_001", "claim", ["event_001"], 0.7))
    store.get("agent_001")

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
    assert memory_store.get_all_memories() == before_memories
