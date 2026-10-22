"""Production-path counterfactuals for cognition-driven NPC autonomy."""

from cognitive_world.agent import (
    AgentActionLoop,
    Character,
    CognitionContext,
    RuntimeAgent,
)
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import (
    CognitionContainer,
    Goal,
    GoalResourceDemand,
    MemoryStore,
    Personality,
    SelfModel,
)
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.core.world_state import WorldStateSlot
from cognitive_world.resolution.engine import ResolutionDecision
from _trusted_event_support import FixedResolutionEngine
from cognitive_world.decision import AgentDecision
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory
from cognitive_world.observation import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler


def _production_world(
    goals: dict[str, tuple[str, str]],
    *,
    registration_order: tuple[str, ...] | None = None,
    door_open: bool = False,
    door_locked: bool = False,
    physical_capabilities: dict[str, tuple[str, ...]] | None = None,
    co_located: bool = False,
    resource_demands: dict[str, tuple[GoalResourceDemand, ...]] | None = None,
    include_claimed_resource: bool = True,
):
    world = WorldState()
    door = DoorState("door:archive", "hall", door_open, door_locked, True)
    world.load_environment_snapshot({door.door_id: door})
    resource_demands = resource_demands or {}
    if include_claimed_resource:
        resource_ids = {
            demand.resource_ref.removeprefix("object:")
            for demands in resource_demands.values()
            for demand in demands
            if demand.resource_ref.startswith("object:")
        }
        for resource_id in sorted(resource_ids):
            world.load_entity(Entity(resource_id, "resource"))
    physical_capabilities = physical_capabilities or {}
    registry = AgentRegistry()
    cognition = CognitionContainer()
    memory_store = MemoryStore()
    observations = ObservationStore()
    characters: dict[str, Character] = {}
    for owner, (goal_id, description) in goals.items():
        capabilities = physical_capabilities.get(owner, ("manual_manipulation", "locomotion"))
        world.load_entity(Entity(
            owner,
            "character",
            sensory_capabilities=("sight",),
            physical_capabilities=capabilities,
        ))
        world.load_location(owner, "hall" if co_located or owner == "agent-a" else "workshop")
        goal = Goal(
            goal_id, owner, description, 1.0, "active",
            resource_demands=resource_demands.get(owner, ()),
        )
        cognition.add_goal(goal)
        cognition.add_personality(Personality(owner))
        # The SelfModel may be mistaken. Resolution uses the canonical WorldState
        # Entity capabilities and is the only authority on feasibility.
        cognition.add_self_model(SelfModel(
            owner,
            capabilities={"manual_manipulation": True, "locomotion": True},
        ))
        character = Character(
            f"character:{owner}", owner, owner, goal_ids=[goal_id]
        )
        characters[owner] = character
        registry.register(RuntimeAgent(owner, character.id, goal_ids=[goal_id]))

    if registration_order is not None:
        # Rebuild to exercise the actual registry insertion order.
        registry = AgentRegistry()
        for owner in registration_order:
            registry.register(RuntimeAgent(
                owner, characters[owner].id, goal_ids=list(characters[owner].goal_ids)
            ))

    history = EventHistory()
    clock = SimulationClock()
    scheduler = EventScheduler()
    agent_scheduler = AgentScheduler()
    processor = EventProcessor(
        event_history=history,
        world_state=world,
        simulation_clock=clock,
        agent_registry=registry,
        observation_store=observations,
    )
    context = RuntimeContext(
        clock,
        world,
        history,
        event_scheduler=scheduler,
        agent_scheduler=agent_scheduler,
        agent_registry=registry,
        observation_store=observations,
    )
    contexts = {
        owner: CognitionContext.from_character(
            character, cognition, memory_store, observation_store=observations
        )
        for owner, character in characters.items()
    }
    loop = AgentActionLoop(
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world),
            world_state=world,
        )
    )
    runtime = SimulationRuntime(
        context,
        scheduler=scheduler,
        event_processor=processor,
        agent_action_loop=loop,
        cognition_context_provider=lambda agent: contexts[agent.agent_id],
        agent_decision=AgentDecision(),
    )
    initial_state_event = SystemEventFactory().create(
        event_id="event:environment-seed:door-archive",
        event_type="environment_state_observed",
        timestamp="initialization",
        changes=[{"environment_id": door.door_id}],
        simulation_tick=clock.current_time,
    )
    processor.dispatch_with_evidence(initial_state_event)
    runner = AutonomousWorldRunner(runtime)
    return runner, world, history, observations


