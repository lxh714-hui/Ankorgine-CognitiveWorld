"""Run any supported v2 content file through installed object/door/observation paths.

This developer host initializes lit observation rooms explicitly. It is not a new
player-input API, visual geometry model or general interaction coordinator.
"""
import argparse
from pathlib import Path
from cognitive_world.content import ContentRegistry, ContentValidator, ContentInstantiator, parse_generation_proposal
from cognitive_world.core.world_state import WorldState
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.event import EventProcessor, EventHistory, SystemEventFactory
from cognitive_world.observation.store import ObservationStore
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext, PlayerMode, PlayerSessionBinding
from cognitive_world.presentation import PresentationPipeline, InMemoryChatOutputGateway
from cognitive_world.decision import ActionPipeline, ActionProposal
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine


def run(path, scenario_id, *, observer_key=None):
    from cognitive_world.safety.governance import UniversalSafetyGovernance
    registry = ContentRegistry(ContentValidator(UniversalSafetyGovernance()))
    proposal = parse_generation_proposal(Path(path).read_text(encoding="utf-8"))
    registry.register(proposal)
    template = registry.scenario(scenario_id)
    world, cognition, agents = WorldState(), CognitionContainer(), AgentRegistry()
    instance = ContentInstantiator(registry).instantiate(scenario_id, "demo", "local",
        world=world, cognition=cognition, agents=agents)
    for location in instance.locations:
        world.load_environment_data(location.instance_id, {"light_on": True})
    keys = [key for key, _, _ in template.characters]
    index = keys.index(observer_key) if observer_key is not None else 0
    actor = instance.characters[index].agent_id
    history, clock, observations = EventHistory(timeline_id="json-demo"), SimulationClock(), ObservationStore()
    # Ephemeral process-local demo signing; no trust material is written to disk.
    import secrets
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=agents, observation_store=observations,
        persistence_trust=HmacPersistenceTrust(secrets.token_bytes(32)))
    context = RuntimeContext(clock, world, history, agent_registry=agents, observation_store=observations,
        player_session=PlayerSessionBinding("demo", "player", PlayerMode.ROLEPLAY, controlled_agent_id=actor))
    presentation = PresentationPipeline.for_runtime(context, InMemoryChatOutputGateway(context))
    for key, _, _, _ in template.objects:
        for precision in ("coarse", "detail"):
            event = SystemEventFactory().create(event_id=f"view:{key}:{precision}",
                event_type="object_observed", timestamp="", simulation_tick=clock.current_time,
                participants=[actor], changes=[{"entity_id":f"local:demo:object:{key}",
                    "observer_id":actor,"precision":precision}])
            processor.dispatch_with_evidence(event)
            for message in presentation.publish_event(event.id).messages:
                print(message.content)
    # Offer the existing installed method, not a narrative assertion of success.
    for target, state in world.environment.items():
        from cognitive_world.core.door import DoorState
        if not isinstance(state, DoorState):
            continue
        proposal = ActionProposal("try:"+target, actor, "Try opening the door", [target],
            {"method":"use key to unlock and open the door", "tools":[] if state.key_id is None else [state.key_id]})
        attempt = ActionPipeline().create_attempt(proposal)
        result, event = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world),
            world_state=world, event_history=history).execute_with_result(attempt, simulation_tick=clock.capture())
        if event is not None:
            processor.dispatch_with_evidence(event)
            for message in presentation.publish_event(event.id).messages:
                print(message.content)
        print("Committed door result:", result.success if event is not None else "unresolved")
    return context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content", type=Path)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--observer")
    args = parser.parse_args()
    run(args.content, args.scenario, observer_key=args.observer)

if __name__ == "__main__":
    main()
