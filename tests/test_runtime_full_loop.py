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
from cognitive_world.runtime import (
    AgentScheduler,
    EventScheduler,
    RuntimeContext,
    ScheduledEvent,
    SimulationClock,
    SimulationRuntime,
)
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.resolution.engine import ResolutionDecision
from _trusted_event_support import FixedResolutionEngine as TrustedTestResolutionEngine, make_system_event


class SequentialDecision(AgentDecision):
    def __init__(self):
        self.turn = 0

    def propose(self, context):
        self.turn += 1
        return ActionProposal(
            proposal_id=f"proposal_{self.turn}",
            agent_id=context.cognition_state.agent_id,
            action_type="record_turn",
            parameters={"turn": self.turn},
        )


class ConfirmedResolutionEngine(TrustedTestResolutionEngine):
    def __init__(self):
        super().__init__(ResolutionDecision(True, "confirmed"))


class RecordingWorldState(WorldState):
    def __init__(self):
        super().__init__()
        self.applied_event_ids = []

    def apply_event(self, event, update):
        self.applied_event_ids.append(event.id)
        super().apply_event(event, update)


class StoreEventFactHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate(
            target_id="facts",
            operation="update",
            payload={event.id: {"type": event.type, "cause": event.cause}},
        )


class RecordingEventProcessor(EventProcessor):
    def __init__(self):
        super().__init__()
        self.dispatched_event_ids = []

    def dispatch(self, scheduled_or_event):
        event = (
            scheduled_or_event
            if isinstance(scheduled_or_event, Event)
            else scheduled_or_event.event
        )
        self.dispatched_event_ids.append(event.id)
        return super().dispatch(scheduled_or_event)


def make_cognition_context():
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


def test_run_executes_full_agent_and_scheduled_event_loop_for_multiple_steps():
    clock = SimulationClock()
    world_state = RecordingWorldState()
    event_history = EventHistory()
    event_scheduler = EventScheduler()
    scheduled_events = (
        make_system_event(event_id="scheduled_1", event_type="scheduled", timestamp="t1"),
        make_system_event(event_id="scheduled_3", event_type="scheduled", timestamp="t3"),
    )
    event_scheduler.schedule(ScheduledEvent(1, scheduled_events[0]))
    event_scheduler.schedule(ScheduledEvent(3, scheduled_events[1]))

    agent_scheduler = AgentScheduler()
    for execute_time in (1, 2, 3):
        agent_scheduler.schedule_agent("agent_001", execute_time)
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent_001", "character_001"))

    context = RuntimeContext(
        clock=clock,
        world_state=world_state,
        event_history=event_history,
        event_scheduler=event_scheduler,
        agent_scheduler=agent_scheduler,
        agent_registry=registry,
    )
    processor = RecordingEventProcessor()
    processor.register_handler("scheduled", StoreEventFactHandler())
    processor.register_handler("resolution", StoreEventFactHandler())
    decision = SequentialDecision()
    runtime = SimulationRuntime(
        context=context,
        event_processor=processor,
        agent_action_loop=AgentActionLoop(
            action_resolution_flow=ActionResolutionFlow(
                resolution_engine=ConfirmedResolutionEngine()
            )
        ),
        cognition_context_provider=lambda _agent: make_cognition_context(),
        agent_decision=decision,
    )

    step_results = runtime.run(3)

    assert clock.current_time == 3
    assert len(step_results) == 3
    assert [len(result) for result in step_results] == [2, 1, 2]
    assert decision.turn == 3

    generated_events = [
        event
        for event in event_history.get_events()
        if event.type == "resolution"
    ]
    assert len(generated_events) == 3
    assert [event.metadata["action_proposal_id"] for event in generated_events] == [
        "proposal_1",
        "proposal_2",
        "proposal_3",
    ]
    assert all(event.metadata["attempt_id"] for event in generated_events)
    assert all(
        event.metadata["resolution_id"] == f"resolution:{event.metadata['attempt_id']}"
        for event in generated_events
    )

    assert len(event_history.get_events()) == 5
    assert set(world_state.facts) == set(processor.dispatched_event_ids)
    assert world_state.applied_event_ids == processor.dispatched_event_ids


def test_run_without_agent_scheduler_or_processor_keeps_basic_runtime_behavior():
    clock = SimulationClock()
    world_state = WorldState()
    event_history = EventHistory()
    runtime = SimulationRuntime(RuntimeContext(clock, world_state, event_history))

    results = runtime.run(3)

    assert results == ((), (), ())
    assert clock.current_time == 3
    assert world_state.facts == {}
    assert event_history.get_events() == ()