def _action(report, agent_id):
    return next(item for item in report.rounds[0].agent_actions if item.agent_id == agent_id)


def test_same_agent_goal_change_changes_candidate_proposal_and_trusted_world_result():
    open_runner, open_world, open_history, _ = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    })
    open_report = open_runner.run(1)
    open_action = _action(open_report, "agent-a")

    wait_runner, wait_world, wait_history, _ = _production_world({
        "agent-a": ("goal-wait", "wait for a clear signal"),
    })
    wait_report = wait_runner.run(1)
    wait_action = _action(wait_report, "agent-a")

    assert open_action.proposal is not None and wait_action.proposal is not None
    assert any(item.target == "door:archive" for item in open_action.proposal.candidates)
    assert all(item.target != "door:archive" for item in wait_action.proposal.candidates)
    assert open_action.proposal.action_type != wait_action.proposal.action_type
    selected = next(
        item for item in open_action.proposal.candidates
        if item.candidate_id == open_action.proposal.selected_candidate_id
    )
    assert selected.goal_id == "goal-open"
    assert dict(selected.factors)["goal_drive"] > 0
    assert dict(selected.factors)["observed_affordance_goal_alignment"] > 0
    assert open_action.status == "success"
    assert open_world.environment["door:archive"].is_open is True
    committed = open_history.get_events()
    assert any(event.has_trusted_source("resolution") for event in committed)
    assert wait_action.status == "unresolved"
    assert wait_world.environment["door:archive"].is_open is False
    assert not any(
        event.has_trusted_source("resolution")
        for event in wait_history.get_events()
    )


def test_observed_environment_state_changes_available_affordance_and_proposal():
    closed_runner, closed_world, _, closed_observations = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    }, door_open=False)
    closed_action = _action(closed_runner.run(1), "agent-a")

    open_runner, open_world, _, open_observations = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    }, door_open=True)
    already_open_action = _action(open_runner.run(1), "agent-a")

    assert any(item.content.value is False for item in closed_observations.get_by_observer("agent-a"))
    assert any(item.content.value is True for item in open_observations.get_by_observer("agent-a"))
    assert any(item.target == "door:archive" for item in closed_action.proposal.candidates)
    assert all(item.target != "door:archive" for item in already_open_action.proposal.candidates)
    assert closed_action.proposal.method != already_open_action.proposal.method
    assert closed_world.environment["door:archive"].is_open is True
    assert open_world.environment["door:archive"].is_open is True


def test_missing_authoritative_capability_cannot_confirm_candidate_success():
    runner, world, history, _ = _production_world(
        {"agent-a": ("goal-open", "open the archive door")},
        physical_capabilities={"agent-a": ()},
    )
    action = _action(runner.run(1), "agent-a")

    assert action.proposal is not None
    assert action.proposal.target_refs == ("door:archive",)
    assert action.status == "unresolved"
    assert action.event_id is None
    assert world.environment["door:archive"].is_open is False
    assert not any(event.type == "resolution" for event in history.get_events())


