"""Small runnable, data-driven AutonomousWorldRunner example.

Run with ``python -m cognitive_world.runtime.demo`` from an installed source
environment. This prints a developer report, not player Presentation.
"""

from __future__ import annotations

from dataclasses import asdict
import json

from cognitive_world.agent import AgentActionLoop, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import CognitionContainer, Goal, MemoryStore, Personality, SelfModel
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


def build_demo_runner() -> tuple[AutonomousWorldRunner, WorldState]:
    """Build a two-NPC world through initialization and trusted Event paths."""
    world = WorldState()
    world.load_environment_snapshot({
        "door:archive": DoorState(
            "door:archive", "hall", is_open=False, is_locked=False,
            hand_operable=True,
        ),
    })
    world.load_entity(Entity(
        "agent-a", "character", sensory_capabilities=("sight",),
        physical_capabilities=("manual_manipulation", "locomotion"),
    ))
    world.load_entity(Entity(
        "agent-b", "character", sensory_capabilities=("sight",),
        physical_capabilities=("locomotion",),
    ))
    world.load_location("agent-a", "hall")
    world.load_location("agent-b", "workshop")

    cognition = CognitionContainer()
    memory_store = MemoryStore()
    observations = ObservationStore()
    registry = AgentRegistry()
    characters: dict[str, Character] = {}
    for owner, goal_id, description, capabilities in (
        (
            "agent-a", "goal-open-archive", "open the archive door",
            {"manual_manipulation": True, "locomotion": True},
        ),
        (
            "agent-b", "goal-keep-watch", "keep watch from the workshop",
            {"manual_manipulation": False, "locomotion": True},
        ),
    ):
        cognition.add_goal(Goal(goal_id, owner, description, 1.0, "active"))
        cognition.add_personality(Personality(owner))
        cognition.add_self_model(SelfModel(
            owner,
            capabilities=capabilities,
        ))
        character = Character(
            f"character:{owner}", owner, owner, goal_ids=[goal_id]
        )
        characters[owner] = character
        registry.register(RuntimeAgent(owner, character.id, goal_ids=[goal_id]))

    history = EventHistory()
    clock = SimulationClock()
    event_scheduler = EventScheduler()
    agent_scheduler = AgentScheduler()
    processor = EventProcessor(
        event_history=history,
        world_state=world,
        simulation_clock=clock,
        agent_registry=registry,
        observation_store=observations,
    )
    context = RuntimeContext(
        clock, world, history,
        event_scheduler=event_scheduler,
        agent_scheduler=agent_scheduler,
        agent_registry=registry,
        observation_store=observations,
    )
    cognition_contexts = {
        owner: CognitionContext.from_character(
            character, cognition, memory_store, observation_store=observations
        )
        for owner, character in characters.items()
    }
    action_loop = AgentActionLoop(
        action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world),
            world_state=world,
        )
    )
    runtime = SimulationRuntime(
        context,
        scheduler=event_scheduler,
        event_processor=processor,
        agent_action_loop=action_loop,
        cognition_context_provider=lambda agent: cognition_contexts[agent.agent_id],
        agent_decision=AgentDecision(),
    )

    # This records the initial typed environment state through the same
    # EventProcessor and visibility/Observation path used at runtime.
    processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id="event:demo-initial-environment:archive-door",
        event_type="environment_state_observed",
        timestamp="world-initialization",
        changes=[{"environment_id": "door:archive"}],
        simulation_tick=clock.current_time,
    ))
    return AutonomousWorldRunner(runtime), world


def run_demo(rounds: int = 3) -> dict[str, object]:
    runner, world = build_demo_runner()
    report = runner.run(rounds)
    return {
        "report": asdict(report),
        "world_result": {
            "archive_door_open": world.environment["door:archive"].is_open,
            "event_count": len(runner.runtime.context.event_history.get_events()),
        },
    }


def main() -> None:
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
