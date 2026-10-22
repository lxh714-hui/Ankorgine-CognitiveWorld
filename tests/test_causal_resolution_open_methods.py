import pytest
import json
from dataclasses import replace
from urllib.error import URLError

from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.core.entity import Entity
from cognitive_world.core.passage import PassageState
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine
from cognitive_world.resolution.causal import ActionInterpreter, MethodBasedResolutionEngine
from cognitive_world.resolution.causal import (
    AssessmentStatus,
    CausalAssessment,
    CausalReasoningAdvice,
    CausalWorldContext,
)
from cognitive_world.resolution.providers import OpenAICompatibleCausalProvider
from cognitive_world.resolution.provider_budget import provider_call_scope
from cognitive_world.resolution.stepwise import (
    PlannedStep,
    StepProgressStatus,
    StepwisePlanExecutor,
    StepwiseProgress,
)
from cognitive_world.runtime.clock import SimulationClock


def _route_world(two_routes=False):
    world = WorldState()
    world.load_environment_data("route-1", PassageState("route-1", "A", "B", True))
    if two_routes:
        world.load_environment_data("route-2", PassageState("route-2", "B", "C", True))
    world.load_entity(Entity(
        "agent-a", "character", sensory_capabilities=("sight",),
        physical_capabilities=("locomotion",),
    ))
    world.load_location("agent-a", "A")
    return world


def test_non_door_open_method_runs_through_resolution_event_observation_and_perception():
    world = _route_world()
    clock = SimulationClock(5)
    proposal = ActionProposal(
        "move-proposal", "agent-a", "reach the other side", ["route-1"],
        {"method": "I successfully walk through route-1; the guard runs away"},
    )
    attempt = ActionPipeline().create_attempt(proposal)
    flow = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world), world_state=world)
    event = flow.execute(attempt, action_proposal_id=proposal.proposal_id, simulation_tick=clock.capture())
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a"))
    observations = ObservationStore()
    processor = EventProcessor(
        event_history=EventHistory(), world_state=world, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
    )

    processor.dispatch_with_evidence(event)

    assert world.locations["agent-a"] == "B"
    assert len(event.changes) == 2
    assert event.changes[1]["effect_type"] == "actor_location_changed"
    assert "guard" not in str(event.changes[1]).casefold()
    authorized = observations.get_by_observer("agent-a")
    assert len(authorized) == 1
    assert authorized[0].has_trusted_provenance()
    cognition = CognitiveRuntime().process("agent-a", authorized)
    assert f"percept:{authorized[0].observation_id}" in cognition.percept_ids
    with pytest.raises(PermissionError, match="initialization is closed"):
        world.load_location("agent-a", "elsewhere")


def test_unknown_passage_stays_unresolved_and_does_not_change_location():
    world = _route_world()
    clock = SimulationClock()
    proposal = ActionProposal("unknown-route", "agent-a", "move", ["missing"], {"method": "walk"})
    attempt = ActionInterpreter().interpret(proposal, actor_id="agent-a")
    result = MethodBasedResolutionEngine(world, simulation_time=clock.capture()).resolve(attempt)
    assert result.confirmed is False
    assert result.outcome == "unresolved"
    assert world.locations["agent-a"] == "A"


def test_failed_confirmed_resolution_cannot_apply_a_world_effect():
    world = _route_world()

    class InvalidEffectEngine(ResolutionEngine):
        def _adjudicate(self, attempt):
            return ResolutionDecision(False, "failed", world_effects=({
                "effect_type": "actor_location_changed",
                "passage_id": "route-1",
                "expected": PassageState("route-1", "A", "B", True),
                "actor_id": "agent-a",
                "expected_location": "A",
                "destination_location": "B",
            },))

    proposal = ActionProposal("failed-effect", "agent-a", "try move", ["route-1"], {"method": "walk"})
    attempt = ActionInterpreter().interpret(proposal, actor_id="agent-a")
    event = ActionResolutionFlow(InvalidEffectEngine(), world_state=world).execute(attempt)
    processor = EventProcessor(event_history=EventHistory(), world_state=world)

    with pytest.raises(PermissionError, match="failed Resolution"):
        processor.dispatch_with_evidence(event)

    assert world.locations["agent-a"] == "A"
    assert processor.event_history.get_events() == ()


