"""Scenario lifecycle uses canonical state and never turns hooks into events."""
from dataclasses import FrozenInstanceError, replace

import pytest

from cognitive_world.cognition import CognitionContainer
from cognitive_world.cognition import MemoryStore
from cognitive_world.agent import AgentActionLoop, CognitionContext
from cognitive_world.content import ContentInstantiator
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.content import (ScenarioLifecycle, ScenarioPhase,
                                     ScenarioSeedScheduler, scenario_state_key)
from cognitive_world.core.event import Event
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext

from test_reusable_world_content import install, registry, proposal


def prepared():
    instance, world, cognition, agents = install(registry())
    history, observations, clock = EventHistory(), ObservationStore(), SimulationClock()
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=agents, observation_store=observations)
    context = RuntimeContext(clock, world, history, agent_scheduler=AgentScheduler(),
        agent_registry=agents, observation_store=observations)
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(instance)
    return instance, world, processor, context, lifecycle


def test_entry_exit_are_event_processed_and_template_remains_immutable():
    instance, world, processor, context, lifecycle = prepared()
    actor = instance.characters[0].agent_id
    proposal = lifecycle.propose_entry(instance.instance_id, actor)
    active = lifecycle.enter(proposal)
    assert active.phase is ScenarioPhase.ACTIVE
    assert active.revision == 2
    assert len(context.event_history.get_events()) == 4
    assert world.facts[scenario_state_key(instance.world_id, instance.instance_id)] == active
    with pytest.raises(FrozenInstanceError):
        instance.entry_location_id = "changed"
    with pytest.raises(PermissionError):
        lifecycle.enter(proposal)
    with pytest.raises(PermissionError):
        lifecycle.propose_exit(instance.instance_id, actor)
    assert context.event_history.get_event(active.last_event_id).has_trusted_source("system")


def test_manual_event_cannot_enter_or_change_scenario():
    instance, world, processor, context, lifecycle = prepared()
    actor = instance.characters[0].agent_id
    change = {"instance_id": instance.instance_id, "actor_id": actor,
              "target": "entering", "revision": 0}
    manual = Event("manual-entry", "scenario_lifecycle", "", [actor], changes=[change], simulation_tick=0)
    with pytest.raises(ValueError):
        processor.dispatch(manual)
    forged_system = SystemEventFactory().create(event_id="forged-entry",
        event_type="scenario_lifecycle", timestamp="", participants=[actor],
        changes=[change], simulation_tick=0)
    with pytest.raises(PermissionError):
        processor.dispatch(forged_system)
    assert lifecycle.state(instance.instance_id).phase is ScenarioPhase.AVAILABLE
    assert context.event_history.get_events() == ()


def test_instance_states_are_isolated_and_seed_never_autocommits():
    instance, world, processor, context, lifecycle = prepared()
    second, _, _, _ = install(registry(), "second", world=world,
        cognition=CognitionContainer(),
        agents=context.agent_registry)
    lifecycle.register(second)
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, instance.characters[0].agent_id))
    assert lifecycle.state(second.instance_id).phase is ScenarioPhase.AVAILABLE
    count = len(context.event_history.get_events())
    scheduler = ScenarioSeedScheduler(context, lifecycle)
    assert scheduler.poll(instance.instance_id) == ()
    assert len(context.event_history.get_events()) == count


def test_seed_wakes_only_authorized_observer_and_does_not_create_event():
    instance, world, processor, context, lifecycle = prepared()
    actor = instance.characters[0].agent_id
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, actor))
    door_id = instance.locations[0].mechanism_ids[0]
    # The seed waits for a real authorized door-open observation. A mere
    # scenario entry and an unobserved/closed door do not satisfy it.
    processor.dispatch_with_evidence(SystemEventFactory().create(event_id="closed-door",
        event_type="environment_state_observed", timestamp="", simulation_tick=0,
        changes=[{"environment_id": door_id}]))
    before = len(context.event_history.get_events())
    assert ScenarioSeedScheduler(context, lifecycle).poll(instance.instance_id) == ()
    assert len(context.event_history.get_events()) == before


