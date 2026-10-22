import asyncio
from threading import Event as ThreadEvent, Thread

import pytest

from cognitive_world.cognition import (
    Belief, BeliefChange, BeliefStore, BeliefUpdateProposal, CognitiveUpdateApplier,
    CognitiveUpdateValidator, GoalStore,
)
from cognitive_world.cognition.self_model import SelfModel, SelfModelStore
from cognitive_world.cognition.self_model_evolution import SelfModelUpdateProposal
from cognitive_world.core.door import DoorState
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.runtime import RuntimeContext, SimulationClock, SimulationRuntime


class DoorHandler(EventHandler):
    def handle(self, event):
        raise AssertionError("WorldState path is required")

    def handle_with_world_state(self, event, world_state):
        return WorldUpdate("environment", "update", {"door": event.changes[0]})


def make_event(event_id="event"):
    return SystemEventFactory().create(
        event_id=event_id, event_type="door-change", timestamp="t0",
        changes=[DoorState("door", "room", True, False, True)], simulation_tick=0,
    )


def test_late_event_result_is_rejected_before_world_or_history_write():
    async def scenario():
        fence = RuntimeWriteFence("session-a")
        world = WorldState()
        world.load_environment_data("door", DoorState("door", "room", False, False, True))
        history = EventHistory()
        processor = EventProcessor(event_history=history, world_state=world, write_fence=fence)
        processor.register_handler("door-change", DoorHandler())
        ready, release = asyncio.Event(), asyncio.Event()
        event = None

        async def late_operation():
            ready.set()
            await release.wait()
            processor.process_with_evidence(event, world)

        with fence.operation():
            event = make_event()
            task = asyncio.create_task(late_operation())
            await ready.wait()
        fence.freeze_and_advance()
        fence.unfreeze()
        release.set()
        with pytest.raises(PermissionError, match="stale|frozen"):
            await task
        assert world.environment["door"].is_open is False
        assert history.get_event("event") is None
        assert history.get_processing_status("event") is None
        with fence.operation():
            with pytest.raises(PermissionError, match="candidate is not bound"):
                processor.process_with_evidence(event, world)

    asyncio.run(scenario())


def test_late_cognitive_candidate_cannot_change_canonical_belief():
    async def scenario():
        fence = RuntimeWriteFence("session-a")
        beliefs, goals = BeliefStore(), GoalStore()
        beliefs.add(Belief("b", "agent", "old", ["init"], 0.5))
        applier = CognitiveUpdateApplier(beliefs, goals, write_fence=fence)
        ready, release = asyncio.Event(), asyncio.Event()
        proposal = None
        validation = None

        async def late_apply():
            ready.set()
            await release.wait()
            applier.apply(proposal, validation)

        with fence.operation():
            proposal = BeliefUpdateProposal(
                owner_id="agent", belief_id="b",
                change=BeliefChange("replace", "old", "new", "evidence", ["obs"]),
                source_refs=["obs"],
            )
            validation = CognitiveUpdateValidator().validate(
                proposal, {"agent_id": "agent"}
            )
            task = asyncio.create_task(late_apply())
            await ready.wait()
        fence.freeze_and_advance()
        fence.unfreeze()
        release.set()
        with pytest.raises(PermissionError, match="stale|frozen"):
            await task
        assert beliefs.get_by_id("b").content == "old"
        with fence.operation():
            with pytest.raises(PermissionError, match="candidate is not bound"):
                applier.apply(proposal, validation)
            # The canonical Store is itself the final barrier; callers cannot
            # bypass the Applier and submit the same stale validated proposal.
            with pytest.raises(PermissionError, match="candidate is not bound"):
                beliefs.update(
                    Belief("b", "agent", "new", ["obs"], 0.5),
                    proposal=proposal,
                    validation_result=validation,
                )

    asyncio.run(scenario())


def test_old_context_stays_invalid_after_unfreeze_and_other_session_is_rejected():
    from contextvars import ContextVar
    fence = RuntimeWriteFence("session-a")
    active: ContextVar[object] = ContextVar("test_active_permit", default=None)
    with fence.operation() as old_permit:
        active.set(old_permit)
    fence.freeze_and_advance()
    fence.unfreeze()
    with pytest.raises(PermissionError):
        with fence.commit_scope():
            pass
    other = RuntimeWriteFence("session-b")
    with other.operation():
        with pytest.raises(PermissionError):
            with fence.commit_scope():
                pass


