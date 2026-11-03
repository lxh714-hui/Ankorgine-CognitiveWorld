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


@contextmanager
def processor_write_scope(
    world: object, event: Event, update: WorldUpdate, *, relationship_authority=None
) -> Iterator[None]:
    """Grant one synchronous, content-bound write to the processor boundary."""
    if not isinstance(event, Event) or not event.has_trusted_source():
        raise PermissionError("world writes require an intact trusted Event")
    if not isinstance(update, WorldUpdate):
        raise TypeError("update must be a WorldUpdate")
    state = None
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
    )
    token = _CURRENT.set(permit)
    try:
        yield
    finally:
        _CURRENT.reset(token)
