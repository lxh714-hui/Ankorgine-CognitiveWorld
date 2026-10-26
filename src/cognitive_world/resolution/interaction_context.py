"""Attempt-scoped, permission-separated state aggregation for Resolution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cognitive_world.core.door import DoorState
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.passage import PassageState
from cognitive_world.core.world_state import WorldState, WorldStateSlot, WorldStateSlotRead
from cognitive_world.decision.attempt import Attempt
from cognitive_world.runtime.clock import SimulationTime

if TYPE_CHECKING:
    from cognitive_world.resolution.evidence import AuthorizedStateQuery, ObservedStateEvidence


@dataclass(frozen=True)
class CausalWorldContext:
    """Narrow physical view supplied to a causal assessment policy.

    This preserves the existing Resolution contract while binding the view to
    the exact Attempt, target, and trusted simulation tick that produced it.
    ``source_refs`` identify the authoritative WorldState collections read;
    they are provenance labels, not credentials or alternate fact stores.
    """

    actor_id: str
    actor_location: str | None
    physical_capabilities: tuple[str, ...] | None
    target: DoorState | PassageState | None
    held_tool_ids: tuple[str, ...]
    attempt_id: str = ""
    attempt_fingerprint: str = ""
    target_ref: str | None = None
    simulation_tick: int | None = None
    source_refs: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    grounded_refs: tuple[str, ...] = ()
    slot_reads: tuple[WorldStateSlotRead, ...] = ()
    interaction_reach: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("physical context requires an actor identity")
        if self.actor_location is not None and (not isinstance(self.actor_location, str) or not self.actor_location):
            raise ValueError("actor_location must be non-empty or unknown")
        if self.physical_capabilities is not None and (
            not isinstance(self.physical_capabilities, tuple)
            or any(not isinstance(item, str) or not item for item in self.physical_capabilities)
        ):
            raise TypeError("physical capabilities must be an immutable tuple or unknown")
        if self.target is not None and type(self.target) not in (DoorState, PassageState):
            raise TypeError("physical target must be a supported immutable state or unknown")
        if not isinstance(self.held_tool_ids, tuple) or any(not isinstance(item, str) or not item for item in self.held_tool_ids):
            raise TypeError("held_tool_ids must be an immutable tuple")
        if self.attempt_id and not isinstance(self.attempt_id, str):
            raise TypeError("attempt_id must be text")
        if self.attempt_fingerprint and not isinstance(self.attempt_fingerprint, str):
            raise TypeError("attempt_fingerprint must be text")
        if self.simulation_tick is not None and (
            isinstance(self.simulation_tick, bool) or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0
        ):
            raise ValueError("simulation_tick must be a non-negative integer or unknown")
        if not isinstance(self.source_refs, tuple) or any(not isinstance(item, str) or not item for item in self.source_refs):
            raise TypeError("source_refs must be an immutable tuple")
        if not isinstance(self.unknown_fields, tuple) or any(not isinstance(item, str) or not item for item in self.unknown_fields):
            raise TypeError("unknown_fields must be an immutable tuple")
        if not isinstance(self.grounded_refs, tuple) or any(not isinstance(item, str) or not item for item in self.grounded_refs):
            raise TypeError("grounded_refs must be an immutable tuple")
        if (not isinstance(self.slot_reads, tuple) or len(self.slot_reads) > 32
                or any(not isinstance(item, WorldStateSlotRead) for item in self.slot_reads)):
            raise TypeError("slot_reads must be a bounded immutable tuple of WorldStateSlotRead")


@dataclass(frozen=True)
class CognitiveInteractionView:
    """Facts already authorized to this Attempt's owner, never world truth."""

    owner_id: str
    attempt_id: str
    attempt_fingerprint: str
    simulation_tick: int
    target_refs: tuple[str, ...]
    evidence: tuple[ObservedStateEvidence, ...]
    unknown_refs: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.owner_id or not self.attempt_id or not self.attempt_fingerprint:
            raise ValueError("cognitive view must be bound to owner and Attempt")
        if isinstance(self.simulation_tick, bool) or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0:
            raise ValueError("cognitive view requires a non-negative simulation tick")
        if (not isinstance(self.target_refs, tuple)
                or any(not isinstance(item, str) or not item for item in self.target_refs)
                or not isinstance(self.evidence, tuple)
                or not isinstance(self.unknown_refs, tuple)
                or not isinstance(self.source_refs, tuple)):
            raise TypeError("cognitive view collections must be immutable tuples")
        if any(item.observer_id != self.owner_id for item in self.evidence):
            raise PermissionError("cognitive view contains another observer's evidence")
        if any(item.source_event_id not in self.source_refs for item in self.evidence):
            raise ValueError("cognitive evidence source references are incomplete")


