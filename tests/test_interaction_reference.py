"""Interaction addressing is neither world truth nor target authorization."""
import pytest

from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.passage import PassageState
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.resolution.causal import ActionInterpreter, MethodBasedResolutionEngine
from cognitive_world.runtime.clock import SimulationClock


def test_reference_separates_stable_address_from_state_and_legacy_ids():
    assert InteractionReference.parse("object:shared") == InteractionReference("object", "shared")
    assert InteractionReference.parse("agent:shared") == InteractionReference("agent", "shared")
    assert InteractionReference.parse("door:archive") == InteractionReference("object", "door:archive", True)
    with pytest.raises(ValueError):
        InteractionReference.parse("agent:")
    with pytest.raises(ValueError):
        InteractionReference.parse("")
    with pytest.raises(ValueError):
        InteractionReference("unverified", "shared")


def test_same_identifier_cannot_route_an_agent_address_to_object_causality():
    world = WorldState()
    world.load_environment_data("shared", DoorState("shared", "room", False, False, True))
    world.load_entity(Entity("shared", "agent"))
    world.load_entity(Entity("actor", "character", physical_capabilities=("manual_manipulation",)))
    world.load_location("actor", "room")
    clock = SimulationClock(1)
    engine = MethodBasedResolutionEngine(world, simulation_time=clock.capture())
    for ref, expected in (("agent:shared", False), ("object:unknown", False),
                          ("object:shared", True)):
        attempt = ActionInterpreter().interpret(ActionProposal(
            f"proposal:{ref}", "actor", "try to open", [ref], {"method": "push the door"}
        ), actor_id="actor")
        result = engine.resolve(attempt)
        assert result.confirmed is expected
        assert world.environment["shared"].is_open is False
        assert world.get_entity("shared").type == "agent"


def test_same_reference_contract_supports_existing_passage_without_new_action_kind():
    world = WorldState()
    world.load_environment_data("route", PassageState("route", "A", "B", True))
    world.load_entity(Entity("walker", "character", physical_capabilities=("locomotion",)))
    world.load_location("walker", "A")
    attempt = ActionInterpreter().interpret(ActionProposal(
        "walk", "walker", "cross", ["object:route"], {"method": "walk through route"}
    ), actor_id="walker")
    result = MethodBasedResolutionEngine(world, simulation_time=SimulationClock(1).capture()).resolve(attempt)
    assert result.confirmed and result.success
    assert world.locations["walker"] == "A"  # Resolution cannot commit its own effect.


def test_interpreter_cannot_replace_a_supplied_target_with_model_guess():
    class Provider:
        def interpret_attempt(self, proposal, *, max_output_chars):
            return '{"target_refs":["object:hidden"],"method":"push the door"}'

    proposal = ActionProposal("p", "actor", "try", ["object:visible"], {})
    with pytest.raises(PermissionError, match="outside the supplied reference set"):
        ActionInterpreter(Provider()).interpret(proposal, actor_id="actor")
    assert proposal.target_refs == ["object:visible"]
    with pytest.raises(PermissionError):
        ActionInterpreter(Provider()).interpret(ActionProposal("empty", "actor", "try", [], {}), actor_id="actor")


def test_interpreter_cannot_hide_a_new_target_inside_model_steps():
    class Provider:
        def interpret_attempt(self, proposal, *, max_output_chars):
            return '{"steps":[{"method":"push the door","target":"object:hidden"}]}'

    proposal = ActionProposal("p-steps", "actor", "try", ["object:visible"], {})
    with pytest.raises(PermissionError, match="step target is outside"):
        ActionInterpreter(Provider()).interpret(proposal, actor_id="actor")