def test_distinct_open_methods_can_reach_same_verified_passage_result():
    for index, method in enumerate(("walk through the route", "pass through the route")):
        world = _route_world()
        attempt = ActionInterpreter().interpret(
            ActionProposal(f"p{index}", "agent-a", "get across", ["route-1"], {"method": method}),
            actor_id="agent-a",
        )
        result = MethodBasedResolutionEngine(world, simulation_time=SimulationClock().capture()).resolve(attempt)
        assert result.confirmed is True
        assert result.success is True
        assert result.world_effects[0]["effect_type"] == "actor_location_changed"


def test_stepwise_plan_reloads_world_and_requires_trusted_observation_before_next_step():
    world = _route_world(two_routes=True)
    clock = SimulationClock(1)
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a"))
    observation_store = ObservationStore()
    history = EventHistory()
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        agent_registry=registry, observation_store=observation_store,
    )
    flow = ActionResolutionFlow(MethodBasedResolutionEngine(world), world_state=world)
    cognitive_runtime = CognitiveRuntime()
    executor = StepwisePlanExecutor(flow, processor, world, cognitive_runtime=cognitive_runtime)
    proposal = ActionProposal(
        "two-leg-plan", "agent-a", "reach C", ["route-1", "route-2"],
        {"steps": [
            {"method": "walk through route 1", "target": "route-1"},
            {
                "method": "traverse route 2",
                "target": "route-2",
                "condition": {
                    "predicate": "actor_arrived",
                    "value": "B",
                    "subject_ref": "agent-a",
                },
            },
        ]},
    )

    first = executor.advance(proposal, simulation_tick=clock.capture())
    assert first.progress.status is StepProgressStatus.WAITING_FOR_OBSERVATION
    assert world.locations["agent-a"] == "B"
    with pytest.raises(PermissionError, match="refreshed CognitionContext"):
        executor.advance(proposal, progress=first.progress, simulation_tick=clock.capture())
    empty_context = CognitionContext.from_character(
        Character("character-a", "agent-a", "personality-a"),
        CognitionContainer(), MemoryStore(), observation_store=ObservationStore(),
    )
    with pytest.raises(PermissionError, match="must be observed through the trusted perception path"):
        executor.advance(
            proposal, progress=first.progress, cognition_context=empty_context,
            simulation_tick=clock.capture(),
        )

    cognition_context = CognitionContext.from_character(
        Character("character-a", "agent-a", "personality-a"),
        CognitionContainer(), MemoryStore(), observation_store=observation_store,
    )
    prior_observation = cognition_context.get_observations()[0]
    assert prior_observation.observer_id == "agent-a"
    assert prior_observation.source_event_id == first.event.id
    assert prior_observation.has_trusted_provenance()
    assert prior_observation.content.source_event_id == first.event.id
    assert prior_observation.content.subject_ref == "agent-a"
    assert not cognitive_runtime.has_consumed_observation(
        "agent-a", prior_observation, source_event_id=first.event.id
    )
    assert not cognitive_runtime.has_consumed_observation(
        "agent-a", f"percept:{prior_observation.observation_id}",
        source_event_id=first.event.id,
    )
    assert not cognitive_runtime.has_consumed_observation(
        "agent-a", prior_observation, source_event_id="different-event"
    )
    # Another owner's call cannot create an actor-a L1 receipt.
    cognitive_runtime.process("agent-b", (prior_observation,))
    assert not cognitive_runtime.has_consumed_observation(
        "agent-a", prior_observation, source_event_id=first.event.id
    )
    assert not cognitive_runtime.has_consumed_observation(
        "agent-b", prior_observation, source_event_id=first.event.id
    )
    first_consumption = cognitive_runtime.process("agent-a", (prior_observation,))
    assert first_consumption.percept_ids == [f"percept:{prior_observation.observation_id}"]
    assert cognitive_runtime.has_consumed_observation(
        "agent-a", prior_observation, source_event_id=first.event.id
    )
    repeated_first = cognitive_runtime.process("agent-a", (prior_observation,))
    assert repeated_first.percept_ids == []
    assert cognitive_runtime.has_consumed_observation(
        "agent-a", prior_observation, source_event_id=first.event.id
    )
    # Replaying an old cursor returns the already committed event; it does not
    # apply the location transition twice or append duplicate history.
    replay = executor.advance(proposal, simulation_tick=clock.capture())
    assert replay.event is not None and replay.event.id == first.event.id
    assert world.locations["agent-a"] == "B"
    clock.tick()
    second = executor.advance(
        proposal, progress=replay.progress, cognition_context=cognition_context,
        simulation_tick=clock.capture(),
    )
    assert second.progress.status is StepProgressStatus.COMPLETE
    assert first.event is not None and second.event is not None
    assert world.locations["agent-a"] == "C"
    assert len(history.get_events()) == 2
    # The second confirmed movement has its own trusted Observation and is a
    # new L1 input; replaying the full set must then be idempotent for both.
    all_observations = cognition_context.get_observations()
    assert len(all_observations) == 2
    first_observation = next(
        item for item in all_observations if item.source_event_id == first.event.id
    )
    second_observation = next(
        item for item in all_observations if item.source_event_id == second.event.id
    )
    assert first_observation.observation_id == prior_observation.observation_id
    assert first_observation.source_event_id == first.event.id
    assert first_observation.has_trusted_provenance()
    assert first_observation.content.has_trusted_source(first.event)
    assert first_observation.content.value == "B"
    assert second_observation.observer_id == "agent-a"
    assert second_observation.source_event_id == second.event.id
    assert second_observation.observation_id != first_observation.observation_id
    assert second_observation.has_trusted_provenance()
    assert second_observation.content.has_trusted_source(second.event)
    assert second_observation.content.source_event_id == second.event.id
    assert second_observation.content.subject_ref == "agent-a"
    assert second_observation.content.value == "C"
    assert first.event.has_trusted_source("resolution")
    assert second.event.has_trusted_source("resolution")
    assert first.event.changes[1]["actor_id"] == second.event.changes[1]["actor_id"] == "agent-a"

    second_consumption = cognitive_runtime.process("agent-a", all_observations)
    assert second_consumption.percept_ids == [f"percept:{second_observation.observation_id}"]
    assert cognitive_runtime.has_consumed_observation(
        "agent-a", first_observation, source_event_id=first.event.id
    )
    assert cognitive_runtime.has_consumed_observation(
        "agent-a", second_observation, source_event_id=second.event.id
    )
    # The second step's Observation cannot stand in for the first Event's
    # observation, even though both are owned by the same Agent.
    assert not cognitive_runtime.has_consumed_observation(
        "agent-a", second_observation, source_event_id=first.event.id
    )
    second_only_store = ObservationStore()
    second_only_store.add(second_observation)
    second_only_context = CognitionContext.from_character(
        Character("character-a", "agent-a", "personality-a"),
        CognitionContainer(), MemoryStore(), observation_store=second_only_store,
    )
    with pytest.raises(PermissionError, match="must be observed through the trusted perception path"):
        executor.advance(
            proposal, progress=replay.progress, cognition_context=second_only_context,
            simulation_tick=clock.capture(),
        )

    repeated_all = cognitive_runtime.process("agent-a", all_observations)
    assert repeated_all.percept_ids == []
    assert cognitive_runtime.has_consumed_observation(
        "agent-a", first_observation, source_event_id=first.event.id
    )
    assert cognitive_runtime.has_consumed_observation(
        "agent-a", second_observation, source_event_id=second.event.id
    )
    # Replaying an authentic earlier cursor finds the same committed second
    # Event and cannot apply it a second time.
    replayed_second = executor.advance(
        proposal, progress=replay.progress, cognition_context=cognition_context,
        simulation_tick=clock.capture(),
    )
    assert replayed_second.event is not None and replayed_second.event.id == second.event.id
    assert world.locations["agent-a"] == "C"
    assert len(history.get_events()) == 2


