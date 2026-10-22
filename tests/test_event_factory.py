from copy import deepcopy

from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventFactory, EventHistory
from cognitive_world.resolution import ResolutionResult
from cognitive_world.decision.attempt import Attempt
from _trusted_event_support import FixedResolutionEngine


def trusted_result(**kwargs):
    attempt = Attempt("attempt_001", "agent", "proposal", "open-ended-action")
    decision = kwargs.pop("decision")
    result = FixedResolutionEngine(decision).resolve(attempt)
    return result


def test_resolution_result_creates_event_with_resolution_source():
    from cognitive_world.resolution.engine import ResolutionDecision
    result = trusted_result(decision=ResolutionDecision(True, "door_opened", metadata={"timestamp": "t42", "rule_ref": "rule_001"}))

    event = EventFactory().create_from_resolution(result)

    assert event.id == "event:resolution:attempt_001"
    assert event.type == "resolution"
    assert event.timestamp == "t42"
    assert event.cause == "attempt_001"
    assert event.changes == [{"success": True, "outcome": "door_opened"}]
    assert event.metadata["resolution_id"] == "resolution:attempt_001"
    assert event.metadata["attempt_id"] == "attempt_001"
    assert event.metadata["rule_ref"] == "rule_001"


def test_factory_does_not_modify_resolution_result():
    from cognitive_world.resolution.engine import ResolutionDecision
    result = trusted_result(decision=ResolutionDecision(True, "completed", metadata={"timestamp": "t42", "nested": {"values": ["before"]}}))
    original = deepcopy(result)

    EventFactory().create_from_resolution(result)

    assert result == original
    assert result.metadata == original.metadata


def test_factory_does_not_modify_world_state_or_execute_event():
    world_state = WorldState()
    event_history = EventHistory()
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()
    from cognitive_world.resolution.engine import ResolutionDecision
    result = trusted_result(decision=ResolutionDecision(True, "completed"))

    event = EventFactory().create_from_resolution(result)

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
    assert event.id == "event:resolution:attempt_001"
