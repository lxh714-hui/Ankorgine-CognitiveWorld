# CognitiveWorld — Checkpoint, History and Runtime Lifecycle

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Checkpoint, history and Runtime lifecycle.

## Authority and scope

**Frozen authority level:** Domain architecture; exact formats/signature payloads stay DATA_CONTRACTS.

**Assigned responsibility:** Capture/verify, ancestry/forks, staged reconstruction, activation/cold resume, retained recovery limitations.

Only marked architectural excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A31 — Persistence/capture/recovery responsibility**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A33 — Isolated Runtime reconstruction and publication roles**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- Domain meaning of world facts, Memory, Belief and social experience.
- Detailed record/signature payload definitions owned by DATA_CONTRACTS.md.
- Unspecified host-task restoration or stronger recovery guarantees.

## Migrated excerpts and pending section outline

Only marked approved excerpts have migrated. Other entries remain pending. Source titles retain their original stage/status; no title is new acceptance evidence.

### ID 79 — Persistence

<a id="arch-source-79"></a>

<!-- phase3c-begin:C-79-1130-1158 -->

<a id="arch-source-79-part-1"></a>

**Phase 3C source excerpt:** ID 79, lines 1130–1158 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-79-1130-1158:1130-1158 -->

The current persistence foundation has two distinct layers. An Event is ordinary
data until the trusted `EventProcessor` completes its normal validation and
WorldState application. When a host explicitly injects a `PersistenceTrust`
signer, successful processing also emits a versioned attestation tied to the
Event digest, processor evidence, actual WorldUpdate digest, simulation tick,
changed slot fingerprints, and preceding attestation. The attestation is
stored alongside the canonical EventHistory entry; it does not replace
EventHistory or grant an Event new authority.

`WorldState` can export a versioned, signed checkpoint from its canonical
collections and slot provenance. Restore verifies the checkpoint trust,
attested EventHistory chain, current slot fingerprints, and each Event-origin
slot's attested resulting value, then constructs an isolated WorldState and
EventHistory pair. A failed verification returns no restorable pair and does
not mutate an active WorldState. Initialization and unknown provenance remain
distinct from Event provenance. `WindowsDpapiPersistenceTrust` provides an
explicitly initialized, current-user DPAPI-protected HMAC key ring for local
Windows desktop use. It stores only protected keys under the user's LocalAppData
profile by default; signature envelopes carry format version, algorithm, key
ID and purpose. Opening a missing or corrupt ring fails closed, and signing
never initializes it implicitly. Rotation activates a new key while retaining
older keys for verification until explicit revocation. DPAPI protects at the
Windows user-profile boundary, not against malicious same-user processes or
cross-device migration. HMAC is shared-key trust, not non-repudiation.
`HmacPersistenceTrust` remains a raw-key adapter for tests and explicitly
managed hosts. No production root is initialized by default. Snapshot capture
does not itself freeze Runtime writes.


<!-- phase3c-end:C-79-1130-1158 -->


### ID 137 — Timeline, save slots, and live sessions (lifecycle contract; backend partial)

<a id="arch-source-137"></a>

<!-- phase3c-begin:C-137-1974-2006 -->

<a id="arch-source-137-part-1"></a>

**Phase 3C source excerpt:** ID 137, lines 1974–2006 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-137-1974-2006:1974-2006 -->

A timeline is a branch of simulation history; a save slot is a player/system
reference to a recoverable checkpoint on one timeline; and a live session is
the currently active runtime. They are distinct identities and lifecycles.
Automatic saves are system-managed and may be evicted only by an explicit
automatic-save retention policy. Quick saves are a separate convenience path.
Manual saves are player-managed: the player may create, replace, or delete a
named save, and the system must never silently evict one. Replacement must
make the new checkpoint fully recoverable before releasing the old save's
dependencies; a failed replacement leaves the old checkpoint usable.

Continuing from an older checkpoint creates or selects an isolated timeline
branch. WorldState, EventHistory, cognition state, and per-slot provenance on
the branch must not leak into or mutate sibling timelines. Shared ancestor
history is immutable. Save deletion, timeline deletion, and automatic-save
retention eviction are separate operations. Logical deletion is separate from
physical reclamation so a save or timeline operation cannot reclaim data still
needed by another checkpoint.