@dataclass(frozen=True)
class InteractionStateAggregate:
    """One ephemeral, Attempt-bound pair of physically and cognitively scoped views."""

    attempt_id: str
    attempt_fingerprint: str
    actor_id: str
    simulation_tick: int
    physical: CausalWorldContext
    cognitive: CognitiveInteractionView | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.attempt_fingerprint or not self.actor_id:
            raise ValueError("aggregate must be bound to one Attempt and actor")
        if self.physical.actor_id != self.actor_id or self.physical.attempt_id != self.attempt_id:
            raise PermissionError("physical view does not match aggregate owner or Attempt")
        if self.physical.attempt_fingerprint != self.attempt_fingerprint or self.physical.simulation_tick != self.simulation_tick:
            raise ValueError("physical view is stale or belongs to different Attempt content")
        if self.cognitive is not None and (
            self.cognitive.owner_id != self.actor_id
            or self.cognitive.attempt_id != self.attempt_id
            or self.cognitive.attempt_fingerprint != self.attempt_fingerprint
            or self.cognitive.simulation_tick != self.simulation_tick
        ):
            raise PermissionError("cognitive view is stale or belongs to another owner/Attempt")


class InteractionStateAggregator:
    """Build only the bounded views required by one current interaction.

    Physical state comes from the canonical WorldState read-only accessors and
    is intended only for Resolution. The optional cognitive view comes only
    from AuthorizedStateQuery over the actor's already-authorized Observations.
    No result is cached or written to any Store.
    """

    def aggregate(
        self,
        attempt: Attempt,
        world_state: WorldState,
        simulation_time: SimulationTime,
        *,
        query_service: AuthorizedStateQuery | None = None,
        event_history: object | None = None,
    ) -> InteractionStateAggregate:
        if not isinstance(attempt, Attempt) or not isinstance(world_state, WorldState):
            raise TypeError("aggregation requires an Attempt and canonical WorldState")
        if not isinstance(simulation_time, SimulationTime) or not simulation_time.is_clock_issued():
            raise PermissionError("aggregation requires a trusted SimulationClock capture")
        fingerprint = attempt.content_fingerprint()
        physical = self._physical_view(
            attempt, world_state, simulation_time, fingerprint, event_history
        )
        cognitive = None
        if query_service is not None:
            cognitive = self._cognitive_view(attempt, query_service, simulation_time.tick, fingerprint)
        return InteractionStateAggregate(
            attempt.attempt_id, fingerprint, attempt.agent_id,
            simulation_time.tick, physical, cognitive,
        )

    def _physical_view(
        self,
        attempt: Attempt,
        world_state: WorldState,
        simulation_time: SimulationTime,
        fingerprint: str,
        event_history: object | None,
    ) -> CausalWorldContext:
        actor = world_state.get_entity(attempt.agent_id)
        actor_location = world_state.get_location(attempt.agent_id)
        if not isinstance(actor_location, str) or not actor_location:
            actor_location = None
        capabilities = None if actor is None else getattr(actor, "physical_capabilities", None)
        if capabilities is not None and not isinstance(capabilities, tuple):
            capabilities = None

        target_ref = attempt.target
        target_state: DoorState | PassageState | None = None
        unknown: list[str] = []
        source_refs = [f"world_state:entities:{attempt.agent_id}", f"world_state:locations:{attempt.agent_id}"]
        grounded_refs: set[str] = set()
        if actor is None:
            unknown.append("actor_entity")
        else:
            grounded_refs.add(f"agent:{attempt.agent_id}")
        if actor_location is None:
            unknown.append("actor_location")
        if capabilities is None:
            unknown.append("physical_capabilities")
        if target_ref is None:
            unknown.append("target")
        else:
            try:
                address = InteractionReference.parse(target_ref)
            except ValueError:
                address = None
                unknown.append("target_reference")
            if address is not None and address.namespace == "object":
                source_refs.append(f"world_state:environment:{address.identifier}")
                candidate = world_state.get_environment_entry(address.identifier)
                if type(candidate) in (DoorState, PassageState):
                    candidate_id = candidate.door_id if isinstance(candidate, DoorState) else candidate.passage_id
                    if candidate_id == address.identifier:
                        target_state = deepcopy(candidate)
                        grounded_refs.add(target_ref)
                if target_state is None:
                    unknown.append("target_state")
            elif address is not None:
                unknown.append("agent_target_state")

        held_tool_ids = tuple(sorted(
            entity.id for entity in world_state.get_owned_entities(attempt.agent_id)
            if getattr(entity, "type", None) == "tool"
            and (not (location := world_state.read_state_slot(
                WorldStateSlot("locations", entity.id))).present
                 or location.value == attempt.agent_id)
        ))
        if actor is not None:
            source_refs.append(f"world_state:entities:owned_tools:{attempt.agent_id}")
            grounded_refs.update(f"object:{item}" for item in held_tool_ids)

        # Submitted references are requests to check identity, not proof.
        # Read only the bounded references on this Attempt and expose no other
        # entity state through the physical view.
        for reference in attempt.target_refs:
            try:
                submitted = InteractionReference.parse(reference)
            except ValueError:
                unknown.append("participant_reference")
                continue
            if reference in grounded_refs:
                continue
            if submitted.namespace == "object":
                entity = world_state.get_entity(submitted.identifier)
                source_refs.append(f"world_state:entities:{submitted.identifier}")
                if entity is not None and getattr(entity, "id", None) == submitted.identifier:
                    grounded_refs.add(reference)
                else:
                    unknown.append(f"entity_identity:{reference}")
            else:
                entity = world_state.get_entity(submitted.identifier)
                source_refs.append(f"world_state:entities:{submitted.identifier}")
                if entity is not None and getattr(entity, "id", None) == submitted.identifier:
                    grounded_refs.add(reference)
                else:
                    unknown.append(f"entity_identity:{reference}")
        if attempt.initiator_id:
            initiator = world_state.get_entity(attempt.initiator_id)
            if initiator is not None and getattr(initiator, "id", None) == attempt.initiator_id:
                source_refs.append(f"world_state:entities:{attempt.initiator_id}")
                grounded_refs.add(f"agent:{attempt.initiator_id}")
        # Slot addresses are derived from the actual typed records and the
        # fields this physical view consumed. They are read-source receipts;
        # their optional Event IDs are independently checked by EventHistory.
        slots = [
            WorldStateSlot("entities", attempt.agent_id, ("physical_capabilities",)),
            WorldStateSlot("locations", attempt.agent_id),
        ]
        if actor is not None:
            slots.extend((
                WorldStateSlot("entities", attempt.agent_id, ("id",)),
                WorldStateSlot("entities", attempt.agent_id, ("type",)),
            ))
        if target_state is not None:
            target_id = (target_state.door_id if isinstance(target_state, DoorState)
                         else target_state.passage_id)
            slots.extend(
                WorldStateSlot("environment", target_id, (name,))
                for name in target_state.__dataclass_fields__
            )
        for tool_id in held_tool_ids:
            slots.extend((
                WorldStateSlot("entities", tool_id, ("type",)),
                WorldStateSlot("entities", tool_id, ("owner_id",)),
                WorldStateSlot("locations", tool_id),
            ))
        reach = None
        if type(target_state) is DoorState:
            from cognitive_world.resolution.interaction_range import capture_reach
            reach = capture_reach(world_state, attempt.agent_id, target_state.door_id,
                                  target_state.interaction_location_id)
            if reach.configured:
                slots.extend(reach.slots)
        unique_slots = tuple(dict.fromkeys(slots))
        if len(unique_slots) > 32 and reach is not None and reach.configured:
            raise ValueError("configured reach evidence exceeds the supported slot bound")
        unique_slots = unique_slots[:32]
        slot_reads = tuple(
            world_state.read_state_slot(slot, event_history=event_history)
            for slot in unique_slots
        )
        return CausalWorldContext(
            actor_id=attempt.agent_id,
            actor_location=actor_location,
            physical_capabilities=capabilities,
            target=target_state,
            held_tool_ids=held_tool_ids,
            attempt_id=attempt.attempt_id,
            attempt_fingerprint=fingerprint,
            target_ref=target_ref,
            simulation_tick=simulation_time.tick,
            source_refs=tuple(source_refs),
            unknown_fields=tuple(unknown),
            grounded_refs=tuple(sorted(grounded_refs)),
            slot_reads=slot_reads,
            interaction_reach=reach,
        )

    def _cognitive_view(
        self,
        attempt: Attempt,
        query_service: AuthorizedStateQuery,
        simulation_tick: int,
        fingerprint: str,
    ) -> CognitiveInteractionView:
        from cognitive_world.resolution.evidence import (
            MAX_QUERIES,
            AuthorizedQuerySession,
            AuthorizedStateQuery,
            ObservedStateEvidence,
            StateQueryProposal,
        )

        if not isinstance(query_service, AuthorizedStateQuery) or query_service.observer_id != attempt.agent_id:
            raise PermissionError("cognitive aggregation requires this actor's authorized query service")
        session = AuthorizedQuerySession(query_service, attempt, simulation_tick=simulation_tick)
        targets = tuple(attempt.target_refs)
        evidence: list[ObservedStateEvidence] = []
        unknown: list[str] = []
        for reference in targets[:MAX_QUERIES]:
            try:
                address = InteractionReference.parse(reference)
            except ValueError:
                unknown.append(reference)
                continue
            if address.namespace != "object":
                unknown.append(reference)
                continue
            found = session.query(StateQueryProposal(reference))
            if found:
                evidence.extend(found)
            else:
                unknown.append(reference)
        unknown.extend(targets[MAX_QUERIES:])
        unique = {item.fact_id: item for item in evidence}
        ordered = tuple(unique[key] for key in sorted(unique))
        sources = tuple(sorted({item.source_event_id for item in ordered}))
        return CognitiveInteractionView(
            owner_id=attempt.agent_id,
            attempt_id=attempt.attempt_id,
            attempt_fingerprint=fingerprint,
            simulation_tick=simulation_tick,
            target_refs=targets,
            evidence=ordered,
            unknown_refs=tuple(dict.fromkeys(unknown)),
            source_refs=sources,
        )