def test_stepwise_false_observed_condition_stops_without_running_next_step():
    world = _route_world(two_routes=True)
    clock = SimulationClock(1)
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-a"))
    store = ObservationStore()
    processor = EventProcessor(
        event_history=EventHistory(), world_state=world, simulation_clock=clock,
        agent_registry=registry, observation_store=store,
    )
    executor = StepwisePlanExecutor(
        ActionResolutionFlow(MethodBasedResolutionEngine(world), world_state=world),
        processor,
        world,
        cognitive_runtime=CognitiveRuntime(),
    )
    proposal = ActionProposal(
        "condition-stop", "agent-a", "reach C", ["route-1", "route-2"],
        {"steps": [
            {"method": "walk through route 1", "target": "route-1"},
            {
                "method": "walk through route 2",
                "target": "route-2",
                "condition": {
                    "predicate": "actor_arrived",
                    "value": "C",
                    "subject_ref": "agent-a",
                },
            },
        ]},
    )
    first = executor.advance(proposal, simulation_tick=clock.capture())
    context = CognitionContext.from_character(
        Character("character-a", "agent-a", "personality-a"),
        CognitionContainer(), MemoryStore(), observation_store=store,
    )

    stopped = executor.advance(
        proposal, progress=first.progress, cognition_context=context,
        simulation_tick=clock.capture(),
    )

    assert stopped.progress.status is StepProgressStatus.FAILED
    assert stopped.event is None
    assert world.locations["agent-a"] == "B"
    assert len(processor.event_history.get_events()) == 1


