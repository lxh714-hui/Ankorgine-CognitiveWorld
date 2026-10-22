from cognitive_world.agent import AgentActionLoop, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionPipeline, ActionProposal, AgentDecision
from cognitive_world.event import EventHandler, EventHistory, EventProcessor
from cognitive_world.observation import Observation, ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.resolution.engine import ResolutionDecision
from _trusted_event_support import FixedResolutionEngine as TrustedTestResolutionEngine, make_system_event
from tests._trusted_observation_support import make_trusted_observation


class ObservingDecision(AgentDecision):
    def __init__(self, proposal):
        self.proposal = proposal
        self.observations = ()

    def propose(self, context):
        self.observations = context.cognition_state.percept_ids
        return self.proposal


class RecordingActionPipeline(ActionPipeline):
    def __init__(self):
        super().__init__()
        self.attempt = None

    def create_attempt(self, action_proposal):
        self.attempt = super().create_attempt(action_proposal)
        return self.attempt


class TrackingWorldState(WorldState):
    def __init__(self):
        super().__init__()
        self.apply_event_calls = []

    def apply_event(self, event, update):
        self.apply_event_calls.append((event.id, update.target_id))
        super().apply_event(event, update)


class RecordResolutionHandler(EventHandler):
    def handle(self, event):
        return WorldUpdate(
            target_id="facts",
            operation="update",
            payload={
                "latest_event_id": event.id,
                "latest_outcome": event.changes[0]["outcome"],
            },
        )


class ConfirmedResolutionEngine(TrustedTestResolutionEngine):
    def __init__(self):
        super().__init__(ResolutionDecision(False, "attempt_observed"))


def test_full_agent_cycle_observes_decides_creates_event_then_applies_it():
    world_state = TrackingWorldState()
    event_history = EventHistory()
    source_event = make_system_event(
        event_id="source_event_001", event_type="world_fact", timestamp="t1",
        changes=[{"weather": "rain"}],
    )
    event_history.append(source_event)

    observation = make_trusted_observation(
        observation_id="observation_001",
        observer_id="agent_001",
        source_event_id=source_event.id,
        content={"noticed": "rain"},
    )
    observation_store = ObservationStore()
    observation_store.add(observation)
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
    )
    cognition_context = CognitionContext.from_character(
        character,
        CognitionContainer(),
        MemoryStore(),
        observation_store=observation_store,
    )
    agent = RuntimeAgent("agent_001", character.id)
    proposal = ActionProposal(
        proposal_id="proposal_001",
        agent_id=agent.agent_id,
        action_type="take_shelter",
        target_refs=["shelter_001"],
    )
    decision = ObservingDecision(proposal)
    pipeline = RecordingActionPipeline()
    loop = AgentActionLoop(
        action_pipeline=pipeline,
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=ConfirmedResolutionEngine()
        ),
    )

    world_before = dict(world_state.facts)
    history_before = event_history.get_events()
    event = loop.run_turn(agent, cognition_context, decision)

    # Cognition received the subject-scoped Observation; generation did not mutate world history.
    assert decision.observations == ("percept:observation_001",)
    assert world_state.facts == world_before
    assert event_history.get_events() == history_before
    assert world_state.apply_event_calls == []

    # The chain is traceable from proposal through Attempt and Resolution to Event.
    attempt = pipeline.attempt
    assert attempt is not None
    assert attempt.action_proposal_id == proposal.proposal_id
    assert event.metadata["action_proposal_id"] == proposal.proposal_id
    assert event.metadata["attempt_id"] == attempt.attempt_id
    assert event.metadata["resolution_id"] == f"resolution:{attempt.attempt_id}"
    assert event.id == f"event:resolution:{attempt.attempt_id}"
    assert event.cause == attempt.attempt_id

    # Only EventProcessor applies the Event and appends it to EventHistory.
    processor = EventProcessor(event_history=event_history)
    processor.register_handler("resolution", RecordResolutionHandler())
    processor.process(event, world_state)

    assert world_state.apply_event_calls == [(event.id, "facts")]
    assert world_state.facts["latest_event_id"] == event.id
    assert world_state.facts["latest_outcome"] == "attempt_observed"
    assert event_history.get_events() == (*history_before, event)
