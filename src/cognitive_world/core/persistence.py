"""Explicit value encoding and injected trust authority for durable checkpoints.

The codec is deliberately allow-listed. Hosts must register application value
types before attempting a checkpoint; arbitrary import paths from save files
are never imported.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import base64
from contextlib import contextmanager
import ctypes
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import threading
from typing import Protocol


class PersistenceTrust(Protocol):
    """Host-owned signing and verification boundary for durable evidence."""

    def sign(self, purpose: str, payload: bytes) -> bytes: ...
    def verify(self, purpose: str, payload: bytes, signature: bytes) -> bool: ...


class HmacPersistenceTrust:
    """Raw-key HMAC adapter for deterministic tests and explicit host injection.

    This class does not manage a production key lifecycle. Desktop composition
    should use :class:`WindowsDpapiPersistenceTrust` instead.
    """

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("persistence trust key must contain at least 32 bytes")
        self._key = bytes(key)

    def sign(self, purpose: str, payload: bytes) -> bytes:
        if not purpose or not isinstance(payload, bytes):
            raise ValueError("purpose and payload are required")
        return hmac.new(self._key, purpose.encode() + b"\0" + payload, hashlib.sha256).digest()

    def verify(self, purpose: str, payload: bytes, signature: bytes) -> bool:
        return isinstance(signature, bytes) and hmac.compare_digest(
            self.sign(purpose, payload), signature
        )


class WindowsDpapiPersistenceTrust:
    """Current-user DPAPI protected HMAC key ring for a local Windows install.

    Initialization is explicit. Verification never creates or replaces keys,
    and signatures carry a versioned algorithm/key-id envelope. DPAPI binds the
    protected key to the current Windows user profile; it is not a defense
    against same-user malicious processes or a portable cross-device key.
    """

    _FORMAT = "cognitive-world-persistence-signature"
    _VERSION = 1
    _ALGORITHM = "hmac-sha256"
    _PURPOSE = b"CognitiveWorld persistence root v1"
    _MAX_RING_BYTES = 64 * 1024
    _process_lock = threading.RLock()

    def __init__(self, key_file: str | os.PathLike[str]) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI persistence trust is available only on Windows")
        self._path = Path(key_file)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")

    @classmethod
    def default_path(cls) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise OSError("LOCALAPPDATA is unavailable; persistence trust is not configured")
        return Path(local_app_data) / "CognitiveWorld" / "persistence-trust.json"

    @classmethod
    def initialize(cls, key_file: str | os.PathLike[str] | None = None) -> "WindowsDpapiPersistenceTrust":
        """Create the root exactly once; never overwrite an existing trust root."""
        instance = cls(key_file or cls.default_path())
        instance._path.parent.mkdir(parents=True, exist_ok=True)
        with instance._file_lock():
            if instance._path.exists():
                raise FileExistsError("persistence trust root already exists")
            entry = instance._new_key_entry()
            instance._write_ring_exclusive({
                "format": "cognitive-world-dpapi-key-ring",
                "version": 1,
                "algorithm": cls._ALGORITHM,
                "active_key_id": entry["key_id"],
                "keys": [entry],
            })
        return instance

    @classmethod
    def open(cls, key_file: str | os.PathLike[str] | None = None) -> "WindowsDpapiPersistenceTrust":
        """Open an existing root. Missing/corrupt roots fail closed."""
        instance = cls(key_file or cls.default_path())
        with instance._file_lock():
            instance._load_ring()
        return instance

    @property
    def active_key_id(self) -> str:
        with self._file_lock():
            return self._load_ring()["active_key_id"]

    def sign(self, purpose: str, payload: bytes) -> bytes:
        if not isinstance(purpose, str) or not purpose or not isinstance(payload, bytes):
            raise ValueError("purpose and byte payload are required")
        with self._file_lock():
            ring = self._load_ring()
            entry = next(item for item in ring["keys"] if item["key_id"] == ring["active_key_id"])
            key = self._unprotect(entry["protected_key"])
            descriptor = self._signature_descriptor(purpose, entry["key_id"])
            mac = hmac.new(key, descriptor + b"\0" + payload, hashlib.sha256).digest()
            return json.dumps({
                **json.loads(descriptor.decode("utf-8")),
                "signature": base64.b64encode(mac).decode("ascii"),
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def verify(self, purpose: str, payload: bytes, signature: bytes) -> bool:
        if (not isinstance(purpose, str) or not purpose or not isinstance(payload, bytes)
                or not isinstance(signature, bytes)):
            return False
        try:
            envelope = json.loads(signature.decode("utf-8"))
            required = {"format", "version", "algorithm", "key_id", "purpose", "signature"}
            if (not isinstance(envelope, dict) or set(envelope) != required
                    or envelope["format"] != self._FORMAT
                    or envelope["version"] != self._VERSION
                    or envelope["algorithm"] != self._ALGORITHM
                    or envelope["purpose"] != purpose
                    or not isinstance(envelope["key_id"], str)):
                return False
            mac = base64.b64decode(envelope["signature"], validate=True)
            with self._file_lock():
                ring = self._load_ring()
                entry = next((item for item in ring["keys"] if item["key_id"] == envelope["key_id"]), None)
                if entry is None:
                    return False
                key = self._unprotect(entry["protected_key"])
            descriptor = self._signature_descriptor(purpose, envelope["key_id"])
            expected = hmac.new(key, descriptor + b"\0" + payload, hashlib.sha256).digest()
            return hmac.compare_digest(expected, mac)
        except (OSError, ValueError, TypeError, KeyError, StopIteration, UnicodeDecodeError,
                json.JSONDecodeError, base64.binascii.Error):
            return False

    def rotate(self) -> str:
        """Activate a new key while retaining old keys for verification."""
        with self._file_lock():
            ring = self._load_ring()
            entry = self._new_key_entry()
            if any(item["key_id"] == entry["key_id"] for item in ring["keys"]):
                raise RuntimeError("generated duplicate persistence key identity")
            ring["keys"].append(entry)
            ring["active_key_id"] = entry["key_id"]
            self._replace_ring(ring)
            return entry["key_id"]

    def revoke(self, key_id: str) -> None:
        """Explicitly revoke a key; revoking the active key is prohibited."""
        with self._file_lock():
            ring = self._load_ring()
            if key_id == ring["active_key_id"]:
                raise ValueError("rotate before revoking the active persistence key")
            remaining = [item for item in ring["keys"] if item["key_id"] != key_id]
            if len(remaining) == len(ring["keys"]):
                raise KeyError("unknown persistence key ID")
            ring["keys"] = remaining
            self._replace_ring(ring)

    def _new_key_entry(self) -> dict[str, str]:
        key = secrets.token_bytes(32)
        return {
            "key_id": hashlib.sha256(key).hexdigest()[:24],
            "protected_key": base64.b64encode(self._protect(key)).decode("ascii"),
        }

    @classmethod
    def _signature_descriptor(cls, purpose: str, key_id: str) -> bytes:
        return json.dumps({
            "format": cls._FORMAT, "version": cls._VERSION,
            "algorithm": cls._ALGORITHM, "key_id": key_id, "purpose": purpose,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _load_ring(self) -> dict[str, object]:
        if not self._path.exists():
            raise FileNotFoundError("persistence trust root is not initialized")
        raw = self._path.read_bytes()
        if len(raw) > self._MAX_RING_BYTES:
            raise ValueError("persistence trust root exceeds size limit")
        value = json.loads(raw.decode("utf-8"))
        if (not isinstance(value, dict) or set(value) != {
                "format", "version", "algorithm", "active_key_id", "keys"
            } or value["format"] != "cognitive-world-dpapi-key-ring"
                or value["version"] != 1 or value["algorithm"] != self._ALGORITHM
                or not isinstance(value["active_key_id"], str)
                or not isinstance(value["keys"], list) or not value["keys"]):
            raise ValueError("persistence trust root format is invalid")
        ids = set()
        for entry in value["keys"]:
            if (not isinstance(entry, dict) or set(entry) != {"key_id", "protected_key"}
                    or not isinstance(entry["key_id"], str) or not entry["key_id"]
                    or not isinstance(entry["protected_key"], str)):
                raise ValueError("persistence trust key entry is invalid")
            if entry["key_id"] in ids:
                raise ValueError("duplicate persistence key ID")
            ids.add(entry["key_id"])
            key = self._unprotect(entry["protected_key"])
            if len(key) != 32 or hashlib.sha256(key).hexdigest()[:24] != entry["key_id"]:
                raise PermissionError("protected persistence key identity mismatch")
        if value["active_key_id"] not in ids:
            raise ValueError("active persistence key ID is absent")
        return value

    def _write_ring_exclusive(self, ring: dict[str, object]) -> None:
        payload = json.dumps(ring, sort_keys=True, separators=(",", ":")).encode("utf-8")
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def _replace_ring(self, ring: dict[str, object]) -> None:
        payload = json.dumps(ring, sort_keys=True, separators=(",", ":")).encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=".cw-trust-", dir=self._path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    @classmethod
    def _crypt(cls, data: bytes, *, protect: bool) -> bytes:
        import ctypes
        if os.name != "nt":
            raise OSError("Windows DPAPI is unavailable")
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(cls._DataBlob), ctypes.c_wchar_p,
            ctypes.POINTER(cls._DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(cls._DataBlob),
        ]
        crypt32.CryptProtectData.restype = ctypes.c_int
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(cls._DataBlob), ctypes.c_void_p,
            ctypes.POINTER(cls._DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(cls._DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        source_buffer = ctypes.create_string_buffer(data)
        entropy_buffer = ctypes.create_string_buffer(cls._PURPOSE)
        source = cls._DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        entropy = cls._DataBlob(len(cls._PURPOSE), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = cls._DataBlob()
        if protect:
            ok = crypt32.CryptProtectData(ctypes.byref(source), "CognitiveWorld persistence key",
                                          ctypes.byref(entropy), None, None, 0x1, ctypes.byref(output))
        else:
            ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy),
                                            None, None, 0x1, ctypes.byref(output))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    @classmethod
    def _protect(cls, key: bytes) -> bytes:
        return cls._crypt(key, protect=True)

    @classmethod
    def _unprotect(cls, protected: str) -> bytes:
        try:
            blob = base64.b64decode(protected, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError("protected persistence key encoding is invalid") from None
        return cls._crypt(blob, protect=False)

    @contextmanager
    def _file_lock(self):
        """Coordinate key-ring operations across threads and processes on Windows."""
        import msvcrt
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._process_lock:
            with open(self._lock_path, "a+b") as lock_file:
                lock_file.seek(0)
                if lock_file.read(1) == b"":
                    lock_file.seek(0)
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


class PersistedValueCodec:
    """Encode bounded JSON values and explicitly registered dataclasses/enums."""

    def __init__(self) -> None:
        self._types: dict[str, type] = {}
        self._names: dict[type, str] = {}
        from cognitive_world.core.observation_range import ObservationZone, ObservationRangePolicy
        from cognitive_world.core.object_appearance import ObjectAppearance
        from cognitive_world.core.interaction_range import InteractionRangePolicy
        from cognitive_world.core.entity import Entity, SafetySubjectProfile
        from cognitive_world.core.event import Event
        from cognitive_world.core.attributed_claim import (
            AttributedClaim, AttributedClaimDraft, ClaimPropertyContract, DialoguePayload,
        )
        from cognitive_world.core.update import WorldUpdate
        from cognitive_world.core.door import DoorState
        from cognitive_world.core.passage import PassageState
        from cognitive_world.observation.observable import (
            EventProcessingEvidence, EventStatePhase, EventTimeObservationContext,
            ObservableFact, ObservableFactDraft,
        )
        from cognitive_world.world_norms.models import (
            GovernanceStatus, NormativeForce, NormRule, NormVersion, WorldNorms,
        )
        for item in (InteractionRangePolicy, ObservationZone, ObservationRangePolicy, ObjectAppearance, Entity, SafetySubjectProfile, Event, WorldUpdate, DoorState, PassageState,
                     AttributedClaim, AttributedClaimDraft, ClaimPropertyContract, DialoguePayload,
                     EventProcessingEvidence, EventStatePhase, EventTimeObservationContext,
                     ObservableFact, ObservableFactDraft,
                     GovernanceStatus, NormativeForce, NormRule, NormVersion, WorldNorms):
            self.register_type(item)

    @staticmethod
    def _name(value_type: type) -> str:
        return f"{value_type.__module__}:{value_type.__qualname__}"

    def register_type(self, value_type: type) -> None:
        if not isinstance(value_type, type) or not (
            issubclass(value_type, Enum) or is_dataclass(value_type)
        ):
            raise TypeError("only Enum and dataclass types may be registered")
        name = self._name(value_type)
        prior = self._types.get(name)
        if prior is not None and prior is not value_type:
            raise ValueError("persisted type name collision")
        self._types[name] = value_type
        self._names[value_type] = name

    def encode(self, value: object, *, _depth: int = 0) -> object:
        if _depth > 64:
            raise ValueError("persisted value nesting exceeds limit")
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("non-finite floats cannot be persisted")
            return value
        if isinstance(value, Enum):
            name = self._names.get(type(value))
            if name is None:
                raise TypeError(f"unregistered persisted enum: {type(value).__qualname__}")
            return {"$enum": name, "value": self.encode(value.value, _depth=_depth + 1)}
        if is_dataclass(value) and not isinstance(value, type):
            name = self._names.get(type(value))
            if name is None:
                raise TypeError(f"unregistered persisted record: {type(value).__qualname__}")
            record_fields = fields(value)
            # Memory/v1 predates the explicit schema and provenance fields.
            # Keep its canonical representation byte-for-byte compatible;
            # Memory/v2 includes the complete current field set.
            if (type(value).__module__ == "cognitive_world.cognition.memory"
                    and type(value).__qualname__ == "Memory"):
                value.__post_init__()
                schema_version = getattr(value, "schema_version", None)
                if type(schema_version) is not int:
                    raise ValueError("unsupported persisted Memory schema")
                if schema_version == 1:
                    legacy_names = {
                        "id", "owner_id", "type", "content", "importance",
                        "source_event", "metadata",
                    }
                    record_fields = tuple(item for item in record_fields if item.name in legacy_names)
                elif schema_version != 2:
                    raise ValueError("unsupported persisted Memory schema")
            return {"$record": name, "fields": {
                item.name: self.encode(getattr(value, item.name), _depth=_depth + 1)
                for item in record_fields if item.init and not item.name.startswith("_")
            }}
        if isinstance(value, dict):
            pairs = [(self.encode(key, _depth=_depth + 1), self.encode(item, _depth=_depth + 1))
                     for key, item in value.items()]
            return {"$map": pairs}
        if isinstance(value, tuple):
            return {"$tuple": [self.encode(item, _depth=_depth + 1) for item in value]}
        if isinstance(value, list):
            return [self.encode(item, _depth=_depth + 1) for item in value]
        raise TypeError(f"unsupported persisted value type: {type(value).__qualname__}")

    def decode(self, value: object, *, _depth: int = 0) -> object:
        if _depth > 64:
            raise ValueError("persisted value nesting exceeds limit")
        if value is None or type(value) in (str, bool, int, float):
            if type(value) is float and not math.isfinite(value):
                raise ValueError("non-finite persisted float")
            return value
        if isinstance(value, list):
            return [self.decode(item, _depth=_depth + 1) for item in value]
        if not isinstance(value, dict):
            raise TypeError("invalid persisted value")
        if set(value) == {"$tuple"} and isinstance(value["$tuple"], list):
            return tuple(self.decode(item, _depth=_depth + 1) for item in value["$tuple"])
        if set(value) == {"$map"} and isinstance(value["$map"], list):
            result = {}
            for pair in value["$map"]:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError("invalid persisted mapping entry")
                key = self.decode(pair[0], _depth=_depth + 1)
                if key in result:
                    raise ValueError("duplicate persisted mapping key")
                result[key] = self.decode(pair[1], _depth=_depth + 1)
            return result
        if set(value) == {"$enum", "value"}:
            cls = self._types.get(value["$enum"])
            if cls is None or not issubclass(cls, Enum):
                raise ValueError("unregistered persisted enum")
            return cls(self.decode(value["value"], _depth=_depth + 1))
        if set(value) == {"$record", "fields"}:
            cls = self._types.get(value["$record"])
            raw_fields = value["fields"]
            if cls is None or not is_dataclass(cls) or not isinstance(raw_fields, dict):
                raise ValueError("unregistered persisted record")
            expected = {item.name for item in fields(cls) if item.init and not item.name.startswith("_")}
            if (cls.__module__ == "cognitive_world.cognition.memory"
                    and cls.__qualname__ == "Memory"):
                legacy = {"id", "owner_id", "type", "content", "importance", "source_event", "metadata"}
                if set(raw_fields) == legacy:
                    raw_fields = {**raw_fields, "schema_version": 1,
                                  "decision_provenance": None, "logical_record_id": None,
                                  "supersedes_record_id": None}
                elif set(raw_fields) == expected and raw_fields.get("schema_version") != 2:
                    raise ValueError("persisted Memory schema mismatch")
            # Event gained an optional signed dialogue extension. Preserve the
            # exact legacy Event representation when reading older records.
            if cls.__module__ == "cognitive_world.core.event" and cls.__qualname__ == "Event" and set(raw_fields) == expected - {"dialogue_payload"}:
                raw_fields = {**raw_fields, "dialogue_payload": None}
            if set(raw_fields) != expected:
                raise ValueError("persisted record schema mismatch")
            kwargs = {key: self.decode(item, _depth=_depth + 1) for key, item in raw_fields.items()}
            return cls(**kwargs)
        raise ValueError("unknown persisted value tag")

    def dumps(self, value: object) -> bytes:
        encoded = self.encode(value)
        return json.dumps(encoded, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")

    def loads(self, payload: bytes) -> object:
        if not isinstance(payload, bytes) or len(payload) > 64 * 1024 * 1024:
            raise ValueError("persisted payload is invalid or exceeds 64 MiB")
        return self.decode(json.loads(payload.decode("utf-8")))


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
