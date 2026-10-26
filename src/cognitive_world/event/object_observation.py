"""A system-requested observation reads canonical typed appearance only."""
from cognitive_world.event.handler import EventHandler
from cognitive_world.core.update import WorldUpdate
from cognitive_world.observation.observable import ObservableFactDraft
from cognitive_world.observation.object_projection import capture

class ObjectObservedHandler(EventHandler):
    def handle_with_world_state(self, event, world):
        if not event.has_trusted_source("system") or len(event.changes) != 1:
            raise PermissionError("object observation requires a controlled system request")
        request = event.changes[0]
        if (not isinstance(request, dict) or set(request) != {"entity_id", "observer_id", "precision"}
                or request["precision"] not in {"coarse", "detail"}
                or any(not isinstance(request[k], str) or not request[k] for k in request)
                or event.participants != [request["observer_id"]]):
            raise ValueError("invalid object observation request")
        return WorldUpdate("environment", "update", {})

    def observable_facts_with_world_state(self, event, update, world):
        r = event.changes[0]
        values = dict(capture(world, r["entity_id"]))
        p = f"object:{r['entity_id']}:"
        actor = world.get_entity(r["observer_id"])
        if (actor is None or actor.sensory_capabilities is None or "sight" not in actor.sensory_capabilities
                or not values.get(p+"visible") or not values.get(p+"lit")
                or world.locations.get(r["observer_id"]) != values.get(p+"location")):
            return ()
        detailed = (r["precision"] == "detail" and values.get(p+"holder") == r["observer_id"]
                    and values.get(p+"detail_visible") is True)
        key = "detail" if detailed else "shape"
        return (ObservableFactDraft("object_appearance", "object_"+key, values[p+key],
                    subject_ref=r["entity_id"], location_id=values[p+"location"]),)
