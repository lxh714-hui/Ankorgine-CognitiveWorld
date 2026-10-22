"""Production observation provenance is the only state-query authority."""
import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.observation import Observation
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.causal import ActionInterpreter
from cognitive_world.resolution.evidence import (AuthorizedStateQuery, AuthorizedQuerySession, CausalEvidenceAnalysis,
    QueryIntent, StateQueryProposal)
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding, RuntimeContext


def runtime_with_observations():
    world = WorldState()
    world.load_environment_data("door-west", DoorState("door-west", "west", False, False, True))
    world.load_environment_data("door-east", DoorState("door-east", "east", False, False, True))
    world.load_entity(Entity("viewer", "character", sensory_capabilities=("sight",)))
    world.load_entity(Entity("other", "character", sensory_capabilities=("sight",)))
    world.load_location("viewer", "west")
    world.load_location("other", "east")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("viewer", "character:viewer"))
    registry.register(RuntimeAgent("other", "character:other"))
    clock, history, observations = SimulationClock(3), EventHistory(), ObservationStore()
    context = RuntimeContext(clock, world, history, agent_registry=registry,
        observation_store=observations, player_session=PlayerSessionBinding(
            "session", "player", PlayerMode.ROLEPLAY, "viewer"))
    processor = EventProcessor(world_state=world, event_history=history,
        simulation_clock=clock, agent_registry=registry, observation_store=observations)
    for door in ("door-west", "door-east"):
        processor.dispatch_with_evidence(SystemEventFactory().create(
            event_id=f"observed:{door}", event_type="environment_state_observed",
            timestamp="", simulation_tick=clock.current_time,
            changes=[{"environment_id": door}],
        ))
    return context


def attempt(actor="viewer", targets=("object:door-west",)):
    return ActionInterpreter().interpret(ActionProposal(
        "attempt-proposal", actor, "inspect", list(targets), {"method": "inspect the hinge"}
    ), actor_id=actor)


def test_open_query_predicate_reads_only_current_owner_observed_fact_with_source():
    context = runtime_with_observations()
    service = AuthorizedStateQuery(context)
    result = service.query(attempt(), StateQueryProposal("object:door-west", "door_open"), simulation_tick=3)
    assert len(result) == 1
    item = result[0]
    assert (item.observer_id, item.reference, item.predicate, item.value, item.event_tick) == (
        "viewer", "object:door-west", "door_open", False, 3)
    assert item.source_event_id == "observed:door-west"
    assert item.observation_id.startswith("observation:")
    assert not hasattr(item, "world_state")
    assert context.world_state.environment["door-west"].is_open is False


def test_hidden_unknown_and_unsupplied_refs_have_indistinguishable_empty_result():
    service = AuthorizedStateQuery(runtime_with_observations())
    current = attempt(targets=("object:door-west", "object:door-east", "object:missing"))
    for reference in ("object:door-east", "object:missing", "object:unsupplied", "agent:other"):
        assert service.query(current, StateQueryProposal(reference), simulation_tick=3) == ()
    with pytest.raises(PermissionError):
        service.query(attempt(actor="other"), StateQueryProposal("object:door-east"), simulation_tick=3)


def test_store_membership_or_manual_observation_is_not_query_authorization():
    context = runtime_with_observations()
    existing = context.observation_store.get_by_observer("viewer")[0]
    context.observation_store.add(Observation("manual", "viewer", existing.source_event_id, existing.content))
    service = AuthorizedStateQuery(context)
    result = service.query(attempt(), StateQueryProposal("door-west"), simulation_tick=3)
    assert len(result) == 1
    assert result[0].observation_id != "manual"
    with pytest.raises(PermissionError):
        service.query(attempt(), StateQueryProposal("door-west"), simulation_tick=4)
    context.clock.tick()
    old = service.query(attempt(), StateQueryProposal("door-west"), simulation_tick=4)
    assert len(old) == 1 and old[0].event_tick == 3  # Historical observation, not current-state claim.


def test_model_query_and_analysis_schemas_reject_authority_or_forged_citations():
    query = StateQueryProposal.from_model('{"reference":"object:any","predicate":"unlisted_condition"}')
    assert query.predicate == "unlisted_condition"
    assert StateQueryProposal.from_model('{"done":true}') is None
    with pytest.raises(PermissionError):
        StateQueryProposal.from_model('{"reference":"object:any","permissions":["all"]}')
    with pytest.raises(ValueError):
        StateQueryProposal.from_model('{"reference":"object:any","reference":"object:other"}')
    with pytest.raises(PermissionError):
        CausalEvidenceAnalysis.from_model('{"cited_fact_ids":["invented"],"missing_conditions":[],"conflicting_fact_ids":[],"assessment":"success"}', ())
    view = QueryIntent.from_attempt(attempt())
    assert view.actor_id == "viewer" and view.target_refs == ("object:door-west",)
    assert not hasattr(view, "metadata")


def test_per_attempt_query_budget_and_repeat_termination():
    context = runtime_with_observations()
    session = AuthorizedQuerySession(AuthorizedStateQuery(context), attempt(), simulation_tick=3)
    query = StateQueryProposal("object:door-west")
    first = session.query(query)
    assert len(first) == 1 and session.remaining_queries == 1
    assert session.query(query) == ()
    assert session.evidence == first and session.remaining_queries == 1
    assert session.query(StateQueryProposal("object:missing")) == ()
    assert session.remaining_queries == 0
    with pytest.raises(PermissionError):
        session.query(StateQueryProposal("object:door-west", "door_open"))
    assert context.world_state.environment["door-west"].is_open is False
