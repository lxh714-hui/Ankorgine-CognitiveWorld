from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    CognitiveEvolutionEngine,
    Goal,
    MemoryStore,
    ObservationStatus,
)
from cognitive_world.observation import Observation, ObservationStore
from tests._trusted_event_support import make_system_event
from tests._trusted_observation_support import make_trusted_observation


def _context(store):
    cognition = CognitionContainer()
    belief = Belief("belief", "agent-1", {"claim": "old"}, ["prior"], 0.5)
    goal = Goal("goal", "agent-1", "goal", 0.5, "active", ["prior"])
    cognition.add_belief(belief)
    cognition.add_goal(goal)
    character = Character(
        "character", "agent-1", "personality", belief_ids=[belief.id], goal_ids=[goal.id]
    )
    return CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=store
    )


def _assert_denied(observation, *, expected=ObservationStatus.UNAUTHORIZED_OBSERVATION):
    store = ObservationStore()
    store.add(observation)
    context = _context(store)
    event = make_system_event("event-1", "change", metadata={"prompt": "secret"})

    result = CognitiveEvolutionEngine().process(event, context)

    assert result.observation_status is expected
    assert result.belief_update_proposals == ()
    assert result.goal_update_proposals == ()
    assert result.memory_proposals == ()
    assert "prompt" not in repr(result)


def test_manual_observation_and_store_presence_do_not_grant_trust():
    _assert_denied(Observation("obs", "agent-1", "event-1", {"visible": True}))


def test_observer_or_event_id_match_alone_does_not_grant_trust():
    _assert_denied(
        Observation("obs", "agent-1", "different-event", "content"),
        expected=ObservationStatus.UNOBSERVED,
    )
    _assert_denied(
        Observation("other", "agent-2", "event-1", "content"),
        expected=ObservationStatus.UNOBSERVED,
    )
    # A matching pair remains insufficient when stored.
    _assert_denied(Observation("obs", "agent-1", "event-1", "content"))


def test_mutating_issued_content_or_metadata_invalidates_receipt():
    observation = make_trusted_observation(
        "obs", "agent-1", "event-1", {"visible": ["initial"]}, {"source": "test"}
    )
    observation.content["visible"].append("tampered")
    _assert_denied(observation)

    observation = make_trusted_observation(
        "obs-2", "agent-1", "event-1", "content", {"source": "test"}
    )
    observation.metadata["prompt"] = "injected"
    _assert_denied(observation)


def test_other_agent_observation_is_never_consumed():
    store = ObservationStore()
    store.add(make_trusted_observation("other", "agent-2", "event-1", "private"))
    result = CognitiveEvolutionEngine().process(
        make_system_event("event-1", "change"), _context(store)
    )
    assert result.observation_status is ObservationStatus.UNOBSERVED
    assert not result.belief_update_proposals
    assert not result.goal_update_proposals
    assert not result.memory_proposals


def test_store_preserves_but_does_not_create_or_repair_receipts():
    store = ObservationStore()
    manual = Observation("manual", "agent-1", "event-1", "content")
    store.add(manual)
    assert not store.get("manual").has_trusted_provenance()

    trusted = make_trusted_observation("trusted", "agent-1", "event-1", "content")
    store.add(trusted)
    loaded = store.get("trusted")
    assert loaded.has_trusted_provenance()
    loaded.content = "changed"
    assert not loaded.has_trusted_provenance()
    assert store.get("trusted").has_trusted_provenance()
