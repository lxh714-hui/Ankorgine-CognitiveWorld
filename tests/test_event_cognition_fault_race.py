"""Deterministic ordering of cognition commits and a non-replayable Event fault."""

from contextvars import copy_context
from threading import Event as ThreadEvent, Thread

import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition import (
    Belief, BeliefChange, BeliefStore, BeliefUpdateProposal,
    CognitiveUpdateApplier, CognitiveUpdateValidator,
    Goal, GoalChange, GoalStore, GoalUpdateProposal,
)
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import (
    EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory,
)
from cognitive_world.event.history import EventProcessingStatus
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.write_fence import RuntimeWriteFence


class FailingSignature:
    def __init__(self, entered=None, release=None):
        self.entered = entered
        self.release = release
        self.calls = 0

    def sign(self, purpose, payload):
        self.calls += 1
        if self.calls == 1:
            return b"test-only-signature"
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(5), "signature failure was not released"
        raise OSError("event attestation unavailable")

    def verify(self, purpose, payload, signature):
        return signature == b"test-only-signature"


def _setup(*, signer):
    fence = RuntimeWriteFence("event-cognition-race")
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    world.load_entity(Entity("agent-a", "agent"))
    world.load_entity(Entity("agent-b", "agent"))
    history = EventHistory(timeline_id="race-timeline")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a"))
    registry.register(RuntimeAgent("agent-b"))
    clock = SimulationClock()
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        persistence_trust=signer, write_fence=fence,
    )
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    source = SystemEventFactory().create(
        event_id="memory-source", event_type="room_light_changed", timestamp="t0",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
    )
    processor.process_with_evidence(source, world)
    runtime = SimulationRuntime(
        RuntimeContext(clock, world, history, scheduler=EventScheduler(),
                       agent_registry=registry),
        event_processor=processor, write_fence=fence,
    )
    beliefs, goals, memories = BeliefStore(), GoalStore(), MemoryStore()
    applier = CognitiveUpdateApplier(beliefs, goals, write_fence=fence)
    persistence = MemoryPersistence(memories, history, write_fence=fence)
    with fence.operation():
        beliefs.add(Belief("belief-a", "agent-a", "old-a", ["obs-a"], 0.5))
        beliefs.add(Belief("belief-b", "agent-b", "old-b", ["obs-b"], 0.5))
        goals.add(Goal("goal-b", "agent-b", "go", 0.4, "active"))
    runtime.start()
    event = SystemEventFactory().create(
        event_id="fault-event", event_type="room_light_changed", timestamp="t1",
        changes=[{"room_id": "room-a", "from_light_on": True, "to_light_on": False}],
    )
    return runtime, processor, event, applier, persistence, beliefs, goals, memories


def _belief(owner, belief_id, old, new, source):
    return BeliefUpdateProposal(
        owner, belief_id, BeliefChange("replace", old, new, "evidence", [source]),
        [source], 0.7,
    )


def _fault(processor, event, world, failures):
    try:
        processor.process_with_evidence(event, world)
    except OSError as error:
        failures.append(error)


def _assert_fault(runtime, event):
    history = runtime.context.event_history
    assert runtime.context.world_state.environment["room-a"] == {"light_on": False}
    assert history.get_processing_status(event.id) is EventProcessingStatus.RECOVERY_REQUIRED
    assert history.get_event(event.id) is None
    assert history.requires_recovery()
    assert runtime.write_fence.recovery_required and runtime.write_fence.frozen


