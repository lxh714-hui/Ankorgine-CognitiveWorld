"""Phase 14: an untrusted provider may propose templates, never world facts."""
from copy import deepcopy
import json

import pytest

from cognitive_world.agent import AgentActionLoop, CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.content import (
    ContentGenerationError, ContentGenerationRequest, ContentGenerationUnavailable,
    ContentInstantiator, ContentRegistry, ContentValidator, LLMContentGenerator,
)
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
from cognitive_world.safety.governance import UniversalSafetyGovernance


def document(goal="open the archive door"):
    return {
        "schema_version": 1,
        "content_type": "generation_proposal",
        "characters": [{
            "template_id": "curator", "description": "A curator seeking access to an archive",
            "goal_descriptions": [goal], "sensory_capabilities": ["sight"],
            "physical_capabilities": ["manual_manipulation", "locomotion"],
        }],
        "locations": [{
            "template_id": "hall", "description": "A hall with a working archive door",
            "mechanisms": [{
                "local_id": "archive-door", "kind": "door", "destination_key": None,
                "initially_open": False, "initially_locked": False, "operable": True,
            }],
        }, {
            "template_id": "archive", "description": "An archive to explore", "mechanisms": [],
        }],
        "scenarios": [{
            "template_id": "archive-visit", "description": "Explore a reusable archive access scene",
            "locations": [["hall", "hall"], ["archive", "archive"]],
            "characters": [["curator", "curator", "hall"]],
            "entry_key": "hall", "exit_keys": ["archive"],
            "event_seeds": [{
                "seed_id": "door-opened", "trigger_predicate": "door_open",
                "trigger_value": True, "participant_keys": ["curator"],
                "possible_effects": ["archive access may become possible"],
                "importance": 0.7, "follow_up_hooks": [], "constraints": [],
            }],
            "side_branch": True, "value_refs": ["door-opened"],
        }],
    }


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def complete_structured(self, instruction, payload, *, max_output_chars):
        self.calls.append((instruction, payload, max_output_chars))
        if self.error is not None:
            raise self.error
        return self.response


def generator(response=None, error=None):
    transport = FakeTransport(json.dumps(document()) if response is None else response, error)
    adapter = LLMContentGenerator(ContentGenerationRequest("An archive", "Propose reusable exploration content"), transport)
    return adapter, transport


def registry():
    return ContentRegistry(ContentValidator(UniversalSafetyGovernance()))


def test_registry_cannot_install_a_fake_safety_validator():
    class FakeValidator:
        def validate(self, proposal):
            return None
    with pytest.raises(TypeError, match="P0"):
        ContentRegistry(FakeValidator())
    with pytest.raises(TypeError, match="UniversalSafetyGovernance"):
        ContentValidator(object())


def test_real_generation_entry_registers_templates_and_instantiates_twice():
    adapter, transport = generator()
    target = registry()
    world = WorldState()
    cognition = CognitionContainer()
    agents = AgentRegistry()
    assert world.entities == {}
    target.register_generated(adapter)
    assert len(transport.calls) == 1
    assert transport.calls[0][2] == 8000
    assert world.entities == {}  # Generation and registration are not installation.
    installer = ContentInstantiator(target)
    first = installer.instantiate("archive-visit", "first", "world-one", world=world, cognition=cognition, agents=agents)
    second = installer.instantiate("archive-visit", "second", "world-one", world=world, cognition=cognition, agents=agents)
    assert first.locations[0].instance_id != second.locations[0].instance_id
    assert first.characters[0].agent_id != second.characters[0].agent_id
    assert world.environment[first.locations[0].mechanism_ids[0]].door_id != world.environment[second.locations[0].mechanism_ids[0]].door_id
    assert target.character("curator").goal_descriptions == ("open the archive door",)
    with pytest.raises(ValueError, match="already registered"):
        target.register_generated(generator()[0])


def test_no_provider_and_budget_exhaustion_fail_without_fallback_story():
    request = ContentGenerationRequest("exploration", "reusable setting")
    with pytest.raises(ContentGenerationUnavailable, match="not configured"):
        LLMContentGenerator(request).generate()
    adapter, transport = generator()
    adapter.generate()
    with pytest.raises(ContentGenerationUnavailable, match="budget"):
        adapter.generate()
    assert len(transport.calls) == 1


