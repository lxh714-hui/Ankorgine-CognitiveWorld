"""Controlled runtime installation of previously validated reusable content.

The processor commits one world batch; cognition/registry provisioning then
finishes before an instance becomes AVAILABLE. Cross-authority work is not a
durable distributed transaction: failures after the world commit stay pending.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.event import Event
from cognitive_world.core.passage import PassageState
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.processor import EventProcessor
from cognitive_world.runtime.context import RuntimeContext

from .models import ScenarioInstance
from .pipeline import (ContentGenerator, ContentInstallationPlan,
                       ContentInstantiator, ContentRegistry, GenerationProposal)


@dataclass(frozen=True)
class ContentInstallationRecord:
    world_id: str
    instance_id: str
    template_id: str
    source_id: str
    proposal_digest: str | None
    installation_tick: int
    status: str
    installation_event_id: str
    completion_event_id: str | None = None
    source_refs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_refs, tuple) or len(self.source_refs) > 16:
            raise ValueError("installation source references exceed their bound")
        if any(type(item) is not tuple or len(item) != 2 or
               any(not isinstance(value, str) or not value or len(value) > 1000 for value in item)
               for item in self.source_refs):
            raise TypeError("installation source references must be immutable pairs")


def installation_record_key(world_id: str, instance_id: str) -> str:
    return f"content-installation:{world_id}:{instance_id}"


@dataclass(frozen=True)
class WorldContentBatch:
    """One isolated WorldState update, without cognition or registry records."""
    entities: tuple[Entity, ...]
    locations: tuple[tuple[str, str], ...]
    environment: tuple[tuple[str, DoorState | PassageState], ...]
    record_key: str
    record: ContentInstallationRecord


class _RuntimeContentHandler(EventHandler):
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self._pending: dict[str, tuple[tuple[object, ...], object]] = {}

    def authorize(self, event: Event, payload: object) -> None:
        if not event.has_trusted_source("system"):
            raise PermissionError("runtime installation requires a controlled system Event")
        self._pending[event.id] = (event._source_snapshot(), deepcopy(payload))

    def release(self, event_id: str) -> None:
        self._pending.pop(event_id, None)

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if world_state is not self.context.world_state or event.simulation_tick != self.context.clock.capture().tick:
            raise PermissionError("installation requires the current runtime world and clock")
        pending = self._pending.get(event.id)
        if not event.has_trusted_source("system") or pending is None or pending[0] != event._source_snapshot():
            raise PermissionError("installation Event has no matching authorized preparation")
        payload = pending[1]
        if event.type == "runtime_content_installed":
            if type(payload) is not WorldContentBatch:
                raise TypeError("installation requires an isolated world batch")
            record = payload.record
            if (event.id != record.installation_event_id or
                    event.changes != [{"world_id": record.world_id,
                                       "instance_id": record.instance_id,
                                       "template_id": record.template_id,
                                       "proposal_digest": record.proposal_digest}]):
                raise PermissionError("installation Event does not match the prepared content")
            return WorldUpdate("runtime_content", "install", deepcopy(payload))
        if event.type == "runtime_content_ready":
            if type(payload) is not tuple or len(payload) != 3:
                raise TypeError("completion requires a prepared scenario state")
            record_key, record, scenario_state = payload
            current = world_state.facts.get(record_key)
            if (type(current) is not ContentInstallationRecord or current.status != "world_installed"
                    or current != replace(record, status="world_installed", completion_event_id=None)
                    or event.id != record.completion_event_id):
                raise PermissionError("installation completion is stale or unbound")
            if event.changes != [{"world_id": record.world_id, "instance_id": record.instance_id,
                                  "template_id": record.template_id}]:
                raise PermissionError("completion Event has an invalid shape")
            from .runtime import scenario_state_key
            state_key = scenario_state_key(record.world_id, record.instance_id)
            if state_key in world_state.facts:
                raise ValueError("scenario runtime identity already exists")
            return WorldUpdate("facts", "update", {record_key: record, state_key: scenario_state})
        raise LookupError("unsupported runtime content Event")


class RuntimeContentInstaller:
    """Trusted host composition boundary; a generator never receives it."""
    def __init__(self, context: RuntimeContext, processor: EventProcessor,
                 registry: ContentRegistry, cognition: CognitionContainer,
                 agents: AgentRegistry) -> None:
        if (processor.world_state is not context.world_state or
                processor.event_history is not context.event_history or
                processor.simulation_clock is not context.clock or
                context.agent_registry is not agents or
                type(cognition) is not CognitionContainer or type(agents) is not AgentRegistry):
            raise ValueError("runtime installation requires canonical, matching authorities")
        if type(registry) is not ContentRegistry or registry.validator.safety is not context.safety_governance:
            raise PermissionError("runtime content must use the Runtime's shared P0 validator")
        if any(name in processor._handlers for name in ("runtime_content_installed", "runtime_content_ready")):
            raise ValueError("runtime content handler already registered")
        self.context, self.processor, self.registry = context, processor, registry
        self.cognition, self.agents = cognition, agents
        self._handler = _RuntimeContentHandler(context)
        processor.register_handler("runtime_content_installed", self._handler)
        processor.register_handler("runtime_content_ready", self._handler)

    def install_generated(self, generator: ContentGenerator, *, template_id: str,
                          instance_id: str, world_id: str, source_id: str) -> ScenarioInstance:
        """Provider failure occurs before touching registry, world or cognition."""
        return self.install_proposal(generator.generate(), template_id=template_id,
            instance_id=instance_id, world_id=world_id, source_id=source_id)

    def install_proposal(self, proposal: GenerationProposal, *, template_id: str,
                         instance_id: str, world_id: str, source_id: str,
                         source_refs: tuple[tuple[str, str], ...] = ()) -> ScenarioInstance:
        self.registry.validator.validate(proposal)
        if not isinstance(source_id, str) or not source_id or len(source_id) > 160:
            raise ValueError("bounded source ID required")
        if self.registry.has_registered_ids(proposal):
            raise ValueError("generated template ID already exists")
        staging = ContentRegistry(self.registry.validator)
        staging.register(proposal)
        digest = sha256(repr(proposal).encode("utf-8")).hexdigest()
        return self._install(ContentInstantiator(staging), template_id, instance_id,
                             world_id, source_id, digest, proposal, source_refs)

    def install_registered(self, template_id: str, instance_id: str, world_id: str,
                          *, source_id: str = "registered_template",
                          source_refs: tuple[tuple[str, str], ...] = ()) -> ScenarioInstance:
        if not isinstance(source_id, str) or not source_id or len(source_id) > 160:
            raise ValueError("bounded source ID required")
        return self._install(ContentInstantiator(self.registry), template_id,
                             instance_id, world_id, source_id, None, None, source_refs)

    def _install(self, instantiator: ContentInstantiator, template_id: str,
                 instance_id: str, world_id: str, source_id: str,
                 digest: str | None, proposal: GenerationProposal | None,
                 source_refs: tuple[tuple[str, str], ...] = ()) -> ScenarioInstance:
        world, clock = self.context.world_state, self.context.clock
        plan = instantiator.prepare(template_id, instance_id, world_id, world=world,
            cognition=self.cognition, agents=self.agents, clock=clock)
        tick = clock.capture().tick
        event_id = f"runtime-content:{world_id}:{instance_id}"
        record_key = installation_record_key(world_id, instance_id)
        if record_key in world.facts or self.context.event_history.get_event(event_id) is not None:
            raise ValueError("content instance identity already installed")
        record = ContentInstallationRecord(world_id, instance_id, template_id, source_id,
            digest, tick, "world_installed", event_id, source_refs=source_refs)
        batch = WorldContentBatch(plan.entities, plan.locations, plan.environment, record_key, record)
        event = SystemEventFactory().create(event_id=event_id, event_type="runtime_content_installed",
            timestamp="", simulation_tick=tick,
            changes=[{"world_id": world_id, "instance_id": instance_id,
                      "template_id": template_id, "proposal_digest": digest}])
        self._dispatch(event, batch)
        # No Agent is registered until all its owner-scoped cognition is ready.
        # A failure here leaves an explicit world_installed record for manual
        # recovery; it must never be silently retried as a fresh world Event.
        for personality in plan.personalities:
            self.cognition.add_personality(personality)
        for model in plan.self_models:
            self.cognition.add_self_model(model)
        for goal in plan.goals:
            self.cognition.add_goal(goal)
        if proposal is not None:
            self.registry.register(proposal)
        ready_event_id = f"runtime-content-ready:{world_id}:{instance_id}"
        ready = replace(record, status="ready", completion_event_id=ready_event_id)
        ready_event = SystemEventFactory().create(event_id=ready_event_id,
            event_type="runtime_content_ready", timestamp="", simulation_tick=clock.capture().tick,
            changes=[{"world_id": world_id, "instance_id": instance_id,
                      "template_id": template_id}])
        # Registration is deliberately last before the ready marker. Should
        # finalization fail, remove these new Agents so a pending installation
        # cannot be scheduled as a normal NPC by the autonomous Runner.
        try:
            for agent in plan.agents:
                self.agents.register(agent)
            self._dispatch(ready_event, (record_key, ready, plan.state))
        except Exception:
            for agent in plan.agents:
                self.agents.remove(agent.agent_id)
            raise
        return plan.instance

    def _dispatch(self, event: Event, payload: object) -> None:
        self._handler.authorize(event, payload)
        try:
            self.processor.dispatch_with_evidence(event)
        finally:
            self._handler.release(event.id)
