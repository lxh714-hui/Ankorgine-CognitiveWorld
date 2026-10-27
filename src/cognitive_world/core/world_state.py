"""Core world state data container with controlled accessors."""

from copy import deepcopy
import base64
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypeVar

from cognitive_world.core.event import Event
from cognitive_world.core.entity import Entity
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core._world_write import permit_matches
from cognitive_world.world_norms.models import WorldNorms
from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust, sha256_hex


EntityT = TypeVar("EntityT")
RelationshipT = TypeVar("RelationshipT")


@dataclass(frozen=True)
class WorldStateSlot:
    """Stable address of a value already present in a WorldState collection."""

    collection: Literal[
        "entities", "locations", "relationships", "facts", "environment", "world_norms"
    ]
    record_id: str | tuple[str, str]
    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.collection not in {
            "entities", "locations", "relationships", "facts", "environment", "world_norms"
        }:
            raise ValueError("slot collection is not a WorldState collection")
        if isinstance(self.record_id, str):
            if not self.record_id:
                raise ValueError("slot record_id must be non-empty")
        elif (self.collection != "relationships" or not isinstance(self.record_id, tuple)
              or len(self.record_id) != 2
              or any(not isinstance(part, str) or not part for part in self.record_id)):
            raise ValueError("slot record_id is invalid for its collection")
        if not isinstance(self.path, tuple) or any(
            not isinstance(part, str) or not part for part in self.path
        ):
            raise TypeError("slot path must be a tuple of non-empty field names")

    def to_record(self) -> dict[str, object]:
        return {"collection": self.collection, "record_id": self.record_id, "path": self.path}


@dataclass(frozen=True)
class WorldStateSlotRead:
    """Detached value snapshot plus its verified origin classification."""

    slot: WorldStateSlot
    value: object = field(compare=False, repr=False)
    present: bool
    value_fingerprint: str | None
    origin_kind: Literal["event", "initialization", "unknown", "unverified"]
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.slot, WorldStateSlot) or type(self.present) is not bool:
            raise TypeError("slot read requires a valid slot and presence flag")
        if self.value_fingerprint is not None and (
            not isinstance(self.value_fingerprint, str)
            or len(self.value_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in self.value_fingerprint)
        ):
            raise ValueError("slot value fingerprint must be a SHA-256 digest or unknown")
        if self.origin_kind not in {"event", "initialization", "unknown", "unverified"}:
            raise ValueError("unsupported slot origin kind")
        if (self.origin_kind == "event") != (self.source_event_id is not None):
            raise ValueError("only a verified Event origin may expose a source_event_id")
        if self.source_event_id is not None and not self.source_event_id:
            raise ValueError("source_event_id must be non-empty")

    def to_record(self) -> dict[str, object]:
        """Serialize provenance metadata without embedding the state value."""
        return {
            "slot": self.slot.to_record(),
            "present": self.present,
            "value_fingerprint": self.value_fingerprint,
            "origin_kind": self.origin_kind,
            "source_event_id": self.source_event_id,
        }


@dataclass(frozen=True)
class _SlotOrigin:
    kind: Literal["event", "initialization"]
    present: bool
    value_fingerprint: str | None
    event_id: str | None = None


