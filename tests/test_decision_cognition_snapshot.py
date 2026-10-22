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
from tests._trusted_observation_support import make_trusted_observation


class CapturingDecision(AgentDecision):
    def propose(self, context):
        self.context = context
        return super().propose(context)


def _make_context():
    owner = "agent-a"
    container = CognitionContainer()
    container.add_personality(Personality(owner, traits={"patience": 0.6}))
    container.add_belief(
        Belief("belief-a", owner, {"claim": "saw a light"}, ["observation-a"], 0.7)
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
    observations = ObservationStore()
    observations.add(
        make_trusted_observation(
            "observation-a", owner, "event-a", {"room_light_on": True}
        )
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
    return CognitionContext.from_character(
        character,
        container,
        memory_store,
        observation_store=observations,
        metacognitive_feedback=feedback,
    ), container, memory_store


def test_decision_context_contains_owner_scoped_five_layer_inputs_and_emotion():
    cognition_context, _, _ = _make_context()
    decision = CapturingDecision()

    AgentTurn().execute(RuntimeAgent("agent-a", "character-a"), cognition_context, decision)
    snapshot = decision.context

    assert snapshot.cognition_state.agent_id == "agent-a"
    assert tuple(item.source_observation_id for item in snapshot.percepts) == (
        "observation-a",
    )
    assert snapshot.percepts[0].content["room_light_on"] is True
    assert snapshot.working_memory.owner_id == "agent-a"
    assert snapshot.working_memory.percept_ids == ("percept:observation-a",)
    assert tuple(item.id for item in snapshot.long_term_memories) == ("memory-a",)
    assert snapshot.long_term_memories[0].source_event == "event-a"
    assert tuple(item.belief_id for item in snapshot.beliefs) == ("belief-a",)
    assert snapshot.beliefs[0].source_refs == ("observation-a",)
    assert tuple(item.goal_id for item in snapshot.goals) == ("goal-a",)
    assert snapshot.self_model.capabilities["sight"] is True
    assert snapshot.emotion.state == "concern"
    assert snapshot.metacognitive_feedback.review_cues == (
        "check whether the light is still on",
    )
    assert snapshot.metacognitive_feedback.memory_queries[0].owner_id == "agent-a"
    assert not hasattr(snapshot, "world_state")


def test_decision_context_is_recursively_immutable_and_detached_from_stores():
    cognition_context, container, memory_store = _make_context()
    decision = CapturingDecision()
    AgentTurn().execute(RuntimeAgent("agent-a", "character-a"), cognition_context, decision)
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
    cognition_context, _, _ = _make_context()
    decision = CapturingDecision()
    AgentTurn().execute(RuntimeAgent("agent-a", "character-a"), cognition_context, decision)
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
    assert rebuilt.cognition_state.percept_ids == ("percept:observation-a",)
    assert rebuilt.personality.traits["patience"] == 0.6
    with pytest.raises(TypeError):
        rebuilt.personality.traits["patience"] = 0.0
    with pytest.raises(AttributeError):
        rebuilt.cognition_state.percept_ids.append("forged")


def test_foreign_owner_records_and_metacognitive_queries_are_rejected():
    cognition_context, _, _ = _make_context()
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
    cognition_context, _, _ = _make_context()
    decision = CapturingDecision()
    AgentTurn().execute(RuntimeAgent("agent-a", "character-a"), cognition_context, decision)

    with pytest.raises(TypeError):
        EventFactory().create_from_resolution(decision.context)
    perspective = PerspectiveContext(
        "player", "agent-a", frozenset({"environment"}), "session",
        PlayerMode.ROLEPLAY, "character-a",
    )
    with pytest.raises((PermissionError, TypeError)):
        MinimalComposer().compose((decision.context,), perspective)