def test_swapping_goals_moves_action_between_agents_without_id_binding():
    first, first_world, _, _ = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
        "agent-b": ("goal-watch", "wait for a clear signal"),
    }, co_located=True)
    first_report = first.run(1)
    first_by_id = {item.agent_id: item for item in first_report.rounds[0].agent_actions}

    swapped, swapped_world, _, _ = _production_world({
        "agent-a": ("goal-watch", "wait for a clear signal"),
        "agent-b": ("goal-open", "open the archive door"),
    }, co_located=True)
    swapped_report = swapped.run(1)
    swapped_by_id = {item.agent_id: item for item in swapped_report.rounds[0].agent_actions}

    assert first_by_id["agent-a"].status == "success"
    assert swapped_by_id["agent-a"].proposal.goal_id == "goal-watch"
    assert swapped_by_id["agent-a"].status == "unresolved"
    assert swapped_by_id["agent-b"].proposal.goal_id == "goal-open"
    assert swapped_by_id["agent-b"].status == "success"
    assert first_world.environment["door:archive"].is_open is True
    assert swapped_world.environment["door:archive"].is_open is True


def test_registration_order_does_not_change_per_agent_candidates_or_results():
    goal_set = {
        "agent-a": ("goal-open", "open the archive door"),
        "agent-b": ("goal-watch", "wait for a clear signal"),
    }
    forward, forward_world, _, _ = _production_world(
        goal_set, registration_order=("agent-a", "agent-b"), co_located=True
    )
    reverse, reverse_world, _, _ = _production_world(
        goal_set, registration_order=("agent-b", "agent-a"), co_located=True
    )
    forward_report = forward.run(1).rounds[0]
    reverse_report = reverse.run(1).rounds[0]
    forward_by_id = {item.agent_id: item for item in forward_report.agent_actions}
    reverse_by_id = {item.agent_id: item for item in reverse_report.agent_actions}

    assert tuple(item.agent_id for item in forward_report.agent_actions) == ("agent-a", "agent-b")
    assert tuple(item.agent_id for item in reverse_report.agent_actions) == ("agent-a", "agent-b")
    for agent_id in goal_set:
        left, right = forward_by_id[agent_id], reverse_by_id[agent_id]
        assert left.status == right.status
        assert left.proposal.action_type == right.proposal.action_type
        assert left.proposal.candidates == right.proposal.candidates
        assert left.proposal.selected_candidate_id == right.proposal.selected_candidate_id
    assert forward_world.environment["door:archive"].is_open is True
    assert reverse_world.environment["door:archive"].is_open is True


def test_two_npcs_consume_own_observations_decide_independently_and_commit_only_supported_effect():
    resource = "object:resource:archive-key"
    demand = (GoalResourceDemand(resource, "window:morning", True),)
    runner, world, history, observations = _production_world(
        {
            "agent-a": ("shared-goal", "open the archive door"),
            "agent-b": ("shared-goal", "wait for a clear signal"),
        },
        co_located=True,
        resource_demands={"agent-a": demand, "agent-b": demand},
    )
    report = runner.run(1).rounds[0]
    actions = {item.agent_id: item for item in report.agent_actions}
    records = {item.agent_id: item for item in runner.runtime.last_agent_turn_results}
    assert set(actions) == {"agent-a", "agent-b"}
    assert actions["agent-a"].status == "success"
    assert actions["agent-b"].status == "unresolved"
    assert actions["agent-a"].proposal.goal_id == "shared-goal"
    assert actions["agent-b"].proposal.goal_id == "shared-goal"
    assert actions["agent-a"].proposal.action_type != actions["agent-b"].proposal.action_type

    for owner in actions:
        own_observations = observations.get_by_observer(owner)
        assert own_observations
        assert set(records[owner].observation_ids) <= {
            item.observation_id for item in own_observations
        }
        assert all(
            observations.get(observation_id).observer_id == owner
            for observation_id in records[owner].observation_ids
        )
        assert records[owner].newly_consumed_percept_ids
        assert all(
            item.startswith("percept:") for item in records[owner].newly_consumed_percept_ids
        )
        context = runner.runtime.cognition_context_provider(
            runner.runtime.context.agent_registry.get(owner)
        )
        assert context.get_goals()[0].owner_id == owner
        assert context.get_goals()[0].description == (
            "open the archive door" if owner == "agent-a" else "wait for a clear signal"
        )
        assert any(
            finding.kind == "supported_conflict" and finding.goal_ids == ("shared-goal",)
            for finding in records[owner].scheduler_findings
        )

    execution = records["agent-a"].execution
    assert execution.proposal.agent_id == execution.attempt.agent_id == "agent-a"
    assert execution.attempt.initiator_id == "agent-a"
    assert execution.event is not None and records["agent-a"].event_committed
    assert execution.event.metadata["initiator_id"] == "agent-a"
    assert execution.event.id == records["agent-a"].event_id
    assert history.get_event(execution.event.id) == execution.event
    assert world.environment["door:archive"].is_open is True
    slot = world.read_state_slot(
        WorldStateSlot("environment", "door:archive", ("is_open",)),
        event_history=history,
    )
    assert slot.value is True and slot.source_event_id == execution.event.id
    assert not records["agent-b"].event_committed
    assert records["agent-b"].execution.event is None
    assert len([item for item in history.get_events() if item.has_trusted_source("resolution")]) == 1


