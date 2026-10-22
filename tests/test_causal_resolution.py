import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.decision import ActionPipeline, ActionProposal
from cognitive_world.event import DoorResolutionHandler, EventProcessor
from cognitive_world.event.history import EventHistory
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution import (
    ActionInterpreter,
    AssessmentStatus,
    CausalWorldContext,
    DoorCausalAssessmentPolicy,
    MethodBasedResolutionEngine,
)
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.runtime.clock import SimulationClock


def _world(*, locked=False, location="door_contact", capabilities=("manual_manipulation",)):
    state = WorldState()
    state.load_environment_data(
        "door-1", DoorState("door-1", "door_contact", False, locked, True, "key-1")
    )
    state.load_entity(Entity("agent-1", "character", sensory_capabilities=("sight",), physical_capabilities=capabilities))
    state.load_location("agent-1", location)
    return state


def _attempt(method="push the closed door", **extra):
    params = {"method": method, **extra}
    proposal = ActionProposal("proposal-1", "agent-1", "enter the next room", ["door-1"], params)
    return ActionPipeline().create_attempt(proposal)


def test_unlocked_door_attempt_flows_through_resolution_processor_and_observation():
    state = _world()
    attempt = _attempt(expected_result="door opens and guard flees")
    clock = SimulationClock(9)
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=state), world_state=state
    ).execute(attempt, simulation_tick=clock.capture())
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-1"))
    observations = ObservationStore()
    processor = EventProcessor(
        event_history=EventHistory(), world_state=state, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
    )
    processor.register_handler("resolution", DoorResolutionHandler())

    processor.dispatch_with_evidence(event)

    assert state.environment["door-1"].is_open is True
    assert all("npc" not in str(change).casefold() for change in event.changes)
    generated = observations.get_by_observer("agent-1")
    assert len(generated) == 1
    assert generated[0].content.predicate == "door_open"
    assert generated[0].has_trusted_provenance()
    cognition = CognitiveRuntime().process("agent-1", generated)
    assert f"percept:{generated[0].observation_id}" in cognition.percept_ids
    processor.process(event, state)
    assert state.environment["door-1"].is_open is True
    assert len(processor.event_history.get_events()) == 1


def test_processed_door_state_is_captured_in_trusted_environment_context():
    state = _world()
    clock = SimulationClock(12)
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=state), world_state=state
    ).execute(_attempt(), simulation_tick=clock.capture())
    processor = EventProcessor(event_history=EventHistory())

    evidence = processor.process_with_evidence(event, state)

    assert evidence.has_trusted_source(event)
    assert evidence.event_time_context.environment_conditions == (
        ("door:door-1:open", True),
    )
    assert evidence.event_time_context.environment_snapshot_complete is False


def test_unknown_door_or_method_stays_unresolved():
    state = _world()
    policy = DoorCausalAssessmentPolicy()
    context = CausalWorldContext(
        "agent-1", "door_contact", ("manual_manipulation",),
        state.environment["door-1"], (),
    )
    assert policy.assess(
        _attempt("invent a harmless method"), context
    ).status is AssessmentStatus.INSUFFICIENT_INFORMATION
    state.environment  # read-only snapshot access
    result = MethodBasedResolutionEngine(
        world_state=state, simulation_time=SimulationClock().capture()
    ).resolve(_attempt("invent a harmless method"))
    assert result.confirmed is False
    negated = MethodBasedResolutionEngine(
        world_state=state, simulation_time=SimulationClock().capture()
    ).resolve(_attempt("do not push the door"))
    assert negated.confirmed is False


def test_locked_door_without_authoritative_key_is_not_opened():
    state = _world(locked=True)
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=state), world_state=state
    ).execute(_attempt(), simulation_tick=SimulationClock().capture())
    assert event.changes[0]["success"] is False
    assert state.environment["door-1"].is_open is False


def test_locked_door_requires_a_tool_entity_actually_held_and_used():
    state = _world(locked=True)
    state.load_entity(Entity("key-1", "tool", owner_id="agent-1"))
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=state), world_state=state
    ).execute(
        _attempt("use key-1 to unlock and push", tools=["key-1"]),
        simulation_tick=SimulationClock().capture(),
    )
    assert event.changes[0]["success"] is True


def test_claimed_key_id_without_owned_tool_entity_does_not_unlock():
    state = _world(locked=True)
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=state), world_state=state
    ).execute(
        _attempt("use key-1 to unlock and push", tools=["key-1"]),
        simulation_tick=SimulationClock().capture(),
    )
    assert event.changes[0]["success"] is False


def test_wrong_interaction_location_and_missing_capability_do_not_authorize():
    misplaced = _world(location="elsewhere")
    engine = MethodBasedResolutionEngine(world_state=misplaced, simulation_time=SimulationClock().capture())
    result = engine.resolve(_attempt())
    assert result.confirmed and result.success is False
    incapable = _world(capabilities=())
    engine = MethodBasedResolutionEngine(world_state=incapable, simulation_time=SimulationClock().capture())
    result = engine.resolve(_attempt())
    assert result.confirmed is False


def test_action_interpreter_rejects_structural_result_claim_but_ignores_success_prose():
    proposal = ActionProposal("p", "agent-1", "open", ["door-1"], {"method": "I successfully push it"})
    attempt = ActionInterpreter().interpret(proposal, actor_id="agent-1")
    assert attempt.parameters["method"] == "I successfully push it"
    forged = ActionProposal("p2", "agent-1", "open", ["door-1"], {"success": True})
    with pytest.raises(PermissionError):
        ActionInterpreter().interpret(forged)
    for key in ("npc_reactions", "permissions", "observed_facts", "world_changes"):
        forged = ActionProposal("p3", "agent-1", "open", ["door-1"], {key: {"claim": True}})
        with pytest.raises(PermissionError):
            ActionInterpreter().interpret(forged)


def test_resolution_confirmation_is_bound_to_attempt_content():
    state = _world()
    attempt = _attempt()
    engine = MethodBasedResolutionEngine(
        world_state=state, simulation_time=SimulationClock().capture()
    )
    result = engine.resolve(attempt)
    assert result._has_valid_confirmation(attempt)
    with pytest.raises(AttributeError, match="immutable"):
        attempt.action_type = "different attempt"
    assert result._has_valid_confirmation(attempt)


def test_changed_world_state_after_assessment_blocks_stale_effect():
    state = _world()
    event = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=state), world_state=state
    ).execute(_attempt(), simulation_tick=SimulationClock().capture())
    state.load_environment_data(
        "door-1", DoorState("door-1", "door_contact", False, True, True, "key-1")
    )
    processor = EventProcessor(event_history=EventHistory())
    processor.register_handler("resolution", DoorResolutionHandler())
    with pytest.raises(ValueError, match="changed after causal assessment"):
        processor.process(event, state)
    assert state.environment["door-1"].is_locked is True
    assert processor.event_history.get_events() == ()