The backend SaveManager now implements signed save-catalog publication,
content-addressed WorldState/CognitiveState/Bundle resources, automatic,
quick, and manual slot lifecycles, catalog-derived dependency counts, explicit
manual deletion/replacement, and a staged path into the existing
RestoreCoordinator. Its signed catalog is the single logical commit point;
immutable blobs are installed first, and a transaction journal enables
interrupted prepare/commit reconciliation. Shared fork ancestry is retained
through the signed checkpoint index and save resource graph. These are
process-level filesystem contracts, not a guarantee against every power-loss
or storage-device failure. SaveManager does not implement timeline deletion,
full active recovery of scheduler/host configuration, UI, or complete product
save/restore acceptance. The lifecycle and recovery limits are detailed in
`DATA_CONTRACTS.md`.


<!-- phase3c-end:C-137-1974-2006 -->


### ID 174 — Unified cognitive snapshot (implemented staging slice)

<a id="arch-source-174"></a>

<!-- phase3c-begin:C-174-2470-2472 -->

<a id="arch-source-174-part-1"></a>

**Phase 3C source excerpt:** ID 174, lines 2470–2472 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-174-2470-2472:2470-2472 -->

Governed Belief, Goal, SelfModel and Emotion updates now retain a separately registered construction permit. Validator issuance keeps a private record binding the exact candidate and a detached content snapshot; changing or copying the returned result does not alter that record. Applier and canonical Store boundaries recheck the registered origin under the RuntimeWriteFence. Replacing a candidate's public permit or pairing a cloned candidate with an old result does not transfer authority across restore generations. This preserves the existing owner, source and stale-state governance; it does not authenticate arbitrary same-process code or make cognitive proposals durable restore records.


<!-- phase3c-end:C-174-2470-2472 -->

<!-- phase3c-begin:C-174-2474-2477 -->

**Phase 3C source excerpt:** ID 174, lines 2474–2477 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-174-2474-2477:2474-2477 -->

Validation and reconstruction happen in unpublished isolated cognition and memory objects. Unsupported values, missing linked state, invalid owners, source-reference failures, manifest/context mismatches, and unsupported schema versions fail closed. The snapshot records both the Runtime registry manifest and captured links. Isolated reconstruction additionally requires an independently supplied expected Agent manifest from the trusted host; an embedded unsigned manifest cannot prove its own completeness. AgentRegistry uses a membership lock separate from RuntimeWriteFence; direct private `_agents` mutation can bypass it. WorkingMemory, Observation/Percept inputs, DecisionContext, proposals/traces, provider cursors, and diagnostic scheduler/Event Tree state are explicitly excluded. No active Runtime state is switched or modified. A timeline ID in the cognition snapshot is metadata, while signed EventHistory and fork manifests provide the narrower branch-lineage contract. An isolated staged Runtime reconstruction factory and a narrow RestoreCoordinator publication path are available. Cross-process task isolation and full recovery remain future work.



<!-- phase3c-end:C-174-2474-2477 -->


### ID 175 — Timeline-aware EventHistory and Runtime recovery boundary

<a id="arch-source-175"></a>

<!-- phase3c-begin:C-175-2479-2485 -->

<a id="arch-source-175-part-1"></a>

**Phase 3C source excerpt:** ID 175, lines 2479–2485 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-175-2479-2485:2479-2485 -->

Signed Event processing credentials v2 bind new commits to their immutable owning Timeline. Persisted EventHistory lineage v1 represents a child through a signed fork/checkpoint reference, an immutable verified parent prefix, and a child-local suffix. Each local event is checked against its timeline and predecessor; legacy credentials without Timeline ownership are not upgraded.

IsolatedRuntimeReconstructionFactory reconstructs a staged Runtime from verified snapshot components and an explicitly host-assembled dependency set. RestoreCoordinator supplies a narrow in-process freeze, generation invalidation, final staged-state revalidation, and single ActiveRuntimeSlot publication path. SaveManager manages supported save slots, signed catalog/resource dependencies, and cooperating same-directory process leases.

