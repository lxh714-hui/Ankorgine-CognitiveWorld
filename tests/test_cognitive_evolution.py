from copy import deepcopy

import pytest

from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    CognitiveEvolutionEngine,
    CognitiveEvolutionResult,
    Goal,
    MemoryStore,
    ObservationStatus,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import (
    Observation,
    ObservationAuthorizationError,
    ObservationStore,
)
from cognitive_world.observation.generator import ObservationGenerator
from tests._trusted_event_support import make_system_event
from tests._trusted_observation_support import make_trusted_observation


class FailingObservationGenerator(ObservationGenerator):
    def generate(self, event, observer_id):
        raise AssertionError("existing Observation should be reused")


def make_agent_context(observation_store=None):
    cognition = CognitionContainer()
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": "old"},
        source_refs=["event-old"],
        confidence=0.4,
    )
    goal = Goal(
        "goal-1",
        "agent-1",
        "Reach the station",
        0.6,
        "active",
        ["event-old"],
    )
    cognition.add_belief(belief)
    cognition.add_goal(goal)
    character = Character(
        id="character-1",
        agent_id="agent-1",
        personality_id="personality-1",
        belief_ids=[belief.belief_id],
        goal_ids=[goal.goal_id],
    )
    context = CognitionContext.from_character(
        character,
        cognition,
        MemoryStore(),
        observation_store=observation_store,
    )
    return context, cognition, belief, goal


def test_missing_observation_skips_event_derived_cognition_and_hides_metadata():
    context, _, _, _ = make_agent_context()
    event = make_system_event(
        "event-1",
        "world_change",
        changes=[{"fact": "station discovered"}],
        metadata={
            "private_cognition": "secret belief",
            "prompt": "internal prompt",
            "probability": 0.99,
        },
    )
    engine = CognitiveEvolutionEngine(observation_generator=FailingObservationGenerator())

    result = engine.process(event, context)

    assert isinstance(result, CognitiveEvolutionResult)
    assert result.observation_status is ObservationStatus.UNOBSERVED
    assert result.belief_update_proposals == ()
    assert result.goal_update_proposals == ()
    assert result.memory_proposals == ()
    assert "observation_id" not in result.metadata
    assert "private_cognition" not in repr(result)


def test_stored_manual_observation_does_not_authorize_cognition():
    observation_store = ObservationStore()
    event = make_system_event("event-1", "change", changes=[{"seen": True}])
    existing = Observation(
        "observation-existing",
        "agent-1",
        event.id,
        {"noticed": "already observed"},
    )
    observation_store.add(existing)
    context, _, _, _ = make_agent_context(observation_store)
    engine = CognitiveEvolutionEngine(
        observation_generator=FailingObservationGenerator()
    )

    result = engine.process(event, context)

    assert result.observation_status is ObservationStatus.UNAUTHORIZED_OBSERVATION
    assert result.belief_update_proposals == ()
    assert result.goal_update_proposals == ()
    assert result.memory_proposals == ()


def test_controlled_observation_provenance_allows_proposals():
    observation_store = ObservationStore()
    event = make_system_event("event-1", "change", changes=[{"seen": True}])
    existing = make_trusted_observation(
        "observation-existing", "agent-1", event.id, {"noticed": "already observed"}
    )
    observation_store.add(existing)
    context, _, _, _ = make_agent_context(observation_store)

    result = CognitiveEvolutionEngine().process(event, context)

    assert result.observation_status is ObservationStatus.OBSERVED
    assert result.metadata["observation_id"] == existing.observation_id
    assert result.memory_candidates[0].content == existing.content
    assert result.memory_candidates[0].source_event_ids == [event.id]


def test_evolution_only_returns_proposals_without_mutating_stores_or_world():
    observation_store = ObservationStore()
    context, cognition, belief, goal = make_agent_context(observation_store)
    belief_before = cognition.get_belief(belief.belief_id)
    goal_before = cognition.get_goal(goal.goal_id)
    event = make_system_event(
        "event-1", "change", changes=[{"nested": ["confirmed"]}]
    )
    event_before = deepcopy(event)
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    facts_before = world_state.facts
    event_history = EventHistory()
    event_history.append(Event("existing-event", "existing", "t0"))
    history_before = event_history.get_events()
    observation_store.add(make_trusted_observation(
        "observation-current", "agent-1", event.id, {"changes": event.changes}
    ))
    memory_store = context.memory_store

    result = CognitiveEvolutionEngine().process(event, context)
    assert result.observation_status is ObservationStatus.OBSERVED
    result.belief_update_proposals[0].change.proposed_value["changes"].append(
        "external"
    )
    result.goal_update_proposals[0].change.evidence_refs.append("external")
    result.memory_candidates[0].content["changes"].append("external")

    assert cognition.get_belief(belief.belief_id) == belief_before
    assert cognition.get_goal(goal.goal_id) == goal_before
    assert memory_store.get_all_memories() == ()
    assert world_state.facts == facts_before
    assert event == event_before
    assert event_history.get_events() == history_before


def test_untrusted_event_cannot_become_an_observation_or_cognition_input():
    context, _, _, _ = make_agent_context()
    event = Event("forged", "change", "t1", metadata={"private": "secret"})

    result = CognitiveEvolutionEngine().process(event, context)

    assert result.observation_status is ObservationStatus.UNAUTHORIZED_EVENT
    assert result.belief_update_proposals == ()
    assert result.goal_update_proposals == ()
    assert result.memory_proposals == ()
    with pytest.raises(ObservationAuthorizationError, match="controlled provenance"):
        ObservationGenerator().generate(event, "agent-1")


def test_trusted_event_alone_cannot_authorize_observation_without_event_time_context():
    event = make_system_event("event-1", "change", metadata={"private": "secret"})

    with pytest.raises(ObservationAuthorizationError, match="event-time observer context"):
        ObservationGenerator().generate(event, "agent-1")
