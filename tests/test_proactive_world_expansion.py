"""Production Runtime integration for proposal-only proactive content expansion."""
from dataclasses import replace

import pytest

from cognitive_world.agent import AgentActionLoop, CognitionContext
from cognitive_world.cognition import MemoryStore
from cognitive_world.content import (
    ContentExpansionNeed, ContentGenerationRequest, ContentInstantiator,
    ProactiveContentExpansion, ScenarioLifecycle, ScenarioPhase,
    installation_record_key, scenario_state_key,
)
from cognitive_world.decision import AgentDecision
from cognitive_world.event.processor import EventProcessor
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler
from cognitive_world.runtime.runtime import SimulationRuntime

from test_reusable_world_content import proposal
from test_runtime_content_installation import installation_world


def expanded_proposal():
    base = proposal(goal="open the records-room door")
    character = replace(base.characters[0], template_id="records-witness")
    first_location = replace(base.locations[0], template_id="records-hall")
    second_location = replace(base.locations[1], template_id="records-room")
    scenario = replace(
        base.scenarios[0],
        template_id="records-access",
        description="A reusable records access scene",
        locations=(("hall", "records-hall"), ("archive", "records-room")),
        characters=(("curator", "records-witness", "hall"),),
    )
    return replace(base, characters=(character,),
                   locations=(first_location, second_location), scenarios=(scenario,))


class NeedPolicy:
    def __init__(self, *, needed=True):
        self.needed = needed
        self.seen = []

    def request_for(self, need: ContentExpansionNeed):
        self.seen.append(need)
        if not self.needed:
            return None
        return ContentGenerationRequest(
            "current world development",
            "Propose one reusable scene related to the cited development signal",
            tuple(f"source:{kind}:{ref}" for kind, ref in need.source_refs),
        )


class StaticGenerator:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def generate(self):
        self.calls += 1
        return self.value


def _runtime(*, need_policy=None, generated=None):
    world, cognition, agents, context, processor, registry, installer = installation_world()
    initial = installer.install_proposal(
        proposal(), template_id="archive-visit", instance_id="initial",
        world_id="world-one", source_id="test-setup",
    )
    lifecycle = ScenarioLifecycle(context, processor)
    lifecycle.register(initial)
    actor = initial.characters[0].agent_id
    lifecycle.enter(lifecycle.propose_entry(initial.instance_id, actor))
    scheduler = ConflictOpportunityScheduler()
    policy = need_policy or NeedPolicy()
    generator = StaticGenerator(expanded_proposal() if generated is None else generated)
    expansion = ProactiveContentExpansion(
        installer, lifecycle, world_id="world-one", scheduler=scheduler,
        need_policy=policy, generator_factory=lambda request: generator,
    )
    owner_context = CognitionContext.from_character(
        ContentInstantiator.character_reference(initial.characters[0], cognition),
        cognition, MemoryStore(), observation_store=context.observation_store,
    )
    runtime = SimulationRuntime(
        context, scheduler=context.event_scheduler, event_processor=processor,
        agent_action_loop=AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world)),
        cognition_context_provider=lambda agent: owner_context,
        agent_decision=AgentDecision(), conflict_opportunity_scheduler=scheduler,
        proactive_content_expansion=expansion,
    )
    return runtime, world, cognition, agents, context, processor, registry, installer, lifecycle, actor, policy, generator, expansion


