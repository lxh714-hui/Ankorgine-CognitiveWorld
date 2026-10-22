from cognitive_world.decision.attempt import Attempt
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory


def test_attempt_can_be_created():
    attempt = Attempt(
        id="attempt_001",
        actor="entity_001",
        intent_id="intent_001",
        action="push_door",
    )

    assert isinstance(attempt, Attempt)


def test_attempt_saves_intent_id_and_all_fields():
    parameters = {"force": "gently", "options": ["quietly", "slowly"]}
    metadata = {"source": "input", "details": {"attempt_number": 1}}
    attempt = Attempt(
        id="attempt_001",
        actor="entity_001",
        intent_id="intent_001",
        action="push_door",
        target="door_001",
        parameters=parameters,
        metadata=metadata,
    )

    assert attempt.id == "attempt_001"
    assert attempt.actor == "entity_001"
    assert attempt.intent_id == "intent_001"
    assert attempt.action == "push_door"
    assert attempt.target == "door_001"
    assert attempt.parameters == parameters
    assert attempt.metadata == metadata


def test_attempt_target_can_be_empty():
    attempt = Attempt(
        id="attempt_001",
        actor="entity_001",
        intent_id="intent_001",
        action="wait",
        target=None,
    )

    assert attempt.target is None


def test_attempt_stores_proposal_reference_and_new_fields():
    attempt = Attempt(
        attempt_id="attempt_002",
        agent_id="agent_001",
        action_proposal_id="proposal_001",
        action_type="move",
        target_refs=["location_001", "entity_002"],
        parameters={"speed": 2},
        metadata={"channel": "agent"},
    )

    assert attempt.attempt_id == "attempt_002"
    assert attempt.agent_id == "agent_001"
    assert attempt.action_proposal_id == "proposal_001"
    assert attempt.action_type == "move"
    assert attempt.target_refs == ["location_001", "entity_002"]
    assert attempt.parameters == {"speed": 2}
    assert attempt.metadata == {"channel": "agent"}


def test_attempt_mutable_fields_are_isolated_on_input_and_access():
    target_refs = ["target_001"]
    parameters = {"nested": ["original"]}
    metadata = {"nested": {"value": "original"}}
    attempt = Attempt(
        "attempt_003",
        "agent_001",
        "proposal_001",
        "inspect",
        target_refs,
        parameters,
        metadata,
    )

    target_refs.append("external")
    parameters["nested"].append("external")
    metadata["nested"]["value"] = "external"
    attempt.target_refs.append("returned")
    attempt.parameters["nested"].append("returned")
    attempt.metadata["nested"]["value"] = "returned"

    assert attempt.target_refs == ["target_001"]
    assert attempt.parameters == {"nested": ["original"]}
    assert attempt.metadata == {"nested": {"value": "original"}}


def test_attempt_creation_does_not_create_event_or_modify_world_state():
    world_state = WorldState()
    event_history = EventHistory()
    before_entities = world_state.entities
    before_facts = world_state.facts
    before_events = event_history.get_events()

    Attempt("attempt_004", "agent_001", "proposal_001", "wait")

    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
