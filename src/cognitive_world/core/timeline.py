"""Signed, checkpoint-anchored timeline fork metadata.

EventHistory consumes this record to validate immutable parent ancestry and
timeline-local suffix credentials. It does not activate a branch or provide
Runtime publication and recovery isolation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from uuid import uuid4

from cognitive_world.core.persistence import PersistenceTrust, sha256_hex
from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest


_SCHEMA = "cognitive-world/timeline-fork"
_VERSION = 1
_PURPOSE = "cognitive-world/timeline-fork/v1"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class TimelineForkManifest:
    """An immutable signed statement that a new timeline starts at a bundle.

    ``fork_checkpoint_id`` is the SHA-256 of the exact signed bundle-manifest
    bytes. It is an ancestry reference, not an Event ID or a save-slot ID.
    """

    version: int
    timeline_id: str
    parent_timeline_id: str
    fork_checkpoint_id: str
    inherited_event_chain_head_sha256: str | None
    simulation_tick: int
    signature: bytes

    def __post_init__(self) -> None:
        if (type(self.version) is not int or self.version != _VERSION
                or not isinstance(self.timeline_id, str) or not self.timeline_id
                or not isinstance(self.parent_timeline_id, str) or not self.parent_timeline_id
                or self.timeline_id == self.parent_timeline_id
                or not isinstance(self.fork_checkpoint_id, str)
                or len(self.fork_checkpoint_id) != 64
                or any(ch not in "0123456789abcdef" for ch in self.fork_checkpoint_id)
                or isinstance(self.simulation_tick, bool)
                or not isinstance(self.simulation_tick, int)
                or self.simulation_tick < 0 or not isinstance(self.signature, bytes)
                or not self.signature):
            raise ValueError("invalid timeline fork manifest")
        if (self.inherited_event_chain_head_sha256 is not None
                and (not isinstance(self.inherited_event_chain_head_sha256, str)
                     or len(self.inherited_event_chain_head_sha256) != 64
                     or any(ch not in "0123456789abcdef"
                            for ch in self.inherited_event_chain_head_sha256))):
            raise ValueError("invalid inherited Event chain head")

    def _body(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "version": self.version,
            "timeline_id": self.timeline_id,
            "parent_timeline_id": self.parent_timeline_id,
            "fork_checkpoint_id": self.fork_checkpoint_id,
            "inherited_event_chain_head_sha256": self.inherited_event_chain_head_sha256,
            "simulation_tick": self.simulation_tick,
        }

    def to_bytes(self) -> bytes:
        return _canonical({**self._body(),
                           "signature": base64.b64encode(self.signature).decode("ascii")})

    @classmethod
    def create_from_checkpoint(
        cls, *, checkpoint_manifest: SnapshotBundleManifest,
        verified_bundle: object, trust: PersistenceTrust,
        timeline_id: str | None = None,
    ) -> "TimelineForkManifest":
        """Create ancestry from a signed manifest and its isolated reconstruction."""
        from cognitive_world.core.snapshot_bundle import VerifiedSnapshotBundle

        if type(checkpoint_manifest) is not SnapshotBundleManifest:
            raise TypeError("fork requires a verified snapshot bundle manifest")
        if type(verified_bundle) is not VerifiedSnapshotBundle:
            raise TypeError("fork requires the bundle's verified isolated reconstruction")
        if not checkpoint_manifest.verify_signature(trust):
            raise PermissionError("fork checkpoint manifest is not trusted")
        verified_bundle.verify_manifest_binding(checkpoint_manifest)
        if (verified_bundle.timeline_id != checkpoint_manifest.timeline_id
                or verified_bundle.simulation_tick != checkpoint_manifest.simulation_tick):
            raise PermissionError("verified staging result does not match fork checkpoint")
        child_id = timeline_id or str(uuid4())
        body = {
            "schema": _SCHEMA,
            "version": _VERSION,
            "timeline_id": child_id,
            "parent_timeline_id": checkpoint_manifest.timeline_id,
            "fork_checkpoint_id": sha256_hex(checkpoint_manifest.to_bytes()),
            "inherited_event_chain_head_sha256": checkpoint_manifest.event_chain_head_sha256,
            "simulation_tick": checkpoint_manifest.simulation_tick,
        }
        signature = trust.sign(_PURPOSE, _canonical(body))
        if not isinstance(signature, bytes) or not signature:
            raise TypeError("persistence trust authority returned an invalid fork signature")
        return cls(_VERSION, child_id, checkpoint_manifest.timeline_id,
                   body["fork_checkpoint_id"],
                   checkpoint_manifest.event_chain_head_sha256,
                   checkpoint_manifest.simulation_tick, signature)

    @classmethod
    def from_bytes(cls, payload: bytes) -> "TimelineForkManifest":
        try:
            value = json.loads(payload.decode("utf-8"))
            required = {"schema", "version", "timeline_id", "parent_timeline_id",
                        "fork_checkpoint_id", "inherited_event_chain_head_sha256",
                        "simulation_tick", "signature"}
            if not isinstance(value, dict) or set(value) != required or value["schema"] != _SCHEMA:
                raise ValueError("malformed timeline fork manifest")
            return cls(value["version"], value["timeline_id"], value["parent_timeline_id"],
                       value["fork_checkpoint_id"],
                       value["inherited_event_chain_head_sha256"], value["simulation_tick"],
                       base64.b64decode(value["signature"], validate=True))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
                base64.binascii.Error) as error:
            raise ValueError("malformed timeline fork manifest") from error

    def verify_against_checkpoint(
        self, checkpoint_manifest: SnapshotBundleManifest, *,
        verified_bundle: object, trust: PersistenceTrust,
    ) -> None:
        """Verify signer and exact parent/checkpoint/tick/lineage association."""
        from cognitive_world.core.snapshot_bundle import VerifiedSnapshotBundle

        if type(verified_bundle) is not VerifiedSnapshotBundle:
            raise TypeError("fork verification requires an isolated verified bundle")
        verified_bundle.verify_manifest_binding(checkpoint_manifest)
        if not trust.verify(_PURPOSE, _canonical(self._body()), self.signature):
            raise PermissionError("timeline fork signer is not trusted or signature is invalid")
        if not checkpoint_manifest.verify_signature(trust):
            raise PermissionError("fork checkpoint manifest is not trusted")
        if (self.parent_timeline_id != checkpoint_manifest.timeline_id
                or self.fork_checkpoint_id != sha256_hex(checkpoint_manifest.to_bytes())
                or self.simulation_tick != checkpoint_manifest.simulation_tick
                or verified_bundle.timeline_id != checkpoint_manifest.timeline_id
                or verified_bundle.simulation_tick != checkpoint_manifest.simulation_tick
                or self.inherited_event_chain_head_sha256
                != checkpoint_manifest.event_chain_head_sha256):
            raise PermissionError("timeline fork does not match its verified checkpoint")

    def verify_event_history_parent(
        self, checkpoint_manifest: SnapshotBundleManifest, *,
        parent_timeline_id: str, parent_chain_head_sha256: str | None,
        trust: PersistenceTrust,
    ) -> None:
        """Bind a resolved, independently verified EventHistory prefix to the fork."""
        if not trust.verify(_PURPOSE, _canonical(self._body()), self.signature):
            raise PermissionError("timeline fork signer is not trusted or signature is invalid")
        if not checkpoint_manifest.verify_signature(trust):
            raise PermissionError("fork checkpoint manifest is not trusted")
        if (self.parent_timeline_id != checkpoint_manifest.timeline_id
                or self.parent_timeline_id != parent_timeline_id
                or self.fork_checkpoint_id != sha256_hex(checkpoint_manifest.to_bytes())
                or self.simulation_tick != checkpoint_manifest.simulation_tick
                or self.inherited_event_chain_head_sha256 != parent_chain_head_sha256
                or checkpoint_manifest.event_chain_head_sha256 != parent_chain_head_sha256):
            raise PermissionError("resolved parent EventHistory does not match fork checkpoint")