def _canonical_state_value(value: object) -> object | None:
    """Return a bounded-by-shape JSON value for fingerprints, or None if unknown."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return _canonical_state_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        result = {}
        for item in fields(value):
            normalized = _canonical_state_value(getattr(value, item.name))
            if normalized is None and getattr(value, item.name) is not None:
                return None
            result[item.name] = normalized
        return result
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            return None
        result = {}
        for key, item in sorted(value.items()):
            normalized = _canonical_state_value(item)
            if normalized is None and item is not None:
                return None
            result[key] = normalized
        return result
    if isinstance(value, (tuple, list)):
        result = []
        for item in value:
            normalized = _canonical_state_value(item)
            if normalized is None and item is not None:
                return None
            result.append(normalized)
        return result
    return None


def _slot_fingerprint(present: bool, value: object) -> str | None:
    canonical = _canonical_state_value(value) if present else None
    if present and canonical is None and value is not None:
        return None
    encoded = json.dumps({"present": present, "value": canonical}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _leaf_slots(collection: str, record_id: str | tuple[str, str], value: object,
                path: tuple[str, ...] = ()) -> dict[WorldStateSlot, tuple[bool, object]]:
    if is_dataclass(value) and not isinstance(value, type):
        output: dict[WorldStateSlot, tuple[bool, object]] = {}
        for item in fields(value):
            output.update(_leaf_slots(collection, record_id, getattr(value, item.name),
                                      (*path, item.name)))
        return output
    if isinstance(value, Mapping) and value and all(isinstance(key, str) and key for key in value):
        output = {}
        for key, item in value.items():
            output.update(_leaf_slots(collection, record_id, item, (*path, key)))
        return output
    slot = WorldStateSlot(collection, record_id, path)
    return {slot: (True, value)}


@dataclass
class WorldState:
    """Stores the current world data behind controlled accessors."""

    _entities: dict[str, EntityT] = field(default_factory=dict, repr=False)
    _locations: dict[str, Any] = field(default_factory=dict, repr=False)
    _relationships: dict[tuple[str, str], RelationshipT] = field(
        default_factory=dict, repr=False
    )
    _facts: dict[str, Any] = field(default_factory=dict, repr=False)
    _environment: dict[str, Any] = field(default_factory=dict, repr=False)
    _environment_snapshot_complete: bool = field(default=False, repr=False)
    _initialization_sealed: bool = field(default=False, repr=False)
    _world_norms: WorldNorms | None = field(default=None, repr=False)
    _slot_origins: dict[WorldStateSlot, _SlotOrigin] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def _ensure_initialization_open(self) -> None:
        if self._initialization_sealed:
            raise PermissionError("WorldState initialization is closed after runtime processing begins")

    def _seal_initialization(self) -> None:
        """Close trusted load helpers when the first event enters processing."""
        self._initialization_sealed = True

    @property
    def entities(self) -> Mapping[str, EntityT]:
        return MappingProxyType(deepcopy(self._entities))

    @property
    def locations(self) -> Mapping[str, Any]:
        return MappingProxyType(deepcopy(self._locations))

    @property
    def relationships(self) -> Mapping[tuple[str, str], RelationshipT]:
        return MappingProxyType(deepcopy(self._relationships))

    @property
    def facts(self) -> Mapping[str, Any]:
        return MappingProxyType(deepcopy(self._facts))

    @property
    def environment(self) -> Mapping[str, Any]:
        return MappingProxyType(deepcopy(self._environment))

    @property
    def world_norms(self) -> WorldNorms | None:
        """Read-only current world rules; never exposes mutable WorldState internals."""
        return deepcopy(self._world_norms)

    def load_world_norms(self, norms: WorldNorms) -> None:
        """Install a schema-validated world rule package during initialization only."""
        self._ensure_initialization_open()
        if not isinstance(norms, WorldNorms):
            raise TypeError("norms must be a validated WorldNorms record")
        if self._world_norms is not None and self._world_norms.world_id != norms.world_id:
            raise ValueError("WorldNorms world_id cannot change")
        self._world_norms = deepcopy(norms)
        self._record_initialization("world_norms", norms.world_id, self._world_norms)

    @property
    def environment_snapshot_complete(self) -> bool:
        """Whether the current environment mapping is an explicitly complete snapshot.

        An empty mapping is unknown by default. Initialization/restoration may
        mark an empty mapping as known through ``load_environment_snapshot``.
        """
        return self._environment_snapshot_complete

    def load_entity(self, entity: EntityT) -> None:
        """Load an entity into the state without retaining its external reference."""
        self._ensure_initialization_open()
        self._entities[entity.id] = deepcopy(entity)
        self._record_initialization("entities", entity.id, self._entities[entity.id])

    def get_entity(self, entity_id: str) -> EntityT | None:
        """Return the entity with the given identifier, if present."""
        entity = self._entities.get(entity_id)
        return deepcopy(entity) if entity is not None else None

    def get_location(self, entity_id: str) -> Any | None:
        """Return one entity's current location without copying the full index."""
        return deepcopy(self._locations.get(entity_id))

    def get_environment_entry(self, reference: str) -> Any | None:
        """Return one current environment record without exposing the mapping."""
        return deepcopy(self._environment.get(reference))

    def get_owned_entities(self, owner_id: str) -> tuple[EntityT, ...]:
        """Return detached entities whose authoritative owner is ``owner_id``."""
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("owner_id must be non-empty")
        return tuple(
            deepcopy(entity)
            for entity in self._entities.values()
            if getattr(entity, "owner_id", None) == owner_id
        )

    def load_relationship(self, relationship: RelationshipT) -> None:
        """Load a relationship without retaining its external reference."""
        self._ensure_initialization_open()
        key = (relationship.source, relationship.target)
        from cognitive_world.core.physical import PhysicalRelation,validate_physical_world
        if type(relationship) is PhysicalRelation:
            validate_physical_world(self._entities,self._locations,{**self._relationships,key:relationship})
        self._relationships[key] = deepcopy(relationship)
        self._record_initialization("relationships", key, self._relationships[key])

    def load_fact(self, key: str, value: Any) -> None:
        """Load a generic fact value."""
        self._ensure_initialization_open()
        self._facts[key] = deepcopy(value)
        self._record_initialization("facts", key, self._facts[key])

    def load_environment_data(self, key: str, value: Any) -> None:
        """Load one environment entry without claiming the mapping is complete."""
        self._ensure_initialization_open()
        self._environment[key] = deepcopy(value)
        self._record_initialization("environment", key, self._environment[key])

    def load_environment_snapshot(self, values: Mapping[str, Any]) -> None:
        """Load an authoritative complete environment snapshot, including an empty one."""
        self._ensure_initialization_open()
        if not isinstance(values, Mapping):
            raise TypeError("environment snapshot must be a mapping")
        if any(not isinstance(key, str) or not key for key in values):
            raise ValueError("environment snapshot keys must be non-empty strings")
        self._environment = deepcopy(dict(values))
        self._environment_snapshot_complete = True
        self._drop_slot_origins("environment")
        for key, value in self._environment.items():
            self._record_initialization("environment", key, value)

    def load_location(self, entity_id: str, location_id: str) -> None:
        """Load an authoritative entity location during initialization/restoration."""
        self._ensure_initialization_open()
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("entity_id must be non-empty")
        if not isinstance(location_id, str) or not location_id:
            raise ValueError("location_id must be non-empty")
        self._locations[entity_id] = location_id
        self._record_initialization("locations", entity_id, location_id)

    def read_state_slot(
        self, slot: WorldStateSlot, *, event_history: object | None = None
    ) -> WorldStateSlotRead:
        """Read one detached slot and expose only a verifiable latest origin.

        Event IDs are exposed only when EventHistory contains the intact Event
        and the processor-issued evidence for that Event still validates.
        Missing and unverifiable lineage remain explicit.
        """
        if not isinstance(slot, WorldStateSlot):
            raise TypeError("slot must be a WorldStateSlot")
        present, value = self._resolve_slot(slot)
        fingerprint = _slot_fingerprint(present, value)
        origin = self._slot_origins.get(slot)
        if (fingerprint is None or origin is None or origin.present != present
                or origin.value_fingerprint != fingerprint):
            kind: Literal["event", "initialization", "unknown", "unverified"] = "unknown"
            event_id = None
        elif origin.kind == "initialization":
            kind = "initialization"
            event_id = None
        elif self._event_origin_is_authoritative(origin.event_id, event_history):
            kind = "event"
            event_id = origin.event_id
        else:
            kind = "unverified"
            event_id = None
        return WorldStateSlotRead(slot, deepcopy(value), present, fingerprint, kind, event_id)

    def verify_state_slot_read(
        self, read: WorldStateSlotRead, *, event_history: object | None = None
    ) -> bool:
        """Revalidate a read against current state and its recorded origin."""
        if not isinstance(read, WorldStateSlotRead) or read.value_fingerprint is None:
            return False
        current = self.read_state_slot(read.slot, event_history=event_history)
        return (
            current.present == read.present
            and current.value_fingerprint == read.value_fingerprint
            and current.origin_kind == read.origin_kind
            and current.source_event_id == read.source_event_id
            and read.origin_kind != "unverified"
        )

    def verify_state_slot_record(
        self, record: object, *, event_history: object | None = None
    ) -> bool:
        """Validate serialized slot provenance carried through a trusted Event."""
        if not isinstance(record, Mapping) or set(record) != {
            "slot", "present", "value_fingerprint", "origin_kind", "source_event_id"
        }:
            return False
        raw_slot = record["slot"]
        if not isinstance(raw_slot, Mapping) or set(raw_slot) != {
            "collection", "record_id", "path"
        }:
            return False
        try:
            slot = WorldStateSlot(
                raw_slot["collection"], raw_slot["record_id"], raw_slot["path"]
            )
            read = WorldStateSlotRead(
                slot=slot, value=None, present=record["present"],
                value_fingerprint=record["value_fingerprint"],
                origin_kind=record["origin_kind"], source_event_id=record["source_event_id"],
            )
        except (TypeError, ValueError):
            return False
        return self.verify_state_slot_read(read, event_history=event_history)

    def changed_slot_records_for_event(self, event_id: str) -> tuple[dict[str, object], ...]:
        """Return exact current slot fingerprints first changed by this Event."""
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id must be non-empty")
        records = []
        for slot, origin in self._slot_origins.items():
            if origin.kind != "event" or origin.event_id != event_id:
                continue
            present, value = self._resolve_slot(slot)
            fingerprint = _slot_fingerprint(present, value)
            if fingerprint is None or origin.present != present or origin.value_fingerprint != fingerprint:
                continue
            records.append({
                "slot": slot.to_record(), "present": present,
                "value_fingerprint": fingerprint,
            })
        return tuple(sorted(records, key=lambda item: json.dumps(
            item, sort_keys=True, separators=(",", ":")
        )))

    def export_persisted_snapshot(
        self, *, event_history: object, simulation_tick: int,
        trust: PersistenceTrust, timeline_id: str,
        codec: PersistedValueCodec | None = None,
    ) -> bytes:
        """Export a signed, versioned snapshot; unsupported values fail closed."""
        from cognitive_world.event.history import EventHistory
        if type(event_history) is not EventHistory:
            raise TypeError("event_history must be the canonical EventHistory")
        if (isinstance(simulation_tick, bool) or not isinstance(simulation_tick, int)
                or simulation_tick < 0):
            raise ValueError("simulation_tick must be a non-negative integer")
        if not isinstance(timeline_id, str) or not timeline_id:
            raise ValueError("timeline_id must be a non-empty string")
        if not callable(getattr(trust, "sign", None)) or not callable(getattr(trust, "verify", None)):
            raise TypeError("trust must expose sign and verify")
        from cognitive_world.core.physical import validate_physical_world
        validate_physical_world(self._entities, self._locations, self._relationships)
        codec = codec or PersistedValueCodec()
        event_history_state = event_history.export_persisted_state(timeline_id=timeline_id)
        # Verify every timeline segment before signing the checkpoint body.
        _, _, attestations = event_history.verify_persisted_lineage(
            codec=codec, trust=trust,
        )
        event_attestations = {item["event_id"]: item for item in attestations}
        origins = []
        current_slots: dict[WorldStateSlot, tuple[bool, object]] = {}
        for collection, records in (
            ("entities", self._entities), ("locations", self._locations),
            ("relationships", self._relationships), ("facts", self._facts),
            ("environment", self._environment),
        ):
            for record_id, value in records.items():
                current_slots.update(_leaf_slots(collection, record_id, value))
        if self._world_norms is not None:
            current_slots.update(_leaf_slots("world_norms", self._world_norms.world_id,
                                             self._world_norms))
        for slot in self._slot_origins:
            current_slots.setdefault(slot, self._resolve_slot(slot))
        for slot, (present, value) in current_slots.items():
            fingerprint = _slot_fingerprint(present, value)
            origin = self._slot_origins.get(slot)
            kind = "unknown"
            event_id = None
            if origin is not None:
                if (origin.present != present or origin.value_fingerprint != fingerprint
                        or fingerprint is None):
                    raise PermissionError("WorldState slot origin is stale; refusing checkpoint")
                if origin.kind == "initialization":
                    kind = "initialization"
                elif origin.kind == "event":
                    event_id = origin.event_id
                    attestation = event_attestations.get(event_id)
                    if attestation is None:
                        raise PermissionError("slot source Event lacks a trusted persistence record")
                    expected = {
                        "slot": slot.to_record(), "present": present,
                        "value_fingerprint": fingerprint,
                    }
                    expected = json.loads(json.dumps(expected, sort_keys=True))
                    if expected not in attestation["changed_slots"]:
                        raise PermissionError("slot source Event did not attest this resulting value")
                    read = self.read_state_slot(slot, event_history=event_history)
                    if read.origin_kind != "event" or read.source_event_id != event_id:
                        raise PermissionError("slot source is not currently authoritative")
                    kind = "event"
                else:
                    raise PermissionError("unsupported WorldState slot origin")
            origins.append({
                "slot": slot.to_record(), "present": present,
                "value_fingerprint": fingerprint, "origin_kind": kind,
                "source_event_id": event_id,
            })
        body = {
            "entities": self._entities, "locations": self._locations,
            "relationships": self._relationships, "facts": self._facts,
            "environment": self._environment, "world_norms": self._world_norms,
            "environment_snapshot_complete": self._environment_snapshot_complete,
            "initialization_sealed": self._initialization_sealed,
            "slot_origins": origins,
            "event_history": event_history_state,
        }
        body_bytes = codec.dumps(body)
        digest = sha256_hex(body_bytes)
        signed = json.dumps({
            "schema": "cognitive-world/world-state-checkpoint",
            "version": 3, "timeline_id": timeline_id,
            "simulation_tick": simulation_tick,
            "body_sha256": digest,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = trust.sign("cognitive-world/world-state-checkpoint/v3", signed)
        if not isinstance(signature, bytes) or not signature:
            raise TypeError("persistence trust authority returned an invalid signature")
        return json.dumps({
            "schema": "cognitive-world/world-state-checkpoint", "version": 3,
            "timeline_id": timeline_id,
            "simulation_tick": simulation_tick, "body": base64.b64encode(body_bytes).decode("ascii"),
            "body_sha256": digest, "signature": base64.b64encode(signature).decode("ascii"),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def restore_persisted_snapshot(
        cls, payload: bytes, *, trust: PersistenceTrust,
        codec: PersistedValueCodec | None = None,
        event_history_resolver: object | None = None,
    ) -> tuple["WorldState", object, int]:
        """Verify then construct an isolated WorldState and EventHistory pair."""
        from cognitive_world.event.history import EventHistory
        from cognitive_world.event.persistence import PersistedEventRecord
        if not callable(getattr(trust, "verify", None)):
            raise TypeError("trust must expose verify")
        codec = codec or PersistedValueCodec()
        if not isinstance(payload, bytes) or len(payload) > 128 * 1024 * 1024:
            raise ValueError("snapshot is invalid or exceeds 128 MiB")
        try:
            envelope = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("snapshot envelope is malformed") from None
        expected_keys = {"schema", "version", "timeline_id", "simulation_tick", "body", "body_sha256", "signature"}
        if (not isinstance(envelope, dict) or set(envelope) != expected_keys
                or envelope["schema"] != "cognitive-world/world-state-checkpoint"
                or envelope["version"] != 3
                or not isinstance(envelope["timeline_id"], str)
                or not envelope["timeline_id"]
                or isinstance(envelope["simulation_tick"], bool)
                or not isinstance(envelope["simulation_tick"], int)
                or envelope["simulation_tick"] < 0):
            raise ValueError("unsupported WorldState checkpoint version or schema")
        try:
            body_bytes = base64.b64decode(envelope["body"], validate=True)
            signature = base64.b64decode(envelope["signature"], validate=True)
        except (ValueError, TypeError):
            raise ValueError("invalid WorldState checkpoint encoding") from None
        if sha256_hex(body_bytes) != envelope["body_sha256"]:
            raise PermissionError("WorldState checkpoint content digest mismatch")
        signed = json.dumps({
            "schema": envelope["schema"], "version": envelope["version"],
            "timeline_id": envelope["timeline_id"],
            "simulation_tick": envelope["simulation_tick"],
            "body_sha256": envelope["body_sha256"],
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if not trust.verify("cognitive-world/world-state-checkpoint/v3", signed, signature):
            raise PermissionError("WorldState checkpoint trust verification failed")
        body = codec.loads(body_bytes)
        required = {
            "entities", "locations", "relationships", "facts", "environment",
            "world_norms", "environment_snapshot_complete", "initialization_sealed",
            "slot_origins", "event_history",
        }
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError("WorldState checkpoint body has an invalid shape")
        if (any(not isinstance(body[name], dict) for name in
                ("entities", "locations", "relationships", "facts", "environment"))
                or (body["world_norms"] is not None and not isinstance(body["world_norms"], WorldNorms))
                or type(body["environment_snapshot_complete"]) is not bool
                or type(body["initialization_sealed"]) is not bool
                or not isinstance(body["slot_origins"], list)
                or not isinstance(body["event_history"], dict)):
            raise ValueError("WorldState checkpoint values have invalid types")
        restored_history = EventHistory.from_persisted_state(
            body["event_history"], codec=codec, trust=trust,
            parent_history_resolver=event_history_resolver,
        )
        if restored_history.timeline_id != envelope["timeline_id"]:
            raise PermissionError("checkpoint Timeline does not match EventHistory lineage")
        restored = cls(
            _entities=deepcopy(body["entities"]), _locations=deepcopy(body["locations"]),
            _relationships=deepcopy(body["relationships"]), _facts=deepcopy(body["facts"]),
            _environment=deepcopy(body["environment"]),
            _environment_snapshot_complete=body["environment_snapshot_complete"],
            _initialization_sealed=body["initialization_sealed"],
            _world_norms=deepcopy(body["world_norms"]),
        )
        from cognitive_world.core.physical import validate_physical_world
        validate_physical_world(restored._entities,restored._locations,restored._relationships)
        actual_slots: dict[WorldStateSlot, tuple[bool, object]] = {}
        for collection, values in (
            ("entities", restored._entities), ("locations", restored._locations),
            ("relationships", restored._relationships), ("facts", restored._facts),
            ("environment", restored._environment),
        ):
            for record_id, value in values.items():
                actual_slots.update(_leaf_slots(collection, record_id, value))
        if restored._world_norms is not None:
            actual_slots.update(_leaf_slots("world_norms", restored._world_norms.world_id,
                                            restored._world_norms))
        seen_slots: set[WorldStateSlot] = set()
        expected_slots = set(actual_slots)
        attestation_by_event = {}
        _, _, attestations = restored_history.verify_persisted_lineage(
            codec=codec, trust=trust, parent_history_resolver=event_history_resolver,
        )
        attestation_by_event = {item["event_id"]: item for item in attestations}
        for item in body["slot_origins"]:
            if not isinstance(item, dict) or set(item) != {
                "slot", "present", "value_fingerprint", "origin_kind", "source_event_id"
            }:
                raise ValueError("malformed slot-origin record")
            raw_slot = item["slot"]
            if not isinstance(raw_slot, dict) or set(raw_slot) != {"collection", "record_id", "path"}:
                raise ValueError("malformed slot address")
            slot = WorldStateSlot(raw_slot["collection"], raw_slot["record_id"], tuple(raw_slot["path"]))
            if slot in seen_slots:
                raise ValueError("duplicate WorldState slot origin")
            expected_slots.add(slot)
            present, value = actual_slots.get(slot, restored._resolve_slot(slot))
            fingerprint = _slot_fingerprint(present, value)
            if (item["present"] is not present or item["value_fingerprint"] != fingerprint
                    or fingerprint is None):
                raise PermissionError("snapshot slot value does not match its signed provenance")
            kind, event_id = item["origin_kind"], item["source_event_id"]
            if kind == "unknown":
                if event_id is not None:
                    raise ValueError("unknown slot origin cannot name an Event")
            elif kind == "initialization":
                if event_id is not None:
                    raise ValueError("initialization origin cannot name an Event")
                restored._slot_origins[slot] = _SlotOrigin("initialization", present, fingerprint)
            elif kind == "event":
                if not isinstance(event_id, str) or event_id not in attestation_by_event:
                    raise PermissionError("slot references an absent or unauthenticated Event")
                expected = {"slot": slot.to_record(), "present": present,
                            "value_fingerprint": fingerprint}
                expected = json.loads(json.dumps(expected, sort_keys=True))
                if expected not in attestation_by_event[event_id]["changed_slots"]:
                    raise PermissionError("Event attestation does not bind this slot value")
                restored._slot_origins[slot] = _SlotOrigin("event", present, fingerprint, event_id)
            else:
                raise ValueError("unsupported slot origin classification")
            seen_slots.add(slot)
        # Every current leaf is represented, including explicitly unknown lineage.
        if seen_slots != expected_slots:
            raise ValueError("checkpoint omits or invents WorldState slot provenance")
        for slot, origin in restored._slot_origins.items():
            read = restored.read_state_slot(slot, event_history=restored_history)
            expected_kind = "initialization" if origin.kind == "initialization" else "event"
            if read.origin_kind != expected_kind or (
                expected_kind == "event" and read.source_event_id != origin.event_id
            ):
                raise PermissionError("restored slot provenance failed EventHistory verification")
        return restored, restored_history, envelope["simulation_tick"]

    def _event_origin_is_authoritative(
        self, event_id: str | None, event_history: object | None
    ) -> bool:
        if not isinstance(event_id, str) or event_history is None:
            return False
        get_event = getattr(event_history, "get_event", None)
        get_evidence = getattr(event_history, "get_processing_evidence", None)
        event = get_event(event_id) if callable(get_event) else None
        evidence = get_evidence(event_id) if callable(get_evidence) else None
        return (
            isinstance(event, Event) and event.has_trusted_source()
            and evidence is not None
            and callable(getattr(evidence, "has_trusted_source", None))
            and evidence.has_trusted_source(event)
        )

    def _resolve_slot(self, slot: WorldStateSlot) -> tuple[bool, object]:
        if slot.collection == "world_norms":
            record = self._world_norms if (
                self._world_norms is not None and self._world_norms.world_id == slot.record_id
            ) else None
        else:
            store = {
                "entities": self._entities, "locations": self._locations,
                "relationships": self._relationships, "facts": self._facts,
                "environment": self._environment,
            }[slot.collection]
            record = store.get(slot.record_id)
        if record is None:
            return False, None
        value = record
        for part in slot.path:
            if isinstance(value, Mapping) and part in value:
                value = value[part]
            elif (is_dataclass(value) and not isinstance(value, type)
                  and part in value.__dataclass_fields__):
                value = getattr(value, part)
            else:
                return False, None
        return True, value

    def _drop_slot_origins(self, collection: str, record_id: object | None = None) -> None:
        self._slot_origins = {
            slot: origin for slot, origin in self._slot_origins.items()
            if not (slot.collection == collection
                    and (record_id is None or slot.record_id == record_id))
        }

    def _record_initialization(
        self, collection: str, record_id: str | tuple[str, str], value: object
    ) -> None:
        self._drop_slot_origins(collection, record_id)
        for slot, (present, current) in _leaf_slots(collection, record_id, value).items():
            self._slot_origins[slot] = _SlotOrigin(
                "initialization", present, _slot_fingerprint(present, current)
            )

    def _record_event_slot_changes(
        self,
        collection: str,
        before: Mapping[object, object],
        after: Mapping[object, object],
        event_id: str,
        origins: dict[WorldStateSlot, _SlotOrigin],
    ) -> None:
        before_slots: dict[WorldStateSlot, tuple[bool, object]] = {}
        after_slots: dict[WorldStateSlot, tuple[bool, object]] = {}
        for record_id, value in before.items():
            before_slots.update(_leaf_slots(collection, record_id, value))
        for record_id, value in after.items():
            after_slots.update(_leaf_slots(collection, record_id, value))
        for slot in before_slots.keys() | after_slots.keys():
            old_present, old_value = before_slots.get(slot, (False, None))
            new_present, new_value = after_slots.get(slot, (False, None))
            old_fingerprint = _slot_fingerprint(old_present, old_value)
            new_fingerprint = _slot_fingerprint(new_present, new_value)
            if old_present != new_present or old_fingerprint != new_fingerprint:
                origins[slot] = _SlotOrigin("event", new_present, new_fingerprint, event_id)

    def prepare_possession_transition(self, transition):
        """Read-only staging shared by pre-apply validation and final publication."""
        from cognitive_world.core.physical import PossessionTransition, PhysicalRelation, validate_physical_world
        if type(transition) is not PossessionTransition:
            raise TypeError("closed possession transition required")
        transition.__post_init__()
        t = transition
        item, actor = self._entities.get(t.item_id), self._entities.get(t.actor_id)
        if (item is None or actor is None or actor.type not in {"character", "agent"}
                or item.type in {"character", "agent", "location"}
                or item.id != t.item_id or actor.id != t.actor_id
                or item.owner_id != t.expected_owner
                or self._locations.get(t.item_id) != t.expected_location
                or self._locations.get(t.actor_id) != t.expected_location
                or self._entities.get(t.expected_location) is None
                or self._entities[t.expected_location].type != "location"):
            raise PermissionError("possession identities/location/owner changed or unsupported")
        for relation in self._relationships.values():
            if type(relation) is not PhysicalRelation:
                continue
            if relation.source == t.item_id and "held_by" in relation.kinds:
                raise PermissionError("item already has a holder")
            if t.item_id in (relation.source, relation.target) and set(relation.kinds) & {"part_of", "attached_to"}:
                raise PermissionError("structured items are unsupported")
        if self._relationships.get((t.item_id, t.actor_id)) != t.expected_relation:
            raise PermissionError("destination relation changed")
        locations, relations = deepcopy(self._locations), deepcopy(self._relationships)
        locations[t.item_id] = t.actor_id
        relations[(t.item_id, t.actor_id)] = t.relation
        validate_physical_world(self._entities, locations, relations)
        return locations, relations

    def apply_event(self, event: Event, update: WorldUpdate) -> None:
        """Apply an update only inside EventProcessor's scoped commit capability.

        ``update.target_id`` identifies one of this state's top-level
        collections. ``set`` replaces that collection, while ``update`` merges
        the supplied keys into it. The Event is the authority for entering this
        runtime update boundary; event-specific handlers must validate effects
        before this method is reached.
        """
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        if not isinstance(update, WorldUpdate):
            raise TypeError("update must be a WorldUpdate")
        if not permit_matches(self, event, update):
            raise PermissionError("WorldState events can only be applied by EventProcessor")

        if update.target_id == "item_possession":
            if update.operation != "take" or update.metadata:
                raise ValueError("unsupported possession operation")
            locations, relations = self.prepare_possession_transition(update.payload)
            origins = dict(self._slot_origins)
            self._record_event_slot_changes("locations", self._locations, locations, event.id, origins)
            self._record_event_slot_changes("relationships", self._relationships, relations, event.id, origins)
            self._locations, self._relationships, self._slot_origins = locations, relations, origins
            return

        if update.target_id == "runtime_content":
            from cognitive_world.content.installation import (ContentInstallationRecord,
                                                               WorldContentBatch,
                                                               installation_record_key)
            from cognitive_world.core.door import DoorState
            from cognitive_world.core.passage import PassageState
            if (update.operation != "install" or type(update.payload) is not WorldContentBatch
                    or event.type != "runtime_content_installed" or not event.has_trusted_source("system")):
                raise PermissionError("runtime content requires its controlled installation Event")
            batch = deepcopy(update.payload)
            if (type(batch.record) is not ContentInstallationRecord
                    or batch.record.status != "world_installed"
                    or batch.record.installation_event_id != event.id
                    or batch.record_key != installation_record_key(batch.record.world_id, batch.record.instance_id)
                    or any(type(entity) is not Entity for entity in batch.entities)
                    or any(type(value) not in (DoorState, PassageState) for _, value in batch.environment)):
                raise TypeError("runtime content world batch has invalid typed records")
            entity_ids = [entity.id for entity in batch.entities]
            location_ids = [key for key, _ in batch.locations]
            environment_ids = [key for key, _ in batch.environment]
            if (len(entity_ids) != len(set(entity_ids)) or len(location_ids) != len(set(location_ids))
                    or len(environment_ids) != len(set(environment_ids))
                    or any(key in self._entities for key in entity_ids)
                    or any(key in self._locations for key in location_ids)
                    or any(key in self._environment for key in environment_ids)
                    or batch.record_key in self._facts):
                raise ValueError("runtime content identity conflicts with authoritative WorldState")
            if any(location not in self._entities and location not in entity_ids
                   for _, location in batch.locations):
                raise ValueError("runtime content location reference is missing")
            new_entities = deepcopy(self._entities)
            new_locations = deepcopy(self._locations)
            new_environment = deepcopy(self._environment)
            new_facts = deepcopy(self._facts)
            new_entities.update({entity.id: entity for entity in batch.entities})
            new_locations.update(dict(batch.locations))
            new_environment.update(dict(batch.environment))
            new_facts[batch.record_key] = batch.record
            from cognitive_world.core.physical import PhysicalRelation,validate_physical_world
            if set(update.metadata) - {"physical_relations"}:raise ValueError("unsupported installation metadata")
            relations=update.metadata.get("physical_relations",())
            if type(relations) is not tuple or any(type(r) is not PhysicalRelation for r in relations):
                raise TypeError("typed installation relations required")
            new_relationships=deepcopy(self._relationships)
            for relation in relations:
                key=(relation.source,relation.target)
                if key in new_relationships:raise ValueError("relationship identity conflict")
                new_relationships[key]=relation
            validate_physical_world(new_entities,new_locations,new_relationships)
            new_origins = dict(self._slot_origins)
            self._record_event_slot_changes("entities", self._entities, new_entities, event.id, new_origins)
            self._record_event_slot_changes("locations", self._locations, new_locations, event.id, new_origins)
            self._record_event_slot_changes("environment", self._environment, new_environment, event.id, new_origins)
            self._record_event_slot_changes("facts", self._facts, new_facts, event.id, new_origins)
            self._record_event_slot_changes("relationships",self._relationships,new_relationships,event.id,new_origins)
            self._relationships=new_relationships
            self._entities, self._locations = new_entities, new_locations
            self._environment, self._facts = new_environment, new_facts
            self._slot_origins = new_origins
            return

        if update.target_id == "world_norms":
            if update.operation != "set" or not isinstance(update.payload, Mapping) or set(update.payload) != {"value"}:
                raise ValueError("world_norms updates must replace the validated snapshot")
            replacement = update.payload["value"]
            if not isinstance(replacement, WorldNorms):
                raise TypeError("world_norms update requires a validated WorldNorms snapshot")
            if self._world_norms is not None and replacement.world_id != self._world_norms.world_id:
                raise ValueError("WorldNorms world_id cannot change during runtime")
            new_norms = deepcopy(replacement)
            new_origins = dict(self._slot_origins)
            before = {} if self._world_norms is None else {self._world_norms.world_id: self._world_norms}
            after = {new_norms.world_id: new_norms}
            self._record_event_slot_changes("world_norms", before, after, event.id, new_origins)
            self._world_norms = new_norms
            self._slot_origins = new_origins
            return

        collections: dict[str, dict[Any, Any]] = {
            "entities": self._entities,
            "locations": self._locations,
            "relationships": self._relationships,
            "facts": self._facts,
            "environment": self._environment,
        }
        try:
            target = collections[update.target_id]
        except KeyError:
            raise ValueError(
                f"Unknown WorldState collection: {update.target_id}"
            ) from None

        if update.operation not in {"set", "update"}:
            raise ValueError(f"Unsupported WorldUpdate operation: {update.operation}")
        if not isinstance(update.payload, Mapping):
            raise TypeError("WorldUpdate payload must be a mapping")

        copied_payload = deepcopy(dict(update.payload))
        staged = deepcopy(target)
        if update.operation == "set":
            staged.clear()
        staged.update(copied_payload)
        from cognitive_world.core.physical import validate_physical_world
        validate_physical_world(staged if update.target_id=="entities" else self._entities,
            staged if update.target_id=="locations" else self._locations,
            staged if update.target_id=="relationships" else self._relationships)
        new_origins = dict(self._slot_origins)
        self._record_event_slot_changes(
            update.target_id, target, staged, event.id, new_origins
        )
        # Publish the staged collection and its matching provenance only after
        # all copying, validation, and fingerprint work has succeeded.
        setattr(self, f"_{update.target_id}", staged)
        self._slot_origins = new_origins
        if update.target_id == "environment" and update.operation == "set":
            # WorldUpdate.set replaces the whole environment collection, so
            # even an explicitly empty payload is a complete known snapshot.
            self._environment_snapshot_complete = True
