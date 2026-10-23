"""Small production handler for a typed room-light state transition."""

from collections.abc import Mapping

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.handler import EventHandler
from cognitive_world.observation.observable import ObservableFactDraft
from cognitive_world.core.door import DoorState
from cognitive_world.core.interaction import InteractionReference
from cognitive_world.core.passage import PassageState
from cognitive_world.world_norms.models import WorldNorms


def _validate_resolution_summary(event: Event, *, effect_present: bool) -> None:
    if not event.changes or not isinstance(event.changes[0], Mapping):
        raise ValueError("Resolution Event requires a typed result summary")
    summary = event.changes[0]
    if set(summary) != {"success", "outcome"} or type(summary["success"]) is not bool or not isinstance(summary["outcome"], str):
        raise ValueError("Resolution result summary has an invalid shape")
    partial_is_confirmed = summary["outcome"].startswith("partial:")
    if effect_present and summary["success"] is not True and not partial_is_confirmed:
        raise PermissionError("a failed Resolution cannot apply world effects")


def _validate_physical_effect_provenance(
    event: Event, effect: Mapping[str, object], *, target_id: str
) -> None:
    """Require the signed Resolution Event to retain its interaction evidence binding."""
    from cognitive_world.resolution.causal import physical_effect_fingerprint

    records = event.metadata.get("physical_effect_provenance")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], Mapping):
        raise PermissionError("physical effect lacks its bound Resolution provenance")
    record = records[0]
    required = {
        "attempt_id", "attempt_fingerprint", "target_ref", "simulation_tick",
        "source_refs", "verified_conditions", "unknown_conditions", "effect_fingerprint",
        "proposed_participants", "state_slot_reads",
    }
    if set(record) != required:
        raise ValueError("physical effect provenance has an unsupported shape")
    source_refs = record["source_refs"]
    conditions = record["verified_conditions"]
    unknown = record["unknown_conditions"]
    proposed_participants = record["proposed_participants"]
    state_slot_reads = record["state_slot_reads"]
    expected_sources = {
        f"world_state:entities:{effect.get('actor_id')}",
        f"world_state:locations:{effect.get('actor_id')}",
        f"world_state:environment:{target_id}",
    }
    try:
        if not isinstance(record["target_ref"], str):
            raise ValueError("target reference must be text")
        target = InteractionReference.parse(record["target_ref"])
        target_matches = target.namespace == "object" and target.identifier == target_id
    except (TypeError, ValueError):
        target_matches = False
    if (
        not isinstance(record["attempt_id"], str)
        or record["attempt_id"] != event.cause
        or not isinstance(record["attempt_fingerprint"], str)
        or not record["attempt_fingerprint"]
        or record["attempt_fingerprint"] != event.metadata.get("attempt_fingerprint")
        or isinstance(record["simulation_tick"], bool)
        or not isinstance(record["simulation_tick"], int)
        or record["simulation_tick"] != event.simulation_tick
        or not target_matches
        or not isinstance(source_refs, (tuple, list))
        or any(not isinstance(ref, str) or not ref or len(ref) > 512 for ref in source_refs)
        or not expected_sources.issubset(source_refs)
        or not isinstance(conditions, (tuple, list))
        or not conditions
        or any(not isinstance(item, str) or not item or len(item) > 512 for item in conditions)
        or not isinstance(unknown, (tuple, list))
        or bool(unknown)
        or not isinstance(record["effect_fingerprint"], str)
        or record["effect_fingerprint"] != physical_effect_fingerprint(effect)
        or not isinstance(proposed_participants, (tuple, list))
        or len(proposed_participants) > 12
        or not isinstance(state_slot_reads, (tuple, list))
        or not 1 <= len(state_slot_reads) <= 32
    ):
        raise PermissionError("physical effect provenance does not match the submitted Event")
    # These are preserved as model claims for traceability, never as confirmed
    # participant relations or world facts. The supported handlers currently
    # authorize only their actor and typed target.
    for participant in proposed_participants:
        if (not isinstance(participant, Mapping)
                or set(participant) != {"reference", "relation", "status"}
                or participant["status"] != "model_proposed_unverified"
                or participant["reference"] not in {
                    f"agent:{effect.get('actor_id')}", f"object:{target_id}",
                }
                or not isinstance(participant["relation"], str)
                or not participant["relation"] or len(participant["relation"]) > 80):
            raise PermissionError("unverified participant provenance is malformed or outside the confirmed effect scope")


