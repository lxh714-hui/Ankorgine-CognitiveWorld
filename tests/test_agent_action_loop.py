from cognitive_world.agent import (
    AgentActionLoop,
    Character,
    CognitionContext,
    RuntimeAgent,
)
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal
from cognitive_world.event.history import EventHistory
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.resolution.engine import ResolutionDecision
from _trusted_event_support import FixedResolutionEngine as TrustedTestResolutionEngine


class FixedDecision:
    def __init__(self, proposal):
        self.proposal = proposal

    def propose(self, context):
        return self.proposal


class ConfirmedResolutionEngine(TrustedTestResolutionEngine):
    def __init__(self):
        super().__init__(ResolutionDecision(True, "confirmed"))


def make_action_loop():
    return AgentActionLoop(
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=ConfirmedResolutionEngine()
        )
    )


def make_context():
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
    )
    return CognitionContext.from_character(
        character,
        CognitionContainer(),
        MemoryStore(),
    )


def test_agent_action_loop_flows_proposal_through_attempt_to_event():
    agent = RuntimeAgent("agent_001", "character_001")
    context = make_context()
    proposal = ActionProposal(
        "proposal_001", "agent_001", "interact", target_refs=["object_001"]
    )

    event = make_action_loop().run_turn(agent, context, FixedDecision(proposal))

    assert isinstance(event, Event)
    assert event.metadata["action_proposal_id"] == "proposal_001"
    assert event.metadata["attempt_id"].startswith("attempt:")
    assert event.metadata["resolution_id"] == f"resolution:{event.metadata['attempt_id']}"


def test_event_traces_attempt_and_resolution_sources():
    event = make_action_loop().run_turn(
        RuntimeAgent("agent_001"),
        make_context(),
        FixedDecision(ActionProposal("proposal_002", "agent_001", "wait")),
    )

    assert event.cause == event.metadata["attempt_id"]
    assert event.metadata["resolution_id"] == f"resolution:{event.cause}"
    assert event.metadata["action_proposal_id"] == "proposal_002"


def test_loop_does_not_update_world_state_or_event_history():
    agent = RuntimeAgent("agent_001")
    context = make_context()
    world_state = WorldState()
    event_history = EventHistory()
    event_history.append(Event("existing", "existing", "t1"))
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    make_action_loop().run_turn(
        agent,
        context,
        FixedDecision(ActionProposal("proposal_003", "agent_001", "wait")),
    )

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