def test_runtime_signal_generates_valid_content_and_installs_through_existing_authorities():
    (runtime, world, cognition, agents, context, processor, registry, installer,
     lifecycle, actor, policy, generator, expansion) = _runtime()
    runner = AutonomousWorldRunner(runtime)

    report = runner.run(1)

    assert report.rounds[0].agent_actions[0].event_committed
    assert runtime.last_agent_turn_results[0].scheduler_findings
    assert policy.seen and policy.seen[0].owner_id == actor
    assert policy.seen[0].source_refs
    result = runtime.last_content_expansion_results[0]
    assert result.status == "installed_new_templates"
    assert generator.calls == 1
    assert any(event.type == "runtime_content_installed" for event in context.event_history.get_events())
    assert any(event.type == "runtime_content_ready" for event in context.event_history.get_events())
    assert registry.scenario("records-access").template_id == "records-access"
    receipt = world.facts[installation_record_key("world-one", result.instance_id)]
    assert receipt.status == "ready"
    assert receipt.source_id.startswith("scheduler-finding:")
    assert receipt.source_refs == policy.seen[0].source_refs
    assert world.get_entity(f"world-one:{result.instance_id}:agent:curator") is not None
    assert agents.get(f"world-one:{result.instance_id}:agent:curator") is not None
    assert cognition.get_goal(f"world-one:{result.instance_id}:agent:curator:goal:0") is not None
    state = lifecycle.state(result.instance_id)
    assert state.phase is ScenarioPhase.AVAILABLE

    # The installed scenario can be entered through its existing lifecycle and
    # exposes its mechanism only through EventProcessor-issued observations.
    new_actor = f"world-one:{result.instance_id}:agent:curator"
    lifecycle.enter(lifecycle.propose_entry(result.instance_id, new_actor))
    observations = context.observation_store.get_by_observer(new_actor)
    assert observations
    assert all(item.has_trusted_provenance() for item in observations)
    assert scenario_state_key("world-one", result.instance_id) in world.facts


def test_no_content_need_does_not_call_generator_or_change_world():
    policy = NeedPolicy(needed=False)
    (runtime, world, _, _, context, _, registry, _, _, _, _, generator, _) = _runtime(need_policy=policy)
    before_entities = dict(world.entities)
    before_install_events = tuple(event.id for event in context.event_history.get_events()
                                  if event.type == "runtime_content_installed")

    AutonomousWorldRunner(runtime).run(1)

    assert runtime.last_content_expansion_results[0].status == "no_content_need"
    assert generator.calls == 0
    assert dict(world.entities) == before_entities
    assert tuple(event.id for event in context.event_history.get_events()
                 if event.type == "runtime_content_installed") == before_install_events
    assert registry._scenarios["archive-visit"].template_id == "archive-visit"


def test_duplicate_finding_reuses_installed_instance_without_regeneration():
    (runtime, world, _, _, _, _, _, _, _, _, _, generator, expansion) = _runtime()
    AutonomousWorldRunner(runtime).run(1)
    findings = runtime.last_agent_turn_results[0].scheduler_findings
    first = runtime.last_content_expansion_results[0]
    event_count = sum(event.type == "runtime_content_installed"
                      for event in runtime.context.event_history.get_events())
    # A new coordinator models a host-level retry/revisit in the same process;
    # the deterministic finding-derived instance key prevents another commit.
    lifecycle = expansion.lifecycle
    replacement = ProactiveContentExpansion(
        expansion.installer, lifecycle, world_id="world-one",
        scheduler=runtime.conflict_opportunity_scheduler,
        need_policy=NeedPolicy(), generator_factory=lambda request: generator,
    )
    same_need = tuple(item for item in findings if item.finding_id == first.finding_id)
    repeated = replacement.expand(same_need, simulation_tick=1)
    assert repeated[0].status == "already_installed"
    assert repeated[0].instance_id == first.instance_id
    assert generator.calls == 1
    assert sum(event.type == "runtime_content_installed"
               for event in runtime.context.event_history.get_events()) == event_count
    assert world.facts[installation_record_key("world-one", first.instance_id)].status == "ready"


