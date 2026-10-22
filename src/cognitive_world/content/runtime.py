"""Scenario lifecycle and seed wake-ups over existing world/event authorities."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.processor import EventProcessor
from cognitive_world.runtime.context import RuntimeContext

from .models import ScenarioInstance
from .seeds import SeedOpportunity, observed_seed_opportunities


class ScenarioPhase(str, Enum):
    AVAILABLE = "available"
    ENTERING = "entering"
    ACTIVE = "active"
    EXITING = "exiting"
    COMPLETED = "completed"
    ABORTED = "aborted"


def scenario_state_key(world_id: str, instance_id: str) -> str:
    return f"scenario-runtime:{world_id}:{instance_id}"


@dataclass(frozen=True)
class ScenarioRuntimeState:
    world_id: str
    instance_id: str
    template_id: str
    phase: ScenarioPhase
    entry_location_id: str
    exit_location_ids: tuple[str, ...]
    created_tick: int | None
    transition_tick: int | None = None
    revision: int = 0
    entrant_id: str | None = None
    last_event_id: str | None = None
    entry_environment: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class ScenarioEntryProposal:
    instance_id: str
    actor_id: str
    expected_revision: int


@dataclass(frozen=True)
class ScenarioExitProposal:
    instance_id: str
    actor_id: str
    expected_revision: int
    abort: bool = False


class ScenarioLifecycle(EventHandler):
    """Controlled transition handler; state lives only in WorldState.facts."""

    _allowed = {
        ScenarioPhase.AVAILABLE: ScenarioPhase.ENTERING,
        ScenarioPhase.ENTERING: ScenarioPhase.ACTIVE,
        ScenarioPhase.ACTIVE: ScenarioPhase.EXITING,
        ScenarioPhase.EXITING: ScenarioPhase.COMPLETED,
    }

    def __init__(self, context: RuntimeContext, processor: EventProcessor) -> None:
        if processor.world_state is not context.world_state or processor.event_history is not context.event_history:
            raise ValueError("Scenario lifecycle requires the runtime's world and history")
        if processor.simulation_clock is not context.clock:
            raise ValueError("Scenario lifecycle requires the runtime's trusted clock")
        self.context = context
        self.processor = processor
        self._instances: dict[str, ScenarioInstance] = {}
        self._pending: dict[str, tuple[object, ...]] = {}
        if "scenario_lifecycle" in processor._handlers:
            raise ValueError("Scenario lifecycle handler already registered")
        processor.register_handler("scenario_lifecycle", self)

    def register(self, instance: ScenarioInstance) -> None:
        if not isinstance(instance, ScenarioInstance) or instance.world_id == "":
            raise TypeError("registered scenario requires an instance receipt")
        state = self.state(instance.instance_id, instance=instance)
        if state.phase is not ScenarioPhase.AVAILABLE:
            raise ValueError("scenario must be registered before entry")
        if instance.side_branch:
            available = {seed.seed_id for seed in instance.event_seeds
                         if seed.possible_effects or seed.follow_up_hooks}
            available.update(character.instance_id.rsplit(":character:", 1)[-1]
                             for character in instance.characters
                             if self.context.world_state.get_entity(character.agent_id) is not None)
            available.update(mechanism_id.rsplit(":mechanism:", 1)[-1]
                             for location in instance.locations for mechanism_id in location.mechanism_ids
                             if mechanism_id in self.context.world_state.environment)
            if not any(ref in available for ref in instance.value_refs):
                raise PermissionError("scenario side branch has no reachable continuation value")
        previous = self._instances.get(instance.instance_id)
        if previous is not None and previous != instance:
            raise ValueError("scenario instance ID already registered")
        self._instances[instance.instance_id] = instance

    def state(self, instance_id: str, *, instance: ScenarioInstance | None = None) -> ScenarioRuntimeState:
        receipt = instance or self._instances[instance_id]
        value = self.context.world_state.facts.get(scenario_state_key(receipt.world_id, instance_id))
        if not isinstance(value, ScenarioRuntimeState) or (value.world_id, value.instance_id, value.template_id,
                value.entry_location_id, value.exit_location_ids) != (receipt.world_id, receipt.instance_id,
                receipt.template_id, receipt.entry_location_id, receipt.exit_location_ids):
            raise PermissionError("scenario runtime state has no matching trusted instance")
        return value

    def propose_entry(self, instance_id: str, actor_id: str) -> ScenarioEntryProposal:
        instance = self._instances[instance_id]
        state = self.state(instance_id)
        if state.phase is not ScenarioPhase.AVAILABLE or self.context.world_state.locations.get(actor_id) != instance.entry_location_id:
            raise PermissionError("actor must be at the entry of an available scenario")
        if self.context.agent_registry is None or self.context.agent_registry.get(actor_id) is None:
            raise PermissionError("scenario entrant must be registered in the trusted runtime")
        return ScenarioEntryProposal(instance_id, actor_id, state.revision)

    def enter(self, proposal: ScenarioEntryProposal) -> ScenarioRuntimeState:
        if not isinstance(proposal, ScenarioEntryProposal):
            raise TypeError("ScenarioEntryProposal required")
        state = self.state(proposal.instance_id)
        if state.phase is not ScenarioPhase.AVAILABLE or state.revision != proposal.expected_revision:
            raise PermissionError("stale scenario entry proposal")
        self.propose_entry(proposal.instance_id, proposal.actor_id)
        self._transition(proposal.instance_id, proposal.actor_id, ScenarioPhase.ENTERING)
        active = self._transition(proposal.instance_id, proposal.actor_id, ScenarioPhase.ACTIVE)
        self.publish_entry_observations(proposal.instance_id)
        return active

    def publish_entry_observations(self, instance_id: str) -> None:
        """Expose only installed typed mechanisms through existing visibility rules.

        This may be retried after a delivery failure. EventHistory reuses the
        processing evidence, so the world update is not applied a second time.
        """
        state = self.state(instance_id)
        if state.phase is not ScenarioPhase.ACTIVE:
            raise PermissionError("only an active scenario can expose its entry")
        instance = self._instances[instance_id]
        entry = next(location for location in instance.locations
                     if location.instance_id == instance.entry_location_id)
        for mechanism_id in entry.mechanism_ids:
            captured = dict(state.entry_environment).get(mechanism_id)
            if captured is None or self.context.world_state.environment.get(mechanism_id) != captured:
                raise RuntimeError("entry mechanism changed before its observation was issued")
            event = SystemEventFactory().create(
                event_id=f"scenario-entry-observation:{state.world_id}:{instance_id}:{mechanism_id}",
                event_type="environment_state_observed", timestamp="",
                changes=[{"environment_id": mechanism_id}],
                simulation_tick=state.transition_tick)
            self.processor.dispatch_with_evidence(event)

    def propose_exit(self, instance_id: str, actor_id: str, *, abort: bool = False) -> ScenarioExitProposal:
        instance = self._instances[instance_id]
        state = self.state(instance_id)
        if state.phase is not ScenarioPhase.ACTIVE or state.entrant_id != actor_id:
            raise PermissionError("actor is not active in this scenario")
        if not abort and not instance.at_exit(self.context.world_state, actor_id):
            raise PermissionError("actor has not reached a scenario exit")
        return ScenarioExitProposal(instance_id, actor_id, state.revision, abort)

    def exit(self, proposal: ScenarioExitProposal) -> ScenarioRuntimeState:
        if not isinstance(proposal, ScenarioExitProposal):
            raise TypeError("ScenarioExitProposal required")
        state = self.state(proposal.instance_id)
        if state.revision != proposal.expected_revision:
            raise PermissionError("stale scenario exit proposal")
        self.propose_exit(proposal.instance_id, proposal.actor_id, abort=proposal.abort)
        if proposal.abort:
            return self._transition(proposal.instance_id, proposal.actor_id, ScenarioPhase.ABORTED)
        self._transition(proposal.instance_id, proposal.actor_id, ScenarioPhase.EXITING)
        return self._transition(proposal.instance_id, proposal.actor_id, ScenarioPhase.COMPLETED)

    def _transition(self, instance_id: str, actor_id: str, target: ScenarioPhase) -> ScenarioRuntimeState:
        state = self.state(instance_id)
        tick = self.context.clock.capture().tick
        event_id = f"scenario-transition:{state.world_id}:{instance_id}:{state.revision + 1}"
        event = SystemEventFactory().create(event_id=event_id, event_type="scenario_lifecycle",
            timestamp="", participants=[actor_id], simulation_tick=tick,
            changes=[{"instance_id": instance_id, "actor_id": actor_id, "target": target.value,
                      "revision": state.revision}])
        self._pending[event_id] = event._source_snapshot()
        try:
            self.processor.dispatch_with_evidence(event)
        finally:
            self._pending.pop(event_id, None)
        return self.state(instance_id)

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if world_state is not self.context.world_state or not event.has_trusted_source("system"):
            raise PermissionError("scenario transition requires a trusted runtime Event")
        if self._pending.get(event.id) != event._source_snapshot():
            raise PermissionError("scenario transition was not authorized by the entry/exit boundary")
        if event.simulation_tick != self.context.clock.capture().tick:
            raise PermissionError("scenario transition is not at the trusted simulation tick")
        if len(event.changes) != 1 or type(event.changes[0]) is not dict or set(event.changes[0]) != {"instance_id", "actor_id", "target", "revision"}:
            raise PermissionError("invalid scenario transition payload")
        change = event.changes[0]
        instance_id, actor_id = change["instance_id"], change["actor_id"]
        state = self.state(instance_id)
        target = ScenarioPhase(change["target"])
        if state.revision != change["revision"] or event.participants != [actor_id]:
            raise PermissionError("stale or mismatched scenario transition")
        if self._allowed.get(state.phase) is not target and not (state.phase is ScenarioPhase.ACTIVE and target is ScenarioPhase.ABORTED):
            raise PermissionError("invalid scenario lifecycle transition")
        instance = self._instances[instance_id]
        if target is ScenarioPhase.ENTERING:
            if world_state.locations.get(actor_id) != instance.entry_location_id:
                raise PermissionError("scenario entry location changed")
        elif state.entrant_id != actor_id:
            raise PermissionError("scenario transition actor changed")
        if target in (ScenarioPhase.EXITING, ScenarioPhase.COMPLETED) and not instance.at_exit(world_state, actor_id):
            raise PermissionError("scenario exit condition is not met")
        entry_environment = state.entry_environment
        if target is ScenarioPhase.ACTIVE:
            entry = next(location for location in instance.locations
                         if location.instance_id == instance.entry_location_id)
            entry_environment = tuple((mid, world_state.environment.get(mid))
                                      for mid in entry.mechanism_ids)
            if any(value is None for _, value in entry_environment):
                raise PermissionError("scenario entry mechanism is missing")
        next_state = replace(state, phase=target, revision=state.revision + 1,
            entrant_id=actor_id, transition_tick=event.simulation_tick, last_event_id=event.id)
        next_state = replace(next_state, entry_environment=entry_environment)
        return WorldUpdate("facts", "update", {scenario_state_key(state.world_id, instance_id): next_state})


class ScenarioSeedScheduler:
    """Wake eligible Agents; never convert a seed into an Event or Proposal."""

    def __init__(self, context: RuntimeContext, lifecycle: ScenarioLifecycle, *, max_wakeups: int = 16) -> None:
        if context is not lifecycle.context or not 1 <= max_wakeups <= 256:
            raise ValueError("seed scheduling requires the same bounded runtime")
        self.context = context
        self.lifecycle = lifecycle
        self.max_wakeups = max_wakeups
        self._scheduled: set[tuple[str, str, str, str]] = set()

    def poll(self, instance_id: str) -> tuple[SeedOpportunity, ...]:
        state = self.lifecycle.state(instance_id)
        if state.phase is not ScenarioPhase.ACTIVE:
            return ()
        instance = self.lifecycle._instances[instance_id]
        registry, history, observations, scheduler = (self.context.agent_registry,
            self.context.event_history, self.context.observation_store, self.context.agent_scheduler)
        if registry is None or observations is None or scheduler is None:
            raise RuntimeError("seed scheduling needs runtime agents, observations and scheduler")
        eligible = []
        local_locations = {location.instance_id for location in instance.locations}
        for agent in sorted(registry.all_agents(), key=lambda item: item.agent_id):
            if not instance.contains_actor(self.context.world_state, agent.agent_id):
                continue
            for item in observed_seed_opportunities(instance, agent.agent_id,
                    history=history, observations=observations):
                source = next((observation for observation in observations.get_by_observer(agent.agent_id)
                               if observation.observation_id == item.observation_id), None)
                if source is not None and source.content.location_id in local_locations:
                    eligible.append(item)
        result = []
        for item in sorted(eligible, key=lambda x: (x.observer_id, x.source_event_id, x.seed_id)):
            key = (item.scenario_instance_id, item.observer_id, item.observation_id, item.seed_id)
            if key in self._scheduled:
                continue
            if len(result) >= self.max_wakeups:
                break
            scheduler.schedule_agent(item.observer_id, self.context.clock.capture().tick + 1)
            self._scheduled.add(key)
            result.append(item)
        return tuple(result)
