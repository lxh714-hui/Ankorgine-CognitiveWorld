"""Phase 13 content contracts against the real Phase 12 runtime boundaries."""
from dataclasses import FrozenInstanceError
import pytest

from cognitive_world.agent import AgentActionLoop, CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.content import (
    CharacterTemplate, ContentInstantiator, ContentRegistry, ContentValidator,
    EventSeed, GenerationProposal, LocationTemplate, MechanismTemplate,
    ScenarioTemplate, observed_seed_opportunities,
)
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.observation.observation import Observation
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.safety.governance import UniversalSafetyGovernance


def proposal(*, branch=True, goal="open the archive door"):
    return GenerationProposal(
        characters=(CharacterTemplate("curator", "A curator with an archive goal", (goal,),
                                      ("sight",), ("manual_manipulation", "locomotion")),),
        locations=(
            LocationTemplate("hall", "A hall with a closable archive door", (
                MechanismTemplate("archive-door", "door"),
                MechanismTemplate("route", "passage", "archive"),
            )),
            LocationTemplate("archive", "A room behind the hall"),
        ),
        scenarios=(ScenarioTemplate(
            "archive-visit", "Explore the archive access route",
            (("hall", "hall"), ("archive", "archive")),
            (("curator", "curator", "hall"),),
            "hall", ("archive",),
            (EventSeed("opened", "door_open", True, ("curator",),
                       ("archive access becomes possible",), 0.8),),
            branch, ("opened",) if branch else (),
        ),),
    )


def registry(item=None):
    result = ContentRegistry(ContentValidator(UniversalSafetyGovernance()))
    result.register(proposal() if item is None else item)
    return result


def install(reg, instance_id="first", *, world=None, cognition=None, agents=None):
    world = WorldState() if world is None else world
    cognition = CognitionContainer() if cognition is None else cognition
    agents = AgentRegistry() if agents is None else agents
    instance = ContentInstantiator(reg).instantiate(
        "archive-visit", instance_id, "world-one", world=world,
        cognition=cognition, agents=agents,
    )
    return instance, world, cognition, agents


def test_templates_are_reusable_and_runtime_instances_do_not_share_state():
    reg = registry()
    first, world, cognition, agents = install(reg)
    second, _, _, _ = install(reg, "second", world=world, cognition=cognition, agents=agents)
    assert first.locations[0].instance_id != second.locations[0].instance_id
    assert first.characters[0].agent_id != second.characters[0].agent_id
    assert cognition.get_goal(first.characters[0].agent_id + ":goal:0").owner_id == first.characters[0].agent_id
    assert cognition.get_goal(second.characters[0].agent_id + ":goal:0").owner_id == second.characters[0].agent_id
    first_door = first.locations[0].mechanism_ids[0]
    second_door = second.locations[0].mechanism_ids[0]
    assert first_door != second_door
    assert world.environment[first_door].door_id == first_door
    assert world.environment[second_door].door_id == second_door
    assert reg.character("curator").goal_descriptions == ("open the archive door",)
    with pytest.raises(ValueError):
        install(reg, "first", world=world, cognition=cognition, agents=agents)


def test_meaningless_branch_and_broken_references_are_rejected():
    base = proposal()
    bad = ScenarioTemplate("empty-branch", "Decorative errand",
        base.scenarios[0].locations, base.scenarios[0].characters,
        "hall", ("archive",), side_branch=True)
    with pytest.raises(ValueError, match="meaningless"):
        registry(GenerationProposal(base.characters, base.locations, (bad,)))
    broken = ScenarioTemplate("broken", "An inaccessible room",
        (("hall", "absent"),), (), "hall", ("hall",))
    with pytest.raises(ValueError, match="LocationTemplate"):
        registry(GenerationProposal(base.characters, base.locations, (broken,)))
    wrong_hook = EventSeed("hook", "door_open", True, (), ("possible result",), 0.4, ("missing",))
    scenario = ScenarioTemplate("bad-hook", "A dangling hook",
        base.scenarios[0].locations, base.scenarios[0].characters,
        "hall", ("archive",), (wrong_hook,))
    with pytest.raises(ValueError, match="follow-up"):
        registry(GenerationProposal(base.characters, base.locations, (scenario,)))


def test_branch_cannot_claim_value_from_an_empty_seed_and_templates_are_frozen():
    base = proposal()
    empty_seed = EventSeed("hollow", "door_open", True, (), (), 0.1)
    scenario = ScenarioTemplate("hollow-branch", "A detached errand",
        base.scenarios[0].locations, base.scenarios[0].characters,
        "hall", ("archive",), (empty_seed,), True, ("hollow",))
    with pytest.raises(ValueError, match="meaningless"):
        registry(GenerationProposal(base.characters, base.locations, (scenario,)))
    with pytest.raises(FrozenInstanceError):
        base.characters[0].description = "changed after registration"


def test_runtime_initialization_seals_content_installation():
    reg = registry()
    first, world, cognition, agents = install(reg)
    processor = EventProcessor(world_state=world)
    door_id = first.locations[0].mechanism_ids[0]
    processor.dispatch(SystemEventFactory().create(
        event_id="initial-door", event_type="environment_state_observed",
        timestamp="init", changes=[{"environment_id": door_id}], simulation_tick=0,
    ))
    with pytest.raises(PermissionError):
        install(reg, "later", world=world, cognition=cognition, agents=agents)


