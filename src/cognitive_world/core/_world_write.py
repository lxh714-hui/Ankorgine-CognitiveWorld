"""Process-local capability used only by EventProcessor's commit path.

This guards ordinary application call paths. Python code executing in the same
process is not a security sandbox and can still introspect private modules.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import Iterator

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate


@dataclass(frozen=True)
class _ProcessorPermit:
    seal: object
    world_id: int
    event: Event
    event_snapshot: tuple[object, ...]
    update: WorldUpdate
    update_snapshot: tuple[object, ...]
    relationship_state: object = None
    life_write: bool = False
    take_write: bool = False


_SEAL = object()
_CURRENT: ContextVar[_ProcessorPermit | None] = ContextVar(
    "cognitive_world_processor_write_permit", default=None
)


def permit_matches(world: object, event: Event, update: WorldUpdate) -> bool:
    permit = _CURRENT.get()
    return (
        isinstance(permit, _ProcessorPermit)
        and permit.seal is _SEAL
        and permit.world_id == id(world)
        and permit.event is event
        and event.has_trusted_source()
        and permit.event_snapshot == event._source_snapshot()
        and permit.update is update
        and permit.update_snapshot == _update_snapshot(update)
    )


def _update_snapshot(update: WorldUpdate) -> tuple[object, ...]:
    return (
        update.target_id,
        update.operation,
        deepcopy(update.payload),
        deepcopy(update.metadata),
    )


def relationship_state(world, event, update):
    if not permit_matches(world, event, update):
        raise PermissionError("matching Processor scope required")
    state = _CURRENT.get().relationship_state
    if state is None:
        raise PermissionError("validated relationship write required")
    return deepcopy(state)


def protected_writes(world, update, *, life_write=False):
    """Inspect effective protected writes without publishing state."""
    from cognitive_world.core.physical import PhysicalRelation
    if update.target_id == "entities" and update.operation in {"set", "update"}:
        from collections.abc import Mapping
        if not isinstance(update.payload, Mapping):
            raise TypeError("entity update must be a mapping")
        before = world.entities
        after = {} if update.operation == "set" else dict(before)
        after.update(update.payload)
        for key, entity in before.items():
            old = getattr(entity, "state", {})
            new = getattr(after.get(key), "state", {})
            if "life" in new:
                from cognitive_world.core.life import LifeState
                try:
                    if type(new["life"]) is not LifeState:
                        raise ValueError("typed life required")
                    new["life"].__post_init__()
                except (ValueError, TypeError) as error:
                    raise PermissionError("invalid protected life representation") from error
            if ("life" in old) != ("life" in new) or old.get("life") != new.get("life"):
                if not life_write:
                    raise PermissionError("LifeState mutation requires exact LifeTransition")
    if update.target_id == "relationships" and update.operation in {"set", "update"}:
        before = world.relationships
        after = {} if update.operation == "set" else dict(before)
        after.update(update.payload)
        for key in before.keys() | after.keys():
            old, new = before.get(key), after.get(key)
            if type(new) is PhysicalRelation and set(new.kinds) & {"held_by", "attached_to"}:
                try:
                    new.__post_init__()
                except (ValueError, TypeError) as error:
                    raise PermissionError("invalid protected relationship representation") from error
            if any(type(r) is PhysicalRelation and set(r.kinds) & {"held_by", "attached_to"}
                   for r in (old, new)) and old != new:
                raise PermissionError("custody/attachment mutation requires exact domain operation")
    if update.target_id == "runtime_content":
        for relation in update.metadata.get("physical_relations", ()):
            if (type(relation) is PhysicalRelation and relation.source in world.entities
                    and set(relation.kinds) & {"held_by", "attached_to"}):
                raise PermissionError("installation cannot mutate existing protected relationships")


def validate_submission(world, event, update, processor=None):
    """Finite existing domain validators, bound to the complete submitted update."""
    life = any(type(c) is dict and c.get("effect_type") in {"life_transition_v1", "life_transition_v2"}
               for c in event.changes[1:])
    take = update.target_id == "item_possession" or any(
        type(c) is dict and c.get("effect_type") == "item_take_v1" for c in event.changes[1:])
    from cognitive_world.items.relationship import EFFECT, current_update as relation_update
    relation = update.target_id == "object_relationship" or any(
        type(c) is dict and c.get("effect_type") == EFFECT for c in event.changes[1:])
    if relation:
        if processor is None or processor.world_state is not world:
            raise PermissionError("canonical relationship processor required")
        expected = relation_update(event, processor)
        if _update_snapshot(expected) != _update_snapshot(update):
            raise PermissionError("relationship authorization requires its complete exact update")
    if life or take:
        if processor is None or processor.world_state is not world:
            raise PermissionError("canonical domain processor required")
        if life:
            from cognitive_world.resolution.life import current_update
            expected = current_update(event, world, processor.life_authority)
        else:
            from cognitive_world.items.take import ItemTakeHandler, validate_current_adjudication
            validate_current_adjudication(event, processor, world)
            expected = ItemTakeHandler(processor).handle_with_world_state(event, world)
        if _update_snapshot(expected) != _update_snapshot(update):
            raise PermissionError("domain authorization does not match complete submitted write set")
    protected_writes(world, update, life_write=life)
    return life, take


def require_domain_write(world, event, update, kind):
    if not permit_matches(world, event, update) or not getattr(_CURRENT.get(), kind + "_write", False):
        raise PermissionError("exact domain scope required")


@contextmanager
def processor_write_scope(
    world: object, event: Event, update: WorldUpdate, *, relationship_authority=None, processor=None
) -> Iterator[None]:
    """Grant one synchronous, content-bound write to the processor boundary."""
    if not isinstance(event, Event) or not event.has_trusted_source():
        raise PermissionError("world writes require an intact trusted Event")
    if not isinstance(update, WorldUpdate):
        raise TypeError("update must be a WorldUpdate")
    state = None
    life, take = validate_submission(world, event, update, processor)
    if update.target_id == "object_relationship":
        from cognitive_world.items.relationship import RelationshipAuthority
        if (type(relationship_authority) is not RelationshipAuthority
                or relationship_authority.processor.world_state is not world
                or update.operation != "apply" or update.metadata
                or update.payload != event.changes[1]):
            raise PermissionError("exact governed relationship update required")
        state = relationship_authority.validate(event)
    permit = _ProcessorPermit(
        _SEAL,
        id(world),
        event,
        event._source_snapshot(),
        update,
        _update_snapshot(update),
        state,
        life,
        take,
    )
    token = _CURRENT.set(permit)
    try:
        yield
    finally:
        _CURRENT.reset(token)