These capabilities are implemented slices, not a complete application restore guarantee. Scheduler queues, provider work, transient Observation/WorkingMemory, and host configuration are not all persisted. Same-process code outside the fence and registry coordination is not sandboxed; cross-host locking and power-loss durability are not established. See the later reconstruction, activation and SaveManager sections for exact boundaries.


<!-- phase3c-end:C-175-2479-2485 -->


### ID 176 — Isolated Runtime Reconstruction — staged only

<a id="arch-source-176"></a>

<!-- phase3c-begin:C-176-2487-2493 -->

<a id="arch-source-176-part-1"></a>

**Phase 3C source excerpt:** ID 176, lines 2487–2493 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-176-2487-2493:2487-2493 -->

`runtime.reconstruction.IsolatedRuntimeReconstructionFactory` now re-verifies the signed WorldState checkpoint, CognitiveStateSnapshot, bundle manifest, EventHistory lineage and TimelineForkManifest from their serialized inputs. It then creates a child EventHistory whose parent prefix is frozen at the verified checkpoint, creates a fresh clock and a new permanently staged-only RuntimeWriteFence, and asks an explicit host assembler to build the executable Runtime around those isolated objects. Cross-component validation checks the exact Agent/Character roster, six canonical cognition stores through owner-scoped CognitionContexts, EventProcessor bindings, ActionLoop bindings, safety, schedules and provider-discovery policy.

The result is `StagedRuntime(status="staged_not_active")`: stopped, write-frozen, and unable to be unfrozen through the current RuntimeWriteFence API. This is a validated staged assembly, not activation, publication, or a live restore. The factory does not reuse an old Runtime and does not start background work. The host assembler remains trusted code; its dependency declaration records provenance but is not itself a cryptographic proof.

Snapshot-backed dependencies are WorldState, EventHistory prefix, and Belief/Goal/SelfModel/Memory/Emotion/Personality. The clock is rebuilt at the checkpoint tick; the child EventHistory is reconstructed from the verified fork. Character definitions and RuntimeAgent metadata, pending Agent/Event schedules, EventHandler registrations, AgentDecision policy, AgentActionLoop configuration, CognitionContext construction, Safety configuration, Observation delivery policy, providers, player session, and optional content services must be explicitly rebuilt or explicitly disabled where permitted. Missing declarations and unsupported required dependencies fail closed. Observation records, WorkingMemory, DecisionContext, traces, Event Tree diagnostics, scheduler diagnostics, and provider tasks are not restored by these snapshots.


<!-- phase3c-end:C-176-2487-2493 -->

<!-- phase3c-begin:C-176-2495-2501 -->

**Phase 3C source excerpt:** ID 176, lines 2495–2501 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-176-2495-2501:2495-2501 -->

Strict reconstruction uses `SimulationRuntime(strict_dependency_binding=True)` to reject mismatched EventProcessor and ActionLoop dependencies instead of applying the legacy compatibility rebinding behavior. `allow_environment_provider_discovery=False` prevents staged construction from resolving an ambient Cognitive Review endpoint; model providers must be host-injected or explicitly disabled. These flags do not alter existing Runtime defaults.


The reconstruction entry point also requires the currently active `SimulationRuntime` solely as a forbidden-alias set. The host assembler never receives that Runtime. After assembly, mutable Runtime authorities, nested EventProcessor handlers, ActionLoop/Resolution components, schedulers, registry, safety, providers and other directly held services are checked for identity overlap. Where the active Runtime exposes cognition contexts, its actual canonical CognitionContainer and MemoryStore are also checked against the staged stores. This is an object-identity guard, not protection against malicious host assembler code that mutates captured external objects.



<!-- phase3c-end:C-176-2495-2501 -->


### ID 177 — RestoreCoordinator — controlled activation boundary

<a id="arch-source-177"></a>

<!-- phase3c-begin:C-177-2503-2513 -->

<a id="arch-source-177-part-1"></a>

**Phase 3C source excerpt:** ID 177, lines 2503–2513 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-177-2503-2513:2503-2513 -->