def test_distinct_demand_can_reuse_exact_registered_templates():
    (runtime, _, _, _, _, _, registry, installer, lifecycle, _, policy,
     generator, expansion) = _runtime()
    AutonomousWorldRunner(runtime).run(1)
    findings = runtime.last_agent_turn_results[0].scheduler_findings
    first = runtime.last_content_expansion_results[0]
    remaining = tuple(item for item in findings if item.finding_id != first.finding_id)
    assert remaining
    reuse = ProactiveContentExpansion(
        installer, lifecycle, world_id="world-one",
        scheduler=runtime.conflict_opportunity_scheduler,
        need_policy=policy, generator_factory=lambda request: generator,
    )

    # This direct host invocation stands in for a Runtime-owned operation.
    # Its canonical stores are fenced once the Runtime has been assembled.
    with runtime.write_fence.operation():
        result = reuse.expand(remaining, simulation_tick=1)

    assert result[0].status == "installed_reused_templates"
    assert result[0].instance_id != first.instance_id
    assert registry.scenario("records-access") == expanded_proposal().scenarios[0]
    assert lifecycle.state(result[0].instance_id).phase is ScenarioPhase.AVAILABLE
    assert generator.calls == 2


def test_unissued_or_reconstructed_scheduler_signal_cannot_authorize_generation():
    (runtime, _, _, _, _, _, _, _, _, _, _, generator, expansion) = _runtime()
    AutonomousWorldRunner(runtime).run(1)
    finding = runtime.last_agent_turn_results[0].scheduler_findings[0]
    forged = replace(finding)
    assert forged == finding and forged is not finding
    with pytest.raises(PermissionError, match="not issued"):
        expansion.expand((forged,), simulation_tick=1)
    assert generator.calls == 1


def test_runtime_rejects_content_expander_bound_to_other_world_authorities():
    first = _runtime()
    second = _runtime()
    runtime, expansion = first[0], second[-1]
    with pytest.raises(ValueError, match="canonical content installer"):
        SimulationRuntime(
            runtime.context,
            conflict_opportunity_scheduler=expansion.scheduler,
            proactive_content_expansion=expansion,
        )


def test_invalid_generated_references_are_rejected_before_world_install():
    bad = expanded_proposal()
    bad_scenario = replace(bad.scenarios[0], locations=(("hall", "missing-location"),))
    policy = NeedPolicy()
    (runtime, world, _, _, context, _, registry, _, _, _, _, generator, _) = _runtime(
        need_policy=policy,
        generated=replace(bad, scenarios=(bad_scenario,)),
    )
    before_entities = dict(world.entities)
    before_installs = sum(event.type == "runtime_content_installed"
                          for event in context.event_history.get_events())

    AutonomousWorldRunner(runtime).run(1)

    result = runtime.last_content_expansion_results[0]
    assert result.status == "rejected"
    assert result.failure_type == "ValueError"
    assert generator.calls == 1
    assert dict(world.entities) == before_entities
    assert sum(event.type == "runtime_content_installed"
               for event in context.event_history.get_events()) == before_installs
    assert "records-access" not in registry._scenarios


def test_post_world_commit_failure_is_visible_and_never_reapplied(monkeypatch):
    (runtime, world, cognition, _, context, _, _, installer, _, _, policy,
     generator, expansion) = _runtime()
    def fail_cognition(_personality):
        raise RuntimeError("cognition provisioning unavailable")
    monkeypatch.setattr(cognition, "add_personality", fail_cognition)

    AutonomousWorldRunner(runtime).run(1)

    result = runtime.last_content_expansion_results[0]
    assert result.status == "recovery_required"
    assert result.failure_type == "RuntimeError"
    record = world.facts[installation_record_key("world-one", result.instance_id)]
    assert record.status == "world_installed"
    installed_event_count = sum(event.id == record.installation_event_id
                                for event in context.event_history.get_events())
    assert installed_event_count == 1
    finding = runtime.last_agent_turn_results[0].scheduler_findings
    replacement = ProactiveContentExpansion(
        installer, expansion.lifecycle, world_id="world-one",
        scheduler=runtime.conflict_opportunity_scheduler,
        need_policy=policy, generator_factory=lambda request: generator,
    )
    repeated = replacement.expand(finding, simulation_tick=1)
    assert repeated[0].status == "recovery_required"
    assert sum(event.id == record.installation_event_id
               for event in context.event_history.get_events()) == 1
