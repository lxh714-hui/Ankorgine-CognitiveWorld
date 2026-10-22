"""Ephemeral, verified view of Memory revisions visible on one Timeline.

The view is derived from signed checkpoint contents. It is runtime validation
context, not a second Memory store and is never serialized independently.
"""
from __future__ import annotations

from dataclasses import dataclass

from cognitive_world.cognition.memory import (
    Memory, MemoryDecisionProvenance, MemoryDecisionProvenanceV2,
)
from cognitive_world.core.issued_credentials import (
    _issue_object_credential, _require_object_credential,
)


_LINEAGE_SEAL = object()


@dataclass(frozen=True)
class MemoryRevisionLineage:
    """Branch-local revision authority derived from a verified checkpoint."""

    timeline_id: str
    inherited_records: tuple[tuple[str, bytes], ...]
    fork_checkpoint_id: str | None
    parent_timeline_id: str | None
    fork_manifest_sha256: str | None
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _LINEAGE_SEAL:
            raise PermissionError("Memory revision lineage must be issued by a trusted factory")
        if not isinstance(self.timeline_id, str) or not self.timeline_id:
            raise ValueError("Memory revision lineage requires a Timeline identity")
        if not isinstance(self.inherited_records, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2
            or not isinstance(item[0], str) or not isinstance(item[1], bytes)
            for item in self.inherited_records
        ):
            raise TypeError("inherited revisions must be canonical immutable encodings")

    @classmethod
    def root(cls, timeline_id: str) -> "MemoryRevisionLineage":
        """Create an empty root-line view for a newly initialized Runtime."""
        lineage = cls(timeline_id, (), None, None, None, _LINEAGE_SEAL)
        _issue_lineage(lineage)
        return lineage

    @classmethod
    def fork_from_verified_bundle(
        cls, *, verified_bundle: object, checkpoint_manifest: object,
        timeline_id: str, fork_manifest: object, trust: object,
    ) -> "MemoryRevisionLineage":
        """Inherit the exact Memory records of a signed, isolated checkpoint."""
        from cognitive_world.core.snapshot_bundle import _require_verified_snapshot_bundle
        from cognitive_world.cognition.snapshot import IsolatedCognitiveRestore

        _require_verified_snapshot_bundle(verified_bundle)
        if type(verified_bundle.cognition) is not IsolatedCognitiveRestore:
            raise PermissionError("branch lineage requires isolated cognitive reconstruction")
        from cognitive_world.core.timeline import TimelineForkManifest
        if type(fork_manifest) is not TimelineForkManifest:
            raise PermissionError("branch lineage requires the signed Timeline fork manifest")
        from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
        if type(checkpoint_manifest) is not SnapshotBundleManifest:
            raise PermissionError("branch lineage requires the signed parent checkpoint manifest")
        if not callable(getattr(trust, "verify", None)):
            raise PermissionError("branch lineage requires the configured persistence trust")
        fork_manifest.verify_against_checkpoint(
            checkpoint_manifest, verified_bundle=verified_bundle, trust=trust,
        )
        if (fork_manifest.timeline_id != timeline_id
                or fork_manifest.parent_timeline_id != verified_bundle.timeline_id):
            raise PermissionError("fork manifest does not bind the verified parent and child Timelines")
        from cognitive_world.core.persistence import sha256_hex
        from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
        codec = cognitive_snapshot_codec()
        records = verified_bundle.cognition.memory_store.get_all_memories()
        lineage = cls(
            timeline_id,
            tuple(sorted((item.id, codec.dumps(item)) for item in records)),
            fork_manifest.fork_checkpoint_id,
            fork_manifest.parent_timeline_id,
            sha256_hex(fork_manifest.to_bytes()),
            _LINEAGE_SEAL,
        )
        _issue_lineage(lineage)
        return lineage

    def _require_issued(self) -> None:
        if self._seal is not _LINEAGE_SEAL:
            raise PermissionError("Memory revision lineage seal is invalid")
        _require_object_credential("MemoryRevisionLineage", self,
                                   _lineage_fingerprint(self))

    def verify_event_history(self, event_history: object) -> None:
        """Bind this view to the actual signed root/fork descriptor in a Runtime."""
        self._require_issued()
        from cognitive_world.event.history import EventHistory
        if type(event_history) is not EventHistory:
            raise TypeError("revision view requires a canonical EventHistory")
        history_timeline = event_history.timeline_id
        fork_bytes = event_history.fork_manifest_bytes
        checkpoint_bytes = event_history.fork_checkpoint_manifest_bytes
        if (not isinstance(history_timeline, str) or not history_timeline
                or history_timeline != self.timeline_id):
            raise PermissionError("revision view and EventHistory Timeline differ")
        if (fork_bytes is None) != (checkpoint_bytes is None):
            raise PermissionError("EventHistory has incomplete fork metadata")
        if fork_bytes is None:
            if (self.fork_checkpoint_id is not None
                    or self.parent_timeline_id is not None
                    or self.fork_manifest_sha256 is not None
                    or event_history._parent_history is not None
                    or event_history._inherited_events
                    or event_history._inherited_persistence_records):
                raise PermissionError("branch revision view is not bound to a forked EventHistory")
            return
        if (not isinstance(fork_bytes, bytes) or not fork_bytes
                or not isinstance(checkpoint_bytes, bytes) or not checkpoint_bytes
                or not isinstance(self.fork_checkpoint_id, str)
                or not isinstance(self.parent_timeline_id, str)
                or not isinstance(self.fork_manifest_sha256, str)):
            raise PermissionError("branch revision view or EventHistory has incomplete fork metadata")
        from cognitive_world.core.timeline import TimelineForkManifest
        fork = TimelineForkManifest.from_bytes(fork_bytes)
        from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
        checkpoint = SnapshotBundleManifest.from_bytes(checkpoint_bytes)
        from cognitive_world.core.persistence import sha256_hex
        if (self.fork_checkpoint_id != fork.fork_checkpoint_id
                or self.parent_timeline_id != fork.parent_timeline_id
                or self.timeline_id != fork.timeline_id
                or sha256_hex(checkpoint_bytes) != fork.fork_checkpoint_id
                or checkpoint.timeline_id != fork.parent_timeline_id
                or checkpoint.simulation_tick != fork.simulation_tick
                or checkpoint.event_chain_head_sha256 != fork.inherited_event_chain_head_sha256):
            raise PermissionError("revision view does not match EventHistory's signed fork boundary")
        if sha256_hex(fork_bytes) != self.fork_manifest_sha256:
            raise PermissionError("EventHistory fork manifest differs from the verified revision view")

    def validate_records(self, records: tuple[Memory, ...]) -> None:
        """Validate inherited byte-equivalent records and the branch-local DAG."""
        self._require_issued()
        if not isinstance(records, tuple) or any(type(item) is not Memory for item in records):
            raise TypeError("revision validation requires canonical Memory records")
        by_id: dict[str, Memory] = {}
        for item in records:
            prior = by_id.get(item.id)
            if prior is not None and prior != item:
                raise PermissionError("conflicting Memory revision identity")
            by_id[item.id] = item
        from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
        codec = cognitive_snapshot_codec()
        inherited = dict(self.inherited_records)
        if len(inherited) != len(self.inherited_records):
            raise PermissionError("verified checkpoint contains duplicate Memory identities")
        for record_id, expected in inherited.items():
            if record_id not in by_id or codec.dumps(by_id[record_id]) != expected:
                raise PermissionError("branch changed or omitted an inherited checkpoint Memory")
        for item in records:
            if item.schema_version != 2:
                continue
            provenance = item.decision_provenance
            if (type(provenance) not in {
                    MemoryDecisionProvenance, MemoryDecisionProvenanceV2,
                }
                    or provenance.owner_id != item.owner_id
                    or provenance.supersedes_record_id != item.supersedes_record_id
                    or item.source_event not in provenance.source_event_ids
                    or not item.logical_record_id):
                raise PermissionError("Memory revision provenance differs from its canonical record")
            if item.id not in inherited and item.decision_provenance.timeline_id != self.timeline_id:
                raise PermissionError("Memory revision is not authored on this Timeline")

        grouped: dict[tuple[str, str], list[Memory]] = {}
        for item in records:
            if item.schema_version == 2:
                grouped.setdefault((item.owner_id, item.logical_record_id), []).append(item)
        for group in grouped.values():
            ids = {item.id for item in group}
            successors: dict[str, list[str]] = {}
            roots = 0
            for item in group:
                predecessor = item.supersedes_record_id
                if predecessor is None:
                    roots += 1
                else:
                    parent = by_id.get(predecessor)
                    if (parent is None or parent.schema_version != 2
                            or parent.owner_id != item.owner_id
                            or parent.logical_record_id != item.logical_record_id):
                        raise PermissionError("Memory predecessor is absent or crosses its logical owner")
                    successors.setdefault(predecessor, []).append(item.id)
            if roots != 1 or any(len(children) != 1 for children in successors.values()):
                raise PermissionError("branch-local Memory revision graph is ambiguous")
            visited: set[str] = set()
            for item in group:
                current = item
                chain: set[str] = set()
                while current.supersedes_record_id is not None:
                    if current.id in chain:
                        raise PermissionError("Memory revision graph contains a cycle")
                    chain.add(current.id)
                    parent = by_id.get(current.supersedes_record_id)
                    if parent is None:
                        raise PermissionError("Memory revision graph has a missing predecessor")
                    current = parent
                if current.id in visited and roots != 1:
                    raise PermissionError("Memory revision graph has multiple roots")
                visited.add(item.id)


def _lineage_fingerprint(lineage: MemoryRevisionLineage) -> tuple[object, ...]:
    return (lineage.timeline_id, lineage.inherited_records, lineage.fork_checkpoint_id,
            lineage.parent_timeline_id, lineage.fork_manifest_sha256,
            lineage._seal is _LINEAGE_SEAL)


def _issue_lineage(lineage: MemoryRevisionLineage) -> None:
    _issue_object_credential("MemoryRevisionLineage", lineage, _lineage_fingerprint(lineage))