class RoomLightChangedHandler(EventHandler):
    """Apply a validated environment light transition through EventProcessor."""

    def handle(self, event: Event) -> WorldUpdate:
        raise ValueError("RoomLightChangedHandler requires authoritative WorldState")

    def handle_with_world_state(
        self, event: Event, world_state: WorldState
    ) -> WorldUpdate:
        if not event.has_trusted_source("system"):
            raise PermissionError("room light transitions require a controlled system Event")
        if len(event.changes) != 1 or not isinstance(event.changes[0], Mapping):
            raise ValueError("room light Event must contain exactly one typed change")
        change = event.changes[0]
        if set(change) != {"room_id", "from_light_on", "to_light_on"}:
            raise ValueError("room light Event has an unsupported change shape")
        room_id = change["room_id"]
        previous, current = change["from_light_on"], change["to_light_on"]
        if not isinstance(room_id, str) or not room_id:
            raise ValueError("room_id must be non-empty")
        if (
            type(previous) is not bool
            or type(current) is not bool
            or previous == current
        ):
            raise ValueError("room light Event must describe a boolean state transition")
        room_state = world_state.environment.get(room_id)
        if (
            not isinstance(room_state, Mapping)
            or type(room_state.get("light_on")) is not bool
        ):
            raise ValueError("room light state is missing or unknown")
        if room_state["light_on"] is not previous:
            raise ValueError(
                "room light Event does not match the current authoritative state"
            )
        return WorldUpdate(
            target_id="environment",
            operation="update",
            payload={room_id: {"light_on": current}},
        )

    def observable_facts(
        self, event: Event, update: WorldUpdate
    ) -> tuple[ObservableFactDraft, ...]:
        change = event.changes[0]
        return (
            ObservableFactDraft(
                fact_type="environment_state",
                predicate="room_light_on",
                value=change["to_light_on"],
                subject_ref=change["room_id"],
                location_id=change["room_id"],
            ),
        )


class EnvironmentStateObservedHandler(EventHandler):
    """Record one trusted local environment state snapshot.

    The event carries only an entity reference. Fact payloads are built from
    the typed canonical WorldState object, never from caller-supplied values.
    Applying the same immutable state through EventProcessor binds the snapshot
    and its Observation evidence to one event-processing boundary.
    """

    def handle(self, event: Event) -> WorldUpdate:
        raise ValueError("EnvironmentStateObservedHandler requires authoritative WorldState")

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if not event.has_trusted_source("system"):
            raise PermissionError("environment snapshots require a controlled system Event")
        if len(event.changes) != 1 or not isinstance(event.changes[0], Mapping):
            raise ValueError("environment snapshot Event requires one typed reference")
        change = event.changes[0]
        if set(change) != {"environment_id"}:
            raise ValueError("environment snapshot Event contains unsupported fields")
        environment_id = change["environment_id"]
        if not isinstance(environment_id, str) or not environment_id:
            raise ValueError("environment_id must be non-empty")
        current = world_state.environment.get(environment_id)
        if not isinstance(current, (DoorState, PassageState)):
            raise ValueError("environment snapshot requires a supported typed state")
        return WorldUpdate("environment", "update", {environment_id: current})

    def observable_facts(self, event: Event, update: WorldUpdate) -> tuple[ObservableFactDraft, ...]:
        if len(update.payload) != 1:
            return ()
        environment_id, state = next(iter(update.payload.items()))
        if isinstance(state, DoorState):
            return (
                ObservableFactDraft(
                    fact_type="environment_state",
                    predicate="door_open",
                    value=state.is_open,
                    subject_ref=environment_id,
                    location_id=state.interaction_location_id,
                ),
                *((ObservableFactDraft(
                    fact_type="environment_state",
                    predicate="door_locked",
                    value=state.is_locked,
                    subject_ref=environment_id,
                    location_id=state.interaction_location_id,
                ),) if state.is_locked else ()),
            )
        if isinstance(state, PassageState):
            return (ObservableFactDraft(
                fact_type="environment_state",
                predicate="passage_destination",
                value=state.destination_location_id,
                subject_ref=environment_id,
                location_id=state.source_location_id,
            ),)
        return ()