def run_autonomous_scenario(goal, *, sight=True, manipulation=True):
    reg = registry(proposal(goal=goal))
    instance, world, cognition, agents = install(reg)
    actor = instance.characters[0].agent_id
    entity = world.get_entity(actor)
    world.load_entity(replace(entity,
        sensory_capabilities=("sight",) if sight else (),
        physical_capabilities=("manual_manipulation", "locomotion") if manipulation else ("locomotion",)))
    history, observations, clock = EventHistory(), ObservationStore(), SimulationClock()
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=agents, observation_store=observations)
    context = RuntimeContext(clock, world, history, event_scheduler=EventScheduler(),
        agent_scheduler=AgentScheduler(), agent_registry=agents, observation_store=observations)
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(instance)
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, actor))
    cognition_context = CognitionContext.from_character(
        ContentInstantiator.character_reference(instance.characters[0], cognition),
        cognition, MemoryStore(), observation_store=observations)
    runtime = SimulationRuntime(context, scheduler=context.event_scheduler,
        event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: cognition_context,
        agent_decision=AgentDecision())
    report = AutonomousWorldRunner(runtime).run(2)
    return instance, world, context, lifecycle, report


def test_scenario_goal_changes_real_decision_and_seed_only_schedules():
    opening, open_world, open_context, open_lifecycle, open_report = run_autonomous_scenario("open the archive door")
    watching, watch_world, watch_context, _, watch_report = run_autonomous_scenario("keep watch quietly")
    assert opening.characters[0].agent_id == watching.characters[0].agent_id
    open_proposal = next(action.proposal for round_item in open_report.rounds
                         for action in round_item.agent_actions if action.proposal is not None)
    watch_proposal = next(action.proposal for round_item in watch_report.rounds
                          for action in round_item.agent_actions if action.proposal is not None)
    assert (open_proposal.action_type, open_proposal.method) != (watch_proposal.action_type, watch_proposal.method)
    door_id = opening.locations[0].mechanism_ids[0]
    assert open_world.environment[door_id].is_open is True
    assert watch_world.environment[watching.locations[0].mechanism_ids[0]].is_open is False
    before = len(open_context.event_history.get_events())
    scheduler = ScenarioSeedScheduler(open_context, open_lifecycle)
    opportunities = scheduler.poll(opening.instance_id)
    assert len(opportunities) == 1 and opportunities[0].observer_id == opening.characters[0].agent_id
    assert scheduler.poll(opening.instance_id) == ()
    assert len(open_context.event_history.get_events()) == before


def test_real_resolution_movement_unlocks_exit_and_completion():
    instance, world, context, lifecycle, report = run_autonomous_scenario("open the archive door")
    actor = instance.characters[0].agent_id
    assert instance.at_exit(world, actor)
    assert sum(action.status == "success" for round_item in report.rounds
               for action in round_item.agent_actions) >= 2
    proposal = lifecycle.propose_exit(instance.instance_id, actor)
    completed = lifecycle.exit(proposal)
    assert completed.phase is ScenarioPhase.COMPLETED
    assert completed.revision == 4
    assert world.locations[actor] in instance.exit_location_ids
    assert lifecycle.state(instance.instance_id) == completed
    with pytest.raises(PermissionError):
        lifecycle.exit(proposal)


def test_abort_is_lifecycle_only_and_does_not_force_peace_or_world_effects():
    instance, world, processor, context, lifecycle = prepared()
    actor = instance.characters[0].agent_id
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, actor))
    before_environment = dict(world.environment)
    aborted = lifecycle.exit(lifecycle.propose_exit(instance.instance_id, actor, abort=True))
    assert aborted.phase is ScenarioPhase.ABORTED
    assert dict(world.environment) == before_environment
    assert context.event_history.get_event(aborted.last_event_id).type == "scenario_lifecycle"


def test_scenario_perception_and_world_capability_change_real_outcome():
    seen, seen_world, seen_context, _, seen_report = run_autonomous_scenario("open the archive door")
    blind, blind_world, blind_context, _, blind_report = run_autonomous_scenario("open the archive door", sight=False)
    unskilled, unskilled_world, unskilled_context, _, unskilled_report = run_autonomous_scenario("open the archive door", manipulation=False)
    seen_actor = seen.characters[0].agent_id
    assert any(item.observer_id == seen_actor for item in seen_context.observation_store.get_by_observer(seen_actor))
    assert blind_context.observation_store.get_by_observer(blind.characters[0].agent_id) == ()
    assert seen_world.environment[seen.locations[0].mechanism_ids[0]].is_open is True
    assert blind_world.environment[blind.locations[0].mechanism_ids[0]].is_open is False
    assert unskilled_world.environment[unskilled.locations[0].mechanism_ids[0]].is_open is False
    assert not any(event.type == "resolution" and event.changes[0].get("success") is True
                   for event in unskilled_context.event_history.get_events())
