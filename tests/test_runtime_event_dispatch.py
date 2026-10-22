import pytest

from cognitive_world.agent import (
    AgentActionLoop,
    AgentRegistry,
    Character,
    CognitionContext,
    RuntimeAgent,
)
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision
from cognitive_world.event import EventHandler, EventHistory, EventProcessor
from cognitive_world.runtime import AgentScheduler, RuntimeContext, SimulationClock, SimulationRuntime
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.resolution.engine import ResolutionDecision
from _trusted_event_support import FixedResolutionEngine as TrustedTestResolutionEngine


class FixedDecision(AgentDecision):
    def propose(self, context):
        return ActionProposal(
            "proposal_001", context.cognition_state.agent_id, "wait"
        )


class ConfirmedResolutionEngine(TrustedTestResolutionEngine):
    def __init__(self):
        super().__init__(ResolutionDecision(True, "confirmed"))


class TrackingWorldState(WorldState):
    def __init__(self):
        super().__init__()
        self.application_sources = []

    def apply_event(self, event, update):
        self.application_sources.append(event.id)
        super().apply_event(event, update)


class RecordHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate(
            target_id="facts",
            operation="update",
            payload={event.id: event.metadata["attempt_id"]},
        )


class RecordingProcessor(EventProcessor):
    def __init__(self):
        super().__init__()
        self.dispatched_events = []

    def dispatch(self, event):
        self.dispatched_events.append(event)
        return super().dispatch(event)


def make_runtime():
    world_state = TrackingWorldState()
    event_history = EventHistory()
    agent_scheduler = AgentScheduler()
    agent_scheduler.schedule_agent("agent_001", execute_time=1)
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent_001", "character_001"))
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
    )
    cognition_context = CognitionContext.from_character(
        character,
        CognitionContainer(),
        MemoryStore(),
    )
    context = RuntimeContext(
        SimulationClock(),
        world_state,
        event_history,
        agent_scheduler=agent_scheduler,
        agent_registry=registry,
    )
    processor = RecordingProcessor()
    processor.register_handler("resolution", RecordHandler())
    runtime = SimulationRuntime(
        context=context,
        agent_action_loop=AgentActionLoop(
            action_resolution_flow=ActionResolutionFlow(
                resolution_engine=ConfirmedResolutionEngine()
            )
        ),
        cognition_context_provider=lambda _agent: cognition_context,
        agent_decision=FixedDecision(),
        event_processor=processor,
    )
    return runtime, context, processor


def test_runtime_dispatches_agent_event_to_processor_for_application():
    runtime, context, processor = make_runtime()

    result = runtime.step()

    assert result == (None,)
    assert len(processor.dispatched_events) == 1
    event = processor.dispatched_events[0]
    assert isinstance(event, Event)
    assert event.metadata["action_proposal_id"] == "proposal_001"
    assert event.metadata["attempt_id"]
    assert event.metadata["resolution_id"] == f"resolution:{event.metadata['attempt_id']}"
    assert context.world_state.facts == {event.id: event.metadata["attempt_id"]}
    assert context.event_history.get_events() == (event,)
    assert context.world_state.application_sources == [event.id]


def test_runtime_itself_does_not_update_world_or_history_without_processor():
    runtime, context, _ = make_runtime()
    runtime.event_processor = None
    before_events = context.event_history.get_events()
    before_facts = context.world_state.facts

    generated = runtime.step()

    assert len(generated) == 1
    assert context.world_state.facts == before_facts
    assert context.event_history.get_events() == before_events
    assert context.world_state.application_sources == []


def test_post_world_failure_stops_other_agent_turns_and_future_steps():
    class FailingHistory(EventHistory):
        def append(self, event, *, processing_evidence=None):
            raise OSError("history unavailable after world write")

    class CountingDecision(FixedDecision):
        def __init__(self):
            self.owners = []

        def propose(self, context):
            self.owners.append(context.cognition_state.agent_id)
            return super().propose(context)

    runtime, context, processor = make_runtime()
    history = FailingHistory()
    context.event_history = history
    context.agent_registry.register(RuntimeAgent("agent_002", "character_002"))
    context.agent_scheduler.schedule_agent("agent_002", execute_time=1)
    contexts = {
        agent_id: CognitionContext.from_character(
            Character(f"character_{index:03}", agent_id, f"personality_{index:03}"),
            CognitionContainer(), MemoryStore(),
        )
        for index, agent_id in ((1, "agent_001"), (2, "agent_002"))
    }
    runtime.cognition_context_provider = lambda agent: contexts[agent.agent_id]
    decision = CountingDecision()
    runtime.agent_decision = decision

    runtime.step()

    assert decision.owners == ["agent_001"]
    assert len(context.world_state.application_sources) == 1
    assert len(processor.dispatched_events) == 1
    assert history.get_events() == ()
    assert history.requires_recovery()
    assert runtime.write_fence.recovery_required and not runtime.running
    with pytest.raises(RuntimeError, match="recovery"):
        runtime.step()
    assert len(context.world_state.application_sources) == 1
    assert len(processor.dispatched_events) == 1