`runtime.recovery.RestoreCoordinator` is the only supported publisher for a factory-issued `StagedRuntime`. `ActiveRuntimeSlot` provides one synchronized active-reference boundary per host composition. The coordinator serializes requests and re-verifies the original signed bundle, WorldState contents, all six canonical cognition Stores, child EventHistory lineage, assembly bindings, Timeline/tick and checkpoint anchor before freezing the old Runtime. A failed pre-freeze validation leaves the active Runtime untouched.

Freeze and final commits serialize on each RuntimeWriteFence lock. The old fence enters a coordinator-owned frozen state and advances its generation; public unfreeze calls cannot reactivate it during recovery. Once publication succeeds, the old fence is permanently retired, so old Provider results and permits cannot capture a replacement generation. If failure occurs before publication, the coordinator may resume the old Runtime only after the old generation has advanced; previously issued permits remain invalid. If rollback safety is uncertain after old-fence retirement, the slot enters `RECOVERY_REQUIRED` and remains non-writable.

Staged activation is a one-shot coordinator operation. While holding the new fence lock, the coordinator issues a fresh RuntimeSession ID and Restore Generation, starts the already assembled Runtime without launching background services, retires the old fence, and publishes the single active pointer. New writes cannot capture on the new fence until publication finishes. The normal production EventProcessor, cognitive Store and Memory commits remain the final write boundaries under that fence.

ARCH-004 closes the validated-stage publication window: the host pre-publication hook runs before the final check. The coordinator holds the staged AgentRegistry membership lock and staged RuntimeWriteFence lock while rechecking signed inputs, WorldState, six cognition Stores, EventHistory lineage, clock, Timeline, owner roster and dependency aliases. It checks again after `start()` and immediately before the active-pointer swap; the only accepted WorldState difference caused by `start()` is sealing initialization. A changed staged invariant fails closed in `RECOVERY_REQUIRED`, leaving the old slot reference and both writers closed. Ordinary pre-publication hook exceptions without detected integrity changes retain the prior safe-resume behavior with a new old generation. This remains an in-process boundary for fence-governed writes and registry membership; arbitrary same-process private mutation or custom components outside the fence are not sandboxed.

This is an in-process coordination contract, not a process-wide sandbox: hosts must route active Runtime access through `ActiveRuntimeSlot`, and arbitrary same-process code can still mutate private fields or retain unrelated custom callbacks. SaveManager coordinates its catalog and immutable snapshot resources, but does not persist scheduler state, provide autonomous task cancellation, complete Context Freeze, or cross-process stale-task fencing. The phase does not claim fault-tolerant recovery from every process termination or power-loss scenario.


<!-- phase3c-end:C-177-2503-2513 -->


### ID 178 — SaveManager and Save Lifecycle — backend slice

<a id="arch-source-178"></a>

<!-- phase3c-begin:C-178-2515-2563 -->

<a id="arch-source-178-part-1"></a>

**Phase 3C source excerpt:** ID 178, lines 2515–2563 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-178-2515-2563:2515-2563 -->

`runtime.save_manager.SaveManager` captures the canonical WorldState checkpoint,
six-store CognitiveStateSnapshot, EventHistory lineage, and signed
SnapshotBundleManifest under the RuntimeWriteFence and AgentRegistry snapshot
scopes. It also captures the Runtime-owned BehaviorFeedback history as a
versioned signed bundle component; feedback conditions are re-resolved through
the trusted observations bound by each committed failure Event. It stores
immutable content-addressed blobs and publishes a signed
catalog atomically as the logical slot commit point. Catalog records bind
Save_ID to Timeline_ID, tick, source Runtime session/generation, bundle digest,
Event chain head/IDs, fork checkpoint, and resource identities.

Automatic saves use an explicit retention count (default five) and prune only
automatic entries. Quick save uses one independent replaceable slot. Manual
slots are never pruned automatically and can only be replaced or deleted by an
explicit Save_ID operation. Replacement installs resources before catalog
publication, so pre-commit failure leaves the original slot available. A
prepare/commit journal and content-addressed resource reconciliation handle
interrupted operations at process restart; the signed catalog remains the
commit authority. Dependency counts are rebuilt from catalog references.
Child saves retain the full ancestor resource closure, while a signed
checkpoint index resolves parent histories after a parent slot is removed.
Staged/active runtimes hold signed resource-identity lease manifests in the
save directory and keep separate OS file locks for their lifetimes. The
existing cross-process catalog lock serializes lease publication, catalog
changes, reference reconstruction, and garbage collection. Reclamation
requires no catalog or live locked Runtime lease reference. An OS lock
released by process exit can be reclaimed without time-based expiry;
corrupt or unverifiable lease records fail closed. This protects cooperating
local processes using the same directory and trust root, not arbitrary hosts
or power-loss durability.

