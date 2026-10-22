from cognitive_world.agent import (
    AgentActionLoop,
    AgentRegistry,
    Character,
    CognitionContext,
    RuntimeAgent,
)
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import ActionProposal, AgentDecision
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime import (
    AgentScheduler,
    RuntimeContext,
    SimulationClock,
    SimulationRuntime,
)
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


class RecordingLoop:
    def __init__(self):
        self.calls = []

    def run_turn(self, agent, cognition_context, decision):
        self.calls.append((agent, cognition_context, decision))
        return Event("generated", "test", "t1")


def make_agent_context():
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


def make_runtime(agent_execute_time, loop):
    world_state = WorldState()
    event_history = EventHistory()
    agent_scheduler = AgentScheduler()
    agent_scheduler.schedule_agent("agent_001", agent_execute_time)
    registry_agent = RuntimeAgent("agent_001", "character_001")
    context = RuntimeContext(
        clock=SimulationClock(),
        world_state=world_state,
        event_history=event_history,
        agent_scheduler=agent_scheduler,
        agent_registry=AgentRegistry(),
    )
    context.agent_registry.register(registry_agent)
    cognition_context = make_agent_context()
    runtime = SimulationRuntime(
        context=context,
        agent_action_loop=loop,
        cognition_context_provider=lambda _agent: cognition_context,
        agent_decision=FixedDecision(),
    )
    return runtime, context, cognition_context


def test_due_agent_is_executed_and_generated_event_sources_are_preserved():
    loop = RecordingLoop()
    runtime, context, cognition_context = make_runtime(agent_execute_time=1, loop=loop)

    results = runtime.step()

    assert len(loop.calls) == 1
    agent, supplied_context, decision = loop.calls[0]
    assert agent.agent_id == "agent_001"
    assert supplied_context is cognition_context
    assert isinstance(decision, FixedDecision)
    assert results == (Event("generated", "test", "t1"),)
    assert context.clock.current_time == 1


def test_real_action_loop_returns_event_with_attempt_and_proposal_trace():
    action_loop = AgentActionLoop(
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=ConfirmedResolutionEngine()
        )
    )
    runtime, _, _ = make_runtime(agent_execute_time=1, loop=action_loop)

    (event,) = runtime.step()

    assert event.metadata["action_proposal_id"] == "proposal_001"
    assert event.metadata["attempt_id"]
    assert event.metadata["resolution_id"] == f"resolution:{event.metadata['attempt_id']}"
    assert event.id == f"event:{event.metadata['resolution_id']}"


def test_agent_not_due_is_not_executed():
    loop = RecordingLoop()
    runtime, _, _ = make_runtime(agent_execute_time=2, loop=loop)

    assert runtime.step() == ()
    assert loop.calls == []


def test_runtime_does_not_apply_generated_event_or_write_event_history():
    loop = RecordingLoop()
    runtime, context, _ = make_runtime(agent_execute_time=1, loop=loop)
    world_state = context.world_state
    event_history = context.event_history
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    runtime.step()

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events


def test_without_action_loop_existing_runtime_behavior_and_agent_queue_remain():
    context = RuntimeContext(
        SimulationClock(),
        WorldState(),
        EventHistory(),
        agent_scheduler=AgentScheduler(),
    )
    context.agent_scheduler.schedule_agent("agent_001", execute_time=1)
    runtime = SimulationRuntime(context)

    assert runtime.step() == ()
    assert context.agent_scheduler.get_due_agents(1) == ("agent_001",)
