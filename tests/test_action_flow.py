from copy import deepcopy

import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event import EventFactory, EventHistory
from cognitive_world.resolution import ActionResolutionFlow, ResolutionResult
from cognitive_world.resolution import ResolutionDecision, ResolutionEngine
from cognitive_world.event.factory import EventFactory


def test_unresolved_attempt_does_not_flow_to_event():
    attempt = Attempt(
        "attempt_001",
        "agent_001",
        "proposal_001",
        "open",
        target_refs=["door_001"],
    )

    with pytest.raises(ValueError, match="did not issue a valid confirmation"):
        ActionResolutionFlow().execute(attempt)


def test_flow_does_not_modify_attempt_world_state_or_event_history():
    attempt = Attempt(
        "attempt_001",
        "agent_001",
        "proposal_001",
        "move",
        target_refs=["location_001"],
        parameters={"nested": ["original"]},
    )
    original_attempt = deepcopy(attempt)
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("existing", "existing", "t1"))
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    with pytest.raises(ValueError, match="did not issue a valid confirmation"):
        ActionResolutionFlow().execute(attempt)

    assert attempt == original_attempt
    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events


def test_flow_calls_resolution_engine_then_event_factory():
    resolution_result = ResolutionResult(
        "resolution_001", "attempt_001", True, "resolved", confirmed=True
    )
    event = Event("event_001", "resolution", "t1")
    calls = []

    class RecordingEngine(ResolutionEngine):
        def _adjudicate(self, attempt):
            calls.append(("resolve", attempt))
            return ResolutionDecision(True, "resolved")

    class RecordingFactory(EventFactory):
        def create_from_resolution(self, supplied_result, **kwargs):
            calls.append(("create", supplied_result))
            return super().create_from_resolution(supplied_result, **kwargs)

    attempt = Attempt("attempt_001", "agent_001", "proposal_001", "wait")
    flow = ActionResolutionFlow(RecordingEngine(), RecordingFactory())

    generated = flow.execute(attempt)
    assert generated.has_trusted_source("resolution")
    assert calls[0] == ("resolve", attempt)
    assert calls[1][0] == "create"
    assert calls[1][1]._has_valid_confirmation(attempt.attempt_id)
