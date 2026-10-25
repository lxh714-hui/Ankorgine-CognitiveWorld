from dataclasses import FrozenInstanceError

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    Emotion,
    Goal,
    Memory,
    MemoryQuery,
    MemoryStore,
    MetacognitiveFeedback,
    Personality,
    SelfModel,
)
from cognitive_world.decision import AgentDecision, DecisionContext
from cognitive_world.decision.snapshot import FrozenMapping, FrozenRecordSnapshot, freeze_value
from cognitive_world.event import EventFactory
from cognitive_world.observation import ObservationStore
from cognitive_world.presentation import MinimalComposer, PerspectiveContext
from cognitive_world.runtime.context import PlayerMode
from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory, RoomLightChangedHandler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime


class CapturingDecision(AgentDecision):
    def propose(self, context):
        self.context = context
        return super().propose(context)


def _make_context():
    owner = "agent-a"
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    world.load_entity(Entity(owner, "character", sensory_capabilities=("sight",)))
    world.load_location(owner, "room-a")
    registry = AgentRegistry()
    registry.register(RuntimeAgent(owner, "character-a", goal_ids=["goal-a"]))
    history, clock, observations = EventHistory(), SimulationClock(), ObservationStore()
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=registry, observation_store=observations)
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id="event-a", event_type="room_light_changed", timestamp="0", simulation_tick=0,
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}]))
    observation, = observations.get_by_observer(owner)
    assert history.get_processing_evidence("event-a").has_trusted_source(history.get_event("event-a"))
    container = CognitionContainer()
    container.add_personality(Personality(owner, traits={"patience": 0.6}))
    container.add_belief(
        Belief("belief-a", owner, {"claim": "saw a light"}, [observation.observation_id], 0.7)
    )
    container.add_goal(Goal("goal-a", owner, "investigate", 0.8))
    container.add_emotion(Emotion("emotion-a", owner, "concern", 0.3))
    container.add_self_model(SelfModel(owner, capabilities={"sight": True}))

    memory_store = MemoryStore()
    memory_store._commit_memory(
        Memory("memory-a", owner, "experience", {"note": "room was lit"}, 0.8, "event-a")
    )
    memory_store._commit_memory(
        Memory("memory-b", "agent-b", "experience", {"secret": True}, 1.0, "event-b")
    )
    feedback = MetacognitiveFeedback(
        owner,
        review_cues=("check whether the light is still on",),
        memory_queries=(MemoryQuery(owner, "similar room changes", 3),),
    )
    character = Character(
        "character-a",
        owner,
        owner,
        memory_ids=["memory-a", "memory-b"],
        belief_ids=["belief-a"],
        emotion_id="emotion-a",
        goal_ids=["goal-a"],
    )
    cognition_context = CognitionContext.from_character(
        character,
        container,
        memory_store,
        observation_store=observations,
        metacognitive_feedback=feedback,
    )
    runtime = SimulationRuntime(
        RuntimeContext(clock, world, history, agent_registry=registry, observation_store=observations),
        event_processor=processor, agent_action_loop=AgentActionLoop(),
        cognition_context_provider=lambda agent: cognition_context,
        allow_environment_provider_discovery=False)
    return cognition_context, container, memory_store, runtime, observation


def _execute(runtime, cognition_context, decision):
    with runtime.write_fence.operation():
        runtime.agent_action_loop.agent_turn.execute(
            runtime.context.agent_registry.get("agent-a"), cognition_context, decision,
            simulation_tick=runtime.context.clock.capture())


def test_decision_context_contains_owner_scoped_five_layer_inputs_and_emotion():
    cognition_context, _, _, runtime, observation = _make_context()
    decision = CapturingDecision()

    _execute(runtime, cognition_context, decision)
    snapshot = decision.context

    assert snapshot.cognition_state.agent_id == "agent-a"
    assert tuple(item.source_observation_id for item in snapshot.percepts) == (
        observation.observation_id,
    )
    assert snapshot.percepts[0].content.predicate == "room_light_on"
    assert snapshot.percepts[0].content.value is True
    assert snapshot.percepts[0].content.source_event_id == "event-a"
    assert snapshot.working_memory.owner_id == "agent-a"
    assert snapshot.working_memory.percept_ids == ("percept:" + observation.observation_id,)
    assert tuple(item.id for item in snapshot.long_term_memories) == ("memory-a",)
    assert snapshot.long_term_memories[0].source_event == "event-a"
    assert tuple(item.belief_id for item in snapshot.beliefs) == ("belief-a",)
    assert snapshot.beliefs[0].source_refs == (observation.observation_id,)
    assert tuple(item.goal_id for item in snapshot.goals) == ("goal-a",)
    assert snapshot.self_model.capabilities["sight"] is True
    assert snapshot.emotion.state == "concern"
    assert snapshot.metacognitive_feedback.review_cues == (
        "check whether the light is still on",
    )
    assert snapshot.metacognitive_feedback.memory_queries[0].owner_id == "agent-a"
    assert not hasattr(snapshot, "world_state")