`load_verified` rechecks catalog signature, blob digests, SnapshotBundle,
WorldState and cognition signatures, owners, EventHistory sources, tick,
Timeline and fork lineage. `stage_restore` creates only a frozen
StagedRuntime; it cannot activate or publish it. `RestoreCoordinator` remains
the activation path for in-process parent-to-child restore. First publication
after a cold start instead uses `stage_cold_resume` and `ColdRuntimePublisher`:
the former reuses `load_verified`, repeats signed Bundle and complete
EventHistory verification, and assembles the original saved Timeline with a
fresh staged-only fence and session. The latter rechecks signed and assembled
state under the publication lock before issuing an `ActiveRuntimeSlot`. It
neither invents an active parent nor turns original-Timeline resumption into a
fork. The content host provides an explicit Scenario record allowlist to both
WorldState and Bundle verification; codec selection grants no authority.
Transient Observations are not reconstructed as past observations. Current
authorized mechanism facts are observed anew through EventProcessor after
publication. This process-local protocol does not recover tasks or display
delivery across process crashes.

<!-- phase3c-end:C-178-2515-2563 -->


### Content received from coordinated splits

- Original ID **189**, source lines **2694–2696**: pending coordinated migration; the original heading keeps its separate primary assignment.

## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) — canonical owner for A04, A08, A17, A18, A19, A20, A22, A32, A34.
- [MEMORY_DESIGN.md](../MEMORY_DESIGN.md) — canonical owner for A15.
- [EXECUTION.md](EXECUTION.md) — canonical owner for A10, A11.
- [WORLD_MODEL.md](WORLD_MODEL.md) — canonical owner for A03, A24.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [MEMORY_DESIGN.md](../MEMORY_DESIGN.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [COGNITION.md](COGNITION.md)
- [EXECUTION.md](EXECUTION.md)
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md)
- [PERCEPTION.md](PERCEPTION.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)

## Historical and implementation-status handling

Only the explicitly marked Phase 3D historical quotations below have migrated. Other historical or mixed content remains pending. These source-stage records establish no new runtime capability, current test result or normative definition.

<a id="arch-history-h-79-1172-1178"></a>
### Historical source record — Persistence

**Historical record — Historical design rationale.** This is an original-stage quotation, not a current normative definition, current implementation inventory or newly executed test result.

Source: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), original heading ID **79**, lines **1172–1178**; original heading: **Persistence**.
Source document SHA-256: `d111ce446dcdf8a16182dc465f42a851177a569547b3a0cfc6519d6e8653f751`. Captured from the working tree based on `838e6913e6e6d6deefcaa6bbf126cad2139550b7`; the quoted bytes are not asserted to be the committed version.

Original context: Original foundation lists expected long-term persistence content and says it is not full Runtime persistence.
Chronology: Original future/expected wording; no calendar date stated. Calendar date: not stated in the source.

Temporal words such as “now”, “currently”, “here”, “this document”, “below” and “at this stage” retain their original source context. Legacy paths are historical evidence, not current repository instructions. The full quoted limitations and original validation status remain attached; no broader supersession or present-day acceptance is inferred.

Current normative definitions remain with their frozen owners, including [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) and [META_CONTRACTS.md](../META_CONTRACTS.md); this quotation creates no additional authority.

<!-- Phase 3D exact source quotation begins: H-79-1172-1178 -->
> This is not full runtime persistence. Long-term persistence is expected to
> include:
>
> - WorldState;
> - Event History;
> - Memory;
> - Causal Records.
<!-- Phase 3D exact source quotation ends: H-79-1172-1178 -->


Contact: ankorgine@outlook.com