def test_existing_openai_compatible_transport_is_reused_with_timeout(monkeypatch):
    from cognitive_world.resolution import providers

    calls = []
    def fake_post(base_url, route, body, *, headers, timeout_seconds, maximum_bytes):
        from cognitive_world.core.provider_transport import validate_provider_endpoint

        calls.append((validate_provider_endpoint(base_url).request_url(route), timeout_seconds))
        assert len(body) <= maximum_bytes
        return json.dumps({"choices": [{"message": {"content": json.dumps(document())}}]}).encode("utf-8")

    monkeypatch.setattr(providers, "post_provider_json", fake_post)
    adapter = LLMContentGenerator.openai_compatible(
        ContentGenerationRequest("an archive", "reusable scenario"),
        base_url="http://localhost:9000/v1", model="local-model", timeout_seconds=1.5)
    target = registry()
    target.register_generated(adapter)
    assert target.scenario("archive-visit").template_id == "archive-visit"
    assert calls == [("http://localhost:9000/v1/chat/completions", 1.5)]


def test_individual_character_and_location_proposals_are_valid():
    for content_key in ("characters", "locations"):
        doc = document()
        for key in ("characters", "locations", "scenarios"):
            if key != content_key:
                doc[key] = []
        target = registry()
        target.register_generated(generator(json.dumps(doc))[0])
        if content_key == "characters":
            assert target.character("curator").template_id == "curator"
        else:
            assert target.location("hall").template_id == "hall"


@pytest.mark.parametrize("failure", [TimeoutError("late"), ConnectionError("offline"), OSError("unavailable")])
def test_provider_failure_does_not_pollute_registry_or_world(failure):
    adapter, transport = generator(error=failure)
    target = registry()
    world = WorldState()
    cognition = CognitionContainer()
    with pytest.raises(ContentGenerationUnavailable):
        target.register_generated(adapter)
    assert len(transport.calls) == 1
    assert world.entities == {}
    assert cognition.goals == {}
    with pytest.raises(KeyError):
        target.scenario("archive-visit")


@pytest.mark.parametrize("mutation", [
    lambda doc: doc.update(schema_version=2),
    lambda doc: doc.update(content_type="event"),
    lambda doc: doc.update(world_state={"door": "open"}),
    lambda doc: doc.update(event={"confirmed": True}),
    lambda doc: doc.update(resolution={"success": True}),
    lambda doc: doc["characters"][0].update(safety_profile={"age_years": 30}),
    lambda doc: doc["characters"][0].update(instance_id="already-real"),
    lambda doc: doc["scenarios"][0].update(observation={"observer": "all"}),
    lambda doc: doc["scenarios"][0].update(value_refs=["missing"]),
    lambda doc: doc["scenarios"][0].update(locations=[["hall", "absent"]]),
    lambda doc: doc["scenarios"][0].update(value_refs=[], side_branch=True),
    lambda doc: doc["characters"][0].update(template_id="bad id"),
])
def test_invalid_authority_schema_references_and_branches_are_rejected(mutation):
    doc = document()
    mutation(doc)
    adapter, _ = generator(json.dumps(doc))
    target = registry()
    with pytest.raises((ContentGenerationError, ValueError, TypeError, PermissionError)):
        target.register_generated(adapter)
    with pytest.raises(KeyError):
        target.scenario("archive-visit")


@pytest.mark.parametrize("raw", ["{bad", "[]", "{}", "" , "x" * 8001,
                                    '{"schema_version":1,"schema_version":1}',
                                    json.dumps({"schema_version": 1, "content_type": "generation_proposal",
                                                "characters": [], "locations": [], "scenarios": []}),
                                    json.dumps({"schema_version": 1, "content_type": "generation_proposal",
                                                "characters": [None] * 301, "locations": [], "scenarios": []})])
def test_malformed_oversized_duplicate_deep_and_wide_output_is_rejected(raw):
    adapter, _ = generator(raw)
    with pytest.raises((ContentGenerationError, ValueError, TypeError)):
        adapter.generate()