def test_generator_output_is_rejected_before_registration_when_branch_is_empty():
    base = proposal()
    empty = ScenarioTemplate("empty", "Decorative filler",
        base.scenarios[0].locations, base.scenarios[0].characters,
        "hall", ("archive",), side_branch=True)

    class ProposedGenerator:
        def generate(self):
            return GenerationProposal(base.characters, base.locations, (empty,))

    target = ContentRegistry(ContentValidator(UniversalSafetyGovernance()))
    with pytest.raises(ValueError, match="meaningless"):
        target.register_generated(ProposedGenerator())
    with pytest.raises(KeyError):
        target.scenario("empty")


def test_template_can_be_deployed_into_distinct_worlds_without_copied_cognition():
    reg = registry()
    first, first_world, first_cognition, _ = install(reg)
    second_world = WorldState()
    second_cognition = CognitionContainer()
    second = ContentInstantiator(reg).instantiate("archive-visit", "first", "world-two",
        world=second_world, cognition=second_cognition, agents=AgentRegistry())
    assert first.characters[0].agent_id != second.characters[0].agent_id
    assert first_cognition.get_goal(first.characters[0].agent_id + ":goal:0").owner_id != second_cognition.get_goal(second.characters[0].agent_id + ":goal:0").owner_id
    first_world.get_entity(first.characters[0].agent_id).state["injury"] = "minor"
    assert second_world.get_entity(second.characters[0].agent_id).state == {}
    assert reg.character("curator").description == "A curator with an archive goal"


def test_scenario_provides_existing_passage_affordance_state():
    instance, world, _, _ = install(registry())
    passage = world.environment[instance.locations[0].mechanism_ids[1]]
    assert passage.source_location_id == instance.entry_location_id
    assert passage.destination_location_id == instance.exit_location_ids[0]
    assert passage.traversable is True
    actor = instance.characters[0].agent_id
    assert instance.contains_actor(world, actor)
    assert not instance.at_exit(world, actor)
    assert not instance.contains_actor(world, "unknown-actor")


def test_seed_requires_real_observation_and_does_not_create_event():
    reg = registry()
    instance, world, cognition, agents = install(reg)
    history = EventHistory()
    observations = ObservationStore()
    clock = SimulationClock()
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=agents, observation_store=observations)
    actor = instance.characters[0].agent_id
    assert observed_seed_opportunities(instance, actor, history=history, observations=observations) == ()
    door_id = instance.locations[0].mechanism_ids[0]
    evidence = processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id="door-initial", event_type="environment_state_observed",
        timestamp="init", changes=[{"environment_id": door_id}], simulation_tick=0,
    ))
    observations.add(Observation("handmade", actor, "door-initial", evidence.observable_facts[0]))
    assert observed_seed_opportunities(instance, actor, history=history, observations=observations) == ()
    assert len(history.get_events()) == 1


def _run_content_world(goal="open the archive door"):
    reg = registry(proposal(goal=goal))
    instance, world, cognition, agents = install(reg)
    memory = MemoryStore()
    observations = ObservationStore()
    history = EventHistory()
    clock = SimulationClock()
    scheduler = EventScheduler()
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=agents, observation_store=observations)
    context = RuntimeContext(clock, world, history, event_scheduler=scheduler,
        agent_scheduler=AgentScheduler(), agent_registry=agents,
        observation_store=observations)
    actor = instance.characters[0].agent_id
    cognition_context = CognitionContext.from_character(
        ContentInstantiator.character_reference(instance.characters[0], cognition),
        cognition, memory, observation_store=observations)
    runtime = SimulationRuntime(context, scheduler=scheduler, event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: cognition_context,
        agent_decision=AgentDecision())
    door_id = instance.locations[0].mechanism_ids[0]
    processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id="door-state", event_type="environment_state_observed",
        timestamp="init", changes=[{"environment_id": door_id}], simulation_tick=0,
    ))
    report = AutonomousWorldRunner(runtime).run(2)
    return instance, world, history, observations, report


def test_content_instantiated_door_enters_real_autonomous_resolution_and_seed_stays_hook():
    instance, world, history, observations, report = _run_content_world()
    actor = instance.characters[0].agent_id
    door_id = instance.locations[0].mechanism_ids[0]
    assert world.environment[door_id].is_open is True
    assert any(action.proposal and action.proposal.candidates
               for round_report in report.rounds for action in round_report.agent_actions)
    assert any(event.type == "resolution" for event in history.get_events())
    before = len(history.get_events())
    opportunities = observed_seed_opportunities(instance, actor, history=history, observations=observations)
    assert any(hook.seed_id == "opened" and hook.observer_id == actor for hook in opportunities)
    assert observed_seed_opportunities(instance, "other-agent", history=history, observations=observations) == ()
    assert len(history.get_events()) == before


def test_same_instance_identity_with_different_goal_changes_proposal_and_result():
    opened, open_world, _, _, open_report = _run_content_world("open the archive door")
    watching, watch_world, _, _, watch_report = _run_content_world("keep watch quietly")
    assert opened.characters[0].agent_id == watching.characters[0].agent_id
    open_proposal = next(action.proposal for round_item in open_report.rounds
                         for action in round_item.agent_actions if action.proposal is not None)
    watch_proposal = next(action.proposal for round_item in watch_report.rounds
                          for action in round_item.agent_actions if action.proposal is not None)
    assert open_proposal.action_type != watch_proposal.action_type or open_proposal.method != watch_proposal.method
    assert open_world.environment[opened.locations[0].mechanism_ids[0]].is_open is True
    assert watch_world.environment[watching.locations[0].mechanism_ids[0]].is_open is False
