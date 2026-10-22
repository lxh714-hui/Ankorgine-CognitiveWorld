from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal
from cognitive_world.event.history import EventHistory


def test_action_proposal_stores_its_fields():
    proposal = ActionProposal(
        proposal_id="proposal_001",
        agent_id="agent_001",
        action_type="move",
        target_refs=["location_001"],
        parameters={"speed": 2},
        reasoning_refs=["goal_001", "belief_001"],
        metadata={"source": "agent"},
    )

    assert proposal.proposal_id == "proposal_001"
    assert proposal.agent_id == "agent_001"
    assert proposal.action_type == "move"
    assert proposal.target_refs == ["location_001"]
    assert proposal.parameters == {"speed": 2}
    assert proposal.reasoning_refs == ["goal_001", "belief_001"]
    assert proposal.metadata == {"source": "agent"}


def test_mutable_fields_are_isolated_on_construction_and_access():
    target_refs = ["target_001"]
    parameters = {"nested": ["initial"]}
    reasoning_refs = ["goal_001"]
    metadata = {"nested": {"tag": "initial"}}
    proposal = ActionProposal(
        "proposal_001",
        "agent_001",
        "inspect",
        target_refs,
        parameters,
        reasoning_refs,
        metadata,
    )

    target_refs.append("external")
    parameters["nested"].append("external")
    reasoning_refs.append("external")
    metadata["nested"]["tag"] = "external"
    proposal.target_refs.append("returned")
    proposal.parameters["nested"].append("returned")
    proposal.reasoning_refs.append("returned")
    proposal.metadata["nested"]["tag"] = "returned"

    assert proposal.target_refs == ["target_001"]
    assert proposal.parameters == {"nested": ["initial"]}
    assert proposal.reasoning_refs == ["goal_001"]
    assert proposal.metadata == {"nested": {"tag": "initial"}}


def test_action_proposal_has_no_event_or_world_state_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    before_entities = world_state.entities
    before_facts = world_state.facts
    before_events = event_history.get_events()

    ActionProposal("proposal_001", "agent_001", "wait")

    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
    assert event_history.get_events() == before_events