def test_committed_failure_feedback_is_owner_scoped_and_changes_repeat_score():
    runner, world, history, _ = _production_world({
        "agent-a": ("same-goal", "open the archive door"),
        "agent-b": ("same-goal", "wait for a clear signal"),
    }, co_located=True, door_locked=True)
    first = runner.run_round()
    assert first.agent_actions[0].event_committed
    assert world.environment["door:archive"].is_open is False
    assert history.get_event(first.agent_actions[0].event_id) is not None
    assert len(runner.runtime.behavior_feedback.history) == 1
    assert runner.runtime.behavior_feedback.history[0].owner_id == "agent-a"

    second = runner.run_round()
    proposal = runner.runtime.last_agent_turn_results[0].execution.proposal
    first_trace = proposal.metadata["decision_trace"]
    selected = next(item for item in first_trace if item["candidate_id"] ==
                    proposal.metadata["selected_candidate_id"])
    assert dict(selected["factors"])["recent_confirmed_failure"] < 0
    other = runner.runtime.last_agent_turn_results[1].execution.proposal.metadata["decision_trace"]
    assert all(dict(item["factors"])["recent_confirmed_failure"] == 0 for item in other)
    assert len(runner.runtime.behavior_feedback.history) == 2
    assert runner.runtime.behavior_feedback.history[-1].penalty > runner.runtime.behavior_feedback.history[0].penalty
    assert second.agent_actions[1].status == "unresolved"
    assert all(item.owner_id == "agent-a" for item in runner.runtime.behavior_feedback.history)


def test_locked_door_produces_committed_failure_and_transient_repeat_penalty():
    runner, world, history, observations = _production_world({
        "agent-a": ("same-goal", "open the archive door"),
        "agent-b": ("same-goal", "wait for a clear signal"),
    }, co_located=True, door_locked=True)
    assert any(item.content.predicate == "door_locked" and item.content.value is True
               for item in observations.get_by_observer("agent-a"))
    first = runner.run_round()
    action = first.agent_actions[0]
    assert action.status == "failure"
    assert action.event_committed
    assert runner.runtime.last_agent_turn_results[0].execution.resolution.success is False
    event = history.get_event(action.event_id)
    assert event is not None and event.changes[0]["success"] is False
    assert len(event.changes) == 1
    assert world.environment["door:archive"].is_open is False
    assert world.environment["door:archive"].is_locked is True
    slot = world.read_state_slot(
        WorldStateSlot("environment", "door:archive", ("is_open",)),
        event_history=history,
    )
    assert slot.value is False and slot.source_event_id is None
    assert len(runner.runtime.behavior_feedback.history) == 1
    assert runner.runtime.behavior_feedback.history[0].event_id == event.id
    assert runner.runtime.behavior_feedback.history[0].owner_id == "agent-a"

    second = runner.run_round()
    proposal = runner.runtime.last_agent_turn_results[0].execution.proposal
    selected = next(item for item in proposal.metadata["decision_trace"]
                    if item["candidate_id"] == proposal.metadata["selected_candidate_id"])
    assert dict(selected["factors"])["recent_confirmed_failure"] < 0
    assert len(runner.runtime.behavior_feedback.history) == 2
    assert runner.runtime.behavior_feedback.history[-1].penalty > runner.runtime.behavior_feedback.history[0].penalty
    assert all(item.owner_id == "agent-a" for item in runner.runtime.behavior_feedback.history)
    other = runner.runtime.last_agent_turn_results[1].execution.proposal.metadata["decision_trace"]
    assert all(dict(item["factors"])["recent_confirmed_failure"] == 0 for item in other)
    assert second.agent_actions[0].event_committed
    assert runner.runtime.behavior_feedback.history[0].event_id != runner.runtime.behavior_feedback.history[1].event_id