class DoorResolutionHandler(EventHandler):
    """Apply a door effect only from a controlled Resolution Event."""

    def handle(self, event: Event) -> WorldUpdate:
        raise ValueError("DoorResolutionHandler requires authoritative WorldState")

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if not event.has_trusted_source("resolution"):
            raise PermissionError("door effects require a controlled Resolution Event")
        _validate_resolution_summary(event, effect_present=len(event.changes) > 1)
        raw_effects = event.changes[1:]
        if not raw_effects:
            return WorldUpdate("environment", "update", {})
        if any(
            not isinstance(change, Mapping)
            or change.get("effect_type") != "door_state_changed"
            for change in raw_effects
        ):
            raise LookupError("no installed EventHandler supports this Resolution effect")
        effects = raw_effects
        if len(effects) != 1 or len(event.changes) != 2:
            raise ValueError("door Resolution Event must contain one effect")
        effect = effects[0]
        if set(effect) != {"effect_type", "door_id", "expected", "state", "actor_id", "actor_location", "key_id"}:
            raise ValueError("door effect has unsupported fields")
        door_id, expected, state = effect["door_id"], effect["expected"], effect["state"]
        if not isinstance(door_id, str) or not isinstance(expected, DoorState) or not isinstance(state, DoorState):
            raise TypeError("door effect must contain typed door snapshots")
        if expected.door_id != door_id or state.door_id != door_id:
            raise ValueError("door effect identity mismatch")
        _validate_physical_effect_provenance(event, effect, target_id=door_id)
        if (
            expected.is_open
            or not state.is_open
            or state.is_locked
            or (state.interaction_location_id, state.hand_operable, state.key_id)
            != (expected.interaction_location_id, expected.hand_operable, expected.key_id)
        ):
            raise ValueError("door effect is not a supported open-state transition")
        current = world_state.environment.get(door_id)
        if current != expected:
            raise ValueError("door state changed after causal assessment")
        actor_id, actor_location, key_id = effect["actor_id"], effect["actor_location"], effect["key_id"]
        if not isinstance(actor_id, str) or world_state.locations.get(actor_id) != actor_location or actor_location != expected.interaction_location_id:
            raise ValueError("actor is no longer at the confirmed door interaction location")
        actor = world_state.get_entity(actor_id)
        if actor is None:
            raise ValueError("actor entity is no longer available")
        if not expected.hand_operable or actor.physical_capabilities is None or "manual_manipulation" not in actor.physical_capabilities:
            raise ValueError("required manual capability is no longer confirmed")
        if key_id is not None and key_id != expected.key_id:
            raise ValueError("required key does not match the confirmed door lock")
        if expected.is_locked and key_id != expected.key_id:
            raise ValueError("locked door transition requires its confirmed key")
        if not expected.is_locked and key_id is not None:
            raise ValueError("unlocked door transition must not claim a key use")
        if key_id is not None and ((key := world_state.get_entity(key_id)) is None or key.type != "tool" or key.owner_id != actor_id):
            raise ValueError("required key is not an authoritative tool entity")
        return WorldUpdate("environment", "update", {door_id: state})

    def observable_facts(self, event: Event, update: WorldUpdate) -> tuple[ObservableFactDraft, ...]:
        if not update.payload:
            return ()
        door_id, state = next(iter(update.payload.items()))
        if not isinstance(state, DoorState):
            return ()
        return (ObservableFactDraft(
            fact_type="environment_state",
            predicate="door_open",
            value=state.is_open,
            subject_ref=door_id,
            location_id=state.interaction_location_id,
        ),)


class PassageTraversalHandler(EventHandler):
    """Apply a resolution-confirmed move through a known passage."""

    def handle(self, event: Event) -> WorldUpdate:
        raise ValueError("PassageTraversalHandler requires authoritative WorldState")

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if not event.has_trusted_source("resolution"):
            raise PermissionError("passage traversal requires a controlled Resolution Event")
        _validate_resolution_summary(event, effect_present=True)
        if len(event.changes) != 2 or not isinstance(event.changes[1], Mapping):
            raise ValueError("passage Event must contain exactly one typed effect")
        effect = event.changes[1]
        required = {
            "effect_type", "passage_id", "expected", "actor_id",
            "expected_location", "destination_location",
        }
        if set(effect) != required or effect.get("effect_type") != "actor_location_changed":
            raise ValueError("unsupported passage effect fields")
        expected = effect["expected"]
        actor_id = effect["actor_id"]
        source = effect["expected_location"]
        destination = effect["destination_location"]
        passage_id = effect["passage_id"]
        if not isinstance(expected, PassageState) or expected.passage_id != passage_id:
            raise TypeError("passage effect must contain its typed expected snapshot")
        _validate_physical_effect_provenance(event, effect, target_id=passage_id)
        if (source, destination) != (expected.source_location_id, expected.destination_location_id):
            raise ValueError("passage effect locations do not match the trusted snapshot")
        if not expected.traversable:
            raise ValueError("passage effect cannot traverse a confirmed blocked passage")
        if world_state.environment.get(passage_id) != expected:
            raise ValueError("passage changed after causal assessment")
        if world_state.locations.get(actor_id) != source:
            raise ValueError("actor location changed after causal assessment")
        actor = world_state.get_entity(actor_id)
        if actor is None or actor.physical_capabilities is None or not any(
            cap in actor.physical_capabilities for cap in ("locomotion", "movement")
        ):
            raise ValueError("locomotion capability is not currently confirmed")
        return WorldUpdate("locations", "update", {actor_id: destination})

    def observable_facts(self, event: Event, update: WorldUpdate) -> tuple[ObservableFactDraft, ...]:
        if len(event.changes) != 2 or not isinstance(event.changes[1], Mapping):
            return ()
        effect = event.changes[1]
        if not update.payload or effect.get("effect_type") != "actor_location_changed":
            return ()
        actor_id = effect.get("actor_id")
        destination = effect.get("destination_location")
        if not isinstance(actor_id, str) or not isinstance(destination, str):
            return ()
        return (ObservableFactDraft(
            fact_type="movement",
            predicate="actor_arrived",
            value=destination,
            subject_ref=actor_id,
            location_id=destination,
        ),)


