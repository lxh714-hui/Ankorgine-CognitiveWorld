from cognitive_world.cognition import (
    Belief,
    BeliefStore,
    CognitiveRuntime,
    Goal,
    GoalStore,
    WorkingMemory,
    WorkingMemoryStore,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.observation.observation import Observation
from tests._trusted_observation_support import make_trusted_observation


def _real_input(owner, request_id):
    from test_dialogue_runtime import make_dialogue
    from cognitive_world.dialogue.runtime import DialogueRequest
    service, _, processor, store, _, _ = make_dialogue(listener_id=owner)
    service.submit(DialogueRequest(request_id, owner, "A received statement"))
    observation, = store.get_by_observer(owner)
    runtime = CognitiveRuntime()
    runtime._bind_observation_history(processor.event_history)
    return runtime, observation


def test_observations_produce_cognition_state_and_percepts():
    runtime, observation = _real_input("agent-1", "event-1")

    state = runtime.process("agent-1", [observation])

    assert state.agent_id == "agent-1"
    assert state.percept_ids == ["percept:" + observation.observation_id]
    assert runtime.working_memory_store.get("agent-1").percept_ids == state.percept_ids


def test_manual_or_other_agents_observations_are_not_ingested():
    runtime = CognitiveRuntime()
    manual = Observation("manual", "agent-1", "event-1", {"secret": "manual"})
    other = make_trusted_observation("other", "agent-2", "event-1", "private")

    state = runtime.process("agent-1", [manual, other])

    assert state.percept_ids == []
    assert runtime.working_memory_store.get("agent-1") is None


def test_existing_belief_and_goal_references_are_included():
    beliefs = BeliefStore()
    goals = GoalStore()
    beliefs.add(
        Belief(
            belief_id="belief-1",
            owner_id="agent-1",
            content="A proposition",
            source_refs=["event-1"],
            confidence=0.8,
        )
    )
    goals.add(Goal("goal-1", "agent-1", "An objective", 0.9, "active"))
    goals.add(Goal("goal-2", "agent-1", "Another objective", 0.3, "active"))
    goals.add(Goal("other-goal", "agent-2", "Other agent objective", 0.5, "active"))
    runtime = CognitiveRuntime(belief_store=beliefs, goal_store=goals)

    state = runtime.process("agent-1", [])

    assert state.belief_ids == ["belief-1"]
    assert state.goal_ids == ["goal-1", "goal-2"]
    assert "other-goal" not in state.goal_ids


def test_working_memory_is_updated_without_changing_existing_focus():
    working_memories = WorkingMemoryStore()
    working_memories.add(
        WorkingMemory(
            owner_id="agent-1",
            percept_ids=["percept:earlier"],
            focus={"topic": ["existing"]},
            context={"stage": "current"},
        )
    )
    runtime, observation = _real_input("agent-1", "event-2")
    runtime.working_memory_store = working_memories

    state = runtime.process(
        "agent-1",
        [observation],
    )

    assert working_memories.get("agent-1").percept_ids == [
        "percept:earlier",
        "percept:" + observation.observation_id,
    ]
    assert state.percept_ids == ["percept:" + observation.observation_id]
    assert state.focus == {"topic": ["existing"]}


def test_processing_has_no_world_event_or_action_side_effects():
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    event = Event("event-1", "observed", "t1", changes=[{"fact": "unchanged"}])
    event_snapshot = Event(
        event.id,
        event.type,
        event.timestamp,
        list(event.participants),
        event.cause,
        list(event.changes),
        dict(event.metadata),
    )
    runtime = CognitiveRuntime()

    runtime.process(
        "agent-1",
        [make_trusted_observation("observation-1", "agent-1", event.id, {"detail": "seen"})],
    )

    assert world_state.facts == {"existing": {"value": 1}}
    assert event == event_snapshot
    assert not hasattr(runtime, "action_proposal")
