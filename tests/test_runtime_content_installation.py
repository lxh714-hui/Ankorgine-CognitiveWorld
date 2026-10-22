"""Phase 16 installation crosses the real processor, world and Agent boundary."""
from dataclasses import replace

import pytest

from cognitive_world.agent import AgentActionLoop, CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.content import (ContentInstantiator, ContentRegistry,
    ContentValidator, GenerationProposal, RuntimeContentInstaller,
    ScenarioLifecycle, ScenarioPhase, LLMContentGenerator,
    ContentGenerationRequest, ScenarioSeedScheduler, installation_record_key,
    scenario_state_key)
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler

from test_reusable_world_content import proposal
from test_llm_content_generation import FakeTransport, document
import json


def installation_world():
    world, cognition, agents = WorldState(), CognitionContainer(), AgentRegistry()
    clock, history, observations = SimulationClock(), EventHistory(), ObservationStore()
    world.load_entity(Entity("existing-room", "location"))
    world.load_environment_data("existing-door", DoorState("existing-door", "existing-room", False, False, True))
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=agents, observation_store=observations)
    context = RuntimeContext(clock, world, history, event_scheduler=EventScheduler(),
        agent_scheduler=AgentScheduler(), agent_registry=agents, observation_store=observations)
    registry = ContentRegistry(ContentValidator(context.safety_governance))
    installer = RuntimeContentInstaller(context, processor, registry, cognition, agents)
    processor.dispatch_with_evidence(SystemEventFactory().create(event_id="world-started",
        event_type="environment_state_observed", timestamp="", simulation_tick=0,
        changes=[{"environment_id": "existing-door"}]))
    assert world._initialization_sealed
    return world, cognition, agents, context, processor, registry, installer


def test_runtime_proposal_install_and_multiple_instances_are_isolated():
    world, cognition, agents, context, processor, registry, installer = installation_world()
    item = proposal()
    first = installer.install_proposal(item, template_id="archive-visit", instance_id="one",
        world_id="world-one", source_id="generator-a")
    second = installer.install_registered("archive-visit", "two", "world-one")
    assert first.characters[0].agent_id != second.characters[0].agent_id
    assert first.locations[0].instance_id != second.locations[0].instance_id
    assert world.environment[first.locations[0].mechanism_ids[0]].door_id != world.environment[second.locations[0].mechanism_ids[0]].door_id
    assert cognition.get_goal(first.characters[0].agent_id + ":goal:0").owner_id == first.characters[0].agent_id
    assert cognition.get_goal(second.characters[0].agent_id + ":goal:0").owner_id == second.characters[0].agent_id
    assert agents.get(first.characters[0].agent_id) is not None
    assert registry.character("curator").goal_descriptions == ("open the archive door",)
    receipt = world.facts[installation_record_key("world-one", "one")]
    assert receipt.status == "ready" and receipt.source_id == "generator-a"
    assert receipt.proposal_digest is not None and len(receipt.proposal_digest) == 64
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(first)
    lifecycle.register(second)
    lifecycle.enter(lifecycle.propose_entry(first.instance_id, first.characters[0].agent_id))
    assert lifecycle.state(first.instance_id).phase is ScenarioPhase.ACTIVE
    assert lifecycle.state(second.instance_id).phase is ScenarioPhase.AVAILABLE
    assert registry.scenario("archive-visit") == item.scenarios[0]


def test_validation_provider_and_collision_fail_before_world_commit():
    world, cognition, agents, context, processor, registry, installer = installation_world()
    before = (dict(world.entities), dict(world.environment), dict(world.facts), len(context.event_history.get_events()))
    broken = GenerationProposal((), (), proposal().scenarios)
    with pytest.raises(ValueError):
        installer.install_proposal(broken, template_id="archive-visit", instance_id="bad",
            world_id="world-one", source_id="generator")
    class Offline:
        def generate(self):
            raise RuntimeError("provider offline")
    with pytest.raises(RuntimeError, match="offline"):
        installer.install_generated(Offline(), template_id="archive-visit", instance_id="offline",
            world_id="world-one", source_id="provider")
    assert (dict(world.entities), dict(world.environment), dict(world.facts), len(context.event_history.get_events())) == before
    assert registry._scenarios == {}
    first = installer.install_proposal(proposal(), template_id="archive-visit",
        instance_id="one", world_id="world-one", source_id="generator")
    after = len(context.event_history.get_events())
    with pytest.raises(ValueError, match="already exists"):
        installer.install_proposal(proposal(), template_id="archive-visit",
            instance_id="another", world_id="world-one", source_id="generator")
    with pytest.raises(ValueError):
        installer.install_registered("archive-visit", "one", "world-one")
    assert len(context.event_history.get_events()) == after
    assert registry.scenario("archive-visit") == proposal().scenarios[0]