def test_behavior_feedback_changes_selection_for_identical_production_decision_context():
    """Counterfactual scoring changes only the feedback input, not the choices."""
    from dataclasses import replace

    from cognitive_world.decision.behavior_feedback import BehaviorFeedback

    runner, world, history, _ = _production_world(
        {"agent-a": ("goal", "open the archive door")}, door_locked=True
    )
    for _ in range(3):
        round_report = runner.run_round()
        action = round_report.agent_actions[0]
        assert action.status == "failure" and action.event_committed
        assert history.get_event(action.event_id) is not None

    runtime = runner.runtime
    agent = runtime.context.agent_registry.get("agent-a")
    cognition_context = runtime.cognition_context_provider(agent)
    with runtime.write_fence.operation():
        context, _ = runtime.agent_action_loop.agent_turn.prepare_decision_context(
            agent, cognition_context,
            simulation_tick=runtime.context.clock.capture(),
        )
        tick = runtime.context.clock.current_time
        # Both proposals traverse the production AgentDecision candidate,
        # evaluation, ranking, and selection pipeline over the exact same
        # immutable context. Only the feedback object differs.
        without_feedback = replace(
            runtime.agent_decision,
            simulation_tick=tick,
            behavior_feedback=BehaviorFeedback(),
        ).propose(context)
        with_feedback = replace(
            runtime.agent_decision,
            simulation_tick=tick,
            behavior_feedback=runtime.behavior_feedback,
        ).propose(context)

    plain_trace = {
        item["candidate_id"]: item for item in without_feedback.metadata["decision_trace"]
    }
    informed_trace = {
        item["candidate_id"]: item for item in with_feedback.metadata["decision_trace"]
    }
    assert set(plain_trace) == set(informed_trace)
    assert {
        key: (value["intent"], value["target"], value["method"], value["source_refs"])
        for key, value in plain_trace.items()
    } == {
        key: (value["intent"], value["target"], value["method"], value["source_refs"])
        for key, value in informed_trace.items()
    }

    selected_without = without_feedback.metadata["selected_candidate_id"]
    selected_with = with_feedback.metadata["selected_candidate_id"]
    assert selected_without != selected_with
    assert without_feedback.target_refs == ["door:archive"]
    assert with_feedback.action_type != without_feedback.action_type

    door_candidate = next(
        item for item in plain_trace.values() if item["target"] == "door:archive"
    )
    adjusted_door = informed_trace[door_candidate["candidate_id"]]
    assert adjusted_door["score"] < door_candidate["score"]
    assert dict(adjusted_door["factors"])["recent_confirmed_failure"] < 0
    # It remains a legal candidate: feedback changes ranking, not eligibility.
    assert door_candidate["candidate_id"] in informed_trace
    assert all(
        dict(item["factors"])["recent_confirmed_failure"] == 0
        for item in informed_trace.values() if item["target"] != "door:archive"
    )
    assert all(item.owner_id == "agent-a" for item in runtime.behavior_feedback.history)
    assert all(history.get_event(item.event_id) is not None
               for item in runtime.behavior_feedback.history)
    assert world.environment["door:archive"].is_locked is True
    assert len(runtime.behavior_feedback.history) == 3