def test_stepwise_progress_is_integrity_bound_and_proposal_is_not_mutated():
    class Provider:
        def __init__(self):
            self.calls = 0

        def interpret_attempt(self, proposal, *, max_output_chars):
            self.calls += 1
            return '{"method":"walk through the passage"}'

    world = _route_world()
    clock = SimulationClock(1)
    history = EventHistory()
    processor = EventProcessor(event_history=history, world_state=world, simulation_clock=clock)
    provider = Provider()
    executor = StepwisePlanExecutor(
        ActionResolutionFlow(MethodBasedResolutionEngine(world), world_state=world),
        processor,
        world,
        interpreter=ActionInterpreter(provider),
    )
    proposal = ActionProposal(
        "immutable-plan", "agent-a", "reach B", ["route-1"],
        {"steps": [{"method": "walk through route", "target": "route-1"}]},
    )
    original = {"steps": [{"method": "walk through route", "target": "route-1"}]}

    first = executor.advance(proposal, simulation_tick=clock.capture())

    assert proposal.parameters == original
    assert first.progress.provider_calls_used == 1
    assert provider.calls == 1
    # Lowering the signed count could otherwise recreate a provider call, so
    # use the complete, actually exercised budget as the tamper target.
    tampered = replace(first.progress, provider_calls_used=0)
    with pytest.raises(PermissionError, match="not issued intact"):
        executor.advance(proposal, progress=tampered, simulation_tick=clock.capture())
    assert provider.calls == 1
    # The genuine terminal cursor has an intact signature, but cannot resume.
    with pytest.raises(ValueError, match="not in a resumable state"):
        executor.advance(proposal, progress=first.progress, simulation_tick=clock.capture())
    altered_proposal = ActionProposal(
        proposal.proposal_id,
        proposal.agent_id,
        "different intent",
        proposal.target_refs,
        proposal.parameters,
    )
    with pytest.raises(PermissionError, match="does not match"):
        executor.advance(altered_proposal, progress=first.progress, simulation_tick=clock.capture())


