"""Durable save catalog and content-addressed snapshot resource manager.

The signed SnapshotBundle remains the authority for component authenticity.
This module adds save-slot lifecycle, a single signed catalog commit point, and
conservative dependency retention. It does not recover an active Runtime.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterator
from uuid import uuid4
import weakref

from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, cognitive_snapshot_codec
from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
from cognitive_world.core.persistence import (
    PersistenceTrust, PersistedValueCodec, sha256_hex,
)
from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
from cognitive_world.core.timeline import TimelineForkManifest
from cognitive_world.runtime.reconstruction import (
    DependencyStrategy, RuntimeDependencyManifest, StagedRuntime,
    IsolatedRuntimeReconstructionFactory,
)


class SaveKind(str, Enum):
    AUTOMATIC = "automatic"
    QUICK = "quick"
    MANUAL = "manual"


@dataclass(frozen=True)
class SaveMetadata:
    save_id: str
    timeline_id: str
    kind: SaveKind
    simulation_tick: int
    runtime_session_id: str
    restore_generation: int
    snapshot_id: str
    bundle_sha256: str
    event_chain_head_sha256: str | None
    parent_timeline_id: str | None
    fork_checkpoint_id: str | None
    event_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    schema_version: int = 1
    integrity: str = "signed-bundle-verified"
    created_at: str = ""


@dataclass(frozen=True)
class VerifiedSave:
    metadata: SaveMetadata
    world_checkpoint: bytes
    cognitive_snapshot: bytes
    bundle_manifest: SnapshotBundleManifest
    fork_manifest: TimelineForkManifest | None
    expected_agents: tuple[object, ...]
    behavior_feedback_snapshot: bytes | None = None
    memory_revision_lineage: MemoryRevisionLineage | None = None


class SaveError(RuntimeError):
    """Save operation failed closed; catalog publication did not silently succeed."""


class SaveCommittedError(SaveError):
    """Catalog commit succeeded but post-commit journal/cleanup needs retry."""

    def __init__(self, save_id: str, operation: str, reason: str) -> None:
        super().__init__(f"{operation} for Save_ID {save_id} committed; maintenance needs retry: {reason}")
        self.save_id = save_id
        self.operation = operation
        self.committed = True


class DependencyTracker:
    """Rebuild direct resource references from the signed catalog each time."""

    @staticmethod
    def counts(saves: dict[str, dict[str, object]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in saves.values():
            resources = record.get("resource_ids")
            if not isinstance(resources, list) or len(resources) != len(set(resources)):
                raise ValueError("save catalog has malformed or duplicate resource references")
            for resource_id in resources:
                if not isinstance(resource_id, str) or not resource_id.startswith("sha256:"):
                    raise ValueError("save catalog contains invalid resource identity")
                counts[resource_id] = counts.get(resource_id, 0) + 1
        return counts

    @classmethod
    def validate(cls, saves: dict[str, dict[str, object]], resources: set[str]) -> dict[str, int]:
        counts = cls.counts(saves)
        missing = set(counts) - resources
        if missing:
            raise FileNotFoundError(f"catalog references missing resources: {sorted(missing)}")
        return counts


class SaveManager:
    """Host-owned save lifecycle over immutable blobs and one signed catalog.

    Automatic retention defaults to five saves. Quick save is one replaceable
    slot, isolated from automatic retention and manual slots. Manual slots are
    never removed except by explicit delete or explicit replacement.
    """

    _CATALOG_PURPOSE = "cognitive-world/save-catalog/v1"
    _LEASE_PURPOSE = "cognitive-world/runtime-resource-lease/v1"
    _MAX_CATALOG_BYTES = 64 * 1024 * 1024
    _PATH_LOCKS_GUARD = threading.Lock()
    _PATH_LOCKS: dict[str, threading.RLock] = {}
    _PATH_LEASES: dict[str, dict[int, tuple[weakref.ReferenceType[object], tuple[str, ...], object]]] = {}

    def __init__(
        self, root: str | os.PathLike[str], *, trust: PersistenceTrust,
        event_history_resolver: object | None = None,
        automatic_retention: int = 5,
        codec: PersistedValueCodec | None = None,
        _read_only: bool = False,
    ) -> None:
        if isinstance(automatic_retention, bool) or not isinstance(automatic_retention, int) or automatic_retention < 1:
            raise ValueError("automatic_retention must be a positive integer")
        if not callable(getattr(trust, "sign", None)) or not callable(getattr(trust, "verify", None)):
            raise TypeError("SaveManager requires an explicit persistence trust authority")
        self.root = Path(root)
        self.resources = self.root / "resources"
        self.staging = self.root / ".staging"
        self.leases = self.root / ".runtime-leases"
        self.catalog_path = self.root / "catalog.json"
        self.journal_path = self.root / "transactions.jsonl"
        self.lock_path = self.root / ".save-manager.lock"
        lock_key = str(self.root.resolve()).casefold()
        with self._PATH_LOCKS_GUARD:
            self._path_lock = self._PATH_LOCKS.setdefault(lock_key, threading.RLock())
            # All managers for one directory in this process must see the same
            # staged/active Runtime leases before pruning a shared checkpoint.
            self._runtime_resource_leases = self._PATH_LEASES.setdefault(lock_key, {})
        self.trust = trust
        self.codec = codec or cognitive_snapshot_codec()
        self._host_event_history_resolver = event_history_resolver
        self.event_history_resolver = self._resolve_event_history
        self.automatic_retention = automatic_retention
        self._thread_lock = threading.RLock()
        self._lock_local = threading.local()
        self._checkpoint_verification_local = threading.local()
        self._read_only = _read_only
        if _read_only:
            if not self.catalog_path.is_file():
                raise FileNotFoundError("save catalog is unavailable")
            self._load_catalog()
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.resources.mkdir(exist_ok=True)
        self.staging.mkdir(exist_ok=True)
        self.leases.mkdir(exist_ok=True)
        with self._locked():
            if not self.catalog_path.exists():
                self._write_catalog({"version": 1, "saves": {}, "checkpoints": {},
                                     "last_transaction_id": None})
            self._recover_incomplete_transactions()
            self._load_catalog()

    def create_automatic(self, **capture: object) -> SaveMetadata:
        return self._capture_and_store(SaveKind.AUTOMATIC, replace_id=None, **capture)

    def create_quick_save(self, **capture: object) -> SaveMetadata:
        with self._locked():
            catalog = self._load_catalog()
            existing = next((key for key, item in catalog["saves"].items()
                             if item["kind"] == SaveKind.QUICK.value), None)
        return self._capture_and_store(SaveKind.QUICK, replace_id=existing, **capture)

    def create_manual_save(self, *, name: str | None = None, **capture: object) -> SaveMetadata:
        return self._capture_and_store(SaveKind.MANUAL, replace_id=None, name=name, **capture)

    def replace_manual_save(self, save_id: str, **capture: object) -> SaveMetadata:
        if not isinstance(save_id, str) or not save_id:
            raise ValueError("manual Save_ID is required for replacement")
        return self._capture_and_store(SaveKind.MANUAL, replace_id=save_id, **capture)

    def _capture_and_store(
        self, kind: SaveKind, *, replace_id: str | None,
        runtime: object, cognition: object, memory_store: object,
        agent_contexts: tuple[object, ...], trust: PersistenceTrust | None = None,
        name: str | None = None,
    ) -> SaveMetadata:
        """Capture canonical runtime state under its write and registry barriers."""
        from cognitive_world.runtime.runtime import SimulationRuntime
        from cognitive_world.cognition.snapshot import CognitiveStateSnapshot
        from cognitive_world.agent.registry import AgentRegistry
        if type(runtime) is not SimulationRuntime:
            raise TypeError("save capture requires canonical SimulationRuntime")
        if trust is not None and trust is not self.trust:
            raise PermissionError("save capture trust authority must match manager verifier")
        if not isinstance(agent_contexts, tuple):
            raise TypeError("agent_contexts must be the canonical Runtime context tuple")
        context = runtime.context
        registry = context.agent_registry
        history = context.event_history
        if type(registry) is not AgentRegistry:
            raise PermissionError("save capture requires the canonical AgentRegistry")
        permit_context = runtime.write_fence.operation()
        with permit_context as permit:
            with runtime.write_fence.snapshot_scope():
                with registry.snapshot_scope() as (_, agents):
                    tick = context.clock.current_time
                    timeline_id = history.timeline_id
                    if not isinstance(timeline_id, str) or not timeline_id:
                        raise PermissionError("active EventHistory has no persistent Timeline identity")
                    expected_ids = {item.agent_id for item in agents}
                    contexts = agent_contexts or tuple(
                        runtime.cognition_context_provider(agent)
                        for agent in agents
                    )
                    if not contexts:
                        raise PermissionError("empty-Agent cognition capture requires explicit supported stores")
                    if any(getattr(item, "cognition_container", None) is not cognition
                           or getattr(item, "memory_store", None) is not memory_store
                           for item in contexts):
                        raise PermissionError("CognitionContexts do not share the supplied canonical stores")
                    snapshot = CognitiveStateSnapshot.capture(
                        cognition=cognition, memory_store=memory_store, runtime=runtime,
                        agent_contexts=contexts, timeline_id=timeline_id, trust=self.trust,
                        codec=self.codec,
                        memory_revision_lineage=runtime.memory_revision_lineage,
                    )
                    if set(snapshot.body.agent_ids) != expected_ids:
                        raise PermissionError("cognitive snapshot does not cover the locked Runtime registry")
                    if (snapshot.body.session_id != permit.session_id
                            or snapshot.body.restore_generation != permit.restore_generation
                            or snapshot.body.simulation_tick != tick):
                        raise PermissionError("cognitive snapshot does not match the captured Runtime context")
                    world_bytes = context.world_state.export_persisted_snapshot(
                        event_history=history, simulation_tick=tick, trust=self.trust,
                        timeline_id=timeline_id, codec=self.codec,
                    )
                    cognitive_bytes = snapshot.to_bytes(codec=self.codec)
                    from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
                    behavior_feedback_bytes = BehaviorFeedbackSnapshot.capture(
                        feedback=runtime.behavior_feedback, event_history=history,
                        timeline_id=timeline_id, simulation_tick=tick,
                        session_id=permit.session_id,
                        restore_generation=permit.restore_generation,
                        agent_ids=tuple(sorted(expected_ids)),
                        memory_store=memory_store, trust=self.trust,
                    )
                    bundle = SnapshotBundleManifest.create(
                        world_checkpoint=world_bytes, cognitive_snapshot=cognitive_bytes,
                        expected_agents=snapshot.body.expected_agents, trust=self.trust,
                        event_history_resolver=self.event_history_resolver,
                        behavior_feedback_snapshot=behavior_feedback_bytes,
                        memory_revision_lineage=runtime.memory_revision_lineage,
                        codec=self.codec,
                    )
                    verified = bundle.verify_and_stage(
                        world_checkpoint=world_bytes, cognitive_snapshot=cognitive_bytes,
                        expected_agents=snapshot.body.expected_agents, trust=self.trust,
                        event_history_resolver=self.event_history_resolver,
                        behavior_feedback_snapshot=behavior_feedback_bytes,
                        memory_revision_lineage=runtime.memory_revision_lineage,
                        codec=self.codec,
                    )
                    if verified.event_history.timeline_id != timeline_id or verified.simulation_tick != tick:
                        raise PermissionError("captured bundle does not match active Runtime timeline/tick")
                    fork_bytes = (None if history.fork_manifest_bytes is None
                                  else history.fork_manifest_bytes)
                    parent_bundle_bytes = history.fork_checkpoint_manifest_bytes
                    event_ids = tuple(item.id for item in history.get_events())
                    session_id = permit.session_id
                    generation = permit.restore_generation
                    fork = (None if fork_bytes is None
                            else TimelineForkManifest.from_bytes(fork_bytes))
        return self._publish_bundle(
            kind=kind, world_bytes=world_bytes, cognitive_bytes=cognitive_bytes,
            behavior_feedback_bytes=behavior_feedback_bytes,
            bundle=bundle, fork=fork, parent_bundle_bytes=parent_bundle_bytes,
            event_ids=event_ids, timeline_id=timeline_id, tick=tick,
            session_id=session_id, generation=generation, name=name,
            replace_id=replace_id,
        )

    def _publish_bundle(
        self, *, kind: SaveKind, world_bytes: bytes, cognitive_bytes: bytes,
        behavior_feedback_bytes: bytes,
        bundle: SnapshotBundleManifest, fork: TimelineForkManifest | None,
        parent_bundle_bytes: bytes | None, event_ids: tuple[str, ...],
        timeline_id: str, tick: int, session_id: str, generation: int,
        name: str | None, replace_id: str | None,
    ) -> SaveMetadata:
        bundle_bytes = bundle.to_bytes()
        resource_values = {"world": world_bytes, "cognition": cognitive_bytes,
                           "behavior_feedback": behavior_feedback_bytes,
                           "bundle": bundle_bytes}
        if fork is not None:
            resource_values["fork"] = fork.to_bytes()
        own_ids = {f"sha256:{sha256_hex(value)}" for value in resource_values.values()}
        transaction_id = str(uuid4())
        with self._locked():
            catalog = self._load_catalog()
            saves: dict[str, dict[str, object]] = catalog["saves"]
            if replace_id is not None:
                old = saves.get(replace_id)
                expected_kind = SaveKind.QUICK.value if kind is SaveKind.QUICK else SaveKind.MANUAL.value
                if old is None or old.get("kind") != expected_kind:
                    raise KeyError("replace target does not exist in the requested save namespace")
                save_id = replace_id
            else:
                save_id = str(uuid4())
            lineage_ids: set[str] = set()
            if parent_bundle_bytes is not None:
                parent_manifest_id = f"sha256:{sha256_hex(parent_bundle_bytes)}"
                parent = catalog["checkpoints"].get(parent_manifest_id)
                if (parent is None or parent.get("timeline_id") != fork.parent_timeline_id):
                    raise PermissionError("branch save parent checkpoint is not retained in this save catalog")
                lineage_ids.update(parent["resource_ids"])
            resources = own_ids | lineage_ids
            timestamp = datetime.now(timezone.utc).isoformat()
            metadata = SaveMetadata(
                save_id, timeline_id, kind, tick, session_id, generation,
                f"sha256:{sha256_hex(bundle_bytes)}", sha256_hex(bundle_bytes),
                bundle.event_chain_head_sha256,
                None if fork is None else fork.parent_timeline_id,
                None if fork is None else fork.fork_checkpoint_id,
                tuple(sorted(set(event_ids))), tuple(sorted(resources)),
                created_at=timestamp,
            )
            self._append_journal({"transaction_id": transaction_id, "phase": "PREPARED",
                                  "save_id": save_id, "operation": "replace" if replace_id else "create"})
            stage_dir = self.staging / transaction_id
            stage_dir.mkdir()
            catalog_committed = False
            try:
                refs: dict[str, str] = {}
                for label, content in resource_values.items():
                    resource_id = f"sha256:{sha256_hex(content)}"
                    refs[label] = resource_id
                    self._install_blob(resource_id, content, stage_dir)
                record = self._metadata_record(metadata, refs, name=name)
                updated = {**saves, save_id: record}
                if kind is SaveKind.AUTOMATIC:
                    auto_ids = sorted(
                        (key for key, item in updated.items() if item["kind"] == SaveKind.AUTOMATIC.value),
                        key=lambda key: updated[key]["created_at"], reverse=True,
                    )
                    for obsolete in auto_ids[self.automatic_retention:]:
                        updated.pop(obsolete)
                elif kind is SaveKind.QUICK:
                    for other_id, item in tuple(updated.items()):
                        if other_id != save_id and item["kind"] == SaveKind.QUICK.value:
                            updated.pop(other_id)
                checkpoints = dict(catalog["checkpoints"])
                checkpoints[refs["bundle"]] = {
                    "timeline_id": timeline_id, "simulation_tick": tick,
                    "resource_ids": sorted(resources), "blob_refs": refs,
                    "event_chain_head_sha256": bundle.event_chain_head_sha256,
                }
                checkpoints = self._prune_checkpoint_index(checkpoints, updated)
                self._validate_catalog_resources(updated)
                self._write_catalog({"version": 1, "saves": updated, "checkpoints": checkpoints,
                                     "last_transaction_id": transaction_id})
                catalog_committed = True
                self._append_journal({"transaction_id": transaction_id, "phase": "COMMITTED",
                                      "save_id": save_id})
                self._collect_unreferenced(updated)
                return metadata
            except Exception as error:
                # Catalog is the single commit point. Before it changes, old records
                # stay authoritative; after it changes, recovery recognizes the txn ID.
                if stage_dir.exists():
                    self._remove_tree(stage_dir)
                if catalog_committed:
                    raise SaveCommittedError(save_id, "save publication", str(error)) from error
                raise

    def list_saves(self, *, timeline_id: str | None = None) -> tuple[SaveMetadata, ...]:
        with self._locked():
            catalog = self._load_catalog()
            self._validate_catalog_resources(catalog["saves"])
            saves = catalog["saves"]
            result = [self._metadata_from_record(item) for item in saves.values()
                      if timeline_id is None or item["timeline_id"] == timeline_id]
            return tuple(sorted(result, key=lambda item: (item.created_at, item.save_id), reverse=True))

    @classmethod
    def inspect_verified_saves(
        cls, root: str | os.PathLike[str], *, trust: PersistenceTrust,
        codec: PersistedValueCodec | None = None,
    ) -> tuple[SaveMetadata, ...]:
        """Read and verify recoverable slots without initializing or repairing storage.

        A concurrent catalog publication can invalidate this inspection; a later
        restore repeats verification under the normal SaveManager lock.
        """
        reader = cls(root, trust=trust, codec=codec, _read_only=True)
        records = reader.list_saves()
        for record in records:
            reader.load_verified(record.save_id, timeline_id=record.timeline_id)
        return records

    def manual_deletion_fingerprint(self, save_id: str) -> str:
        """Read-only preview binding; no catalog, journal or lease is created."""
        with self._locked():
            before = self.catalog_path.read_bytes()
            catalog = self._load_catalog()
            record = catalog["saves"].get(save_id)
            if record is None:
                raise KeyError(save_id)
            if record["kind"] != SaveKind.MANUAL.value:
                raise PermissionError("only manual saves can be deleted")
            self._load_verified_locked(save_id, timeline_id=record["timeline_id"])
            if self.catalog_path.read_bytes() != before:
                raise SaveError("save catalog changed during preview")
            return sha256_hex(before)

    def delete_manual_save(self, save_id: str, *, expected_catalog_sha256: str | None = None) -> None:
        with self._locked():
            catalog = self._load_catalog()
            saves = catalog["saves"]
            record = saves.get(save_id)
            if record is None:
                raise KeyError(save_id)
            if record["kind"] != SaveKind.MANUAL.value:
                raise PermissionError("only explicit manual-save deletion is supported")
            if expected_catalog_sha256 is not None:
                if sha256_hex(self.catalog_path.read_bytes()) != expected_catalog_sha256:
                    raise SaveError("save deletion preview is stale")
                self._load_verified_locked(save_id, timeline_id=record["timeline_id"])
            transaction_id = str(uuid4())
            self._append_journal({"transaction_id": transaction_id, "phase": "PREPARED",
                                  "save_id": save_id, "operation": "delete"})
            updated = dict(saves)
            updated.pop(save_id)
            checkpoints = self._prune_checkpoint_index(catalog["checkpoints"], updated)
            self._write_catalog({"version": 1, "saves": updated, "checkpoints": checkpoints,
                                 "last_transaction_id": transaction_id})
            try:
                self._append_journal({"transaction_id": transaction_id, "phase": "COMMITTED",
                                      "save_id": save_id})
                self._collect_unreferenced(updated)
            except Exception as error:
                raise SaveCommittedError(save_id, "manual deletion", str(error)) from error

    def load_verified(self, save_id: str, *, timeline_id: str) -> VerifiedSave:
        with self._locked():
            return self._load_verified_locked(save_id, timeline_id=timeline_id)

    def stage_restore(
        self, save_id: str, *, timeline_id: str, active_runtime: object,
        assembler: object, dependencies: RuntimeDependencyManifest,
        new_timeline_id: str | None = None,
    ) -> StagedRuntime:
        """Validate a save and stage a new child Runtime; activation remains coordinated."""
        from cognitive_world.core.snapshot_bundle import (
            VerifiedSnapshotBundle, _require_verified_snapshot_bundle,
        )
        # load_verified copies and authenticates all immutable resources while
        # holding the catalog lock. The returned bytes own their lifetime, so
        # deletion/GC after that point cannot alter the staged reconstruction.
        with self._locked():
            saved = self._load_verified_locked(save_id, timeline_id=timeline_id)
            verified = saved.bundle_manifest.verify_and_stage(
                world_checkpoint=saved.world_checkpoint,
                cognitive_snapshot=saved.cognitive_snapshot,
                expected_agents=saved.expected_agents, trust=self.trust,
                event_history_resolver=self.event_history_resolver,
                behavior_feedback_snapshot=saved.behavior_feedback_snapshot,
                memory_revision_lineage=saved.memory_revision_lineage,
                codec=self.codec,
            )
            if type(verified) is not VerifiedSnapshotBundle:
                raise SaveError("bundle verifier returned unsupported staging result")
            _require_verified_snapshot_bundle(verified)
            fork = TimelineForkManifest.create_from_checkpoint(
                checkpoint_manifest=saved.bundle_manifest, verified_bundle=verified,
                trust=self.trust, timeline_id=new_timeline_id,
            )
            staged = IsolatedRuntimeReconstructionFactory.stage(
                active_runtime=active_runtime,
                checkpoint_manifest=saved.bundle_manifest,
                world_checkpoint=saved.world_checkpoint,
                cognitive_snapshot=saved.cognitive_snapshot,
                behavior_feedback_snapshot=saved.behavior_feedback_snapshot,
                expected_agents=saved.expected_agents, fork_manifest=fork,
                trust=self.trust, assembler=assembler, dependencies=dependencies,
                event_history_resolver=self.event_history_resolver, codec=self.codec,
                memory_revision_lineage=saved.memory_revision_lineage,
            )
            self._lease_runtime_resources(staged.runtime, saved.metadata.resource_ids)
            return staged

    def stage_cold_resume(
        self, save_id: str, *, timeline_id: str, assembler: object,
        dependencies: RuntimeDependencyManifest,
    ) -> object:
        """Stage the saved Timeline itself, with no fabricated active parent."""
        from cognitive_world.runtime.cold_restore import ColdRuntimeFactory

        with self._locked():
            saved = self._load_verified_locked(save_id, timeline_id=timeline_id)
            staged = ColdRuntimeFactory.stage(
                saved=saved, trust=self.trust, codec=self.codec,
                assembler=assembler, dependencies=dependencies,
                event_history_resolver=self.event_history_resolver,
            )
            self._lease_runtime_resources(staged.runtime, saved.metadata.resource_ids)
            return staged

    def verify_consistency(self) -> dict[str, int]:
        with self._locked():
            catalog = self._load_catalog()
            saves = catalog["saves"]
            resources = {path.stem for path in self.resources.glob("*.blob")}
            ids = {f"sha256:{stem}" for stem in resources} | self._leased_resource_ids()
            counts = DependencyTracker.validate(saves, ids)
            for resource_id in self._leased_resource_ids():
                counts[resource_id] = counts.get(resource_id, 0) + 1
            orphaned = ids - set(counts)
            if orphaned:
                raise ValueError(f"unreferenced save resources require garbage collection: {sorted(orphaned)}")
            roots = set(counts)
            for checkpoint_id, checkpoint in catalog["checkpoints"].items():
                if (checkpoint_id not in ids
                        or not set(checkpoint.get("resource_ids", ())).issubset(roots)):
                    raise ValueError("checkpoint index and Save_ID dependency graph are inconsistent")
            return counts

    def collect_garbage(self) -> tuple[str, ...]:
        with self._locked():
            catalog = self._load_catalog()
            saves = catalog["saves"]
            checkpoints = self._prune_checkpoint_index(catalog["checkpoints"], saves)
            if checkpoints != catalog["checkpoints"]:
                transaction_id = str(uuid4())
                self._append_journal({"transaction_id": transaction_id, "phase": "PREPARED",
                                      "operation": "garbage_collect"})
                self._write_catalog({"version": 1, "saves": saves,
                                     "checkpoints": checkpoints,
                                     "last_transaction_id": transaction_id})
                try:
                    self._append_journal({"transaction_id": transaction_id, "phase": "COMMITTED",
                                          "operation": "garbage_collect"})
                except Exception as error:
                    raise SaveCommittedError("<catalog>", "garbage collection index update", str(error)) from error
            return tuple(self._collect_unreferenced(saves))

    def _validate_catalog_resources(self, saves: dict[str, dict[str, object]]) -> None:
        resources = {f"sha256:{path.stem}" for path in self.resources.glob("*.blob")}
        # Staged immutable resources are installed before the catalog commit.
        DependencyTracker.validate(saves, resources)
        for resource_id in resources:
            self._read_blob(resource_id)

    def _collect_unreferenced(self, saves: dict[str, dict[str, object]]) -> list[str]:
        if self._load_catalog()["saves"] != saves:
            raise ValueError("garbage collection requires the current signed catalog")
        counts = DependencyTracker.counts(saves)
        for resource_id in self._leased_resource_ids():
            counts[resource_id] = counts.get(resource_id, 0) + 1
        removed = []
        for path in self.resources.glob("*.blob"):
            resource_id = f"sha256:{path.stem}"
            if counts.get(resource_id, 0) == 0:
                path.unlink()
                removed.append(resource_id)
        for path in self.staging.iterdir():
            if path.is_dir():
                self._remove_tree(path)
            else:
                path.unlink(missing_ok=True)
        return removed

    def _prune_checkpoint_index(
        self,
        checkpoints: dict[str, dict[str, object]], saves: dict[str, dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        referenced = {resource_id for record in saves.values()
                      for resource_id in record["resource_ids"]}
        referenced.update(self._leased_resource_ids())
        return {key: value for key, value in checkpoints.items()
                if set(value["resource_ids"]).issubset(referenced)}

    def _leased_resource_ids(self) -> set[str]:
        result: set[str] = set()
        for manifest in sorted(self.leases.iterdir(), key=lambda path: path.suffix != ".json"):
            if not manifest.exists():
                continue  # a stale pair was removed earlier in this locked scan
            if manifest.suffix == ".lock":
                if not manifest.with_suffix(".json").exists():
                    try:
                        with open(manifest, "r+b") as stream:
                            stale_lock = self._try_lock_lease(stream)
                            if stale_lock:
                                self._unlock_lease(stream)
                    except OSError as error:
                        raise SaveError("orphan Runtime lease lock cannot be checked") from error
                    if not stale_lock:
                        raise SaveError("active Runtime lease lock has no verifiable manifest")
                    manifest.unlink()
                continue
            if manifest.suffix != ".json":
                raise SaveError("runtime lease directory contains an unknown record")
            lease_id = manifest.stem
            lock_path = self.leases / f"{lease_id}.lock"
            if not lock_path.is_file():
                raise SaveError("runtime lease manifest has no lock")
            try:
                if manifest.stat().st_size > 1024 * 1024:
                    raise ValueError("runtime lease manifest exceeds size limit")
                envelope = json.loads(manifest.read_bytes())
                body = envelope["body"]
                if (set(envelope) != {"body", "signature"} or not isinstance(body, dict)
                        or set(body) != {"version", "lease_id", "resource_ids"}
                        or body["version"] != 1 or body["lease_id"] != lease_id
                        or not isinstance(body["resource_ids"], list)
                        or not body["resource_ids"]
                        or len(body["resource_ids"]) != len(set(body["resource_ids"]))):
                    raise ValueError("runtime lease schema is invalid")
                for resource_id in body["resource_ids"]:
                    self._blob_path(resource_id)
                signature = base64.b64decode(envelope["signature"], validate=True)
                if not self.trust.verify(self._LEASE_PURPOSE, self._canonical(body), signature):
                    raise PermissionError("runtime lease signature is invalid")
            except (OSError, ValueError, TypeError, KeyError, PermissionError) as error:
                raise SaveError("runtime lease cannot be verified; garbage collection is closed") from error
            # The catalog lock serializes creation with GC. A released OS lock
            # means its process is gone or the Runtime was collected. Never use
            # elapsed time as a substitute for testing the lock itself.
            try:
                with open(lock_path, "r+b") as stream:
                    if self._try_lock_lease(stream):
                        self._unlock_lease(stream)
                        stale = True
                    else:
                        stale = False
            except OSError as error:
                raise SaveError("runtime lease state cannot be checked") from error
            if stale:
                manifest.unlink()
                lock_path.unlink()
                continue
            if any(not self._blob_path(resource_id).is_file()
                   for resource_id in body["resource_ids"]):
                raise SaveError("active Runtime lease references a missing resource")
            result.update(body["resource_ids"])
        return result

    def _lease_runtime_resources(self, runtime: object, resource_ids: tuple[str, ...]) -> None:
        leases = self._runtime_resource_leases
        path_lock = self._path_lock
        runtime_id = id(runtime)
        lease_id = str(uuid4())
        lock_path = self.leases / f"{lease_id}.lock"
        manifest_path = self.leases / f"{lease_id}.json"
        body = {"version": 1, "lease_id": lease_id,
                "resource_ids": sorted(set(resource_ids))}
        stream = open(lock_path, "x+b")
        try:
            stream.write(b"0")
            stream.flush()
            os.fsync(stream.fileno())
            if not self._try_lock_lease(stream):
                raise SaveError("new Runtime resource lease could not be locked")
            envelope = {"body": body, "signature": base64.b64encode(
                self.trust.sign(self._LEASE_PURPOSE, self._canonical(body))
            ).decode("ascii")}
            with open(manifest_path, "xb") as record:
                record.write(self._canonical(envelope))
                record.flush()
                os.fsync(record.fileno())
        except BaseException:
            stream.close()
            manifest_path.unlink(missing_ok=True)
            lock_path.unlink(missing_ok=True)
            raise
        def release(_reference: weakref.ReferenceType[object]) -> None:
            with path_lock:
                entry = leases.pop(runtime_id, None)
                if entry is not None:
                    entry[2].close()
        with path_lock:
            leases[runtime_id] = (weakref.ref(runtime, release), tuple(resource_ids), stream)

    @staticmethod
    def _try_lock_lease(stream: object) -> bool:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EDEADLK} or error.winerror in {33, 36}:
                    return False
                raise
        import fcntl
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    @staticmethod
    def _unlock_lease(stream: object) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _load_verified_locked(self, save_id: str, *, timeline_id: str) -> VerifiedSave:
        catalog = self._load_catalog()
        record = catalog["saves"].get(save_id)
        if record is None:
            raise KeyError(save_id)
        if record["timeline_id"] != timeline_id:
            raise PermissionError("Save_ID does not belong to requested Timeline_ID")
        self._validate_catalog_resources(catalog["saves"])
        values = {label: self._read_blob(record["blob_refs"][label])
                  for label in ("world", "cognition", "bundle")}
        bundle = SnapshotBundleManifest.from_bytes(values["bundle"])
        fork = None
        fork_id = record["blob_refs"].get("fork")
        revision_lineage = None
        if fork_id is not None:
            fork = TimelineForkManifest.from_bytes(self._read_blob(fork_id))
            parent_bundle, _ = self._resolve_verified_checkpoint(fork.fork_checkpoint_id)
            parent_checkpoint = catalog["checkpoints"].get(
                f"sha256:{fork.fork_checkpoint_id}"
            )
            if not isinstance(parent_checkpoint, dict):
                raise PermissionError("saved timeline fork checkpoint is absent from dependency index")
            parent_manifest = SnapshotBundleManifest.from_bytes(
                self._read_blob(parent_checkpoint["blob_refs"]["bundle"])
            )
            fork.verify_event_history_parent(
                parent_manifest, parent_timeline_id=parent_bundle.event_history.timeline_id,
                parent_chain_head_sha256=(
                    parent_bundle.event_history.last_persistence_record_digest()
                ), trust=self.trust,
            )
            revision_lineage = MemoryRevisionLineage.fork_from_verified_bundle(
                verified_bundle=parent_bundle, checkpoint_manifest=parent_manifest,
                timeline_id=timeline_id, fork_manifest=fork, trust=self.trust,
            )
        else:
            revision_lineage = MemoryRevisionLineage.root(timeline_id)
        feedback_id = record["blob_refs"].get("behavior_feedback")
        feedback_bytes = None if feedback_id is None else self._read_blob(feedback_id)
        if (sha256_hex(values["bundle"]) != record["bundle_sha256"]
                or bundle.timeline_id != timeline_id
                or bundle.simulation_tick != record["simulation_tick"]
                or bundle.event_chain_head_sha256 != record["event_chain_head_sha256"]):
            raise PermissionError("save metadata does not match its signed bundle")
        expected_agents = self._expected_agents(values["cognition"])
        verified = bundle.verify_and_stage(
            world_checkpoint=values["world"], cognitive_snapshot=values["cognition"],
            expected_agents=expected_agents, trust=self.trust,
            event_history_resolver=self.event_history_resolver,
            behavior_feedback_snapshot=feedback_bytes,
            memory_revision_lineage=revision_lineage,
            codec=self.codec,
        )
        actual_event_ids = tuple(item.id for item in verified.event_history.get_events())
        if tuple(sorted(actual_event_ids)) != tuple(sorted(record["event_ids"])):
            raise PermissionError("Save_ID Event dependency list differs from verified EventHistory")
        if fork_id is not None:
            checkpoint_resource = f"sha256:{fork.fork_checkpoint_id}"
            checkpoint = catalog["checkpoints"].get(checkpoint_resource)
            if not isinstance(checkpoint, dict):
                raise PermissionError("saved timeline fork checkpoint is absent from dependency index")
            parent_manifest = SnapshotBundleManifest.from_bytes(
                self._read_blob(checkpoint["blob_refs"]["bundle"])
            )
            parent_history = self._resolve_event_history(fork.fork_checkpoint_id)
            fork.verify_event_history_parent(
                parent_manifest, parent_timeline_id=parent_history.timeline_id,
                parent_chain_head_sha256=parent_history.last_persistence_record_digest(),
                trust=self.trust,
            )
        if (record["parent_timeline_id"] != (None if fork is None else fork.parent_timeline_id)
                or record["fork_checkpoint_id"] != (None if fork is None else fork.fork_checkpoint_id)):
            raise PermissionError("Save metadata Timeline ancestry differs from its signed fork manifest")
        return VerifiedSave(self._metadata_from_record(record), values["world"],
                            values["cognition"], bundle, fork, expected_agents, feedback_bytes,
                            revision_lineage)

    def _resolve_event_history(self, checkpoint_id: str) -> object:
        """Resolve only retained, signed checkpoint ancestry from the catalog."""
        from cognitive_world.event.history import EventHistory
        resource_id = f"sha256:{checkpoint_id}"
        with self._locked():
            try:
                verified, _ = self._resolve_verified_checkpoint(checkpoint_id)
            except KeyError:
                if callable(self._host_event_history_resolver):
                    return self._host_event_history_resolver(checkpoint_id)
                raise PermissionError("fork checkpoint is not retained by the save dependency graph")
            catalog = self._load_catalog()
            checkpoint = catalog["checkpoints"].get(resource_id)
            if not isinstance(checkpoint, dict):
                raise PermissionError("verified checkpoint disappeared from dependency graph")
            if (verified.timeline_id != checkpoint["timeline_id"]
                    or verified.simulation_tick != checkpoint["simulation_tick"]
                    or verified.event_history.last_persistence_record_digest()
                    != checkpoint["event_chain_head_sha256"]
                    or type(verified.event_history) is not EventHistory):
                raise PermissionError("retained checkpoint metadata does not match signed history")
            return verified.event_history

    def _resolve_verified_checkpoint(
        self, checkpoint_id: str,
    ) -> tuple[object, MemoryRevisionLineage]:
        """Verify a retained Bundle and its exact Memory ancestry recursively."""
        from cognitive_world.core.snapshot_bundle import (
            VerifiedSnapshotBundle, _require_verified_snapshot_bundle,
        )

        resource_id = f"sha256:{checkpoint_id}"
        active = getattr(self._checkpoint_verification_local, "active", None)
        owns_stack = active is None
        if owns_stack:
            active = set()
            self._checkpoint_verification_local.active = active
        if resource_id in active:
            if owns_stack:
                del self._checkpoint_verification_local.active
            raise PermissionError("cycle in saved checkpoint ancestry")
        active.add(resource_id)
        try:
            catalog = self._load_catalog()
            checkpoint = catalog["checkpoints"].get(resource_id)
            if not isinstance(checkpoint, dict):
                raise KeyError(checkpoint_id)
            refs = checkpoint.get("blob_refs")
            if not isinstance(refs, dict):
                raise PermissionError("retained checkpoint has no signed component references")
            world_bytes = self._read_blob(refs["world"])
            cognition_bytes = self._read_blob(refs["cognition"])
            bundle_bytes = self._read_blob(refs["bundle"])
            if f"sha256:{sha256_hex(bundle_bytes)}" != resource_id:
                raise PermissionError("retained checkpoint manifest identity mismatch")
            manifest = SnapshotBundleManifest.from_bytes(bundle_bytes)
            if manifest.timeline_id != checkpoint["timeline_id"]:
                raise PermissionError("checkpoint index Timeline differs from signed Bundle")
            fork_bytes_id = refs.get("fork")
            if fork_bytes_id is None:
                lineage = MemoryRevisionLineage.root(manifest.timeline_id)
            else:
                fork = TimelineForkManifest.from_bytes(self._read_blob(fork_bytes_id))
                parent, _ = self._resolve_verified_checkpoint(fork.fork_checkpoint_id)
                parent_checkpoint = catalog["checkpoints"].get(
                    f"sha256:{fork.fork_checkpoint_id}"
                )
                if not isinstance(parent_checkpoint, dict):
                    raise PermissionError("retained fork checkpoint is absent from dependency index")
                parent_manifest = SnapshotBundleManifest.from_bytes(
                    self._read_blob(parent_checkpoint["blob_refs"]["bundle"])
                )
                fork.verify_event_history_parent(
                    parent_manifest,
                    parent_timeline_id=parent.timeline_id,
                    parent_chain_head_sha256=parent.event_history.last_persistence_record_digest(),
                    trust=self.trust,
                )
                lineage = MemoryRevisionLineage.fork_from_verified_bundle(
                    verified_bundle=parent, checkpoint_manifest=parent_manifest,
                    timeline_id=manifest.timeline_id, fork_manifest=fork,
                    trust=self.trust,
                )
            expected_agents = self._expected_agents(cognition_bytes)
            feedback_id = refs.get("behavior_feedback")
            feedback_bytes = None if feedback_id is None else self._read_blob(feedback_id)
            verified = manifest.verify_and_stage(
                world_checkpoint=world_bytes, cognitive_snapshot=cognition_bytes,
                expected_agents=expected_agents, trust=self.trust,
                event_history_resolver=self._resolve_event_history,
                behavior_feedback_snapshot=feedback_bytes,
                memory_revision_lineage=lineage,
                codec=self.codec,
            )
            if (type(verified) is not VerifiedSnapshotBundle
                    or verified.timeline_id != checkpoint["timeline_id"]
                    or verified.simulation_tick != checkpoint["simulation_tick"]
                    or verified.event_history.last_persistence_record_digest()
                    != checkpoint["event_chain_head_sha256"]):
                raise PermissionError("verified checkpoint differs from retained signed index")
            _require_verified_snapshot_bundle(verified)
            return verified, lineage
        finally:
            active.discard(resource_id)
            if owns_stack:
                del self._checkpoint_verification_local.active

    def _install_blob(self, resource_id: str, content: bytes, stage_dir: Path) -> None:
        if not isinstance(content, bytes) or resource_id != f"sha256:{sha256_hex(content)}":
            raise ValueError("resource identity does not match immutable content")
        target = self._blob_path(resource_id)
        if target.exists():
            if self._read_blob(resource_id) != content:
                raise PermissionError("content-addressed resource collision")
            return
        temporary = stage_dir / f"{uuid4().hex}.tmp"
        with open(temporary, "xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def _read_blob(self, resource_id: str) -> bytes:
        if not isinstance(resource_id, str) or not resource_id.startswith("sha256:"):
            raise ValueError("invalid resource identity")
        path = self._blob_path(resource_id)
        content = path.read_bytes()
        if f"sha256:{sha256_hex(content)}" != resource_id:
            raise PermissionError("immutable resource content digest mismatch")
        return content

    def _blob_path(self, resource_id: str) -> Path:
        digest = resource_id.removeprefix("sha256:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid SHA-256 resource ID")
        return self.resources / f"{digest}.blob"

    def _load_catalog(self) -> dict[str, object]:
        raw = self.catalog_path.read_bytes()
        if len(raw) > self._MAX_CATALOG_BYTES:
            raise ValueError("save catalog exceeds size limit")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            if (not isinstance(envelope, dict) or set(envelope) != {"body", "signature"}
                    or not isinstance(envelope["body"], dict)):
                raise ValueError("malformed save catalog")
            body_bytes = self._canonical(envelope["body"])
            signature = base64.b64decode(envelope["signature"], validate=True)
            if not self.trust.verify(self._CATALOG_PURPOSE, body_bytes, signature):
                raise PermissionError("save catalog signature verification failed")
            body = envelope["body"]
            if (set(body) != {"version", "saves", "checkpoints", "last_transaction_id"}
                    or body["version"] != 1 or not isinstance(body["saves"], dict)
                    or not isinstance(body["checkpoints"], dict)):
                raise ValueError("unsupported save catalog schema")
            for save_id, record in body["saves"].items():
                if not isinstance(save_id, str) or not isinstance(record, dict):
                    raise ValueError("malformed save catalog entry")
                if self._metadata_from_record(record).save_id != save_id:
                    raise ValueError("save catalog key differs from Save_ID")
            for resource_id, checkpoint in body["checkpoints"].items():
                if (not isinstance(resource_id, str) or not isinstance(checkpoint, dict)
                        or set(checkpoint) != {"timeline_id", "simulation_tick", "resource_ids",
                                               "blob_refs", "event_chain_head_sha256"}
                        or not isinstance(checkpoint["timeline_id"], str)
                        or type(checkpoint["simulation_tick"]) is not int
                        or checkpoint["simulation_tick"] < 0
                        or not isinstance(checkpoint["resource_ids"], list)
                        or not isinstance(checkpoint["blob_refs"], dict)
                        or not {"world", "cognition", "bundle"}.issubset(checkpoint["blob_refs"])
                        or checkpoint["blob_refs"]["bundle"] != resource_id
                        or not set(checkpoint["blob_refs"].values()).issubset(set(checkpoint["resource_ids"]))):
                    raise ValueError("malformed retained checkpoint dependency entry")
            return body
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
                base64.binascii.Error) as error:
            raise ValueError("malformed signed save catalog") from error

    def _write_catalog(self, body: dict[str, object]) -> None:
        payload = self._canonical(body)
        signature = self.trust.sign(self._CATALOG_PURPOSE, payload)
        envelope = self._canonical({"body": body, "signature": base64.b64encode(signature).decode("ascii")})
        descriptor, temporary = tempfile.mkstemp(prefix=".catalog-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(envelope)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.catalog_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _append_journal(self, record: dict[str, object]) -> None:
        payload = self._canonical(record) + b"\n"
        with open(self.journal_path, "ab") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def _recover_incomplete_transactions(self) -> None:
        if self.journal_path.exists():
            raw = self.journal_path.read_bytes()
            if len(raw) > 64 * 1024 * 1024:
                raise ValueError("save transaction journal exceeds size limit")
            pending: dict[str, dict[str, object]] = {}
            if raw and not raw.endswith(b"\n"):
                last_break = raw.rfind(b"\n") + 1
                with open(self.journal_path, "r+b") as stream:
                    stream.truncate(last_break)
                    stream.flush()
                    os.fsync(stream.fileno())
                raw = raw[:last_break]
            for line in raw.splitlines():
                item = json.loads(line.decode("utf-8"))
                if not isinstance(item, dict) or not isinstance(item.get("transaction_id"), str):
                    raise ValueError("save transaction journal is malformed")
                if item.get("phase") == "PREPARED":
                    pending[item["transaction_id"]] = item
                elif item.get("phase") in {"COMMITTED", "COMMITTED_RECOVERED", "ABORTED_RECOVERED"}:
                    pending.pop(item["transaction_id"], None)
            catalog = self._load_catalog()
            last_id = catalog.get("last_transaction_id")
            for transaction_id in tuple(pending):
                phase = "COMMITTED_RECOVERED" if transaction_id == last_id else "ABORTED_RECOVERED"
                self._append_journal({"transaction_id": transaction_id, "phase": phase})
                pending.pop(transaction_id)
            # Catalog is the commit authority. All other incomplete staged writes
            # are discarded; immutable unreferenced blobs are later GC-safe.
        catalog = self._load_catalog()
        checkpoints = self._prune_checkpoint_index(catalog["checkpoints"], catalog["saves"])
        if checkpoints != catalog["checkpoints"]:
            transaction_id = str(uuid4())
            self._append_journal({"transaction_id": transaction_id, "phase": "PREPARED",
                                  "operation": "recovery_reconcile"})
            self._write_catalog({"version": 1, "saves": catalog["saves"],
                                 "checkpoints": checkpoints,
                                 "last_transaction_id": transaction_id})
            self._append_journal({"transaction_id": transaction_id, "phase": "COMMITTED",
                                  "operation": "recovery_reconcile"})
            catalog = self._load_catalog()
        self._collect_unreferenced(catalog["saves"])

    @classmethod
    def _canonical(cls, value: object) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    @staticmethod
    def _metadata_record(metadata: SaveMetadata, refs: dict[str, str], *, name: str | None) -> dict[str, object]:
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("save name must be non-empty when supplied")
        return {
            "schema_version": metadata.schema_version, "save_id": metadata.save_id,
            "timeline_id": metadata.timeline_id, "kind": metadata.kind.value,
            "name": name, "created_at": metadata.created_at,
            "simulation_tick": metadata.simulation_tick,
            "runtime_session_id": metadata.runtime_session_id,
            "restore_generation": metadata.restore_generation,
            "snapshot_id": metadata.snapshot_id, "bundle_sha256": metadata.bundle_sha256,
            "event_chain_head_sha256": metadata.event_chain_head_sha256,
            "parent_timeline_id": metadata.parent_timeline_id,
            "fork_checkpoint_id": metadata.fork_checkpoint_id,
            "event_ids": list(metadata.event_ids), "resource_ids": list(metadata.resource_ids),
            "blob_refs": refs, "bundle_resource_id": refs["bundle"],
            "integrity": metadata.integrity,
        }

    @staticmethod
    def _metadata_from_record(record: dict[str, object]) -> SaveMetadata:
        required = {"schema_version", "save_id", "timeline_id", "kind", "name", "created_at",
                    "simulation_tick", "runtime_session_id", "restore_generation", "snapshot_id",
                    "bundle_sha256", "event_chain_head_sha256", "parent_timeline_id",
                    "fork_checkpoint_id", "event_ids", "resource_ids", "blob_refs",
                    "bundle_resource_id", "integrity"}
        if set(record) != required or record["schema_version"] != 1:
            raise ValueError("save metadata schema is unsupported or malformed")
        try:
            kind = SaveKind(record["kind"])
            if (not isinstance(record["save_id"], str) or not record["save_id"]
                    or not isinstance(record["timeline_id"], str) or not record["timeline_id"]
                    or type(record["simulation_tick"]) is not int or record["simulation_tick"] < 0
                    or type(record["restore_generation"]) is not int or record["restore_generation"] < 0
                    or not isinstance(record["event_ids"], list)
                    or not isinstance(record["resource_ids"], list)
                    or not isinstance(record["blob_refs"], dict)):
                raise ValueError("invalid Save metadata values")
            resource_ids = tuple(record["resource_ids"])
            refs = record["blob_refs"]
            if (len(resource_ids) != len(set(resource_ids))
                    or not {"world", "cognition", "bundle"}.issubset(refs)
                    or not set(refs.values()).issubset(set(resource_ids))
                    or record["bundle_resource_id"] != refs["bundle"]
                    or record["snapshot_id"] != f"sha256:{record['bundle_sha256']}"
                    or record["integrity"] != "signed-bundle-verified"
                    or not isinstance(record["runtime_session_id"], str)
                    or not record["runtime_session_id"]
                    or not isinstance(record["created_at"], str)):
                raise ValueError("Save resource, snapshot or integrity metadata is inconsistent")
            return SaveMetadata(
                record["save_id"], record["timeline_id"], kind,
                record["simulation_tick"], record["runtime_session_id"],
                record["restore_generation"], record["snapshot_id"], record["bundle_sha256"],
                record["event_chain_head_sha256"], record["parent_timeline_id"],
                record["fork_checkpoint_id"], tuple(record["event_ids"]),
                resource_ids, record["schema_version"],
                record["integrity"], record["created_at"],
            )
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("save metadata is invalid") from error

    def _expected_agents(self, cognitive_bytes: bytes) -> tuple[object, ...]:
        snapshot = CognitiveStateSnapshot.from_bytes(cognitive_bytes, trust=self.trust, codec=self.codec)
        return snapshot.body.expected_agents

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self._read_only:
            with self._thread_lock:
                yield
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path_lock, self._thread_lock:
            depth = getattr(self._lock_local, "depth", 0)
            if depth:
                self._lock_local.depth = depth + 1
                try:
                    yield
                finally:
                    self._lock_local.depth -= 1
                return
            with open(self.lock_path, "a+b") as stream:
                if os.name == "nt":
                    import msvcrt
                    if os.fstat(stream.fileno()).st_size == 0:
                        stream.seek(0)
                        stream.write(b"0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        self._lock_local.depth = 1
                        yield
                    finally:
                        self._lock_local.depth = 0
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                    try:
                        self._lock_local.depth = 1
                        yield
                    finally:
                        self._lock_local.depth = 0
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        import shutil
        shutil.rmtree(path)
