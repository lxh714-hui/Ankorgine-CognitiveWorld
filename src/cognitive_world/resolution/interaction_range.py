"""Canonical mechanism reach reads, reused by assessment and final submission."""
from dataclasses import dataclass
from cognitive_world.core.interaction_range import InteractionRangePolicy
from cognitive_world.core.observation_range import ObservationZone
from cognitive_world.core.world_state import WorldStateSlot

@dataclass(frozen=True)
class InteractionReach:
    status: str
    configured: bool
    slots: tuple


def capture_reach(world, actor_id, target_id, target_location):
    actor_location = world.get_location(actor_id)
    target = world.get_entity(target_id)
    attributes = {} if target is None else target.attributes
    policy = attributes.get("interaction_policy")
    slots = (WorldStateSlot("entities", target_id, ("attributes", "interaction_policy")),
             WorldStateSlot("locations", actor_id),
             WorldStateSlot("environment", target_id, ("interaction_location_id",)))
    if "interaction_policy" not in attributes:
        return InteractionReach("reachable" if actor_location == target_location else "out_of_reach",False,slots)
    if type(policy) is not InteractionRangePolicy or not actor_location:
        return InteractionReach("unknown",True,slots)
    slots = (*slots, WorldStateSlot("entities", actor_location, ("attributes", "observation_zone")),
             WorldStateSlot("entities", target_location, ("attributes", "observation_zone")))
    observer = world.get_entity(actor_location)
    node = world.get_entity(target_location)
    a = None if observer is None else observer.attributes.get("observation_zone")
    b = None if node is None else node.attributes.get("observation_zone")
    if type(a) is not ObservationZone or type(b) is not ObservationZone or a.frame_id != b.frame_id:
        return InteractionReach("unknown",True,slots)
    return InteractionReach("reachable" if abs(a.offset_m-b.offset_m) <= policy.maximum_distance_m
                            else "out_of_reach",True,slots)
