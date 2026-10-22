from copy import deepcopy

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionPipeline, ActionProposal, Attempt
from cognitive_world.event.history import EventHistory


def test_action_proposal_is_converted_to_attempt():
    proposal = ActionProposal(
        proposal_id="proposal_001",
        agent_id="agent_001",
        action_type="move",
        target_refs=["location_001"],
        parameters={"speed": 2},
        reasoning_refs=["goal_001", "belief_001"],
        metadata={"source": "agent_decision"},
    )

    attempt = ActionPipeline().create_attempt(proposal)

    assert isinstance(attempt, Attempt)
    assert attempt.action_proposal_id == "proposal_001"
    assert attempt.agent_id == "agent_001"
    assert attempt.action_type == "move"
    assert attempt.target_refs == ["location_001"]
    assert attempt.parameters == {"speed": 2}
    assert attempt.metadata["source"] == "agent_decision"
    assert attempt.metadata["action_proposal_reasoning_refs"] == [
        "goal_001",
        "belief_001",
    ]


def test_conversion_does_not_modify_action_proposal():
    proposal = ActionProposal(
        "proposal_001",
        "agent_001",
        "inspect",
        target_refs=["target_001"],
        parameters={"nested": ["original"]},
        reasoning_refs=["belief_001"],
        metadata={"nested": {"value": "original"}},
    )
    original = deepcopy(proposal)

    ActionPipeline().create_attempt(proposal)

    assert proposal == original


def test_conversion_has_no_event_or_world_state_side_effects():
    proposal = ActionProposal("proposal_001", "agent_001", "wait")
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("event_001", "existing", "t1"))
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    ActionPipeline().create_attempt(proposal)

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
