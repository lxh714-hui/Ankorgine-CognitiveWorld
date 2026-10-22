import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event.factory import EventFactory
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine
from _trusted_event_support import FixedResolutionEngine


def make_attempt():
    return Attempt(
        attempt_id="attempt-1",
        agent_id="agent-1",
        action_proposal_id="proposal-1",
        action_type="interact",
    )


def test_confirmed_resolution_creates_event():
    flow = ActionResolutionFlow(
        resolution_engine=FixedResolutionEngine(ResolutionDecision(True, "completed"))
    )

    event = flow.execute(make_attempt())

    assert isinstance(event, Event)
    assert event.metadata["resolution_id"].startswith("resolution:")
    assert event.metadata["attempt_id"] == "attempt-1"


def test_unresolved_resolution_does_not_create_event_or_change_world_state():
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    before = world_state.facts
    flow = ActionResolutionFlow(
        resolution_engine=ResolutionEngine()
    )

    with pytest.raises(ValueError, match="did not issue a valid confirmation"):
        flow.execute(make_attempt())

    assert world_state.facts == before


def test_event_factory_rejects_unconfirmed_resolution():
    untrusted = ResolutionResult("resolution-1", "attempt-1", True, "completed", confirmed=True)
    with pytest.raises(ValueError, match="controlled confirmation"):
        EventFactory().create_from_resolution(untrusted)


def test_event_factory_creates_event_from_confirmed_resolution():
    result = FixedResolutionEngine().resolve(make_attempt())
    event = EventFactory().create_from_resolution(result)

    assert event.id == "event:resolution:attempt-1"
    assert event.cause == "attempt-1"


def test_hand_built_confirmed_result_is_not_a_credential():
    attempt = make_attempt()
    hand_built = ResolutionResult("r", attempt.attempt_id, True, "wins", confirmed=True)
    with pytest.raises(ValueError, match="controlled confirmation"):
        EventFactory().create_from_resolution(hand_built)


def test_mutating_confirmed_result_after_issue_invalidates_it():
    result = FixedResolutionEngine().resolve(make_attempt())
    result.outcome = "tampered"
    with pytest.raises(ValueError, match="controlled confirmation"):
        EventFactory().create_from_resolution(result)
