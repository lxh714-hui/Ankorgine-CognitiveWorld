from copy import deepcopy
from typing import get_type_hints

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event.history import EventHistory
from cognitive_world.resolution import ResolutionEngine, ResolutionResult


def test_resolution_engine_can_be_instantiated():
    assert isinstance(ResolutionEngine(), ResolutionEngine)


def test_resolve_has_expected_interface_types():
    hints = get_type_hints(ResolutionEngine.resolve)

    assert hints["attempt"] is Attempt
    assert hints["return"] is ResolutionResult


def test_resolve_returns_unresolved_result_for_attempt():
    engine = ResolutionEngine()
    attempt = Attempt(
        attempt_id="attempt_001",
        agent_id="agent_001",
        action_proposal_id="proposal_001",
        action_type="wait",
    )

    result = engine.resolve(attempt)

    assert isinstance(result, ResolutionResult)
    assert result.success is False
    assert result.outcome == "unresolved"
    assert result.confirmed is False
    assert result.attempt_id == "attempt_001"


def test_resolve_does_not_modify_attempt_or_world_event_state():
    engine = ResolutionEngine()
    attempt = Attempt(
        attempt_id="attempt_001",
        agent_id="agent_001",
        action_proposal_id="proposal_001",
        action_type="move",
        target_refs=["location_001"],
        parameters={"nested": ["original"]},
    )
    original_attempt = deepcopy(attempt)
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event(id="event_001", type="fact", timestamp="t1"))
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    engine.resolve(attempt)

    assert attempt == original_attempt
    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