def test_manually_constructed_stepwise_progress_cannot_skip_steps_or_budget():
    world = _route_world(two_routes=True)
    clock = SimulationClock()
    processor = EventProcessor(event_history=EventHistory(), world_state=world, simulation_clock=clock)
    executor = StepwisePlanExecutor(
        ActionResolutionFlow(MethodBasedResolutionEngine(world), world_state=world),
        processor,
        world,
    )
    proposal = ActionProposal(
        "forged-progress", "agent-a", "reach C", ["route-1", "route-2"],
        {"steps": ["walk through route 1", "walk through route 2"]},
    )
    forged = StepwiseProgress(
        proposal.proposal_id,
        proposal.agent_id,
        (PlannedStep("walk through route 1", "route-1"), PlannedStep("walk through route 2", "route-2")),
        next_step_index=1,
        provider_calls_used=0,
    )
    with pytest.raises(PermissionError, match="not issued intact"):
        executor.advance(proposal, progress=forged, simulation_tick=clock.capture())


def test_forged_complete_status_is_rejected_before_terminal_state_handling():
    world = _route_world(two_routes=True)
    clock = SimulationClock(1)
    processor = EventProcessor(event_history=EventHistory(), world_state=world, simulation_clock=clock)
    executor = StepwisePlanExecutor(
        ActionResolutionFlow(MethodBasedResolutionEngine(world), world_state=world),
        processor,
        world,
    )
    proposal = ActionProposal(
        "forged-complete", "agent-a", "reach C", ["route-1", "route-2"],
        {"steps": ["walk through route 1", "walk through route 2"]},
    )
    waiting = executor.advance(proposal, simulation_tick=clock.capture())
    assert waiting.progress.status is StepProgressStatus.WAITING_FOR_OBSERVATION
    forged_complete = replace(waiting.progress, status=StepProgressStatus.COMPLETE)
    with pytest.raises(PermissionError, match="not issued intact"):
        executor.advance(
            proposal, progress=forged_complete, simulation_tick=clock.capture()
        )


def test_stepwise_progress_is_bound_to_its_world_and_event_history():
    world = _route_world()
    clock = SimulationClock()
    processor = EventProcessor(event_history=EventHistory(), world_state=world, simulation_clock=clock)
    executor = StepwisePlanExecutor(
        ActionResolutionFlow(MethodBasedResolutionEngine(world), world_state=world),
        processor,
        world,
    )
    proposal = ActionProposal(
        "bound-progress", "agent-a", "reach B", ["route-1"],
        {"steps": ["walk through route"]},
    )
    first = executor.advance(proposal, simulation_tick=clock.capture())

    other_world = _route_world()
    other_processor = EventProcessor(event_history=EventHistory(), world_state=other_world, simulation_clock=clock)
    other_executor = StepwisePlanExecutor(
        ActionResolutionFlow(MethodBasedResolutionEngine(other_world), world_state=other_world),
        other_processor,
        other_world,
    )
    with pytest.raises(PermissionError, match="different runtime state"):
        other_executor.advance(proposal, progress=first.progress, simulation_tick=clock.capture())