def run_dynamic(goal, *, sight=True, manipulation=True):
    world, cognition, agents, context, processor, registry, installer = installation_world()
    initial = proposal(goal=goal)
    character = replace(initial.characters[0],
        sensory_capabilities=("sight",) if sight else (),
        physical_capabilities=("manual_manipulation", "locomotion") if manipulation else ("locomotion",))
    generated = replace(initial, characters=(character,))
    instance = installer.install_proposal(generated, template_id="archive-visit",
        instance_id="new", world_id="world-one", source_id="generator")
    actor = instance.characters[0].agent_id
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(instance)
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, actor))
    cognition_context = CognitionContext.from_character(
        ContentInstantiator.character_reference(instance.characters[0], cognition),
        cognition, MemoryStore(), observation_store=context.observation_store)
    runtime = SimulationRuntime(context, scheduler=context.event_scheduler,
        event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: cognition_context,
        agent_decision=AgentDecision())
    report = AutonomousWorldRunner(runtime).run(2)
    return instance, world, context, report


def test_dynamic_npc_uses_real_decision_resolution_and_observation():
    opening, open_world, open_context, open_report = run_dynamic("open the archive door")
    watching, watch_world, watch_context, watch_report = run_dynamic("keep watch quietly")
    assert opening.characters[0].agent_id == watching.characters[0].agent_id
    open_proposal = next(action.proposal for round_item in open_report.rounds
                         for action in round_item.agent_actions if action.proposal is not None)
    watch_proposal = next(action.proposal for round_item in watch_report.rounds
                          for action in round_item.agent_actions if action.proposal is not None)
    assert (open_proposal.action_type, open_proposal.method) != (watch_proposal.action_type, watch_proposal.method)
    assert open_world.environment[opening.locations[0].mechanism_ids[0]].is_open
    assert not watch_world.environment[watching.locations[0].mechanism_ids[0]].is_open
    actor = opening.characters[0].agent_id
    assert open_context.observation_store.get_by_observer(actor)
    assert any(event.type == "resolution" for event in open_context.event_history.get_events())


def test_model_proposal_only_enters_world_after_validation_and_installation():
    world, cognition, agents, context, processor, registry, installer = installation_world()
    adapter = LLMContentGenerator(ContentGenerationRequest("Archive", "Reusable room"),
        FakeTransport(json.dumps(document())))
    assert registry._scenarios == {}
    assert all("new" not in key for key in world.entities)
    instance = installer.install_generated(adapter, template_id="archive-visit",
        instance_id="new", world_id="world-one", source_id="model-adapter")
    assert world.get_entity(instance.characters[0].agent_id) is not None
    assert registry.scenario("archive-visit").template_id == "archive-visit"
    assert not any(event.type == "resolution" for event in context.event_history.get_events())
    assert not any(event.type == "runtime_content_installed" and event.changes[0].get("success")
                   for event in context.event_history.get_events())


def test_dynamic_observation_and_capability_are_real_constraints():
    seen, seen_world, seen_context, seen_report = run_dynamic("open the archive door")
    blind, blind_world, blind_context, blind_report = run_dynamic("open the archive door", sight=False)
    unskilled, unskilled_world, unskilled_context, unskilled_report = run_dynamic(
        "open the archive door", manipulation=False)
    assert seen_context.observation_store.get_by_observer(seen.characters[0].agent_id)
    assert blind_context.observation_store.get_by_observer(blind.characters[0].agent_id) == ()
    assert seen_world.environment[seen.locations[0].mechanism_ids[0]].is_open is True
    assert blind_world.environment[blind.locations[0].mechanism_ids[0]].is_open is False
    assert unskilled_world.environment[unskilled.locations[0].mechanism_ids[0]].is_open is False
    assert not any(event.type == "resolution" and event.changes[0].get("success") is True
                   and any(isinstance(effect, dict) and effect.get("effect_type") == "door_state_changed"
                           for effect in event.changes[1:])
                   for event in unskilled_context.event_history.get_events())


def run_dynamic_pair(*, swap_goals=False, reverse_registration=False):
    world, cognition, agents, context, processor, registry, installer = installation_world()
    base = proposal()
    opener = replace(base.characters[0], template_id="opener",
        goal_descriptions=("open the archive door",))
    watcher = replace(base.characters[0], template_id="watcher",
        goal_descriptions=("keep watch quietly",))
    character_refs = (("alpha", "watcher" if swap_goals else "opener", "hall"),
                      ("beta", "opener" if swap_goals else "watcher", "hall"))
    if reverse_registration:
        character_refs = tuple(reversed(character_refs))
    seed = replace(base.scenarios[0].event_seeds[0], participant_keys=())
    scenario = replace(base.scenarios[0], characters=character_refs, event_seeds=(seed,))
    generated = GenerationProposal((opener, watcher), base.locations, (scenario,))
    instance = installer.install_proposal(generated, template_id="archive-visit",
        instance_id="pair", world_id="world-one", source_id="generator")
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(instance)
    alpha = next(item for item in instance.characters if item.instance_id.endswith(":character:alpha"))
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, alpha.agent_id))
    memory = MemoryStore()
    cognition_contexts = {item.agent_id: CognitionContext.from_character(
        ContentInstantiator.character_reference(item, cognition), cognition, memory,
        observation_store=context.observation_store) for item in instance.characters}
    runtime = SimulationRuntime(context, scheduler=context.event_scheduler,
        event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: cognition_contexts[agent.agent_id],
        agent_decision=AgentDecision())
    report = AutonomousWorldRunner(runtime).run(1)
    return instance, world, context, report