def test_failure_event_attempt_source_is_bound():
    runner, _, history, _ = _production_world({"agent-a": ("goal", "open the archive door")}, door_locked=True)
    report = runner.run_round()
    event = history.get_event(report.agent_actions[0].event_id)
    attempt = runner.runtime.last_agent_turn_results[0].execution.attempt
    from cognitive_world.event.attempt_source import verify_confirmed_failure_event
    source = event.metadata["confirmed_attempt_failure"]
    assert source["owner_id"] == attempt.agent_id
    assert source["action_type"] == attempt.action_type
    assert source["target_refs"] == tuple(attempt.target_refs)
    assert source["method"] == attempt.parameters["method"]
    assert source["simulation_tick"] == event.simulation_tick
    assert verify_confirmed_failure_event(event, attempt=attempt)
    source["target_refs"] = ("door:forged",)
    assert not verify_confirmed_failure_event(event, attempt=attempt)


def test_feedback_failure_after_event_commit_latches_recovery():
    runner, world, history, _ = _production_world({"agent-a": ("goal", "open the archive door")}, door_locked=True)
    def fail_feedback(**_kwargs):
        raise RuntimeError("injected feedback failure")
    runner.runtime.behavior_feedback.record_failure = fail_feedback
    report = runner.run_round()
    event_id = report.agent_actions[0].event_id
    assert history.get_event(event_id) is not None
    assert history.requires_recovery()
    assert runner.runtime.write_fence.recovery_required
    assert runner.runtime.behavior_feedback.history == []
    assert world.environment["door:archive"].is_locked is True


def test_snapshot_fence_cannot_capture_between_failure_event_and_feedback():
    from threading import Event, Thread

    runner, _, history, _ = _production_world(
        {"agent-a": ("goal", "open the archive door")}, door_locked=True
    )
    entered_feedback, release_feedback = Event(), Event()
    original = runner.runtime.behavior_feedback.record_failure

    def blocked_feedback(**kwargs):
        entered_feedback.set()
        if not release_feedback.wait(5):
            raise TimeoutError("test did not release feedback barrier")
        return original(**kwargs)

    runner.runtime.behavior_feedback.record_failure = blocked_feedback
    writer = Thread(target=runner.run_round)
    writer.start()
    assert entered_feedback.wait(5)
    committed = history.get_events()[-1]
    assert history.get_event(committed.id) == committed
    assert runner.runtime.behavior_feedback.history == []

    snapshot_started, snapshot_done = Event(), Event()
    captured = []

    def capture_consistent_pair():
        snapshot_started.set()
        with runner.runtime.write_fence.operation():
            with runner.runtime.write_fence.snapshot_scope():
                captured.append((history.get_event(committed.id) is not None,
                                 len(runner.runtime.behavior_feedback.history)))
        snapshot_done.set()

    snapshotter = Thread(target=capture_consistent_pair)
    snapshotter.start()
    assert snapshot_started.wait(5)
    assert not snapshot_done.wait(0.05)
    release_feedback.set()
    writer.join(5)
    snapshotter.join(5)
    assert not writer.is_alive() and not snapshotter.is_alive()
    assert captured == [(True, 1)]


def test_success_and_unresolved_attempts_do_not_create_failure_feedback():
    success, *_ = _production_world({"agent-a": ("goal", "open the archive door")})
    assert success.run_round().agent_actions[0].status == "success"
    assert success.runtime.behavior_feedback.history == []

    unresolved, *_ = _production_world({
        "agent-a": ("goal", "open the archive door")
    }, physical_capabilities={"agent-a": ()})
    assert unresolved.run_round().agent_actions[0].status == "unresolved"
    assert unresolved.runtime.behavior_feedback.history == []