def test_stepwise_provider_budget_survives_failed_call_without_returned_progress():
    class Provider:
        def __init__(self):
            self.calls = 0

        def interpret_attempt(self, proposal, *, max_output_chars):
            self.calls += 1
            return '{"method":"walk through the passage"}'

    class OnceFailingEngine(MethodBasedResolutionEngine):
        failed_once = False

        def resolve(self, attempt):
            if not self.failed_once:
                self.failed_once = True
                raise RuntimeError("transient resolution failure")
            return super().resolve(attempt)

    world = _route_world()
    clock = SimulationClock()
    provider = Provider()
    processor = EventProcessor(event_history=EventHistory(), world_state=world, simulation_clock=clock)
    flow = ActionResolutionFlow(OnceFailingEngine(world_state=world), world_state=world)
    executor = StepwisePlanExecutor(flow, processor, world, interpreter=ActionInterpreter(provider))
    proposal = ActionProposal(
        "retry-budget", "agent-a", "reach B", ["route-1"],
        {"steps": [{"method": "walk route", "target": "route-1"}]},
    )

    with pytest.raises(RuntimeError, match="transient"):
        executor.advance(proposal, simulation_tick=clock.capture())
    completed = executor.advance(proposal, simulation_tick=clock.capture())

    assert provider.calls == 1
    assert completed.event is not None
    assert world.locations["agent-a"] == "B"


def test_action_only_model_schema_rejects_authority_fields_and_keeps_owner_local_actor():
    class Provider:
        def __init__(self, output):
            self.output = output

        def interpret_attempt(self, proposal, *, max_output_chars):
            return self.output

    proposal = ActionProposal("p", "agent-a", "try a new technique", ["route-1"], {})
    valid = ActionInterpreter(Provider('{"method":"walk through the route","target_refs":["route-1"]}')).interpret(
        proposal, actor_id="agent-a"
    )
    assert valid.agent_id == "agent-a"
    assert valid.parameters["method"] == "walk through the route"
    assert valid.target_refs == ["route-1"]
    conditional = ActionInterpreter(Provider(json.dumps({
        "steps": [{
            "method": "walk through route-1",
            "target": "route-1",
            "condition": {"predicate": "actor_arrived", "value": "B", "subject_ref": "agent-a"},
        }],
    }))).interpret(proposal, actor_id="agent-a")
    assert conditional.parameters["steps"][0]["condition"]["value"] == "B"
    for raw in (
        '{"success":true}',
        '{"npc_reactions":["flees"]}',
        '{"owner_id":"agent-b","method":"walk"}',
        '{"observed_facts":["route open"]}',
        '{"steps":[{"method":"walk","condition":{"predicate":"actor_arrived","value":"B","success":true}}]}',
    ):
        with pytest.raises(PermissionError):
            ActionInterpreter(Provider(raw)).interpret(proposal, actor_id="agent-a")
    with pytest.raises(PermissionError, match="does not match"):
        ActionInterpreter(Provider('{"method":"walk"}')).interpret(proposal, actor_id="agent-b")


def test_attempt_input_size_and_cycles_are_rejected_before_provider_use():
    class Provider:
        def interpret_attempt(self, proposal, *, max_output_chars):
            raise AssertionError("unbounded input must be rejected before a model call")

    oversized = ActionProposal("large", "agent-a", "move", ["route"], {"text": "x" * 1025})
    with pytest.raises(TypeError, match="bounded data values"):
        ActionInterpreter(Provider()).interpret(oversized, actor_id="agent-a")

    cyclic = {}
    cyclic["self"] = cyclic
    cyclic_proposal = ActionProposal("cycle", "agent-a", "move", ["route"], cyclic)
    with pytest.raises(TypeError, match="bounded data values"):
        ActionInterpreter(Provider()).interpret(cyclic_proposal, actor_id="agent-a")


def test_attempt_validation_accepts_reused_bounded_tuple_values():
    shared_empty = ()
    proposal = ActionProposal(
        "aliased-values", "agent-a", "inspect the unfamiliar mechanism", [],
        {
            "method": "use a bent copper strip to probe the unfamiliar mechanism",
            "tools": shared_empty,
            "required_capabilities": shared_empty,
            "preconditions": shared_empty,
        },
    )
    attempt = ActionInterpreter().interpret(proposal)
    assert attempt.parameters["method"].startswith("use a bent copper strip")


