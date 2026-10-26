"""Real in-memory history fixtures; no synthetic Observation or provenance seal."""
from cognitive_world.agent import AgentRegistry, RuntimeAgent
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory, RoomLightChangedHandler
from cognitive_world.observation import ObservationStore
from cognitive_world.runtime import RuntimeContext, SimulationClock


def light_history(owner, event_id, *, world=None):
    world = WorldState() if world is None else world
    world.load_entity(Entity(owner, "character", sensory_capabilities=("sight",)))
    world.load_location(owner, "fixture-room")
    world.load_environment_data("fixture-room", {"light_on": False})
    agents = AgentRegistry()
    agents.register(RuntimeAgent(owner, "character-" + owner))
    context = RuntimeContext(SimulationClock(), world, EventHistory(),
        agent_registry=agents, observation_store=ObservationStore())
    processor = EventProcessor(world_state=world, event_history=context.event_history,
        simulation_clock=context.clock, agent_registry=agents, observation_store=context.observation_store)
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    event = SystemEventFactory().create(event_id=event_id, event_type="room_light_changed",
        timestamp="0", simulation_tick=0,
        changes=[{"room_id": "fixture-room", "from_light_on": False, "to_light_on": True}])
    processor.dispatch_with_evidence(event)
    observation, = context.observation_store.get_by_observer(owner)
    assert observation.has_trusted_provenance()
    assert context.event_history.get_processing_evidence(event_id).has_trusted_source(event)
    return context, observation


def qualified_turn(history_context, **kwargs):
    from cognitive_world.agent import AgentTurn
    turn = AgentTurn(**kwargs)
    turn.cognitive_runtime._bind_observation_history(history_context.event_history)
    return turn