def test_dynamic_agent_goals_not_ids_or_registration_order_drive_behavior():
    normal = run_dynamic_pair()
    swapped = run_dynamic_pair(swap_goals=True)
    reversed_order = run_dynamic_pair(reverse_registration=True)
    def summaries(run):
        return {item.agent_id: (item.proposal.action_type if item.proposal else None,
                                item.proposal.method if item.proposal else None,
                                item.status)
                for item in run[3].rounds[0].agent_actions}
    first, second, third = summaries(normal), summaries(swapped), summaries(reversed_order)
    assert set(first) == set(second) == set(third)
    assert first == third
    assert any(first[agent_id][:2] != second[agent_id][:2] for agent_id in first)
    assert any(event.type == "resolution" for event in normal[2].event_history.get_events())
    assert any(event.type == "resolution" for event in swapped[2].event_history.get_events())


def test_manual_installation_event_and_direct_world_write_are_rejected():
    world, cognition, agents, context, processor, registry, installer = installation_world()
    event = SystemEventFactory().create(event_id="unapproved-install",
        event_type="runtime_content_installed", timestamp="", simulation_tick=0,
        changes=[{"world_id": "world-one", "instance_id": "fake",
                  "template_id": "fake", "proposal_digest": None}])
    with pytest.raises(PermissionError):
        processor.dispatch(event)
    from cognitive_world.core.update import WorldUpdate
    with pytest.raises(PermissionError):
        world.apply_event(event, WorldUpdate("facts", "update", {"fake": True}))
    assert "fake" not in world.facts


def test_dynamic_seed_is_only_an_authorized_wakeup():
    world, cognition, agents, context, processor, registry, installer = installation_world()
    instance = installer.install_proposal(proposal(), template_id="archive-visit",
        instance_id="new", world_id="world-one", source_id="generator")
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(instance)
    actor = instance.characters[0].agent_id
    lifecycle.enter(lifecycle.propose_entry(instance.instance_id, actor))
    scheduler = ScenarioSeedScheduler(context, lifecycle)
    before = len(context.event_history.get_events())
    assert scheduler.poll(instance.instance_id) == ()
    assert len(context.event_history.get_events()) == before
    # No seed was promoted to a trusted Event merely because content entered.
    assert not any(event.type == "resolution" for event in context.event_history.get_events())


def test_post_world_provisioning_failure_is_explicit_and_not_runnable(monkeypatch):
    world, cognition, agents, context, processor, registry, installer = installation_world()
    def failed_owner_install(personality):
        raise RuntimeError("cognition unavailable")
    monkeypatch.setattr(cognition, "add_personality", failed_owner_install)
    with pytest.raises(RuntimeError, match="cognition unavailable"):
        installer.install_proposal(proposal(), template_id="archive-visit",
            instance_id="pending", world_id="world-one", source_id="generator")
    receipt = world.facts[installation_record_key("world-one", "pending")]
    assert receipt.status == "world_installed"
    assert scenario_state_key("world-one", "pending") not in world.facts
    assert agents.all_agents() == ()
    assert registry._scenarios == {}
    assert context.event_history.get_event(receipt.installation_event_id) is not None
    with pytest.raises(ValueError):
        installer.install_proposal(proposal(), template_id="archive-visit",
            instance_id="pending", world_id="world-one", source_id="generator")


def test_same_dynamic_template_two_instances_have_independent_world_outcomes():
    world, cognition, agents, context, processor, registry, installer = installation_world()
    first = installer.install_proposal(proposal(), template_id="archive-visit",
        instance_id="first", world_id="world-one", source_id="generator")
    second = installer.install_registered("archive-visit", "second", "world-one")
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(first)
    lifecycle.register(second)
    actor = first.characters[0].agent_id
    lifecycle.enter(lifecycle.propose_entry(first.instance_id, actor))
    owner_context = CognitionContext.from_character(
        ContentInstantiator.character_reference(first.characters[0], cognition),
        cognition, MemoryStore(), observation_store=context.observation_store)
    runtime = SimulationRuntime(context, scheduler=context.event_scheduler,
        event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: owner_context,
        agent_decision=AgentDecision())
    context.agent_scheduler.schedule_agent(actor, 1)
    runtime.step()
    assert world.environment[first.locations[0].mechanism_ids[0]].is_open is True
    assert world.environment[second.locations[0].mechanism_ids[0]].is_open is False
    assert lifecycle.state(second.instance_id).phase is ScenarioPhase.AVAILABLE
    assert any(event.type == "resolution" for event in context.event_history.get_events())