def test_provider_offline_falls_back_and_one_action_call_budget_is_shared():
    class Provider:
        def __init__(self):
            self.calls = 0

        def interpret_attempt(self, proposal, *, max_output_chars):
            self.calls += 1
            return '{"method":"walk through the passage"}'

        def suggest_missing_evidence(self, attempt, context):
            self.calls += 1
            return CausalReasoningAdvice(unknown_conditions=("route evidence",))

    provider = Provider()
    proposal = ActionProposal("budget", "agent-a", "move", ["unknown"], {})
    with provider_call_scope(1):
        attempt = ActionInterpreter(provider).interpret(proposal, actor_id="agent-a")
        result = MethodBasedResolutionEngine(
            world_state=_route_world(),
            simulation_time=SimulationClock().capture(),
            reasoning_provider=provider,
        ).resolve(attempt)
    assert result.confirmed is False
    assert provider.calls == 1

    class OfflineProvider:
        def interpret_attempt(self, proposal, *, max_output_chars):
            raise URLError("offline")

    fallback = ActionInterpreter(OfflineProvider()).interpret(proposal, actor_id="agent-a")
    assert fallback.parameters == proposal.parameters


def test_openai_compatible_provider_uses_bounded_json_chat_adapter(monkeypatch):
    import cognitive_world.resolution.providers as provider_module

    response_payload = json.dumps({
        "choices": [{"message": {"content": '{"method":"walk through the route"}'}}]
    }).encode("utf-8")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, maximum):
            assert len(response_payload) <= maximum
            return response_payload

    seen = {}

    def fake_post(base_url, route, body, *, headers, timeout_seconds, maximum_bytes):
        from cognitive_world.core.provider_transport import validate_provider_endpoint

        seen["url"] = validate_provider_endpoint(base_url).request_url(route)
        seen["timeout"] = timeout_seconds
        seen["headers"] = headers
        assert len(body) <= maximum_bytes
        return response_payload

    monkeypatch.setattr(provider_module, "post_provider_json", fake_post)
    provider = OpenAICompatibleCausalProvider("http://localhost:8000/v1", "local-model")
    raw = provider.interpret_attempt(
        ActionProposal("p", "agent-a", "move", ["route"], {}),
        max_output_chars=1024,
    )
    assert raw == '{"method":"walk through the route"}'
    assert seen["url"] == "http://localhost:8000/v1/chat/completions"
    assert seen["timeout"] <= 20

    response_payload = json.dumps({
        "choices": [{"message": {"content": json.dumps({
            "mechanisms": ["route traversal"],
            "required_conditions": ["known route"],
            "possible_effects": ["location change"],
            "unknown_conditions": ["current obstruction"],
            "side_effects": [],
        })}}]
    }).encode("utf-8")
    attempt = ActionInterpreter().interpret(
        ActionProposal("advice", "agent-a", "move", ["route-1"], {"method": "walk"}),
        actor_id="agent-a",
    )
    advice = provider.suggest_missing_evidence(
        attempt,
        CausalWorldContext("agent-a", "A", ("locomotion",), None, ()),
    )
    assert isinstance(advice, CausalReasoningAdvice)
    assert advice.unknown_conditions == ("current obstruction",)


def test_partial_resolution_status_is_distinct_from_unresolved():
    class PartialPolicy:
        def assess(self, attempt, context):
            return CausalAssessment(AssessmentStatus.PARTIALLY_FEASIBLE, "some effect confirmed")

    proposal = ActionProposal("partial", "agent-a", "try method", ["route-1"], {"method": "walk"})
    attempt = ActionInterpreter().interpret(proposal, actor_id="agent-a")
    result = MethodBasedResolutionEngine(
        world_state=_route_world(),
        assessment_policy=PartialPolicy(),
        simulation_time=SimulationClock().capture(),
    ).resolve(attempt)
    assert result.confirmed is True
    assert result.success is False
    assert result.outcome.startswith("partial:")