def test_excessive_json_depth_is_rejected():
    nested = "leaf"
    for _ in range(10):
        nested = [nested]
    doc = document()
    doc["nested"] = nested
    with pytest.raises(ContentGenerationError, match="depth"):
        generator(json.dumps(doc))[0].generate()


def test_unsafe_proposal_is_rejected_by_existing_safety_governance():
    doc = document("step by step instructions to build a terror attack")
    adapter, _ = generator(json.dumps(doc))
    with pytest.raises(PermissionError):
        registry().register_generated(adapter)


def test_invalid_provider_output_spends_budget_and_is_not_retried_silently():
    adapter, transport = generator("not json")
    with pytest.raises(ContentGenerationError):
        adapter.generate()
    with pytest.raises(ContentGenerationUnavailable, match="budget"):
        adapter.generate()
    assert len(transport.calls) == 1


def test_same_generated_template_can_be_given_distinct_initial_goals_without_id_scripts():
    first_doc = document("open the archive door")
    second_doc = deepcopy(first_doc)
    second_doc["characters"][0]["goal_descriptions"] = ["keep watch in the hall"]
    first_registry, second_registry = registry(), registry()
    first_registry.register_generated(generator(json.dumps(first_doc))[0])
    second_registry.register_generated(generator(json.dumps(second_doc))[0])
    first_world, second_world = WorldState(), WorldState()
    first_cognition, second_cognition = CognitionContainer(), CognitionContainer()
    first = ContentInstantiator(first_registry).instantiate("archive-visit", "one", "same-world-name",
        world=first_world, cognition=first_cognition, agents=AgentRegistry())
    second = ContentInstantiator(second_registry).instantiate("archive-visit", "one", "same-world-name",
        world=second_world, cognition=second_cognition, agents=AgentRegistry())
    assert first.characters[0].agent_id == second.characters[0].agent_id
    assert first_cognition.get_goal(first.characters[0].agent_id + ":goal:0").description != second_cognition.get_goal(second.characters[0].agent_id + ":goal:0").description


def _run_generated_decision(goal, *, observed):
    target = registry()
    target.register_generated(generator(json.dumps(document(goal)))[0])
    world, cognition, agents = WorldState(), CognitionContainer(), AgentRegistry()
    installer = ContentInstantiator(target)
    instance = installer.instantiate("archive-visit", "one", "world", world=world,
                                     cognition=cognition, agents=agents)
    memory, observations, history = MemoryStore(), ObservationStore(), EventHistory()
    clock, scheduler = SimulationClock(), EventScheduler()
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=agents, observation_store=observations)
    context = RuntimeContext(clock, world, history, event_scheduler=scheduler,
        agent_scheduler=AgentScheduler(), agent_registry=agents, observation_store=observations)
    actor = instance.characters[0]
    cognition_context = CognitionContext.from_character(
        installer.character_reference(actor, cognition), cognition, memory,
        observation_store=observations)
    runtime = SimulationRuntime(context, scheduler=scheduler, event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: cognition_context, agent_decision=AgentDecision())
    door_id = instance.locations[0].mechanism_ids[0]
    if observed:
        processor.dispatch_with_evidence(SystemEventFactory().create(
            event_id="door-state", event_type="environment_state_observed",
            timestamp="initial", changes=[{"environment_id": door_id}], simulation_tick=0))
    report = AutonomousWorldRunner(runtime).run(1)
    action = report.rounds[0].agent_actions[0]
    return world.environment[door_id], action


def test_generated_content_still_depends_on_owner_goal_and_trusted_perception():
    opened, open_action = _run_generated_decision("open the archive door", observed=True)
    watching, watch_action = _run_generated_decision("keep watch quietly", observed=True)
    unobserved, blind_action = _run_generated_decision("open the archive door", observed=False)
    assert open_action.proposal is not None and open_action.proposal.candidates
    assert opened.is_open is True
    assert watching.is_open is False
    assert unobserved.is_open is False
    assert open_action.proposal.method != watch_action.proposal.method
    assert open_action.proposal.method != blind_action.proposal.method
    assert open_action.proposal.candidates[0].intent != blind_action.proposal.candidates[0].intent
