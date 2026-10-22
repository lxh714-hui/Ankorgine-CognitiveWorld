"""Application composition for new and signed cold-resumed world sessions.

Canonical state and capabilities stay inside CW; callers receive projections.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from cognitive_world.agent import AgentActionLoop, CognitionContext
from cognitive_world.agent.character import Character
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.content.pipeline import ContentInstantiator, ContentRegistry, ContentValidator
from cognitive_world.core.persistence import PersistenceTrust
from cognitive_world.content.persistence import scenario_snapshot_codec
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.evidence_review import DeterministicLocalEvidenceReviewProvider
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.player.async_coordinator import PlayerInputTaskCoordinator
from cognitive_world.player.input_understanding import PlayerInputUnderstandingProvider
from cognitive_world.player.service import PlayerActionService
from cognitive_world.presentation.gateway import InMemoryChatOutputGateway
from cognitive_world.presentation.pipeline import PresentationPipeline
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding, RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.reconstruction import (
    DependencyStrategy, RuntimeAssemblyInputs, RuntimeDependencyManifest,
    RuntimeDependencyResolution,
)
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.safety.governance import UniversalSafetyGovernance
from cognitive_world.content.runtime import ScenarioRuntimeState

from .world_packages import WorldPackage


@dataclass
class NewWorldSession:
    """Host-private authorities; never serialize this object to a client."""

    package: WorldPackage
    runtime: SimulationRuntime
    cognition: CognitionContainer
    memory_store: MemoryStore
    agent_contexts: tuple[CognitionContext, ...]
    player_service: PlayerActionService
    player_tasks: PlayerInputTaskCoordinator
    output: InMemoryChatOutputGateway

    def close(self) -> None:
        self.player_tasks.close()
        self.runtime.freeze_writes()


def _desktop_dependencies() -> RuntimeDependencyManifest:
    """State where the host obtains each executable, non-snapshot dependency."""
    host_roles = {
        "agent_character_catalog", "agent_runtime_metadata", "agent_scheduler_state",
        "event_scheduler_state", "event_handler_registry", "agent_decision_policy",
        "agent_action_loop_policy", "cognition_context_provider", "safety_policy",
        "observation_policy", "player_session_policy",
    }
    disabled = {"provider_policy", "content_expansion_policy"}
    roles = (
        "agent_character_catalog", "agent_runtime_metadata", "agent_scheduler_state",
        "event_scheduler_state", "event_handler_registry", "agent_decision_policy",
        "agent_action_loop_policy", "cognition_context_provider", "safety_policy",
        "observation_policy", "provider_policy", "conflict_scheduler_policy",
        "event_tree_policy", "content_expansion_policy", "player_session_policy",
    )
    return RuntimeDependencyManifest(tuple(
        RuntimeDependencyResolution(
            role,
            DependencyStrategy.HOST if role in host_roles else (
                DependencyStrategy.DISABLED if role in disabled else DependencyStrategy.REBUILT
            ),
            f"anchor-host:{role}",
        ) for role in roles
    ))


class _DesktopColdAssembler:
    def __init__(self, package: WorldPackage, trust: PersistenceTrust) -> None:
        self.package, self.trust = package, trust

    def assemble(self, inputs: RuntimeAssemblyInputs) -> SimulationRuntime:
        # Match the trusted package's declared player role against identities in
        # the signed WorldState and Agent roster; no character is invented.
        states = tuple(value for value in inputs.world_state.facts.values()
                       if type(value) is ScenarioRuntimeState)
        if (len(states) != 1 or states[0].world_id != self.package.world_id
                or states[0].template_id != self.package.scenario_template_id):
            raise PermissionError("saved world does not identify one trusted scenario instance")
        state = states[0]
        player_id = (f"{state.world_id}:{state.instance_id}:agent:"
                     f"{self.package.player_character_key}")
        expected = {entry.agent_id: entry.character_id for entry in inputs.expected_agents}
        if (expected.get(player_id) != f"{state.world_id}:{state.instance_id}:character:"
                f"{self.package.player_character_key}"):
            raise PermissionError("saved player identity differs from the trusted package")
        registry, observations = AgentRegistry(), ObservationStore()
        links = {item.agent_id: item for item in inputs.agent_links}
        for entry in inputs.expected_agents:
            link = links.get(entry.agent_id)
            if link is None or link.character_id != entry.character_id:
                raise PermissionError("saved Agent/Character link is incomplete")
            registry.register(RuntimeAgent(entry.agent_id, entry.character_id,
                                           goal_ids=list(link.goal_ids)))
        safety = UniversalSafetyGovernance()
        binding = PlayerSessionBinding(
            f"player-session:{uuid4().hex}", "local-player", PlayerMode.ROLEPLAY, player_id,
        )
        context = RuntimeContext(
            inputs.clock, inputs.world_state, inputs.event_history,
            event_scheduler=EventScheduler(), agent_scheduler=AgentScheduler(),
            agent_registry=registry, observation_store=observations,
            player_session=binding, safety_governance=safety,
        )
        processor = EventProcessor(
            event_history=inputs.event_history, world_state=inputs.world_state,
            simulation_clock=inputs.clock, agent_registry=registry,
            observation_store=observations, persistence_trust=self.trust,
            persistence_codec=scenario_snapshot_codec(), write_fence=inputs.write_fence,
        )
        def cognition_context_for(agent: RuntimeAgent) -> CognitionContext:
            link = links[agent.agent_id]
            character = Character(
                link.character_id, link.agent_id, link.personality_id or "",
                list(link.memory_ids), list(link.belief_ids), link.emotion_id or "",
                goal_ids=list(link.goal_ids),
            )
            return CognitionContext.from_character(
                character, inputs.cognition, inputs.memory_store,
                observation_store=observations,
            )
        flow = ActionResolutionFlow(
            MethodBasedResolutionEngine(world_state=inputs.world_state),
            world_state=inputs.world_state, event_history=inputs.event_history,
            safety_governance=safety,
        )
        loop = AgentActionLoop(
            agent_turn=AgentTurn(write_fence=inputs.write_fence),
            action_resolution_flow=flow, safety_governance=safety,
            write_fence=inputs.write_fence,
        )
        return SimulationRuntime(
            context, write_fence=inputs.write_fence,
            event_processor=processor, agent_action_loop=loop,
            cognition_context_provider=cognition_context_for,
            agent_decision=AgentDecision(),
            behavior_feedback=inputs.behavior_feedback,
            behavior_feedback_status=inputs.behavior_feedback_status,
            memory_revision_lineage=inputs.memory_revision_lineage,
            evidence_review_provider=DeterministicLocalEvidenceReviewProvider(),
            conflict_opportunity_scheduler=ConflictOpportunityScheduler(),
            allow_environment_provider_discovery=False,
            strict_dependency_binding=True,
        )


def resume_saved_world(
    package: WorldPackage, *, manager: SaveManager, save_id: str,
    timeline_id: str, trust: PersistenceTrust,
    input_understanding_provider: PlayerInputUnderstandingProvider | None = None,
) -> NewWorldSession:
    """Resume the signed original Timeline and publish only after final validation."""
    if manager.trust is not trust:
        raise PermissionError("save manager and desktop host require the same trust root")
    staged = manager.stage_cold_resume(
        save_id, timeline_id=timeline_id,
        assembler=_DesktopColdAssembler(package, trust),
        dependencies=_desktop_dependencies(),
    )
    slot = ColdRuntimePublisher().activate(staged)
    runtime = slot.current
    context = runtime.context
    output = InMemoryChatOutputGateway(context)
    tasks = None
    try:
        service = PlayerActionService(
            context, runtime.event_processor, ActionPipeline(),
            ActionResolutionFlow(
                MethodBasedResolutionEngine(world_state=context.world_state),
                world_state=context.world_state, event_history=context.event_history,
            ), output, world_id=package.world_id,
            input_understanding_provider=input_understanding_provider,
        )
        # ObservationStore is intentionally transient. Obtain a new, authorized
        # observation of current nearby mechanisms through EventProcessor; do
        # not manufacture a past Observation from the signed history alone.
        player_location = context.world_state.locations.get(context.player_session.controlled_agent_id)
        presentation = PresentationPipeline.for_runtime(context, output)
        for mechanism_id, mechanism in context.world_state.environment.items():
            location = getattr(mechanism, "interaction_location_id", None)
            if location is None:
                location = getattr(mechanism, "source_location_id", None)
            if location != player_location:
                continue
            event_id = f"resume-observation:{uuid4().hex}"
            runtime.event_processor.dispatch_with_evidence(SystemEventFactory().create(
                event_id=event_id, event_type="environment_state_observed",
                timestamp=str(context.clock.current_time),
                simulation_tick=context.clock.current_time,
                changes=[{"environment_id": mechanism_id}],
            ))
            presentation.publish_event(event_id)
        tasks = PlayerInputTaskCoordinator(service)
        agent_contexts = tuple(runtime.cognition_context_provider(agent)
                               for agent in context.agent_registry.all_agents())
        memory = agent_contexts[0].memory_store
        cognition = agent_contexts[0].cognition_container
        return NewWorldSession(package, runtime, cognition, memory, agent_contexts,
                               service, tasks, output)
    except Exception:
        if tasks is not None:
            tasks.close()
        runtime.freeze_writes()
        raise


def start_new_world(
    package: WorldPackage, *, trust: PersistenceTrust,
    input_understanding_provider: PlayerInputUnderstandingProvider | None = None,
) -> NewWorldSession:
    """Create a fresh Runtime from one validated package using existing authorities."""

    if type(package) is not WorldPackage:
        raise TypeError("a validated WorldPackage is required")
    if not callable(getattr(trust, "sign", None)) or not callable(getattr(trust, "verify", None)):
        raise TypeError("an explicit persistence trust root is required")
    safety = UniversalSafetyGovernance()
    registry = ContentRegistry(ContentValidator(safety))
    registry.register(package.proposal)
    world, cognition, agents = WorldState(), CognitionContainer(), AgentRegistry()
    observations, memory = ObservationStore(), MemoryStore()
    history = EventHistory(timeline_id=f"timeline:{package.world_id}:{uuid4().hex}")
    clock, fence = SimulationClock(), RuntimeWriteFence()
    scenario = registry.scenario(package.scenario_template_id)
    instance = ContentInstantiator(registry).instantiate(
        package.scenario_template_id, f"instance:{uuid4().hex}", package.world_id,
        world=world, cognition=cognition, agents=agents, clock=clock,
    )
    player_key_to_instance = dict(zip(
        (key for key, _, _ in scenario.characters), instance.characters,
    ))
    player_id = player_key_to_instance[package.player_character_key].agent_id
    session = PlayerSessionBinding(
        f"player-session:{uuid4().hex}", "local-player", PlayerMode.ROLEPLAY, player_id,
    )
    context = RuntimeContext(
        clock, world, history, event_scheduler=EventScheduler(),
        agent_scheduler=AgentScheduler(), agent_registry=agents,
        observation_store=observations, player_session=session,
        safety_governance=safety,
    )
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        agent_registry=agents, observation_store=observations,
        persistence_trust=trust, persistence_codec=scenario_snapshot_codec(),
        write_fence=fence,
    )
    agent_contexts = tuple(
        CognitionContext.from_character(
            ContentInstantiator.character_reference(character, cognition),
            cognition, memory, observation_store=observations,
        ) for character in instance.characters
    )
    for item in agent_contexts:
        item.bind_write_fence(fence)
    by_owner = {item.owner_id: item for item in agent_contexts}
    resolution = ActionResolutionFlow(
        MethodBasedResolutionEngine(world_state=world), world_state=world,
        event_history=history,
    )
    action_loop = AgentActionLoop(
        agent_turn=AgentTurn(write_fence=fence), action_resolution_flow=resolution,
        write_fence=fence,
    )
    runtime = SimulationRuntime(
        context, write_fence=fence, event_processor=processor,
        agent_action_loop=action_loop,
        cognition_context_provider=lambda agent: by_owner[agent.agent_id],
        agent_decision=AgentDecision(),
        allow_environment_provider_discovery=False,
    )
    # The package installs state before the first Event. Each initial mechanism
    # becomes a real processed Observation source, never a fabricated target.
    initial_event_ids: list[str] = []
    for location in instance.locations:
        for mechanism_id in location.mechanism_ids:
            event_id = f"initial-environment:{uuid4().hex}"
            processor.dispatch_with_evidence(SystemEventFactory().create(
                event_id=event_id,
                event_type="environment_state_observed", timestamp="0",
                simulation_tick=clock.current_time,
                changes=[{"environment_id": mechanism_id}],
            ))
            initial_event_ids.append(event_id)
    tasks = None
    try:
        runtime.start()
        output = InMemoryChatOutputGateway(context)
        player_service = PlayerActionService(
            context, processor, ActionPipeline(),
            ActionResolutionFlow(
                MethodBasedResolutionEngine(world_state=world), world_state=world,
                event_history=history,
            ), output, world_id=package.world_id,
            input_understanding_provider=input_understanding_provider,
        )
        # Initial state reaches the desktop through the same observed-Event,
        # authorization and safety projection used by later committed facts.
        presentation = PresentationPipeline.for_runtime(context, output)
        for event_id in initial_event_ids:
            presentation.publish_event(event_id)
        tasks = PlayerInputTaskCoordinator(player_service)
    except Exception:
        if tasks is not None:
            tasks.close()
        runtime.freeze_writes()
        raise
    return NewWorldSession(
        package, runtime, cognition, memory, agent_contexts,
        player_service, tasks, output,
    )