def test_decision_context_is_recursively_immutable_and_detached_from_stores():
    cognition_context, container, memory_store, runtime, observation = _make_context()
    decision = CapturingDecision()
    _execute(runtime, cognition_context, decision)
    snapshot = decision.context

    with pytest.raises(FrozenInstanceError):
        snapshot.metadata = {"write": True}
    with pytest.raises(TypeError):
        snapshot.personality.traits["patience"] = 0.0
    with pytest.raises(TypeError):
        snapshot.beliefs[0].content["claim"] = "changed"
    with pytest.raises(AttributeError):
        snapshot.goals[0].description = "changed"
    with pytest.raises(AttributeError):
        snapshot.working_memory.percept_ids.append("forged")

    assert container.get_belief("belief-a").content == {"claim": "saw a light"}
    assert container.get_personality("agent-a").traits == {"patience": 0.6}
    assert memory_store.get_memory("memory-a").content == {"note": "room was lit"}


def test_freezing_a_frozen_record_again_preserves_its_fields():
    from cognitive_world.cognition.runtime import CognitionState

    original = CognitionState("agent-a", percept_ids=["percept:one"])
    frozen = freeze_value(original)
    frozen_again = freeze_value(frozen)

    assert isinstance(frozen, FrozenRecordSnapshot)
    assert frozen_again is frozen
    assert frozen_again.agent_id == "agent-a"
    assert frozen_again.percept_ids == ("percept:one",)

    source = {"items": ["original"]}
    constructed = FrozenRecordSnapshot(
        "test.Record", FrozenMapping((("payload", source),))
    )
    source["items"].append("mutated")
    assert constructed.payload["items"] == ("original",)


def test_rebuilt_decision_context_retains_owner_traits_and_percept_ids():
    cognition_context, _, _, runtime, observation = _make_context()
    decision = CapturingDecision()
    _execute(runtime, cognition_context, decision)
    initial = decision.context

    rebuilt = DecisionContext(
        cognition_state=initial.cognition_state,
        personality=initial.personality,
        self_model=initial.self_model,
        goals=initial.goals,
        beliefs=initial.beliefs,
        metadata=initial.metadata,
        percepts=initial.percepts,
        working_memory=initial.working_memory,
        long_term_memories=initial.long_term_memories,
        emotion=initial.emotion,
    )

    assert rebuilt.cognition_state.agent_id == "agent-a"
    assert rebuilt.cognition_state.percept_ids == ("percept:" + observation.observation_id,)
    assert rebuilt.personality.traits["patience"] == 0.6
    with pytest.raises(TypeError):
        rebuilt.personality.traits["patience"] = 0.0
    with pytest.raises(AttributeError):
        rebuilt.cognition_state.percept_ids.append("forged")


def test_foreign_owner_records_and_metacognitive_queries_are_rejected():
    cognition_context, _, _, runtime, observation = _make_context()
    with pytest.raises(PermissionError, match="different Agent"):
        MetacognitiveFeedback(
            "agent-a", memory_queries=(MemoryQuery("agent-b", "private", 1),)
        )

    from cognitive_world.cognition.runtime import CognitionState

    with pytest.raises(PermissionError, match="another Agent"):
        DecisionContext(
            CognitionState("agent-a"),
            beliefs=(Belief("belief-b", "agent-b", "private"),),
        )

    cognition_context.metacognitive_feedback = MetacognitiveFeedback("agent-b")
    with pytest.raises(PermissionError, match="another Agent"):
        cognition_context.get_metacognitive_feedback()


def test_resolution_and_presentation_boundaries_do_not_accept_cognition_snapshot():
    cognition_context, _, _, runtime, observation = _make_context()
    decision = CapturingDecision()
    _execute(runtime, cognition_context, decision)

    with pytest.raises(TypeError):
        EventFactory().create_from_resolution(decision.context)
    perspective = PerspectiveContext(
        "player", "agent-a", frozenset({"environment"}), "session",
        PlayerMode.ROLEPLAY, "character-a",
    )
    with pytest.raises((PermissionError, TypeError)):
        MinimalComposer().compose((decision.context,), perspective)


def test_direct_turn_without_history_defers_real_observation_without_consuming():
    context, _, _, _, observation = _make_context()
    turn = AgentTurn()
    decision = CapturingDecision()
    turn.execute(RuntimeAgent("agent-a", "character-a"), context, decision)
    state = decision.context.cognition_state
    assert not state.percept_ids and not decision.context.percepts
    assert turn.cognitive_runtime.working_memory_store.get("agent-a") is None
    assert not turn.cognitive_runtime.has_consumed_observation(
        "agent-a", observation, source_event_id=observation.source_event_id)
    item, = state.metadata["l1_ingestion"]["items"]
    assert item["source"] == "eligible"
    assert item["history"] == "undetermined"
    assert item["consumption"] == "not_consumed"
    assert item["code"] == "history_context_unavailable"
