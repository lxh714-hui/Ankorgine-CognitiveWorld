"""Reusable content definitions; runtime authority stays in existing stores."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


def _id(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError("content ID must be a bounded non-empty string")


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError("content text must be bounded and non-empty")


@dataclass(frozen=True)
class CharacterTemplate:
    template_id: str
    description: str
    goal_descriptions: tuple[str, ...]
    sensory_capabilities: tuple[str, ...] = ()
    physical_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.template_id)
        _text(self.description)
        for values in (self.goal_descriptions, self.sensory_capabilities, self.physical_capabilities):
            if not isinstance(values, tuple):
                raise TypeError("template collections must be immutable tuples")
        for value in self.goal_descriptions:
            _text(value)
        for value in (*self.sensory_capabilities, *self.physical_capabilities):
            _id(value)


@dataclass(frozen=True)
class MechanismTemplate:
    """A supported environment mechanism, not an action category."""
    local_id: str
    kind: str
    destination_key: str | None = None
    initially_open: bool = False
    initially_locked: bool = False
    operable: bool = True
    key_ref: str | None = None
    interaction_policy: object | None = None
    appearance_ref: str | None = None

    def __post_init__(self) -> None:
        _id(self.local_id)
        if self.kind not in {"door", "passage"}:
            raise ValueError("mechanism has no installed world adapter")
        if self.key_ref is not None:
            _id(self.key_ref)
            if self.kind != "door":
                raise ValueError("only the door adapter accepts a key reference")
        from cognitive_world.core.interaction_range import InteractionRangePolicy
        if self.interaction_policy is not None and (type(self.interaction_policy) is not InteractionRangePolicy or self.kind != "door"):
            raise TypeError("only the installed door adapter supports the typed reach policy")
        if self.appearance_ref is not None:
            _id(self.appearance_ref)
            if self.kind != "door":
                raise ValueError("only the installed door has an object representation")
        if self.kind == "passage":
            _id(self.destination_key)
        elif self.destination_key is not None:
            raise ValueError("door has no passage destination")
        if any(type(x) is not bool for x in (self.initially_open, self.initially_locked, self.operable)):
            raise TypeError("mechanism flags must be bool")


@dataclass(frozen=True)
class LocationTemplate:
    template_id: str
    description: str
    mechanisms: tuple[MechanismTemplate, ...] = ()
    observation_zone: object | None = None

    def __post_init__(self) -> None:
        _id(self.template_id)
        _text(self.description)
        if not isinstance(self.mechanisms, tuple) or any(type(x) is not MechanismTemplate for x in self.mechanisms):
            raise TypeError("mechanisms must be typed immutable definitions")
        from cognitive_world.core.observation_range import ObservationZone
        if self.observation_zone is not None and type(self.observation_zone) is not ObservationZone:
            raise TypeError("location zone must use the exact versioned record")
        ids = [x.local_id for x in self.mechanisms]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate mechanism local ID")


@dataclass(frozen=True)
class EventSeed:
    """Potential event hook. Never a confirmed Event or an action script."""
    seed_id: str
    trigger_predicate: str
    trigger_value: str | bool
    participant_keys: tuple[str, ...]
    possible_effects: tuple[str, ...]
    importance: float
    follow_up_hooks: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.seed_id)
        _id(self.trigger_predicate)
        if type(self.trigger_value) not in (str, bool):
            raise TypeError("seed trigger must be scalar")
        if isinstance(self.trigger_value, str):
            _id(self.trigger_value)
        if isinstance(self.importance, bool) or not isinstance(self.importance, (int, float)) or not isfinite(self.importance) or not 0 <= self.importance <= 1:
            raise ValueError("importance must be finite and in [0,1]")
        for values in (self.participant_keys, self.possible_effects, self.follow_up_hooks, self.constraints):
            if not isinstance(values, tuple):
                raise TypeError("seed references must be immutable tuples")
            for value in values:
                _id(value)


@dataclass(frozen=True)
class ScenarioTemplate:
    template_id: str
    description: str
    locations: tuple[tuple[str, str], ...]  # local key, template ID
    characters: tuple[tuple[str, str, str], ...]  # local key, template ID, location key
    entry_key: str
    exit_keys: tuple[str, ...]
    event_seeds: tuple[EventSeed, ...] = ()
    side_branch: bool = False
    value_refs: tuple[str, ...] = ()  # linked local character, mechanism or seed
    objects: tuple[tuple[str, str, str, str | None], ...] = ()
    physical_relations: tuple = ()
    physical_rules: tuple = ()

    def __post_init__(self) -> None:
        _id(self.template_id)
        _text(self.description)
        _id(self.entry_key)
        if type(self.side_branch) is not bool:
            raise TypeError("side_branch must be bool")
        for values in (self.locations, self.characters, self.exit_keys, self.event_seeds, self.value_refs, self.objects, self.physical_relations, self.physical_rules):
            if not isinstance(values, tuple):
                raise TypeError("scenario collections must be immutable tuples")


@dataclass(frozen=True)
class CharacterInstance:
    template_id: str
    instance_id: str
    agent_id: str
    location_id: str


@dataclass(frozen=True)
class LocationInstance:
    template_id: str
    instance_id: str
    mechanism_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioInstance:
    """Identity receipt. Mutable runtime state stays with canonical authorities."""
    template_id: str
    instance_id: str
    world_id: str
    locations: tuple[LocationInstance, ...]
    characters: tuple[CharacterInstance, ...]
    entry_location_id: str
    exit_location_ids: tuple[str, ...]
    event_seeds: tuple[EventSeed, ...]
    side_branch: bool = False
    value_refs: tuple[str, ...] = ()

    def contains_actor(self, world: object, agent_id: str) -> bool:
        """Read current authoritative location; never move or admit an actor."""
        from cognitive_world.core.world_state import WorldState
        if type(world) is not WorldState or not isinstance(agent_id, str):
            raise TypeError("scenario presence requires canonical WorldState and actor ID")
        return world.locations.get(agent_id) in {item.instance_id for item in self.locations}

    def at_exit(self, world: object, agent_id: str) -> bool:
        """An exit is eligible only when the actor is actually at that exit."""
        from cognitive_world.core.world_state import WorldState
        if type(world) is not WorldState or not isinstance(agent_id, str):
            raise TypeError("exit check requires canonical WorldState and actor ID")
        return world.locations.get(agent_id) in self.exit_location_ids


@dataclass(frozen=True)
class ObjectTemplate:
    template_id: str
    description: str
    kind: str
    appearance: object
    observation_policy: object | None = None
    physical_state: object | None = None

    def __post_init__(self):
        from cognitive_world.core.physical import PhysicalStateSet
        if self.physical_state is not None:
            if type(self.physical_state) is not PhysicalStateSet:raise TypeError("typed physical state required")
            self.physical_state.__post_init__()
        from cognitive_world.core.object_appearance import ObjectAppearance
        _id(self.template_id)
        _text(self.description)
        if self.kind not in {"object", "tool"} or type(self.appearance) is not ObjectAppearance:
            raise ValueError("unsupported object definition")
        self.appearance.__post_init__()
        from cognitive_world.core.observation_range import ObservationRangePolicy
        if self.observation_policy is not None and type(self.observation_policy) is not ObservationRangePolicy:
            raise TypeError("object range policy must use the exact versioned record")