def test_cognition_holding_final_lock_finishes_before_event_fault():
    signer = FailingSignature()
    runtime, processor, event, applier, _, beliefs, goals, _ = _setup(signer=signer)
    fence = runtime.write_fence
    with fence.operation():
        proposal = _belief("agent-a", "belief-a", "old-a", "committed-a", "obs-a")
        result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-a"})
        operation = copy_context()
    entered, release, fault_attempted = ThreadEvent(), ThreadEvent(), ThreadEvent()
    outcomes = []
    failures = []

    def cognition_commit():
        def inside_operation():
            with fence.commit_scope():
                entered.set()
                assert release.wait(5), "cognition commit was not released"
                outcomes.append(applier.apply(proposal, result))
        operation.run(inside_operation)

    def event_commit():
        fault_attempted.set()
        _fault(processor, event, runtime.context.world_state, failures)

    cognition_thread = Thread(target=cognition_commit)
    fault_thread = Thread(target=event_commit)
    cognition_thread.start()
    assert entered.wait(5)
    fault_thread.start()
    assert fault_attempted.wait(5)
    assert runtime.context.world_state.environment["room-a"] == {"light_on": True}
    release.set()
    cognition_thread.join(5)
    fault_thread.join(5)
    assert not cognition_thread.is_alive() and not fault_thread.is_alive()
    assert len(outcomes) == 1 and outcomes[0].content == "committed-a"
    assert len(failures) == 1
    _assert_fault(runtime, event)
    assert beliefs.get_by_id("belief-a").content == "committed-a"
    assert goals.get_owned("agent-b", "goal-b").status == "active"
    with pytest.raises(PermissionError):
        operation.run(applier.apply, proposal, result)


def test_event_fault_invalidates_other_agents_pending_belief_goal_and_memory():
    signature_entered, release_signature = ThreadEvent(), ThreadEvent()
    runtime, processor, event, applier, persistence, beliefs, goals, memories = _setup(
        signer=FailingSignature(signature_entered, release_signature)
    )
    fence = runtime.write_fence
    with fence.operation():
        belief = _belief("agent-b", "belief-b", "old-b", "late-b", "obs-b")
        belief_result = CognitiveUpdateValidator().validate(
            belief, {"agent_id": "agent-b"}
        )
        belief_operation = copy_context()
    with fence.operation():
        goal = GoalUpdateProposal(
            "agent-b", "goal-b",
            GoalChange("update", "active", "completed", 0.4, 0.6,
                       "evidence", ["obs-b"]), ["obs-b"],
        )
        goal_result = CognitiveUpdateValidator().validate(
            goal, {"agent_id": "agent-b"}
        )
        goal_operation = copy_context()
    with fence.operation():
        memory_proposal = MemoryProposal(
            "late", "memory-source", "agent-b", "experience", "late memory", 0.7
        )
        decision = MemoryDecisionAuthority().issue(
            memory_proposal, accepted=True, importance=memory_proposal.importance,
            memory_type=memory_proposal.memory_type,
        )
        memory_request = MemoryWriteFactory().create_request(decision, memory_proposal)
        memory_operation = copy_context()

    old_generation = fence.restore_generation
    fault_failures = []
    fault_thread = Thread(target=_fault, args=(
        processor, event, runtime.context.world_state, fault_failures,
    ))
    fault_thread.start()
    assert signature_entered.wait(5)
    assert runtime.context.world_state.environment["room-a"] == {"light_on": False}
    assert not runtime.context.event_history.requires_recovery()
    ready = [ThreadEvent() for _ in range(3)]
    denied = []

    def pending(index, context, commit):
        ready[index].set()
        try:
            context.run(commit)
        except PermissionError as error:
            denied.append((index, error))

    threads = [
        Thread(target=pending, args=(0, belief_operation,
                                     lambda: applier.apply(belief, belief_result))),
        Thread(target=pending, args=(1, goal_operation,
                                     lambda: applier.apply(goal, goal_result))),
        Thread(target=pending, args=(2, memory_operation,
                                     lambda: persistence.save(memory_request))),
    ]
    for thread in threads:
        thread.start()
    assert all(item.wait(5) for item in ready)
    assert beliefs.get_by_id("belief-b").content == "old-b"
    assert goals.get_owned("agent-b", "goal-b").status == "active"
    assert memories.get_memory("memory:late") is None
    release_signature.set()
    fault_thread.join(5)
    for thread in threads:
        thread.join(5)
    assert not fault_thread.is_alive() and all(not thread.is_alive() for thread in threads)
    assert len(fault_failures) == 1 and {index for index, _ in denied} == {0, 1, 2}
    _assert_fault(runtime, event)
    assert fence.restore_generation == old_generation + 1
    assert beliefs.get_by_id("belief-a").content == "old-a"
    assert beliefs.get_by_id("belief-b").content == "old-b"
    assert goals.get_owned("agent-b", "goal-b").status == "active"
    assert memories.get_memory("memory:late") is None
    assert [item.id for item in runtime.context.event_history.get_events()] == ["memory-source"]