def test_generation_change_serializes_with_commit_linearization():
    fence = RuntimeWriteFence()
    entered, release, frozen = ThreadEvent(), ThreadEvent(), ThreadEvent()
    order = []

    def committing_operation():
        with fence.operation():
            with fence.commit_scope():
                entered.set()
                assert release.wait(2)
                order.append("commit")

    def freeze_operation():
        assert entered.wait(2)
        fence.freeze_and_advance()
        order.append("freeze")
        frozen.set()

    commit_thread = Thread(target=committing_operation)
    freeze_thread = Thread(target=freeze_operation)
    commit_thread.start()
    freeze_thread.start()
    assert entered.wait(2)
    release.set()
    assert frozen.wait(2)
    commit_thread.join(2)
    freeze_thread.join(2)
    assert order == ["commit", "freeze"]
    assert fence.frozen


def test_runtime_refuses_steps_while_frozen_and_runs_new_generation_after_unfreeze():
    runtime = SimulationRuntime(RuntimeContext(
        SimulationClock(), WorldState(), EventHistory()
    ))
    original_generation = runtime.write_fence.restore_generation
    runtime.freeze_writes()
    with pytest.raises(PermissionError, match="frozen"):
        runtime.step()
    runtime.unfreeze_writes()
    runtime.start()
    assert runtime.step() == ()
    assert runtime.write_fence.restore_generation == original_generation + 1


def test_generation_cannot_be_advanced_reentrantly_inside_commit():
    fence = RuntimeWriteFence()
    before = fence.restore_generation
    with fence.operation():
        with fence.commit_scope():
            with pytest.raises(RuntimeError, match="inside a commit"):
                fence.freeze_and_advance()
    assert fence.restore_generation == before
    assert not fence.frozen


def test_old_action_proposal_cannot_be_resubmitted_after_generation_change():
    fence = RuntimeWriteFence()
    action_loop = AgentActionLoop(write_fence=fence)
    with fence.operation():
        proposal = ActionProposal("p", "agent", "wait")
    fence.freeze_and_advance()
    fence.unfreeze()
    with fence.operation():
        with pytest.raises(PermissionError, match="candidate is not bound"):
            action_loop.run_proposal_with_result(proposal)


def test_current_generation_event_and_self_model_updates_are_allowed_but_stale_self_model_is_not():
    fence = RuntimeWriteFence()
    world = WorldState()
    world.load_environment_data("door", DoorState("door", "room", False, False, True))
    history = EventHistory()
    processor = EventProcessor(event_history=history, world_state=world, write_fence=fence)
    processor.register_handler("door-change", DoorHandler())
    with fence.operation():
        processor.process_with_evidence(make_event(), world)
    assert world.environment["door"].is_open is True
    assert history.get_event("event") is not None

    store = SelfModelStore()
    initial = SelfModel("agent", self_beliefs=[])
    store.add(initial)
    applier = CognitiveUpdateApplier(BeliefStore(), GoalStore(), store, write_fence=fence)
    with fence.operation():
        proposal = SelfModelUpdateProposal(
            owner_id="agent", previous_self_beliefs=(), claim="tentative capability",
            source_refs=("obs",), source_event_ids=("event",),
        )
        validation = CognitiveUpdateValidator().validate(proposal, {
            "agent_id": "agent", "authorized_source_refs": ("obs",),
            "authorized_event_ids": ("event",),
            "authorized_source_event_pairs": {"obs": "event"},
        })
        applier.apply(proposal, validation)
    assert len(store.get("agent").self_beliefs) == 1

    async def late_self_model_apply():
        ready, release = asyncio.Event(), asyncio.Event()
        stale = None
        stale_validation = None

        async def late():
            ready.set()
            await release.wait()
            applier.apply(stale, stale_validation)

        with fence.operation():
            stale = SelfModelUpdateProposal(
                owner_id="agent", previous_self_beliefs=tuple(store.get("agent").self_beliefs),
                claim="stale candidate", source_refs=("obs-2",), source_event_ids=("event-2",),
            )
            stale_validation = CognitiveUpdateValidator().validate(stale, {
                "agent_id": "agent", "authorized_source_refs": ("obs-2",),
                "authorized_event_ids": ("event-2",),
                "authorized_source_event_pairs": {"obs-2": "event-2"},
            })
            task = asyncio.create_task(late())
            await ready.wait()
        fence.freeze_and_advance()
        fence.unfreeze()
        release.set()
        with pytest.raises(PermissionError, match="stale|frozen"):
            await task

    asyncio.run(late_self_model_apply())
    assert len(store.get("agent").self_beliefs) == 1
