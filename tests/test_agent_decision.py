from copy import deepcopy

from cognitive_world.cognition import CognitionContainer
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision
from cognitive_world.event.history import EventHistory


def test_agent_decision_returns_action_proposal():
    result = AgentDecision().propose(
        {
            "agent_id": "agent_001",
            "goals": ["goal_001"],
            "observations": [{"content": "information"}],
            "beliefs": [{"content": "belief"}],
            "emotions": [{"state": "calm"}],
        }
    )

    assert isinstance(result, ActionProposal)
    assert result.agent_id == "agent_001"
    assert result.action_type == "unselected"


def test_agent_decision_does_not_modify_context_input():
    context = {
        "agent_id": "agent_001",
        "goals": [{"id": "goal_001", "data": [1]}],
        "observations": [{"content": {"seen": True}}],
        "beliefs": ["belief_001"],
        "emotions": {"state": "calm"},
    }
    original = deepcopy(context)

    AgentDecision().propose(context)

    assert context == original


def test_agent_decision_has_no_world_event_or_cognition_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event(id="event_001", type="fact", timestamp="t1"))
    cognition = CognitionContainer()
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()
    before_cognition = (
        cognition.personalities,
        cognition.beliefs,
        cognition.goals,
        cognition.emotions,
    )

    AgentDecision().propose({"agent_id": "agent_001", "goals": [], "observations": []})

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
    assert (
        cognition.personalities,
        cognition.beliefs,
        cognition.goals,
        cognition.emotions,
    ) == before_cognition