class ResolutionEffectsHandler(EventHandler):
    """Shared resolution event ingress for installed typed effect adapters."""

    def __init__(self) -> None:
        self._door = DoorResolutionHandler()
        self._passage = PassageTraversalHandler()

    def handle(self, event: Event) -> WorldUpdate:
        raise ValueError("ResolutionEffectsHandler requires authoritative WorldState")

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if not event.has_trusted_source("resolution"):
            raise PermissionError("Resolution effects require a controlled Event")
        if len(event.changes) == 1:
            _validate_resolution_summary(event, effect_present=False)
            return WorldUpdate("environment", "update", {})
        _validate_resolution_summary(event, effect_present=True)
        if not isinstance(event.changes[1], Mapping):
            raise ValueError("Resolution effect must be a typed mapping")
        effect_type = event.changes[1].get("effect_type")
        if effect_type == "door_state_changed":
            return self._door.handle_with_world_state(event, world_state)
        if effect_type == "actor_location_changed":
            return self._passage.handle_with_world_state(event, world_state)
        raise LookupError("no installed Resolution effect adapter supports this effect")

    def observable_facts(self, event: Event, update: WorldUpdate):
        if len(event.changes) > 1 and isinstance(event.changes[1], Mapping):
            if event.changes[1].get("effect_type") == "door_state_changed":
                return self._door.observable_facts(event, update)
            if event.changes[1].get("effect_type") == "actor_location_changed":
                return self._passage.observable_facts(event, update)
        return ()


class WorldNormsUpdatedHandler(EventHandler):
    """Apply an explicitly authorized rules-version change through EventProcessor."""

    def handle(self, event: Event) -> WorldUpdate:
        raise ValueError("WorldNormsUpdatedHandler requires authoritative WorldState")

    def handle_with_world_state(self, event: Event, world_state: WorldState) -> WorldUpdate:
        if not event.has_trusted_source("system"):
            raise PermissionError("WorldNorms changes require a controlled system Event")
        if len(event.changes) != 1 or not isinstance(event.changes[0], Mapping):
            raise ValueError("WorldNorms Event must contain one typed change")
        change = event.changes[0]
        if set(change) != {"expected_version_id", "world_norms"}:
            raise ValueError("WorldNorms change contains unsupported fields")
        current = world_state.world_norms
        replacement = change["world_norms"]
        if not isinstance(current, WorldNorms) or not isinstance(replacement, WorldNorms):
            raise ValueError("current and replacement WorldNorms must be validated snapshots")
        if change["expected_version_id"] != current.active_version_id:
            raise ValueError("WorldNorms update was prepared from a stale version")
        if replacement.world_id != current.world_id or replacement.active_version_id == current.active_version_id:
            raise ValueError("WorldNorms update must retain the world and select a new version")
        if replacement.versions[:len(current.versions) - 1] != current.versions[:len(current.versions) - 1]:
            raise ValueError("WorldNorms history cannot rewrite prior versions")
        if len(replacement.versions) != len(current.versions) + 1:
            raise ValueError("WorldNorms update must append exactly one version")
        previous, closed_previous = current.versions[-1], replacement.versions[len(current.versions) - 1]
        new_version = replacement.versions[-1]
        if (
            previous.version_id != closed_previous.version_id
            or previous.legal_rules != closed_previous.legal_rules
            or previous.social_norms != closed_previous.social_norms
            or closed_previous.effective_until_tick != new_version.effective_from_tick
            or new_version.version_id != replacement.active_version_id
            or event.simulation_tick != new_version.effective_from_tick
        ):
            raise ValueError("WorldNorms update must close the current version and append a new one")
        return WorldUpdate("world_norms", "set", {"value": replacement})

    def observable_facts(self, event: Event, update: WorldUpdate) -> tuple[ObservableFactDraft, ...]:
        # Rule text is not automatically public or automatically known by any Agent.
        # A separate audience-specific Observation policy must project it.
        return ()
