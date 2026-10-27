# CognitiveWorld Data Contracts

## B3 immutable expectation and authoritative result association

B3 adds two exact system-only payloads in the existing MemoryStore:
`ActionExpectationRecord/v1` (`system_action_expectation_v1`) and
`ActionResultAssociation/v1` (`system_action_result_association_v1`). Their
independent signing purposes are `cognitive-world/action-expectation/v1` and
`cognitive-world/action-result-association/v1`; the closed historical policy is
`attempt-result-association/v1`. They are not L1 proofs, semantic Memory,
WorldState facts or permissions to revise cognition.

### Trusted action expectation source binding v1

`ActionExpectationSourceBinding/v1` is a third, independent system record of
entry provenance, not another expectation, result or L1 proof. Its exact Memory
type is `system_action_expectation_source_v1`, signing purpose is
`cognitive-world/action-expectation-source/v1`, and closed policy is
`trusted-action-entry/v1`. Identity binds version, canonical Timeline, owner and
proposal ID; content changes conflict instead of creating another identity.

The closed common envelope stores identity/policy, source kind, owner/Timeline,
proposal ID and canonical proposal digest, representation, source-specific
payload, original source references and entry tick. `NpcSelectedExpectation`
contains exactly candidate ID, actual decision tick and the unchanged original
prediction. `PlayerExpectationAbsent` contains only the registered player-absence
policy. Missing required fields, extra payload fields, unknown kinds/versions or
policies are not inferred or accepted as defaults. References remain cited
provenance, not proof of Belief influence.

NPC issuance occurs inside the real validated candidate-selection boundary.
The original clock capture is bound to the active issuer/Timeline/permit in a
transient stamp before the proposal is built. Player issuance is a separate
trusted service entry, checks the controlled roleplay actor, and records explicit
absence according to that entry contract without an extra model call. Open
Attempt parameters do not classify source kind or establish a player's prediction.
The source's `issued_tick` denotes the original entry boundary (the selection
tick for NPCs), not delayed signing, retry or restore time.

The source is signed and committed in the existing fenced MemoryStore before
final Attempt construction. Pipeline-owned metadata then stores only its version,
stable ID and canonical body digest; this immutable reference is covered by the
existing Attempt fingerprint. The same fence remains held until the Attempt is
fully frozen. Legacy reference-free Attempts retain byte-equivalent snapshots,
UUID generation and the original fingerprint algorithm. A reference cannot be
transplanted to another proposal or replaced after freezing.

One shared semantic rule reconstructs the original proposal projection from the
canonical Attempt, checks its digest and source refs, and compares every B3
expectation claim against the signed source-specific payload. It validates owner,
Timeline, proposal, original content/absence, candidate and decision tick. `origin`
is a claim, never a switch that can erase prediction data. Re-signing expectation,
association and snapshot, or even changing the source payload, cannot override
an unchanged Attempt reference. Signed decoding applies these cross-record
checks before EventHistory is available; full isolated verification additionally
checks history and exact checkpoint ancestry.

A source signature is historical evidence, not Runtime write authority. Permits,
cancellation state and current-entry receipts are never serialized. Publication
failure or uncertainty enters existing recovery-required isolation before any
Attempt/Resolution can proceed; a pre-write validation rejection publishes
nothing. Repeated valid issuance reuses original bytes/ticks. Restored pending
sources cannot create current authorization or restart an old action.

Source-bound snapshots use cognition schema/signing purpose v5 with explicit
exact-type codec registrations. v2/v3 readers and original signing purposes
remain. v4 syntax remains decodable for inspection, but B3 records lacking
independent source evidence reject as `ambiguous_action_expectation_source`;
they are not backfilled or automatically upgraded. Old envelopes cannot contain
the new source type. The outer SnapshotBundle remains v2. Parent sources retain
original signatures/ticks and require exact fork-checkpoint membership; sibling
and post-fork-only sources are denied. Recovery verifies, never re-signs.

Implementation: [source contract and shared rule](../src/cognitive_world/cognition/action_expectation_source.py),
[coordinated attack and provenance tests](../tests/test_action_expectation_source.py).

**Freeze and identity.** In a signed Runtime with canonical owner contexts, B3
is bound automatically, with no feature-disable switch. The actual validated
AgentDecision selection captures the trusted clock and originating permit in a
transient receipt. The final immutable Attempt is created by the existing
pipeline; before its first Resolution, the issuer checks the original selection
and proposal binding, fixes a separate freeze tick, signs and commits the
expectation under the existing fence. Its ID binds version, Timeline, owner and
Attempt ID. Digest changes conflict rather than mint another identity. Repeated
registration returns the original ticks/bytes. A selected proposal cannot be
rebound to a second Attempt, and a started/restored incomplete Attempt is not
automatically re-executed. Attempt ID and fingerprint algorithms are unchanged.

The record retains a bounded canonical preimage of the selected Attempt so
restore can recompute its original fingerprint, including its existing source
references and metadata; it does not create persistent records for unselected
candidates or persist the live candidate/provider/task pipeline. References mean
cited decision provenance, not proof that a particular Belief caused selection.
No Belief revision is inferred. `free_text` is a subjective prediction, never a
physical law. Player actions use `expectation_absent` with no inferred prediction
or extra model call. A source-bound physical action without authenticated
entry provenance is ambiguous/rejected; no origin or selection time is inferred. `typed` is reserved but rejected
without a registered projector; this slice supplies none. Comparison remains
explicitly `uncomparable`, including when prose appears to contradict Resolution.

**Result.** Only a committed Resolution Event with canonical signed history and
processing evidence can establish the separate association. Verification binds
expectation identity/body digest, owner, original Timeline, full Attempt
fingerprint, proposal, Event cause/Attempt fields, Resolution identity, Event
source digest and event time. The deterministic association ID binds the
expectation and fixed formal-result role. Identical duplicates are idempotent;
changed Event bindings conflict. The expectation is never amended with an Event
ID. An unresolved or pre-execution-rejected request has no formal association.
Observation delivery failure does not undo a committed Event or imply L1
consumption. Presentation and UI receive no new authority or cognition objects.

**Failure and capture.** Pre-mutation validation rejection has no action effect.
Signing/Store failure after expectation publication begins, including uncertain
writes, freezes the existing Runtime recovery fence and prevents Resolution.
Event processing and association completion share the existing commit lock.
A committed Event survives association failure; the fence is marked recovery-
required before returning to outer handlers, blocking protected writes and
snapshot capture. No rollback, uncertain-action retry or replacement identity is
invented. A checkpoint may capture a frozen expectation before execution, but
cannot capture a committed B3 Event lacking its required association. Restored
incomplete expectations are deferred and cannot restart Resolution automatically.
An expectation without an association cannot by itself distinguish a never-started
Attempt, an unresolved Resolution or a pre-commit interruption after restoration;
it is not evidence of a confirmed success or failure.

**Persistence and branches.** Canonical in-memory records are not durable until
SaveManager publishes a checkpoint containing them and their authoritative
history. No pending-intent journal or stronger uncheckpointed crash guarantee is
added. Source-bound B3 uses cognition snapshot v5 and its v5 purpose; captures
without B3 content retain v3 encoding/purpose. v2/v3 retain their original
readers/purposes. Unbound legacy v4 B3 data is inspectable but ambiguous and
cannot authorize a resumed lifecycle; no provenance is inferred. SnapshotBundle v2 is
unchanged because its component set and exact-byte binding are unchanged.
Unknown types/versions/policies, malformed envelopes and signature-valid semantic
mismatches fail closed. Restore verifies existing bytes, never re-signs or
reconstructs missing predictions from text. Required Event/association gaps
reject rather than being repaired.

Ancestor records must match exact immutable records in the verified fork
checkpoint, not merely possess a valid ancestor signature. Parent records keep
original Timeline/ticks/signatures; post-fork parent and sibling-only records
are denied. A child cannot execute an inherited incomplete Attempt and attach
its own result to the ancestor expectation. New child actions use new Attempts
and child-scoped expectation identities. Old Runtime capabilities cannot commit.

B1 authorization, B2 identity/time/proofs, and existing BehaviorFeedback are
independent and unchanged. B3 does not prove observation, consumption,
understanding or belief; B4 remains responsible for governed revision. Legacy
unsigned or cognition-less host compositions cannot issue recoverable B3
records; they retain their prior compatibility behavior without a B3 claim.
See [implementation](../src/cognitive_world/cognition/action_expectation.py) and
[contract tests](../tests/test_action_expectation.py).


Version: 1.0

---

# 1. Purpose

## Committed Anchor boundary snapshot (2026-10-22)

The sections below mix implemented contracts, historical phase records and approved future schemas. For the current product path, `PlayerInputRequest` is bound to the host player session and request ID. An explicitly selected interpreter may return a bounded `PlayerInputAssessment`: ACTION, OBSERVE, CLARIFICATION_REQUIRED, UNPARSEABLE, INDEPENDENT_REQUEST or CANCELLED. A model-selected request-local `AuthorizedTargetCandidate.handle` is only a locator into the service's current authorized Observation-derived candidate set. The service validates the handle, offered method, target, current authorization and Runtime session/generation before forming a formal action; model text and an Event ID string are not credentials. An unavailable, timed-out or invalid Provider does not become a successful action or a player fault.

`_PendingClarification` is service-owned and process-local. It binds original request/assessment, answer mode/options, player session, Runtime session/generation, cancellation and deadline; its answer supplements the original intent only after current revalidation. It is not saved. OBSERVE produces a separate request-bound `ReadOnlyObservationResult` from current trusted, authorized Observations, rechecked by Presentation, with no World Event. ACTION proceeds through Safety, Proposal/Attempt, Resolution and EventFactory/EventProcessor. After completed processing, source-bound Observations may support a fact message; closed `ActionResultKind` feedback is a separate non-fact message and cannot substitute for a confirmed WorldUpdate. Clarification, no-result narrative, progress and failure remain distinct display contracts. Thin desktop DTOs omit Event, Observation, Runtime, signatures, internal provenance and cognition objects.

The desktop's `ScenarioRuntimeState` uses an explicit `PersistedValueCodec` type registration supplied by the content layer to both encoding and decoding. `SaveManager.load_verified` and `stage_cold_resume`, signed SnapshotBundle v2, complete EventHistory lineage/ancestor checks and `ColdRuntimePublisher` verify an isolated original-Timeline Runtime before first publication. A new session/generation invalidates old permits; the transient Observation store, pending clarification, provider tasks and UI delivery are not restored from the Bundle. In-process restore/fork and cold original-Timeline resume are different operations. The broader social, physical, retrieval and product contracts below do not become implemented merely through this snapshot.

## Ordinary L1 per-Observation history qualification

`CognitiveRuntime.process()` still returns `CognitionState`. Its transient `metadata.l1_ingestion` contains `version=1` and ordered `items`, one per input position. Each item carries `index`, a trusted-source `observation_id` or null, `source` (`eligible`/`rejected`), `history` (`not_checked`/`eligible`/`ineligible`/`undetermined`), `consumption` (`not_consumed`/`ingested`/`duplicate`) and an allowlisted `code`. Empty input has no items; empty `percept_ids` alone never establishes a qualification result. These fields are internal machine-readable processing results, not player prose, persisted history or a consumption proof.

Runtime, dialogue and stepwise assembly bind the actual EventHistory and its available codec/trust context to one ordinary L1 qualifier. The persistent path verifies the complete signed lineage; the in-memory path checks canonical Event and controlled processing evidence without claiming persistent authenticity. A fork without sufficient ancestry-verification context is undetermined. Exact observable-fact and original issuance-context checks reuse ObservationGenerator without saving or redelivering its comparison values. Neither delivery Timeline equality nor provenance alone establishes history membership; generation changes alone do not disqualify history.

Ineligible and undetermined items create no usable Percept, new/refreshed receipt or WorkingMemory change. If no item qualifies, WorkingMemory is not updated or created; existing receipts/proofs remain untouched. Eligible items retain normal deduplication and ordinary receipt behavior. AgentTurn retains uncertainty for deferred observations; dialogue qualifies every stored item independently; Stepwise requires both current eligibility and actual consumption of its required prior observation, so an old receipt alone cannot advance a plan. Direct compatibility calls without a bound history defer rather than infer authority. Existing action fences, B2 acceptance, signing payloads, snapshot schemas and save contracts are unchanged.

## B2 durable L1 identity and instance-bound proof

B2 adds `L1ConsumptionInstance/v1` and `InstanceL1ConsumptionProof/v2` only for
B1's owner-specific `action_result/door_open_attempt_failed=True`. It does not
change either legacy v1 proof's meaning, ID formula, signing purpose or verifier.
The new reserved Memory type is `system_l1_instance_consumption_proof_v2`; its
fixed signing purpose is `cognitive-world/l1-instance-consumption-proof/v2`.

**History-binding prerequisite.** Before entering L1 acceptance, the issuer and CognitiveRuntime must reference the same canonical EventHistory and the exact codec/trust context bound to the issuer's RuntimeWriteFence. A missing or mismatched binding is rejected with PermissionError before Percept construction, WorkingMemory mutation, receipt publication or proof construction; B2 does not infer or auto-install that context. This preflight runs under the existing permit/commit fence and does not latch recovery-required merely for an unmet prerequisite. It never clears an existing recovery latch. Correct Runtime assembly supplies these bindings; an unbound direct adapter is not an alternative acceptance path. Once the protected L1 invocation begins, result mismatch, actual ambiguity and publication failures retain the existing recovery-required behavior. No proof, signature, snapshot or public return contract changes.

**Actual acceptance.** A scheduled AgentTurn explicitly submits the eligible
result to `L1ConsumptionIssuer.accept_owner_result`, which uses the same
CognitiveRuntime/PerceptionProcessor/WorkingMemory path. Source signatures,
owner, current Observation session/generation, exact fact/digest, event-time
rule and canonical MemoryStore fence binding are checked before L1. Within
RuntimeWriteFence's commit lock, the trusted clock and EventHistory fix the
consumption tick and Timeline; L1 updates WorkingMemory, then publishes the
instance-bearing receipt. Only after that acceptance may the issuer sign and
commit the proof. Generation, storage, retrieval and ordinary context assembly
alone are not acceptance. Legacy direct `CognitiveRuntime.process()` cannot
be promoted to B2: a prior unbound consumption is ambiguous, not backfilled.
A normally completed legacy receipt without a B2 instance, and a partial legacy
write leaving the exact `percept:<Observation ID>` WorkingMemory cursor without
a receipt, both prevent fresh B2 acceptance. Missing receipts do not prove
non-consumption. The deterministic rejection is `AmbiguousL1ConsumptionError`
with code `ambiguous_l1_consumption`; it never assigns the current tick to an
old Percept. A verified existing B2 proof is checked first and still returns its
original instance and tick.

Before publishing an instance-bearing receipt, the protected invocation must
return the expected newly accepted Percept ID, owner, exact Observation content
and metadata, with one matching WorkingMemory cursor. Reusing an existing
Percept is insufficient. Known ambiguity rejected before any new protected
mutation leaves the legacy workspace unchanged and does not itself latch
recovery-required. That transient workspace is excluded from checkpoints; a
checkpoint without a B2 proof does not establish never-consumed status. A
mismatch or publication failure after L1 begins instead latches the existing
recovery boundary described below. Neither case rolls back or automatically
recovers historical consumption. This correction changes no proof identity,
signature, snapshot version or Bundle version.

**Default identity.** Canonical encoding of contract scope `l1-consumption-instance/v1`,
Timeline, owner, Observation ID and fixed occurrence scope `default` determines
the instance ID. Digest and consumption tick are immutable bindings, not ways
to create another instance for the same input ID. Duplicate acceptance returns
the original verified proof/instance/tick without L1 or signing again. A changed
payload conflicts. Concurrent calls recheck under the same fence. B2 has no
independent-instance creation API or caller-selected occurrence identity.
Runtime permits remain transient; they are not fields of the signed instance.

**Source and historical authorization.** `door-open-failed-owner-result/v1`
checks the exact trusted Resolution/confirmed-failure source, original owner,
Attempt ID/fingerprint, locked-door slot-read fingerprint, result fact identity,
door, location and captured event-time conditions. Inner proof verification
independently verifies the source Event chain, source and consumption Timeline
ancestry, original ticks, Observation digest and this versioned rule. Ancestor
proofs must also match exact system records in the existing verified parent
checkpoint Memory lineage; a parent post-fork proof cannot enter a child even
when it has a valid signature and the same tick. It does
not re-adjudicate the present door. Ordinary sensory rules and private owner
access remain unchanged. Explicit delivery retry may reuse an exact recorded
ancestor Event's processing evidence through EventProcessor; local delivery
bookkeeping neither appends an Event nor reapplies WorldState. Restore itself
does not deliver historical Observations or issue replacement proofs.

**Failure and durability.** From the first possible L1 mutation through proof
completion, any failure (including a write that may have happened before an
exception) latches the existing fence's recovery-required state before releasing
the lock. Runtime halts the current tick; protected writes and snapshot capture
are frozen. There is no automatic re-consumption, new tick, uncertain-write
retry, Resolution replay or rollback claim. A committed in-memory proof is not
durable until SaveManager publishes a checkpoint containing its exact bytes.
Encoding/publication failures preserve this distinction; a committed catalog
with a later error follows SaveManager's existing committed-error semantics.
No pending-intent journal or power-loss/exactly-once guarantee is introduced.

**Ambiguous history and branches.** The issuer records source Event IDs present
at its construction as a conservative historical boundary. Without a verified
current-Timeline v2 instance proof, a result from that boundary is rejected as
ambiguous; absence is not evidence of never having consumed it. Later committed
Events remain eligible for actual new acceptance. The trusted fork reconstruction
factory alone clears this boundary for the just-created, independently verified
child Timeline, whose consumption scope did not previously exist. Original-
Timeline cold resume, including resume of an existing child, keeps the boundary
for all loaded sources, including ancestors. Inherited proofs retain their
original Timeline/tick/signature; a real later child consumption has a different
Timeline-scoped instance. Sibling suffixes remain isolated. Recovery cannot
reconstruct an uncheckpointed consumption, and cannot promote an old missing
record merely because an Observation can be re-delivered.

**Persistence and non-goals.** Existing MemoryStore system authority and the
closed cognition codec accept the exact new proof and nested instance types.
Both are system-only, excluded from semantic Memory and ordinary Memory writes.
CognitiveStateSnapshot v3 explicitly validates the new payload; v2 reading and
legacy proof validation remain intact, and v2 envelopes cannot contain the new
payload. SnapshotBundle v2's component set and signed meaning are unchanged.
Unknown types/versions/rules, mismatched records and corrupted signatures reject;
legacy snapshots gain no inferred instances. Restore verifies existing proof
bytes and rebuilds neither actual consumption nor signatures. The B2 result
receipt is withheld from existing decision/revision projections, preserving
legacy failure scoring; no semantic Memory, Belief, Goal or SelfModel revision,
B3 expectation/result journal or B4 learning is added.

Implementation: [instance/proof lifecycle](../src/cognitive_world/cognition/l1_instance.py),
[historical rule](../src/cognitive_world/observation/historical_rules.py),
[adversarial tests](../tests/test_l1_instance.py).

## B1 actor-authorized execution-result Observation

B1 implements authorized result issuance only. CPU-controlled Resolution first
confirms the Attempt; EventProcessor validates and commits the Event, then its
existing ObservationGenerator/ObservationStore delivery path may issue one
`action_result/door_open_attempt_failed=True` Observation to the original owner.
This means that this Attempt failed to open this door, not that every method or
future attempt must fail. No additional Event or artificial WorldUpdate is made.

Eligibility reuses `cognitive-world/confirmed-attempt-failure/v1` and the existing
canonical locked-door/state-slot-read validation. The trusted Resolution must
bind the original Attempt ID/fingerprint, owner, one typed closed locked door,
method, Event ID and tick. B1 accepts only the installed manual door-opening
method recognition, without negation, and exactly the verified conditions
`door_locked` and `attempt_method_does_not_unlock`. Missing evidence, other
failure causes, successful effects and unresolved actions confer no B1 result.
EventProcessor alone adds the reserved result draft after source validation;
the fact's subject is the verified door and its location is the interaction
location. The registered owner must have a canonical Entity and matching
location at the processing tick. Handler-supplied lookalike result drafts are
rejected before commit.

Authorization checks the intact committed Event and its recorded processing
evidence in the supplied canonical EventHistory, plus the event-time owner,
door state and location bindings. Only that owner may receive the result;
co-location or sight does not authorize bystanders. This private result channel
does not require sight and does not grant sensory access to any other facts.
Existing door-state visibility remains separate. Result Observations retain the
existing Event/fact provenance and Runtime session/generation binding. Runtime
write permits still fence commit and delivery. Delivery failure leaves the
committed Event authoritative and pending; retry resumes existing evidence
without repeating Resolution, world effects or the original Event.

The result is available in the existing owner-scoped ObservationStore. B1
explicitly defers this result kind in ordinary AgentTurn input assembly, so
issuance does not automatically consume it, influence the legacy precondition
score, issue a consumption proof, or revise Memory, Belief or Goal. The
independent BehaviorFeedback path remains unchanged. B2 recoverable
actual-consumption proof, B3 durable expectation/result association and B4
governed cognitive revision are **not implemented by B1**. Historical rule and
proof registries, signing purposes, snapshot formats and migration rules are
unchanged; ordinary Event processing evidence is not a B2 consumption proof.
See [system authority boundaries](ARCHITECTURE.md) and the
[current implementation status](REPOSITORY_STATUS.md).

## Behavior feedback v0.3b (signed snapshot component)

This section preserves the legacy v1 contract. The additional consumption-gated reach-failure branch uses [BehaviorFeedbackSnapshot/v2](#consumed-physical-failure-feedback-v2); it does not change v1 record meaning or the outer Bundle v2 contract.

v0.2 locked-door evidence is an `environment_state/door_locked=True` fact issued from a typed `DoorState` by a trusted environment observation Event and checked against event-time conditions. A confirmed failed manual open has a Resolution Event containing only `{success: false, outcome: ...}`; its empty WorldUpdate leaves all state-slot provenance unchanged. The feedback receipt is the committed Event ID, not the model's explanation. Unknown lock state has no such affirmative observation or confirmed-failure shortcut.

v0.3a adds optional `confirmed_attempt_failure` Event metadata (schema `cognitive-world/confirmed-attempt-failure/v1`) containing Attempt ID/fingerprint, owner, action type, target references, method, tick, cited source references, verified condition labels and WorldState slot-read receipts. It is generated only from a Resolution-confirmed Attempt snapshot. EventProcessor checks the locked-door condition and slot read against canonical WorldState before append. Existing Event processing attestations sign the Event payload containing this metadata; older signed Events without the field remain verifiable history but are not eligible for feedback. Event dispatch plus feedback application share RuntimeWriteFence's commit lock. If feedback application raises after append, EventHistory and the fence enter recovery-required. This provides in-process commit/snapshot coordination. Persistence is supplied by the separate signed BehaviorFeedbackSnapshot v1 component and SnapshotBundle v2 described below; v0.3a alone did not provide that persistence.

`BehaviorFailure` records owner, exact action intent/target/method, cited
observed predicate/value conditions, committed failure Event ID, simulation
tick, bounded penalty and consecutive count. `BehaviorFeedback` is owned by
one `SimulationRuntime`, deduplicates Event IDs and provides read-only score
adjustments. Penalty uses `P(t)=P0*2**(-(t-t0)/h)` for `t>=t0`; invalid or
reversed time is rejected. Frustration is a separate bounded, shorter-lived
decision cue, not an EmotionStore value.

Snapshot component `cognitive-world/behavior-feedback-snapshot` v1 serializes
this bounded history. SnapshotBundle v2 signs its exact byte digest together
with the WorldState and cognition components. Capture and isolated restore
resolve each failure Event in the verified EventHistory, verify the signed
Attempt projection, and resolve every recorded condition through trusted
EventProcessor observation evidence named by the Attempt's source references.
Unknown references or conditions fail closed. Restore creates a fresh
BehaviorFeedback object; child timelines do not share the parent's mutable
feedback. Bundle v1 remains readable and yields fresh empty feedback explicitly
marked `legacy_not_captured`, since old saves did not contain this state. This
does not assert that the older timeline had no failures. The component remains
restricted to the currently supported confirmed locked-door failure schema;
it is not a general behavioral outcome journal.

This document defines the core data structures and communication contracts inside CognitiveWorld.

The purpose is to ensure:

- stable communication between modules;
- clear responsibility boundaries;
- extensible architecture;
- predictable system behavior.

Data structures describe information. They do not directly perform actions.

---

# 2. Core Data Flow

The main interaction pipeline:

```text
Player Input
  ↓
Semantic Understanding
  ↓
Intent
  ↓
Attempt
  ↓
Resolution
  ↓
Event
  ↓
World State
  ↓
Memory
```

Each stage has its own data contract.

---

## Task context, information gaps and exploration (approved requirements; unified API not implemented)

This section defines the semantic requirements for the task-driven flow in ARCHITECTURE.md. It does **not** register new runtime classes, signed record versions, Store entries or stable client APIs. Reuse existing `DecisionContext`, `CognitionContext`, `MemoryQuery`, `AuthorizedQuerySession`, player request/clarification and candidate contracts before proposing new fields. CPU need analysis and context assembly must operate without an LLM; later model-proposed information needs are optional untrusted requests under `POST-MVP-01`.

### Task identity and authorized source plan

| Required meaning for a future task/context | Existing binding or gap | Boundary |
|---|---|---|
| Task/request identity, purpose, caller, recipient and owner/Character where applicable | Player requests and AgentTurn have scoped identities; there is no general production-task envelope | The trusted host binds the principal and purpose. A model-supplied owner, role or system-task label grants nothing. |
| Runtime session, restore generation, Timeline, trusted tick and relevant source/state version | Existing permits, trusted Observation/Event lineage, Attempt fingerprints and slot reads supply specific bindings | These locate/validate the original scope; they are not replacement permits. Recheck freshness at use/commit and reject abandoned-generation results. |
| Needed information types, required/optional conditions, target scope and source allowlist | Player missing slots, causal `missing_evidence` and bounded Memory queries are partial seams | A missing installed rule is an unresolved model gap; do not infer a negative fact or silently downgrade a required condition to optional. No general need vocabulary or planner exists. |
| Queries, authorized candidate set, selected context items and evidence sufficiency | Current retrievers bound candidate IDs/results and re-read canonical Memory; no uniform per-task sufficiency contract exists | Keep searchable authorization, index scope, candidate set and final context budget separate. Content is filtered before Provider disclosure and revalidated after lookup. |
| Count/compute/Token/latency limits, deadline, attempts and terminal/gap disposition | Local query/call/branch/time bounds exist; no shared budget ledger exists | Exhaustion stops optional work without proving impossibility. Future budget records are diagnostics/policy inputs, not facts or permissions. |

NPC-task sources are current owner-authorized Observation/Percept evidence, explicitly linked canonical Memory and allowed cognition snapshots. Subjective Belief/Goal/Emotion is not objective evidence. A CPU causal task may use its existing Attempt-bound canonical state capability; a system comparison may use its separately verified minimal projection. Neither permits dumping global state, another owner's cognition or complete EventHistory into the NPC/model context. EventHistory/source-event IDs locate evidence and require verification; they do not independently establish permission, L1 consumption, causality or completeness. Narrative/generated text is not a source of authoritative world facts.

Every included evidence item must retain enough internal binding to recheck its source record/revision, owner/audience, Observation/Event pair when applicable, Timeline/temporal applicability, verification status and relevant state receipt. Do not manufacture these fields for sources that lack them; mark that condition unknown or omit the candidate. Provider projections contain only necessary authorized text/typed values and opaque request-local handles, never signing material, permits, Stores or internal traces. Client projections remain smaller still and pass the existing Presentation boundary.

### Context meanings and missing-information dispositions

The future context must distinguish (a) committed/verified objective evidence in its allowed scope, (b) the recipient's subjective belief or experience, (c) installed versioned causal/model capability, (d) unresolved assumptions and evidence gaps, and (e) hypothetical future/candidate content. Conflict between records is retained with sources and time; similarity or relevance cannot resolve truth. Candidate futures are not current observations. A snapshot of a present value alone does not prove an arbitrary past interval or that no intervening change occurred.

The proposed gap lifecycle separates **retrieval needed**, **clarification needed**, **capability/model gap**, **conflicting or stale evidence**, **budget/deadline deferred**, **unresolved terminal**, and **verified constraint rejection**. These are semantic design dispositions, not new enum members in `PlayerActionOutcome`, `AssessmentStatus`, `ResolutionResult` or client DTOs. A later implementation must define an explicit compatible mapping before exposing them. A rejected data request means “not supplied in this scope”, not “the datum does not exist”; ending this exploration means “not explored now”, not “physically impossible”. If all necessary conditions are available, re-enter ordinary candidate evaluation and Resolution rather than marking the task's prose as a result.

Current `BoundedMetacognitionPolicy` issues at most two retrievals/two review rounds, with at most five results per query, and skips duplicate normalized queries. AgentTurn stops further review when a query returns matches; it does not verify task-wide information sufficiency, entailment or a total Token envelope. Optional semantics scans at most its bounded authorized subset and fills unused lexical slots; verified Event anchors add only current-source-associated candidates. Unavailable channels preserve direct results and uncertainty. These count bounds do not establish a combined all-channel Store-read, model-call or latency guarantee.

### Dynamics, candidate futures and budget records

`Goal`, `MotivationAssessment` and `DecisionModulation` retain their existing owner-scoped meanings. There is no canonical “potential energy” field or universal goal-distance score. `ConflictOpportunityCandidate` carries typed issue/evidence links, bounded importance/relevance, uncertainties and process-local first/last-seen, sightings/revision and active/dormant state. Owner-local tension and affordance opportunities remain interpretations. `supported_conflict` describes matching structured exclusive-use Goal demands over a grounded object/scope, not an enacted fight, capacity violation or the NPC's awareness of another Goal. Cooperation discovery, general resource/time pressure and Event-to-Goal reactivation remain unimplemented contracts.

`EventTreeSnapshot`/`EventTreeBranch` retain candidate/parent/source/evaluation and pruning/expansion diagnostics. Current evaluated alternatives remain distinct from Provider-added unassessed branches. Existing expansion records can say unexplored, expanded, pruned or blocked; a budget-pruning/provider-error reason cannot be interpreted as causal infeasibility. Runtime bounds materialized branches and records the proposal/tick/finding relationship; it does not simulate branch WorldState. Optional proposals cannot expand the allowed owner/Goal/target/evidence scope. A future tree task may propose alternative mechanisms or emergent content only as separately validated hypotheses; no new entity/relationship is installed through a branch record.

A future compute allocator may retain task value cues, estimated/actual cost, remaining per-axis budgets, duplicate/diversity considerations, expiry and expand/reuse/defer/degrade/stop reasons. These are tunable policy metadata with no predetermined formula, truth probability or plot authority. Reuse must bind the unchanged scope and relevant source versions; generic cached trust, cross-turn branch reuse and a shared Token/call ledger are not implemented. Cognition, perception and physics LOD requests remain independent; budget pressure cannot make a hidden fact visible or waive a physical/causal constraint.

No new task/context/gap or exploration record is added to signed persistence by this design. Bundle v2 continues to bind its declared canonical components, complete Timeline/Event ancestry and original verification purposes. Transient tasks, pending clarification and diagnostic scheduler/tree records are not silently restored. New or late work must use original-context checks and the existing write fence; cold resume publishes only verified isolated state with a fresh session. This section changes no signature, codec allowlist, WorldUpdate, Event confirmation, Memory provenance or client authorization contract.

# 3. Player Message Contract

## Definition

Player Message represents raw input from the player.

Example:

```text
"I slowly approach the guard and ask if I can enter."
```

## Structure

```json
{
  "text": "player input",
  "timestamp": "",
  "context_id": ""
}
```

## Responsibility

Used by Cognitive AI. It cannot directly modify:

- World State;
- Events;
- Memory.

---

# 4. Intent Contract

## Definition

Intent represents what the player wants to achieve. It describes purpose, not execution.

## Structure

```json
{
  "id": "",
  "goal": "",
  "actor": "",
  "target": "",
  "motivation": "",
  "constraints": []
}
```

## Example

```json
{
  "goal": "enter_area",
  "actor": "player",
  "target": "castle",
  "motivation": "exploration"
}
```

## Rules

Intent:

- does not guarantee success;
- does not define method;
- does not change the world.

---

# 5. Attempt Contract

## Definition

Attempt represents how the player tries to achieve an intent. Different attempts under the same intent must remain distinguishable.

## Structure

```json
{
  "id": "",
  "intent_id": "",
  "actor": "",
  "method": "",
  "target": "",
  "conditions": [],
  "expected_effect": ""
}
```

## Examples

Intent: Enter castle.

Persuasion attempt:

```json
{
  "method": "persuasion",
  "target": "guard",
  "expected_effect": "gain_permission"
}
```

Climbing attempt:

```json
{
  "method": "climbing",
  "target": "castle_wall",
  "expected_effect": "enter_area"
}
```

### Runtime compatibility and future target namespace

The compact JSON shape above is a conceptual/legacy contract, not an exact dump of the current Python runtime object. The current immutable `decision.Attempt` stores `agent_id`, `action_proposal_id`, open-text `action_type`, `target_refs`, `parameters`, and `metadata`; `target` is a compatibility view of the first target reference. Current target references are **not yet required** to use an explicit namespace.

The implemented `InteractionReference` is an immutable address with `namespace`, `identifier`, and a legacy-object marker. Parsing `object:{id}` or `agent:{id}` selects the address namespace; historical bare IDs are object addresses, not inferred Agent IDs. The reference has no state or permission. The current Resolution reader accesses only one objective environment entry for an object address; an agent address has no installed causal adjudicator and remains unresolved. The `Attempt` API still accepts open `target_refs`; it does not itself validate grounding, owner visibility, or state. The model interpreter may only narrow the proposal's existing target references; a target in a model-generated ordered step must also come from that supplied reference set. Neither route may mint a new model-generated target. This is a limited application boundary, not a complete natural-language grounding solution. An Agent remains `agent:{id}` through temporary state changes.

Future structured Attempt interpretation should be language-independent and able to represent an actor/subject, predicate or intent, target/object, optional parameters/modifiers, and contextual constraints. “Subject–predicate–object–complement” is an engineering shorthand only; it is not a universal linguistic claim, and the contract need not preserve a particular source-language sentence form. LLM output may propose this structure but cannot ground an ambiguous reference using hidden WorldState, confirm a predicate, or assert an outcome. Unreliable grounding remains uncertain, requires clarification, or stays unresolved. The Attempt remains a request and all effects continue through authorization/safety, Resolution, trusted Event issuance, and EventProcessor.

---

Presentation consumes authorized structured results; generated prose is not a world-data contract and cannot become an input to Resolution/Event authority. This is the data-contract expression of **Output Anti-Enumeration** in `docs/ARCHITECTURE.md`, not a claim that a general LLM narrator is implemented.

# 6. Resolution Contract

## Definition

Resolution determines the consequences of an Attempt. It is not only success or failure; its real output is the world consequence.

## Structure

```json
{
  "attempt_id": "",
  "result_category": "",
  "confidence": 0.0,
  "consequences": []
}
```

## Result Category

Human-readable categories:

```text
critical_success
success
partial_success
failure
critical_failure
```

## Consequences

The consequences are the important output.

Relationship change example:

```json
{
  "type": "relationship_change",
  "target": "guard",
  "change": -10
}
```

Location change example:

```json
{
  "type": "location_change",
  "from": "outside",
  "to": "castle_gate"
}
```

---

# 7. Event Contract

## Definition

Event represents a confirmed change that happened in the world. Events are the only source of reality changes.

## Structure

```json
{
  "id": "",
  "type": "",
  "timestamp": "",
  "participants": [],
  "cause": "",
  "changes": [],
  "metadata": {}
}
```

## Example

```json
{
  "type": "conversation",
  "participants": ["player", "guard"],
  "changes": [
    {
      "type": "relationship",
      "target": "guard",
      "trust": -5
    }
  ]
}
```

### Controlled provenance (Phase 12.0b foundation implemented)

`ResolutionResult.confirmed` is a compatibility/data field, not authority by itself. `ResolutionEngine` issues a confirmation receipt bound to the result snapshot only when an installed `_adjudicate(Attempt)` policy returns `ResolutionDecision`. The base engine returns `None` and therefore remains unresolved. Mutating resolution identity, attempt identity, success, outcome, event IDs, or metadata after issuance invalidates the receipt. `EventFactory.create_from_resolution()` rejects results without an intact receipt and produces a Resolution-sourced Event.

Non-action events use `SystemEventFactory.create()` as an explicit trusted application ingress and receive a system-source receipt. EventScheduler schedules an Event but does not create or authorize it. EventProcessor checks the Event receipt and snapshot before processing. EventHistory remains a record of events, not a source of authorization; membership there cannot make a hand-built Event trusted. No parallel WorldState or EventHistory is used.

The source receipts are in-process misuse guards, not cryptographic credentials. The implementation does not defend against malicious same-process code that can call private APIs or alter module state. SystemEventFactory must only be exposed to trusted application subsystems.

No fixed action enum is introduced. Open-ended Attempt input may describe unknown action methods, but text claims such as `success`, `confirmed`, `outcome`, or `world_changes` are not Resolution authority. With no installed Resolution policy, the engine returns unresolved and no Event is produced.

### Typed action-result feedback (narrow implementation)

`ActionResultKind` is a closed, presentation-oriented classification that can accompany a controlled Resolution result: `state_changed`, `goal_already_satisfied`, `executed_no_observable_change`, `action_failed`, `insufficient_information`, and `unsupported_action`. The installed method-based policy currently issues `state_changed`, `goal_already_satisfied` for its verified already-open condition, and `action_failed` for confirmed infeasibility. Unresolved policy output still creates no Event and is not upgraded to one of these confirmed outcomes. EventFactory copies an issued kind into optional `action_result_kind` Event metadata, so the Event's existing source receipt and any configured persistence attestation bind it; this adds no Event or Bundle format version. Presentation accepts only a recorded, completed, trusted Resolution Event plus its processor evidence. It emits `PlayerActionFeedbackMessage` on a separate typed channel for finite result wording. Successful observable changes remain ordinary Observation-backed fact messages. A successful adjudication with no player-visible fact may produce only the safe statement that no confirmed change is available to show; it does not assert that the whole WorldState was unchanged. Free-form Resolution explanations and model/player text are never used to compose action feedback.

### Attempt-bound physical effect proposal (implemented, narrow domains)

`PhysicalEffectProposal` is an immutable, uncommitted proposal with:

- `attempt_id` and `attempt_fingerprint`;
- `target_ref` and clock-issued `simulation_tick`;
- `source_refs` naming the canonical WorldState reads used by the aggregate;
- bounded `state_slot_reads` carrying `WorldStateSlotRead` metadata for the
  precise slots consumed (slot address, presence, value fingerprint, origin
  classification, and an Event ID only when verified against EventHistory);
- `verified_conditions` and `unknown_conditions`;
- a bounded effect payload containing only immutable supported state snapshots
  and scalar values.

The installed door/passage policies create this proposal from the current
`CausalWorldContext`. `MethodBasedResolutionEngine` requires an exact binding to
the current Attempt, target, tick, and source refs; it rejects raw legacy effect
mappings, mismatched bindings, unknown conditions, and a feasible assessment
with no effect proposal. The effect payload digest and provenance are included
in the issued Resolution metadata and then in the Event metadata. EventProcessor
handlers verify the Event/Attempt/tick/target/effect binding and recheck the
expected typed state, actor location, capability, and any required tool before
returning a WorldUpdate. Proposal creation alone changes neither WorldState nor
EventHistory.

`source_refs` are read-location labels, not source Event IDs. `WorldStateSlot`
addresses a real top-level collection, record identity, and nested field path.
`WorldState.read_state_slot()` returns a detached current value and fingerprint
with one of `event`, `initialization`, `unknown`, or `unverified` origin states.
An Event origin is exposed only if the current value still matches its stored
fingerprint and the Event plus processor-issued evidence remain in the
authoritative EventHistory. Missing or unverifiable source metadata never
becomes a guessed Event ID. Initialization and legacy state are not converted
to synthetic Events. A WorldUpdate stages its target collection and provenance
diff before publishing; provenance updates only changed slots, so same-value
updates retain the prior last-changing Event. This is bounded current-slot
lineage, not full history or causal reconstruction.

### Hybrid physical simulation and three-axis LOD (approved design; not implemented)

This section records design constraints, not a new persisted schema or production
API. The existing `PhysicalEffectProposal`, `WorldStateSlotRead`,
`ResolutionResult`, EventFactory, EventProcessor, and WorldUpdate remain the
only current state-change chain; only door operation and known-passage movement
have installed physical adjudicators.

Future physical inputs should use versioned, unit-bearing typed values rather
than unstructured effect dictionaries: canonical 3D world position/orientation;
an explicit local-frame transform; bounded force/impulse and duration vectors;
and receiver response parameters for shape/structure, mass-like resistance,
friction, elasticity, strength, constraints, and environmental conditions. The
world/scenario package owns those values and model registrations. A subject-local
polar/spherical projection `(r, azimuth, elevation)` is derived from canonical
coordinates for relative queries and scheduling only. Its frame must identify
origin, axes, handedness, units, and version; changing observer changes the
projection, never the canonical position.

Future perception, cognition, and physical LOD decisions are separate typed
decisions with separate inputs, outputs, budgets, and reasons. A shared
coordinator may enforce an aggregate tick/compute budget but may not collapse
them into a distance threshold. Perception LOD controls authorized detail;
cognitive LOD controls reasoning work; physical LOD controls the physical
solver, time step, collision tests, frequency, and tolerance. Distance is one
signal only. Collision proximity, speed, energy, constraints, hazard, model
validity, uncertainty, and consequence severity can request higher precision.
Each physical assessment must state its validity bounds and uncertainty; a
request for upgrade that cannot be funded remains unresolved rather than
silently accepting a low-precision result.

The planned pipeline is: immutable canonical input snapshot and tick →
deterministic domain rules and/or bounded simplified physical estimate →
precision escalation when a hard constraint or consequential threshold is
uncertain → typed Resolution proposal bound to Attempt, state-slot reads,
units/model version and uncertainty → Resolution confirmation → EventFactory →
EventProcessor revalidation and WorldUpdate. A model or LLM may suggest a
candidate or request evidence, but cannot supply a confirmed contact, force
response, collision, injury, or state update. Lower/higher precision disagreement
invalidates the lower-precision result for consequential adjudication; if a
repeat at adequate precision remains divergent or exceeds budget, no Event is
issued. Permission, hard constraints, current-state checks, and Event validity
are independent of LOD.

No physical LOD result, local perceptual projection, or cognitive inference is
canonical WorldState, an Observation, or a persisted fact until its authorized
Event path produces that record. Future deterministic tests must cover frame
round trips and multiple simultaneous observer frames, bounded spatial and
collision queries, conservative upgrade requests, agreement/disagreement and
budget exhaustion, and unchanged WorldState/EventHistory before EventProcessor.
Any committed result must then be checked through EventProcessor and its typed
handler. Continuous integration, general materials, collision, occlusion,
multi-body propagation, and the three-axis scheduler are not implemented.

### Lazy expansion commitment and recovery boundaries (design only)

The [selected hybrid expansion direction](ARCHITECTURE.md#hybrid-lazy-world-expansion-selected-direction-acceptance-boundary-unresolved) distinguishes temporary Candidate, recomputable Derived Artifact, accepted World Commitment and Materialized Structure. Commitment and materialization are independent dimensions, not new serialized types, Stores or a frozen lifecycle. The path admitting initially undetermined structure remains undecided: this text authorizes neither a direct WorldState write nor a new EventProcessor operation. Existing installation and runtime mutation permissions remain limited to their approved scopes.

Topology may use typed graph connections and local spatial models without a universal Euclidean embedding. The physical section's canonical coordinate/frame requirements apply to the geometric domain where their inputs and transforms are defined; a topological connection does not provide a metric, FOV, acoustic path or collision result. Unsupported cross-domain queries remain unresolved.

Accepted structures require suitable stable identity, provenance, constraint basis and Timeline scope before any recoverability claim. Existing verified ancestor/checkpoint rules remain authoritative: inherited commitments cannot be silently regenerated or overwritten; child variation is limited to undetermined content or separately authorized world changes. Seeds do not prove reproducible LLM output. A repeated materialization is not permission to replay a committed effect, and model updates cannot reinterpret accepted history.

These are design constraints, not general graph persistence or new recovery support. SaveManager/RuntimeSnapshot do not automatically capture proposed structures, caches, pending generation or schedules. Any newly persisted record requires separate closed-codec, signing/verification and compatibility approval; no Bundle/schema version changes, journal, migration or re-signing are introduced. Missing historical inputs remain missing, not a reason to reconstruct old facts from current state.

Candidate [perceptual mathematics](ARCHITECTURE.md#visual-and-auditory-lod-mathematics-candidate-models-uncalibrated) and [policy-deviation scores](SOCIAL_CAUSAL_DESIGN.md#reference-policy-deviation-candidate-mathematics-not-a-production-classifier) grant no Observation, cognition-write or world authority. The existing observer-sampling correction remains unchanged: new evidence explicitly records post-update sampling; restore preserves exact signed historical phase/payload, and a legacy BEFORE label alone proves no pre-update sampling. No new historical geometry or consumption-proof coverage is implied.

## Persistent trust, Event attestations, and WorldState checkpoints (implemented local Windows foundation; root initialization required)

`Event` data is not proof that `EventProcessor` accepted it. The optional
`PersistenceTrust` boundary explicitly signs and verifies versioned
`PersistedEventRecord` attestations. An attestation binds the canonical Event
digest, processing evidence digest, handler-produced update digest, committed
simulation tick, resulting changed-slot fingerprints, source kind, and prior
attestation digest. It is emitted only after the existing processor path
successfully applies the update. The record retains the Event and the
processor evidence; it is not a second EventHistory.

`WorldState.export_persisted_snapshot()` exports the canonical supported
collections, environment completeness and initialization state, per-slot
current-value fingerprints and origin (`initialization`, verified `event`, or
`unknown`), and the attested EventHistory chain in a versioned signed envelope.
Unsupported payload types and legacy EventHistory entries without attestations
fail closed. Restore verifies the envelope, each Event attestation and chain,
and each slot's fingerprint/source against EventHistory before constructing a
new isolated `(WorldState, EventHistory, simulation_tick)` result. It does not
mutate an active WorldState. Initialization and unknown origins are not
converted to Events.

`PersistenceTrust` is an injected trust boundary, not a trust root stored in
the snapshot. `WindowsDpapiPersistenceTrust` is the local Windows production
adapter: explicit `initialize()` creates a random 256-bit HMAC key protected
with current-user DPAPI; `open()` only loads an existing root and fails closed
when absent, malformed, replaced by an unusable blob, or unsupported. The
default root path is under `%LOCALAPPDATA%\CognitiveWorld`; the profile's
Windows access boundary applies. Plain configuration stores only protected
key blobs, never raw key material. Key-ring entries have stable key IDs;
signatures are versioned envelopes binding format, `hmac-sha256`, key ID,
purpose, and MAC. `rotate()` retains old verification keys; `revoke()` is
explicit and cannot revoke the active key. Lost/revoked keys make corresponding
records unverifiable; there is no silent key regeneration or fallback.

DPAPI is scoped to the current Windows user profile (or configured machine
scope if a future host explicitly chooses that policy); this implementation
uses current-user scope. It does not protect against malicious code running as
the same user and does not provide portable cross-device trust. HMAC proves
possession of the shared protected key, not a distinct signer identity. The
raw-key `HmacPersistenceTrust` adapter remains available for tests and explicit
host-managed trust only. No root is created automatically at import, Runtime
startup, or verification. The host must explicitly provision and securely
back up/manage the root. This foundation also does not provide an atomic
Runtime freeze while a checkpoint is being captured; callers must quiesce
writes, and full Context Freeze remains unimplemented.

Event record signatures carry the versioned signature envelope inside the
persisted signature bytes. The Event attestation covers canonical Event and
processing-evidence digests, applied update digest, simulation tick, changed
slot fingerprints, source kind, and previous attestation digest. WorldState
checkpoint schema v2 binds its canonical body digest, tick, and explicit
Timeline ID. CognitiveStateSnapshot v2 signs its legacy canonical body with
the v2 purpose; v3 signs the same top-level capture contract plus versioned
Memory records with a separate v3 purpose. Both cover the Agent manifest, six
Store payloads and owners, source statuses, capture scope, tick, Timeline,
session, and Restore Generation.

`SnapshotBundleManifest` v1 binds the exact serialized WorldState and cognition
component digests, shared tick and Timeline, independently checked Agent roster
digest, and Event-chain head. Verification first checks the manifest signature
against the externally opened trust root, then verifies both component
signatures/content and their Event/owner/roster associations. A manifest
prevents mixing individually valid files from different ticks or Timelines; it
does not itself implement Timeline isolation or active Runtime restore. A
signature proves cryptographic provenance under the configured key, not
semantic truth or causal correctness.

Version 2 adds the exact digest of the v1 BehaviorFeedback snapshot component
under its own version-specific signature purpose. Version 1 purpose and bytes
remain supported; v1 manifests cannot silently acquire a feedback component.
Version 2 requires the signed component at staging and rejects missing,
modified, unsupported, or unverifiable feedback data.

This remains a WorldState/EventHistory trust foundation, not a complete
Runtime/cognition restore or complete event-sourcing system. No migration
upgrades unsigned legacy history; such history cannot be exported as trusted.

## SaveManager and save lifecycle (IMPLEMENTED / PARTIAL)

Keep three identities separate: a simulation timeline/branch, a save slot, and
an active runtime session. A save references a timeline and a recoverable
checkpoint; it is not itself a second WorldState or EventHistory. Automatic
saves are system-created and may be pruned only under an explicit automatic
retention policy. Quick saves are independent of that policy. Manual saves are
player-owned and are never silently evicted; create, replace, and delete are
explicit operations. Replacement uses prepare-new-before-release-old semantics:
the old save remains recoverable until the replacement checkpoint and all of
its required references are verified usable.

Continuing from a checkpoint must isolate branch-local WorldState,
EventHistory, canonical cognition, and per-slot last-changing-event metadata.
Shared ancestor history is immutable. Deleting a save, deleting a timeline,
and evicting an automatic save are distinct lifecycle operations. Logical
deletion must not physically reclaim shared data still referenced by another
save or branch.

`runtime.save_manager.SaveManager` stores a versioned signed catalog and
immutable content-addressed blobs for the WorldState checkpoint,
CognitiveStateSnapshot, SnapshotBundleManifest, and applicable fork manifest.
`SaveMetadata` distinguishes Save_ID from Timeline_ID and records tick, source
Runtime session/generation, exact bundle digest, Event chain head, Event IDs,
fork ancestry, resource IDs, schema, and integrity status. Catalog metadata
does not replace verification of the underlying signed components.

Capture is initiated explicitly by the host with canonical CognitionContainer,
MemoryStore, and owner CognitionContexts. It holds the RuntimeWriteFence
snapshot scope and AgentRegistry membership snapshot while capturing the
signed cognition snapshot, WorldState checkpoint, and bundle at one tick and
Timeline. A child history is accepted only when its signed parent checkpoint
is retained or resolved by an explicit host resolver. There is no implicit
safe-point scheduler; the host chooses when to call the API.

Lifecycle rules: automatic saves default to a configurable retention of five
and prune only automatic entries; quick save is one replaceable quick slot;
manual saves have independent IDs and are removed/replaced only by explicit
manual operations. Replacement installs and verifies new immutable resources
before the catalog swap; the old slot stays authoritative if publication does
not occur. The signed catalog replacement is the logical commit point.
Post-commit journal or GC errors are reported as `SaveCommittedError` because
the catalog change has already committed.

The transaction journal records prepare/commit intent; on reopen, the signed
catalog decides whether a transaction committed, incomplete staged files are
discarded, and unreferenced blobs can be reclaimed. Content-addressed blobs
are never edited in place. `DependencyTracker` recomputes references from the
signed catalog; child saves include the referenced ancestor resource closure,
and the signed checkpoint index preserves parent-history lookup after a save
slot is deleted. Staged/active Runtime objects receive a signed lease manifest
listing exact resource IDs plus a distinct OS-locked lease file in the shared
save directory. The existing cross-process catalog lock covers lease
publication and GC. GC reopens the signed catalog, verifies lease manifests,
probes OS locks, then deletes only resources with no catalog or live Runtime
lease references. Process exit releases the OS lock; elapsed time alone never
expires a live lease. Corrupt records, missing active resources and uncertain
lock state stop GC without deleting blobs. A released lease may leave files
until the next reconciliation. This is local cooperating-process protection;
it does not provide cross-host coordination or power-loss durability.

The Scenario content host extends the explicit `PersistedValueCodec` allowlist
with `ScenarioPhase` and `ScenarioRuntimeState`. The same selected codec must
decode the WorldState checkpoint during Bundle creation, Bundle verification,
SaveManager loading, and Runtime staging. Unknown record types and unsupported
checkpoint versions remain errors. This is a host-selected canonical record
contract, not a generic object serializer or permission to change signed
bytes. `ColdStagedRuntime` is a process-local verified staging object, not a
persisted record or client DTO. It retains signed input bytes, trust, codec,
source Timeline and a fresh staged-only fence for final publication checks.

`load_verified` checks Save_ID plus Timeline_ID, catalog signature, resource
digests, bundle signature, component tick/Timeline, cognition owner coverage,
EventHistory provenance, and fork ancestry. `stage_restore` delegates to
`IsolatedRuntimeReconstructionFactory` and returns only a frozen
`StagedRuntime`; parent-to-child activation still goes through
`RestoreCoordinator`. Cold resumption of the original Timeline uses the same
verified save and lineage, but requires `stage_cold_resume` followed by
`ColdRuntimePublisher` first publication. A new session/generation is issued;
it does not reconstruct transient Observations or grant client access to the
signed snapshot. Desktop save and entry status DTOs expose only allowlisted
IDs, display metadata, state and error code. Qt pages never receive a Bundle,
EventHistory, Runtime, trust root or write permit.

The desktop save-entry availability query uses `SaveManager.inspect_verified_saves`
only when a catalog file already exists. This read-only inspection verifies the
signed catalog and each candidate through the existing `load_verified` rules,
without creating directories, lock files, an empty catalog or recovery journal.
No directory means no saves; a partial directory, unreadable catalog, invalid
signature, missing resource or failed Bundle/history verification means
availability is unknown and the restore entry stays disabled. Inspection is a
momentary UI hint, not a restore credential: actual restore repeats the normal
locked verification and publication checks. Concurrent changes can make an
inspection stale; they do not authorize a later restore.

The following remaining recovery mechanisms are not implied by SaveManager:

- **Dependency scope:** the signed catalog tracks the supported snapshot and
  ancestry blobs. Durable dependencies of unrelated host processes and
  unsupported scheduler/provider resources are not tracked.
- **Context Freeze:** RestoreCoordinator freezes the old Runtime and validates
  the staged replacement in process. Complete host task cancellation and
  cross-process stale-task fencing are not implemented.
- **Timeline Generation:** RuntimeWriteFence rejects old in-process permits at
  final writes; this does not provide cross-process task isolation.
- **Cognition Restore:** six canonical Stores are reconstructed. Observation,
  transient WorkingMemory, schedules, and provider work require explicit host
  reassembly or remain unsupported.

A Windows DPAPI integration uses the actual SaveManager directory, reopens
both a parent save and a child save after parent-slot deletion in independent
Python processes, activates the child through RestoreCoordinator, and commits
a new door effect through AgentTurn, Resolution and EventProcessor. It checks
the child credential chain and the changed WorldState slot origin. This is a
narrow synthetic acceptance path; it does not establish arbitrary host
configuration recovery or power-loss durability.

SaveManager does not delete timelines, implement a UI, persist scheduler or
host policy state, or make Runtime restore a single transaction with slot
operations. The catalog uses atomic same-volume replacement and a recovery
journal, but power-loss durability and every filesystem failure mode are not
proven by the deterministic tests. The manager requires an explicitly opened
PersistenceTrust; it never initializes or downgrades the trust root. Existing
RestoreCoordinator remains responsible for in-process activation and stale
generation invalidation. This backend slice is not complete save/restore
product acceptance.

### In-process restore-generation write fence (implemented narrow slice)

`RuntimeWriteFence` distinguishes a generated runtime `session_id` and
`restore_generation` from `Simulation_Tick` and any future `Timeline_ID`.
`SimulationRuntime.step()` captures one opaque permit in its operation context;
Python task context propagation carries it across awaited provider work.
Runtime-created ActionProposal, Event, BeliefUpdateProposal, GoalUpdateProposal,
SelfModelUpdateProposal, and EmotionProposal retain their originating permit.
The fence itself retains the issued permit identity, so callers cannot supply
session/generation fields to mint a valid permit. `freeze_writes()` stops new
steps and atomically advances the generation; `unfreeze_writes()` allows only
new captures and never revives old permits.

For governed Belief, Goal, SelfModel and Emotion candidates, an in-process
origin marker records the permit captured at construction. Detached copies
retain that marker; changing the public permit field or using
`dataclasses.replace` to pair the marker with a different permit is rejected.
The validator's accepted result is backed by a private issuance record binding
the exact candidate object, a detached content snapshot and its original
permit; copying or changing the returned result cannot change that record.
Applier and canonical Store final
write boundaries independently verify that origin while holding the Runtime
fence. A result for another candidate, owner, Store type or altered content
cannot authorize the write. This is an in-process capability check, not a
cryptographic provenance proof against arbitrary code with private module
access. A newly created candidate still requires ordinary source, owner and
old-state validation; no old candidate receives a new generation implicitly.

The final EventProcessor processing/dispatch boundary holds the same
reentrant lock across validation and WorldState/EventHistory/Observation
submission. `CognitiveUpdateApplier` checks the captured permit and delegates
to BeliefStore, GoalStore, or SelfModelStore; those canonical `update`
boundaries repeat the origin check while holding the same fence. Emotion uses
`EmotionUpdateApplier` plus the final `CognitionContainer.apply_emotion_update`
boundary. `AgentTurn` binds its owner context's canonical stores to the
Runtime fence before provider review. Player dialogue captures the processor's
fence before L1 and persuasion provider work, so its later Belief proposal
keeps the original generation.

Goal identity is `(owner_id, goal_id)`; different Agents may use the same
`goal_id`. Goal update application reads its return snapshot with both keys.
Agent-facing `CognitionContext` and `DecisionContext` use owner-scoped Goal
links. The legacy unqualified `GoalStore.get_by_id` and
`CognitionContainer.get_goal` reads reject an ambiguous ID rather than
selecting whichever owner appears first; callers with an owner must use
`get_owned` or pass `owner_id`. The legacy container-wide `goals` mapping also
rejects duplicate IDs because a single-key mapping cannot represent both.

Memory's final path is `MemoryProposal → MemoryDecision → MemoryWriteRequest →
MemoryPersistence.save → MemoryStore._commit_memory`. A MemoryProposal captures
its originating permit; the sealed write request preserves and integrity-checks
that same permit. When MemoryStore is bound by AgentTurn or MemoryPersistence,
both the persistence boundary and store commit boundary validate under the
shared lock. Reissuing a request from an old proposal preserves the old permit
and is rejected. Standalone MemoryPersistence without an explicitly bound or
runtime-bound MemoryStore retains its legacy unfenced mode and is not claimed
as Runtime-isolated.

PersonalityStore has trusted initialization and a public legacy `update`
method, but there is no production Personality evolution caller or governed
proposal contract. Once bound to a Runtime through CognitionContext, that
`update` method rejects; initial setup before binding remains available. This
does not implement Personality evolution.

This remains an in-process fence, not Timeline isolation, Runtime restore,
durable generation storage, or cancellation of provider requests. Direct
mutation of private Store fields, unbound standalone Stores, initialization
`add` APIs used outside a Runtime operation, externally managed delayed
callbacks, and custom providers that discard Python task context are not
covered. When canonical stores are Runtime-bound, their `add` initialization
entry points also require an active commit scope; however these trusted
initialization APIs do not have a proposal-origin contract of their own.
Future async APIs must carry the originating capability to their own final
write boundary; a caller cannot make an old proposal current by merely
reissuing its request.

#### Canonical cognition write-boundary inventory

| Canonical state | Owner and runtime write route | Final fence boundary | Runtime evolution status |
|---|---|---|---|
| WorldState / EventHistory / delivered Observation | `RuntimeContext`; EventProcessor applies submitted Events and their observations | EventProcessor processing/dispatch scope, same permit and lock | Fenced on Runtime Event path; Event is not cognition state |
| Belief / Goal | BeliefStore / GoalStore; validator-approved CognitiveUpdateApplier, including Dialogue persuasion | Store `update` rechecks proposal origin; Dialogue captures before provider work | Fenced when bound to Runtime; content remains under existing validator/applier |
| SelfModel | SelfModelStore; CognitiveUpdateApplier | Store `update` rechecks proposal origin | Fenced when bound to Runtime; only governed tentative evolution path writes |
| Emotion | `CognitionContainer._emotions`; EmotionUpdateApplier | `apply_emotion_update` rechecks proposal origin | Fenced when bound to Runtime; initial add requires active scope after binding |
| Memory | MemoryStore; MemoryPersistence from sealed MemoryWriteRequest | `MemoryPersistence.save` and `MemoryStore._commit_memory` | Fenced when MemoryStore is bound by AgentTurn or persistence; unbound standalone use is legacy and not Runtime-isolated |
| Personality | PersonalityStore; trusted initialization only in current production | Initial add requires scope after binding; legacy update rejects after binding | No production evolution writer or governed proposal exists; no Personality evolution is enabled |
| WorkingMemory | CognitiveRuntime's transient owner-scoped WorkingMemoryStore | Not a canonical persistent cognition Store in this inventory | Temporary turn state, not treated as long-term Memory; complete restore-time invalidation is future work |

Store ownership and the fence do not grant semantic approval. Proposal
validation, source/owner checks, stale-value checks, and Memory authorization
remain separate requirements. This inventory is process-local and does not
claim all persistence/recovery surfaces are covered.

Physical effect provenance carries the aggregate's serialized slot-read
receipts separately from `source_refs`. EventProcessor verifies those receipts
against current WorldState and EventHistory before applying the update. This
proves that the read still names the same current slot value and, when present,
that its prior source Event has a valid processor receipt; it does not prove
that the prior Event's narrative or actor caused the state. Only existing door
transitions and known passage movement have production adjudicators; other
physical effects remain unresolved.

`PhysicalEffectSuggestion` is a separate untrusted semantic candidate. Its
locally stamped binding contains Attempt ID/fingerprint, actor, optional
initiator, submitted target, simulation tick, and the aggregate read-source
labels. `EffectParticipant` records a typed reference with an open-text causal
relation; the same reference may have multiple relations. Each
`SuggestedPhysicalChange` records a possible effect type, one or more possible
affected references, advisory required conditions, unknown conditions, and
effect-local participant relations. These are proposed semantic links, not
confirmed causal relationships.
These records assert neither entity existence nor occurrence of an effect.
The Ollama adapter accepts only an exact `participants`/`changes` JSON shape,
bounded arrays/text, and references from the current physical aggregate's
identity-grounded set. The aggregate checks only the actor, current typed
target, owned tools, and bounded Attempt references against WorldState entity
identity; it does not provide unrelated entity state. An unknown reference is
rejected and even a grounded reference does not prove visibility, capability,
or causal relation. The adapter
receives no complete WorldState or private cognition and uses the Dialogue
loopback transport and shared bounded model settings. Selection is explicit via
`COGNITIVEWORLD_PHYSICAL_EFFECT_PROVIDER=ollama` plus host injection into the
existing `MethodBasedResolutionEngine`; no request occurs at import/startup.

`SupportedPhysicalEffectTranslator` is the shared semantic-to-state conversion
boundary. It accepts open effect labels and participant relations; it does not
define an exhaustive output set. It verifies current Attempt/view binding and
grounded references, then asks an installed typed causal policy whether that
specific state transition can be derived from authoritative state. Its
`PhysicalEffectTranslation` contains either the policy's assessment or concrete
`missing_contracts` diagnostics, never an arbitrary `WorldUpdate`. Resulting
proposals carry accepted model participant relations as
`model_proposed_unverified` provenance through Resolution and Event metadata;
they remain metadata and are not emitted as ObservableFacts. Original actor,
Attempt initiator, possible direct cause, and affected identity remain distinct.
Initiator attribution stays bound to the Attempt/Event even when no physical
rule can verify it. The current
door and passage labels are compatibility examples of installed state semantics,
not a limit on what the LLM may propose. New semantics require actual state,
evidence and a legal transition policy before confirmation. Model-listed
required conditions do not count as verified conditions. Explicitly unknown
conditions, ungrounded participants, multiple effects, unsupported dimensions,
absent target state, timeout or invalid output remain unresolved. The existing
EventFactory/handler checks still govern any resulting world update. Collision
and physiological effects have no supported transition contract or handler.

---

# 8. World State Contract

## Definition

World State represents current reality.

## Structure

```json
{
  "entities": {},
  "locations": {},
  "relationships": {},
  "facts": {},
  "environment": {}
}
```

## Rules

World State:

- can only be modified through Events;
- cannot be directly modified by AI.

---

# 9. Entity Contract

## Definition

The [identity-continuity principle](ARCHITECTURE.md#entity-identity-continuity-and-epistemic-disagreement-approved-architectural-principle) separates authoritative identity from an observer's tracked target and identity judgment. Existing request-local candidate handles and InteractionReference addresses locate targets within their contracted mappings; they are not independent proof of an observer's identity recognition, knowledge or permission. A stable observation reference alone does not confirm true identity. No new tracking field, identity record or schema is introduced. LOD changes and reappearance do not authorize identity recreation or UI-driven merge/split; unsupported identity associations remain unknown. Existing trusted state, Observation provenance and governed cognition remain distinct, and historical records must not be supplemented with invented identity evidence.

Entity represents anything that exists in the world, such as characters, objects, and locations.

## Structure

```json
{
  "id": "",
  "type": "",
  "attributes": {},
  "state": {}
}
```

## Example

```json
{
  "id": "npc_001",
  "type": "character",
  "attributes": {
    "name": ""
  },
  "state": {
    "location": "",
    "mood": ""
  }
}
```

This sample is illustrative legacy documentation, not a guarantee that every listed value is authoritative in the current runtime. In particular, `mood` here must not be read as permission to store or mutate an Agent's authoritative EmotionState on Entity; cognition and Emotion remain in the existing owner-scoped cognition contracts.

### Future Entity state-slot direction (not implemented as a universal schema)

Architecturally, an Entity is its stable identity together with its current runtime state collection; categories/types primarily define eligible initial state slots and capability contracts, not a closed behavior taxonomy. A type remains distinct from temporary runtime state. This is a direction, not a replacement schema for the current `Entity(id, type, attributes, ...)` model. Do not infer that every future slot is currently represented in `Entity.state`, and do not add a parallel entity-state Store. Runtime state remains authoritative in the existing world/cognition authorities according to ownership; this concept does not merge private cognition into WorldState.

This future contract follows **State Anti-Enumeration**: represent a change through a typed, authorized effect with its source and interaction where possible, rather than adding a dedicated field for every transient or compound condition. Explicit fields remain appropriate for stable concepts with defined semantics and authority. This principle does not authorize arbitrary key/value state mutation or replace existing typed contracts.

Temporary or terminal conditions (for example, consciousness, injury, restraint, or death) change appropriate state while preserving base identity. In particular, an Agent never becomes an Object because it cannot currently act. Cognition remains in existing owner-scoped authoritative Stores and governance; this conceptual state-slot model does not move private Memory, Belief, Goal, Emotion, or SelfModel into WorldState.

Future Physical and Cognitive adjudication domains must have disjoint authorized write scopes. Physical effects may change only supported objective world slots through Resolution/Event/EventProcessor. Cognitive or physiological responses may change only their explicitly governed subject state; they do not become physical effects or objective facts by narrative assertion. The two domains are connected through confirmed Events and owner-authorized Observations, not by granting either a second WorldState writer. No general Physics, Physiology, Cognitive, or Combat Engine is defined by this contract update.

---

### Proposed Entity, Component and relation contracts (not a runtime API)

**Proposed evolution; not implemented or a stable JSON/schema/API.** This section supplies semantic requirements for ARCHITECTURE.md's ECS/declarative-composition direction and `POST-MVP-07`. It does not replace current Entity, Relationship, Attempt, WorldUpdate, Memory or Bundle encodings. Existing examples above remain historical/illustrative. Component data is not permission to relocate private cognition into WorldState or create a parallel Store.

| Proposed record meaning | Required identity, bounds and validation |
|---|---|
| Entity identity and display | A stable canonical ID, world/instance scope and separately authorized display name/description. Names and JSON nesting paths are not keys or credentials. Reject collisions and unresolved references; keep inherited identity and source Timeline on branch/restore. |
| Component definition | Registered component kind/schema identity and version, field allowlist, value types/bounds/units, invariants and permitted read/write domains. Registration is a trusted host/code operation, not a JSON instruction. Unknown definitions cannot execute. |
| Component instance | Owning Entity ID, exact understood definition/version, bounded data and relevant state revision/source. Multiplicity and required/optional dependencies are specified by that contract, not inferred from missing keys. Unknown, absent and confirmed values remain distinct. |
| Declarative world definition | Versioned package and local-to-canonical identity mapping, initial entities/components, relation endpoints and initial composition. Validate bounded JSON, duplicate keys/IDs, schema/version support, references, dependency/cardinality rules and P0 before instantiation. No arbitrary object decoding, executable expression or dynamic import. |
| Typed relation | Independently addressable relation identity, registered kind/version, explicit endpoints and roles, applicable scope/state, cardinality/topology constraints and change provenance. Structural parent/part, attachment, transmission, constraint, location/containment, ownership, membership/employment and business links have different semantics. The current pair-keyed Relationship map does not implement a parallel-edge/typed relation graph. |
| Interaction input | Existing actor/Attempt/request and original Runtime binding, currently grounded target/part references, intent/method/parameters, required capabilities/resources, relevant state reads and uncertainty. Model-selected handles must resolve through the current authorized candidate set; an Entity ID alone grants no access. |
| Calculation result | Bounded candidate deltas or explicit insufficiency/unsupported-model status, input/Attempt fingerprint, mechanism identity/version and parameters, simulation tick, exact affected slots/relations, expected prior revisions, evidence/source references and uncertainty. It is neither a confirmed Resolution nor a WorldUpdate capability. |

These are required meanings, **not frozen field spellings, record versions or new Python types**. Choose the smallest reviewed concrete schema in a later implementation. Registered component type, codec type, mechanism applicability and action permission are independent checks: succeeding at one does not establish the others. A new box-like instance can reuse installed components/mechanisms as data, but novel semantics require an explicitly reviewed definition rather than a new field that silently executes.

Four states remain distinct: **JSON initial declaration**, **canonical current runtime state**, **LLM/System candidate state**, and **confirmed Event-backed effects**. Trusted initialization can establish the initial state without inventing historical actions; after initialization closes, content creation and changes must use the existing controlled installation/adjudication/EventProcessor boundaries. A file edit or model-generated JSON cannot patch a running world or signed save. A declaration is not a persistence checkpoint and is not sufficient cold-restore evidence.

A composite's child has its own stable identity, state and eligible interactions; parent membership alone supplies neither observation nor authority. Before a part operation, revalidate child/parent endpoints, the exact applicable relation, current authorization/state and original Runtime session/generation. A detach candidate must name its intended relation changes and affected invariants. It must not implicitly delete other links, transfer ownership, create an entity or move the part. Structural cycles, missing endpoints, duplicate/incompatible components and conflicting deltas must fail the relevant typed check; domain-specific graph cycles are evaluated under their own relation contract. No universal deletion/cascade rule is established here.

System inputs are detached, explicit and scoped; any clock/random/model/I/O result is captured through its separate validated side-effect boundary. Deterministic output is reproducible for the same inputs, selected mechanism versions and explicit random sample where applicable. Mechanism composition must state dependencies/order, affected records and conflict handling. Resolution independently validates applicability/effects; EventProcessor and its supported handler recheck current preconditions and the original permit before applying an authorized update. Source references must resolve to trusted records, not labels asserted by the model. No generic candidate-delta confirmation, multi-record graph transaction or component handler is implemented by this text.

Unknown component schemas/versions are ineligible for loading/execution; unfamiliar combinations or missing mechanism coverage may remain external candidates with explicit gaps. CPU may request bounded registered evidence/completion or alternatives under `POST-MVP-02`; it must not invent semantics, dynamically execute generated code or convert budget exhaustion/no model into a proven impossibility. P0, access denial and verified hard-constraint rejection retain their independent meanings.

Future persistence must explicitly encode/decode every admitted record, bind the concrete schema/registry and mechanism compatibility requirements where needed, preserve source/Timeline and reference integrity, and reject missing dependencies or unsupported versions before publication. Any migration requires separate compatibility/signature review; this proposal neither changes Bundle v2 nor upgrades old bytes. Reconstruct from verified Bundle/EventHistory/ancestry in isolation, then use existing publication boundaries with a new Runtime binding; no new trust root or substitute parent Runtime is introduced. Current pending clarification/provider work remains transient. Only reviewed authorized Observation facts may enter Presentation; raw component/relation graphs, internal IDs, private cognition and signatures remain outside client DTOs.

---

# 10. Relationship Contract

## Definition

Relationship represents connections between entities.

## Structure

```json
{
  "source": "",
  "target": "",
  "attributes": {
    "trust": 0,
    "fear": 0,
    "respect": 0
  }
}
```

Relationships change through Events.

---

# 11. Memory Contract

Memory is divided into two layers.

## 11.1 Short-term Memory

Format: natural language.

Example:

```text
The player appeared nervous when talking with the guard.
The guard noticed this behavior.
```

## 11.2 Long-term Memory

Format: structured data.

Structure:

```json
{
  "id": "",
  "owner": "",
  "type": "",
  "content": {},
  "importance": 0.0,
  "source_event": ""
}
```

Memory type examples:

```text
fact
relationship
experience
causal_link
```

---

# 12. Causal Link Contract

## Definition

Causal Link represents why something affects something else.

## Structure

```json
{
  "cause": "",
  "effect": "",
  "strength": 0.0,
  "confidence": 0.0
}
```

## Example

```json
{
  "cause": "player_helped_npc",
  "effect": "npc_trust_increased"
}
```

---

# 13. Event Tree Contract (candidate exploration slice)

`EventTreeSnapshot` is an immutable, per-Agent-turn diagnostic projection built from the canonical `ActionProposal.metadata["decision_trace"]`. It binds `source_proposal_id`, owner, tree/root IDs and the Runtime simulation tick (when Runtime-built). It carries bounded child `branches`, `branch_budget`, pending count, provider-call use/limit, and `EventTreePruning` entries with candidate ID, parent, source refs and reason; `pruned_candidate_ids` remains a compatibility projection. Each `EventTreeBranch` records stable candidate-derived `node_id`/`parent_id`, candidate and owner IDs, candidate generation source when supplied, intent/target/method/goal, evidence refs, subjective score/evaluation factors only if evaluated, uncertainty, selection, and `expansion_status` (`unexplored`, `expanded`, `pruned`, or `blocked`). These are exploration states, never causal outcome statuses. Legacy traces lacking candidate generation source retain an explicit unknown (`None`), rather than inventing provenance.

Expansion is lazy and stable (descending existing subjective score, then candidate ID). The trusted per-turn limit is at most four materialized branches. Root alternatives beyond that limit are pruned with `global_branch_budget`. A branch provider, when explicitly injected, receives only a bounded owner-scoped `EventTreeBranchProposalContext`, at most two proposed children per call, and no more than two provider calls per explorer (a lower trusted limit may be set). A parent is called at most once. The application validates the entire returned batch before adding any branch, checks owner, goal/target/source membership and remaining budget, and records duplicate candidate IDs or equivalent full provider-candidate semantics as pruning rather than multiplying nodes. Evaluated trace candidates have only a diagnostic subset of their original fields, so cross-source semantic equivalence is not inferred from incomplete data. Provider failure blocks that parent and consumes its call budget. Provider branches remain unassessed and cannot alter the selected ActionProposal. Runtime also verifies trace-linked scheduler finding IDs against current owner/tick findings; those links are attention diagnostics, not new evidence or authorization.

The snapshot is held only in `AgentRuntimeTurnRecord` diagnostics. It contains no WorldState, EventHistory, Cognition Store, ResolutionResult, or WorldUpdate reference. It cannot authorize queries, create Events, mutate state, or feed player Presentation. A direct explorer built from a caller-supplied Proposal inherits that Proposal's provenance; it does not independently verify Observation permission. The current contract supports candidate alternatives and bounded pruning only; isolated branch state, outcome simulation/propagation, value propagation, persistence, and live model proposal/evaluation are not implemented. `EventSeed` is not an Event Tree node and is never automatically converted to an Event.

---

# 14. Proposal Contract

AI outputs always use proposals.

## Structure

```json
{
  "type": "",
  "source": "",
  "content": {},
  "confidence": 0.0
}
```

Examples:

```text
IntentProposal
AttemptProposal
MemoryProposal
EventProposal
```

---

# 15. Data Authority Rules

Authority order:

```text
World Core
  ↓
Event System
  ↓
Memory System
  ↓
AI Proposals
```

AI output has the lowest authority. AI suggestions must always be validated.

---

# Final Principle

Data structures define communication. They do not define reality.

Reality is created only through:

```text
Validated Event
  ↓
World State Update
```

CognitiveWorld remains AI-assisted, but world-controlled.

---

# 16. Implemented Runtime Contracts (Phase 9–11)

## ResolutionResult Confirmation

`resolution.ResolutionResult` is distinct from the older `decision.Resolution` model. It retains `confirmed: bool` as a data field, but this flag is not authority. The ResolutionEngine issues confirmation bound to a result snapshot only when its controlled policy returns a `ResolutionDecision`; EventFactory verifies the receipt. The base ResolutionEngine remains unresolved when no policy is installed. This is an in-process misuse guard, not authentication against malicious code in the same process.

## Agent Decision Input

`AgentTurn` binds `RuntimeAgent.agent_id` to `CognitionContext.owner_id` and checks the Character binding when available. It forms the following owner-scoped decision snapshot:

- **L1 Perception:** Percepts from Observations whose provenance and observer identity passed the existing consumer checks. Source Observation IDs are retained.
- **L2 Working Memory:** the current isolated WorkingMemory snapshot for that owner, including Percept references.
- **L3 Long-term Memory:** retrieval candidates are restricted to Memory IDs referenced by the Character, records whose `owner_id` matches the DecisionContext owner, and records classified as semantically retrievable by the canonical MemoryStore contract. System-only proof payloads use a typed content marker; known proof record discriminators with inconsistent payloads also fail closed. Both `CognitionContext` views and `MemoryRetriever` enforce this boundary, while trusted proof verification and snapshot persistence continue to read the canonical Store. `MemoryRetriever` returns detached immutable `MemorySnapshot` values with the full `source_event` ID preserved. Relevance is not truth or confidence.
- **L4 Beliefs & Self-Model:** owner-matched Beliefs, Goals, Personality, and SelfModel from their authoritative Stores; Belief/Goal source references are retained. Goals continue to represent current motivations.
- **Cross-layer Emotion:** the owner's Emotion record is included without defining an extra cognition layer.
- **L5 Metacognition:** owner-bound, turn-local `MetacognitiveFeedback` carries review cues and scoped `MemoryQuery` requests. `BoundedMetacognitionPolicy` is the replaceable deterministic baseline used by `AgentTurn`; it has no Store and creates no persistent cognition updates.

`DecisionContext` recursively freezes records, mappings, and sequences into immutable value snapshots. It rejects any mixed-owner record, exposes no Store or WorldState reference, and cannot update either. Snapshot fields preserve source IDs but do not promote Beliefs or Memories into objective WorldState facts.

Phase 12.2 retrieval contract:

- `CognitionContext` supplies the Retriever only the current Character's referenced Memory IDs and rechecks returned IDs, current owner, canonical Memory source, and semantic retrievability before creating `MemorySnapshot` values. System-only evidence is excluded by its typed payload classification even when a Character explicitly lists its ID; `MemorySnapshot.from_memory` and `MemoryRetriever` apply the same rule. This is a semantic visibility boundary, not proof-write authority. The Retriever cannot query WorldState or write MemoryStore.
- The intended production caller is `CognitionContext` through `AgentTurn`; the lower-level Retriever accepts the supplied candidate-ID tuple as a strategy input and is not an authentication mechanism against arbitrary code in the same Python process.
- `MemoryQuery` is immutable, owner-bound, and has a positive result limit. Its optional metadata is retained only for compatibility; it cannot grant access or alter ranking.
- `MemoryRetriever` ranks by lexical token overlap of the query and explicit Memory content text, then uses the existing finite `importance` only as a tie-break when every memory in that equal-overlap group provides a valid value, and otherwise orders that group by Memory ID. A missing/invalid optional tie-break does not create a synthetic score. No recency or emotional salience is calculated because the canonical Memory model has no corresponding field.
- Returned `MemorySnapshot` content and metadata are recursively immutable detached values. `source_event` remains a provenance reference; retrieval does not validate subjective content as objective fact.
- The default L5 policy can request a second distinct query only after an empty first result. `AgentTurn` enforces at most two retrievals, two review rounds, and five results per query by default; repeated queries are skipped. Exhaustion and missing cues retain uncertainty. These controls are turn-local and configurable through the policy instance; they do not persist feedback or modify stores.
- L5 does not resolve belief conflict or confirm facts. Persistent changes remain subject to the existing cognition update validation and memory write authorization flows.

## Hybrid Associative Retrieval: Current Narrow Channels and Approved Future Design

The current implementation adds narrow semantic and Event-to-Memory candidate locators; the broader retrieval contract below remains approved future design. Neither adds a schema, persistence format, or authorization grant.

### Optional semantic candidate discovery

`EmbeddingProvider.embed(text)` is a host-injected, framework-neutral strategy. Providers may also expose an optional `embed_many(tuple[str, ...])` batch operation returning one ordered vector per text; absent that operation, the retriever uses the original single-text method. Batch size is capped at 16 and all vectors must share a finite nonzero dimension of at most 4096. The optional `OllamaEmbeddingProvider` implements this same strategy against a host-configured local loopback `/api/embed` endpoint; the default retriever still makes no model call. Tests use configured deterministic vectors, while a separate opt-in test measures a real local model. `HybridMemoryRetriever` remains an optional `CognitionContext` retrieval strategy. It first obtains the unchanged lexical ranking, then builds a disposable `MemorySemanticIndex` for at most 64 distinct Character-linked IDs from the current canonical `MemoryStore`. It checks owner, semantic retrievability and nonempty `source_event` before supplying bounded content text to the provider. The query text is also supplied to that provider. Hosts must explicitly approve the provider's data destination and must not run a slow implementation on a UI main thread.

The query-local index retains Memory ID, source Event reference, text digest and finite normalized embedding; it is not persisted or a fact credential. It returns at most five similarity-ranked candidates after re-reading current canonical records and checking the current Character ID set, owner, semantic retrievability, source reference and indexed text. `CognitionContext` performs its existing final canonical Store recheck. Lexical results keep their order and fill the result budget first; semantic candidates fill only remaining slots, with stable ID ties. AgentTurn's independently verified Event candidates merge afterward. Similarity is a ranking hint and cannot issue a `VerifiedEventAnchor`, authenticate a source Event, or establish truth or causality.

The index is rebuilt per query, so Memory updates/deletions, Character link changes and restored Runtime stores do not inherit old embeddings. A retriever bound to a Runtime fence also drops semantic candidates when its session or restore generation changes. Provider absence, timeout, invalid dimensions/nonfinite vectors and other provider failures leave lexical results intact. The new channel adds at most 64 canonical build reads and five candidate rechecks per query; the pre-existing lexical scan remains scoped to the Character's full authorized ID set and has no new global read cap. At most five final snapshots enter the current result budget. No persistence, shared cache, remote embedding transport, or general async AgentTurn executor is added. The Ollama adapter accepts bounded nonempty text or at most 16 texts per call, checks response count, model, finite coordinates and consistent dimension, and rejects redirects and non-loopback destinations. Query text may include sensitive cognition context, so hosts must authorize its local destination and run slow retrieval away from the UI main thread. Provider output cannot authorize Memory, Event anchors, or facts.

### Current Event-anchored candidate discovery

`MemoryEventIndex` is rebuilt for an `AgentTurn` from the current `CognitionContext`'s Character-linked Memory ID set and the Runtime-bound canonical `EventHistory`. The complete persisted EventHistory lineage is verified before links are built. The derived index stores only Memory IDs and verified Event/time locators; each candidate is re-read from the canonical `MemoryStore` and rechecked for the current owner, Character authorization, semantic retrievability, and unchanged `source_event` before a snapshot is admitted.

A source Event ID in an `Observation` is only a locator. It becomes an ephemeral `VerifiedEventAnchor` only when the Observation has trusted provenance for the current owner, matches the corresponding Event and processing evidence returned by complete EventHistory verification, has a supported reconstructable issuance rule, matches the signed source Timeline, carries the issuing Runtime session and restore-generation binding, and was consumed through the current turn's L1 path. The bound Runtime fence must still have that session and generation when candidates are resolved. Anchors are bound to one verified index generation and Timeline; they cannot be supplied by model output, natural-language IDs, evaluation gold labels, an earlier Runtime generation, or a different Observation/history context. Unsupported, stale, mismatched, or unverifiable anchors yield no association candidates. When the turn consumed an Observation but cannot establish any valid anchor, or candidate resolution detects a stale Runtime/history binding, AgentTurn retains lexical results and records association-channel unavailability in metacognitive feedback. With no consumed Observation, it uses the ordinary lexical path without classifying the channel as failed. Index verification failure likewise leaves lexical retrieval available and records unavailability rather than treating the result as proof that no Memory exists. These process-local receipts are application misuse guards, not a defense against malicious same-process code.

Lexical snapshots remain first in stable merge order; Event-linked candidates are deduplicated after canonical Store revalidation and the existing per-query result cap applies. Retrieval remains read-only: the index and anchors do not write Memory, Belief, Goal, WorldState, or EventHistory, and a source link or association path is not itself evidence that the Memory content is objectively true or causally related to the Event. The current fixed natural-language evaluation set does not supply trusted Observation anchors, so its scores measure lexical retrieval and do not demonstrate an association-channel gain.

This is a per-turn rebuild and bounded-result slice, not a general-purpose retrieval scheduler. The current authorization universe is still the Character-linked ID set and the existing retriever's candidate scan; no independent global compute budget or index persistence is introduced.

- **Canonical records and derived index:** entities, events, causal relations, semantic labels/relations, activation state, and association paths used for recall are derived retrieval structures. Canonical Memory remains in `MemoryStore`; EventHistory and WorldState remain their respective authorities. An index entry is only a locator and must retain a verifiable canonical record/source reference. Index rebuild or refresh cannot synthesize Memory, Event, or world facts.
- **Four independent scopes:** authorization scope is determined by the current trusted owner/Character context; searchable-index scope is the authorized subset that the index may inspect; a query's candidate set is the subset actually returned by its selected channels; context budget is the subset admitted to this turn's immutable `DecisionContext`. Exclusion at a later scope does not imply absence or permanent ineligibility at an earlier scope. Index membership never grants authorization.
- **Channel result:** a future channel result should identify the canonical record, channel, source Event/record references, time information, authorization basis, evidence state, and (for associative recall) typed path and edge kinds. Candidate merge/deduplication must preserve multiple independent paths and conflicting evidence rather than collapsing them into an unsupported certainty. Semantic similarity, activation, and importance are ranking signals only.
- **Node and relation kinds:** an entity node identifies a canonical or otherwise validated person/place/object/organization/concept; an event node retains source, participants, time, and linked canonical Memory references; causal relations are directed and require source/evidence and temporal validation; semantic labels/relations can connect aliases, paraphrases, and related concepts but are discovery hints, not evidence that linked statements are true or causally related.
- **Query-time activation:** node activation is transient state for one bounded query, not a Memory attribute or persistent cognition update. Keep it distinct from edge propagation weight, context relevance, temporal validity, and evidence reliability. Any future activation payload must be scoped to its query and owner and discarded after retrieval; it cannot be persisted as a Belief or fact without the existing governed update path.
- **Propagation bounds:** a future implementation must cap rounds/hops, fan-out/candidates, repeated-path influence, cycle revisits, and aggregate compute. Causal traversal follows direction and verified event-time/source constraints. Semantic traversal may add candidates only. Activation decay does not mean forgetting, a low activation is not permanent exclusion, a path does not prove causality, and an empty result does not prove nonexistence. Formulas and weights remain subject to evaluation.
- **Evidence and uncertainty:** retrieval output retains provenance, association path, time, authorization scope, evidence status, and detected conflicts. Metacognitive follow-up is limited by explicit retrieval-round, result-count, and compute budgets. If evidence is conflicting, missing, or over budget, preserve uncertainty; never infer truth from relevance or silently complete a missing fact.
- **Authority boundary:** retrieval has no WorldState, EventProcessor, MemoryStore write, Belief/Goal apply, or Event-creation authority. Each candidate is re-read and validated through the canonical Store and active access contract before inclusion. Any actual world effect remains subject to Resolution, EventFactory, EventProcessor, and `WorldState.apply_event()`.
- **LOD relationship:** a future aggregate scheduler may allocate a total compute envelope, but cognitive retrieval effort, perceptual detail, and physical simulation precision keep independent requests, budgets, and outputs. Distance alone cannot determine retrieval effort or authorize access.

`AgentDecision` accepts the immutable owner-scoped `DecisionContext` from AgentTurn and emits the existing `ActionProposal`. Direct `CognitionState` and Mapping inputs remain compatibility APIs and retain their legacy placeholder behavior. For compatibility, `AgentActionLoop` routes an uncustomized exact `AgentDecision` instance through that legacy `CognitionState` API; injected policies and subclasses use the DecisionContext proposal path. Owner identity is checked both before decision and on the returned proposal. A Proposal is not an Event; Resolution must confirm an outcome before EventFactory can create an Event, and EventProcessor remains the normal runtime WorldState update path.

## Cognition Update Authorization

BeliefUpdateProposal and GoalUpdateProposal describe candidate changes. CognitiveUpdateValidator returns a sealed ValidationResult only when source references and Agent ownership pass. CognitiveUpdateApplier requires that matching accepted result and verifies the stored prior value before updating the respective authoritative Store. Proposal creation alone does not change stored cognition.

## Cognitive LOD (Approved Design, Not Implemented)

Cognitive LOD is a compute-scheduling policy, not another cognition Store or data authority. Every precision mode reads and updates the existing canonical cognition state under existing Store governance. It may vary reasoning granularity, cadence, and resource allocation based on NPC importance, player demand, event relevance, and available cognition budget. It may not discard confirmed important Events, create unrecorded experience during precision upgrades, alter WorldState, or grant Event-confirmation authority. It is distinct from Causal LOD and does not alter L1–L5; Emotion and Motivation remain cross-layer modulators.

## Memory Write Authorization

The candidate contract is `MemoryProposal`. `MemoryCandidate` is only a compatibility alias. The authorized write sequence is:

```text
MemoryProposal
  ↓
MemoryDecisionAuthority → accepted MemoryDecision
  ↓
MemoryWriteFactory → snapshot-protected MemoryWriteRequest
  ↓
MemoryPersistence → MemoryStore
```

The decision snapshot must remain intact and reference the supplied proposal. The write request retains snapshots of the proposal, decision fields, source references, and Memory fields. Persistence rechecks the request and requires the source Event to exist in EventHistory before committing. The authority issues the caller's decision; it does not decide acceptance itself.

`EventMemoryProposalFactory`, `MemoryFormer`, and `ObservationMemoryFormer` are distinct formation adapters that produce the same MemoryProposal type. EventHistory validation is performed by MemoryFormer/ShortTermMemoryFormation at formation where injected, and by MemoryPersistence before a long-term write. Proposal formation is not Memory persistence.

## 17. Phase 12.0 Presentation Contracts (Prototype; Trusted Narrow Path in 12.0d)

The original metadata-based `VisibilityFilter` path is closed: `Event.metadata["presentation_facts"]`, caller-supplied audience/scope, and direct `PerspectiveContext` construction do not authorize output. The existing Presentation package is reused with these contracts:

- `PlayerSessionBinding(session_id, player_id, mode, controlled_agent_id, observer_agent_id)` is an optional host-populated RuntimeContext binding. No binding is synthesized; absent or invalid identity denies.
- `PerspectiveResolver` reads only that binding and `AgentRegistry`. Roleplay requires the registered RuntimeAgent and its Character ID. Observer mode uses a separately bound registered view Agent. Director mode is denied until a director policy exists.
- `PerspectiveContext` has a closed field set and can only be trusted after resolver issuance. `VisibleInput` contains typed fact fields and source Event/Fact/Observation IDs; it has no arbitrary text or metadata bag.
- `VisibilityFilter` requires trusted EventProcessor evidence and an existing unmodified Observation for the resolved Agent in the existing ObservationStore. It verifies that the ObservableFact is bound to that Event and re-evaluates the shared `VisibilityPolicy`. It never reads Event.metadata or any Cognition/Memory Store.
- `MinimalComposer` renders only explicitly supported authorized typed facts: room-light-on, door open/closed/locked, passage presence, and separately authorized spoken output. The door and passage wording uses generic nouns until validated world-package display names have their own contract. An unknown predicate or value fails closed; no subject/location identifier, raw predicate, internal state key or unchecked package string is a fallback display name. It does not accept Events, Observations, free text, Cognition, or diagnostic objects as fact inputs.
- `PlayerVisibleMessage` is closed and includes recipient/session/view and source Event/Fact references. `PresentationValidator` rechecks each authorized input and exact output text, then issues `ValidatedMessageBatch`. A manually constructed message or batch has no validator receipt.
- `ChatOutputGateway` accepts only an intact validated batch and re-resolves the active RuntimeContext session before delivery. `InMemoryChatOutputGateway` is the current callable adapter. No PySide6/UI sender has been migrated.

The production chain is `SystemEventFactory → RoomLightChangedHandler → EventProcessor/EventHistory evidence → existing Observation authorization → PerspectiveResolver → VisibilityFilter → MinimalComposer → PresentationValidator → ChatOutputGateway`. The same Agent Observation authorization result is reused; Presentation does not access private cognition. Unknown sessions, identities, evidence, or Observations default to no output. The original positive fact was room-light-on; later trusted door and passage policies extend the supported fact set. Private Python receipts protect ordinary application paths, not malicious code in the same process; the host must populate PlayerSessionBinding from its trusted session setup, as no network authentication service exists.

## 18. Phase 12.0c Shared Observable Facts and Agent Perception (Partial; 12.0c-4 Narrow Slice Implemented)

The trusted Resolution and Event provenance foundation from Phase 12.0b is implemented as described in the Event contract above. Phase 12.0c-4 implements one narrow Agent Perception vertical slice; general observable-fact evaluation is not implemented. Existing Event provenance does not establish that each Event field is observable.

### Shared observable-fact decision

Agent Observation and player Presentation share an observable-fact evaluation boundary, but use separate resolved identities, permissions, and output contracts. Inputs are trusted event facts, only the necessary WorldState for the event time, resolved observer identity, location/environment conditions, and applicable sensory/visibility rules. Missing required inputs default to no observation. Event metadata and caller-provided scope/audience fields do not grant visibility. Full Event metadata is not Observation or Presentation input.

Phase 12.0c-3 adds `ObservableFactDraft`, `ObservableFact`, `EventTimeObservationContext`, and `EventProcessingEvidence`. Fact records use an immutable limited value shape (`fact_type`, `predicate`, optional `subject_ref` and `location_id`, and finite scalar or scalar-tuple value); `fact_type` and `predicate` remain open strings and are not action enums. EventHandler's default fact hook returns no drafts. EventProcessor validates the trusted Event before and after the handler, validates each draft before applying the WorldUpdate, and only issues immutable fact receipts after a successful WorldState update. Receipts bind the Event source snapshot and fact payload. EventHistory may retain the resulting evidence beside the Event but remains storage-only; consumers must verify receipts. Phase 12.0c-4 adds the real `RoomLightChangedHandler`, which verifies a controlled system Event against the current typed room light state and explicitly drafts a `room_light_on` fact for the changed room.

`EventTimeObservationContext` records the trusted SimulationClock integer, source Event ID, and distinct capture phase. The Phase 12.0c-4 room-light slice samples the changed room environment after the WorldUpdate. Phase 12.5B captures registered Agent positions and typed sensory capabilities at the same synchronous post-update EventProcessor boundary. Newly issued processing evidence explicitly labels `observer_state_phase` as `AFTER_WORLD_UPDATE`; this describes observer sampling, separately from the fact-state phase. Historical restoration preserves the signed phase value and exact payload bytes without relabeling or re-signing. A legacy `BEFORE_WORLD_UPDATE` label alone is not proof of pre-update sampling: earlier issuance used that default despite post-update capture. This correction changes no record schema or signing purpose and supplies no new historical-geometry guarantee. `event_timestamp` remains descriptive Event data, not clock input. Observer positions come only from `WorldState.locations` keyed by identities in the Runtime's `AgentRegistry`; sensory capability comes only from the corresponding typed `Entity.sensory_capabilities`. Missing values remain unknown. Environment capture is limited to the fact location's supported typed conditions. These necessary snapshots are immutable and attached to processor-issued evidence; later WorldState changes do not update them. The narrow `VisibilityPolicy` requires a trusted processed Event, a supported typed ObservableFact, registered observer identity, exact known location, known `sight` capability, and known SimulationClock time. Any missing condition denies issuance. It does not authorize hearing, occlusion, geometry, or other unsupported fact types. `ObservationGenerator.generate_authorized()` issues only typed ObservableFact content after that policy succeeds; Event metadata, participants, private cognition, and caller-provided scopes are not inputs. CognitiveEvolutionEngine rejects untrusted Events; it returns `UNOBSERVED` with no proposals if the Agent has no matching Observation and `UNAUTHORIZED_OBSERVATION` with no proposals if a matching record lacks valid provenance. A match on observer and Event IDs is insufficient. Observation provenance binds the Observation ID, observer ID, source Event ID, content, metadata, and authorization-context fingerprint; changing bound payload invalidates the receipt. CognitiveRuntime and PerceptionProcessor independently require valid provenance and matching observer identity before creating Percepts. ObservationStore only isolates and retrieves records; adding or retrieving a manual Observation does not authorize it. The process-local receipts are application misuse guards, not a defense against malicious same-process code. No code may infer perception from EventHistory membership, participants alone, current/default location, or caller-provided metadata.

For this first slice, `room_light_changed` is a controlled system Event with exactly one change object containing `room_id`, `from_light_on`, and `to_light_on` boolean fields. The production handler requires the current `WorldState.environment[room_id].light_on` to equal the declared prior value, then applies the new value through EventProcessor. A registered Agent must also have a known `WorldState.locations[agent_id]` and a corresponding `Entity` whose `sensory_capabilities` contains `sight`. These are explicit inputs to this narrow rule, not general schemas for all world events or actions.

For `EventTimeObservationContext.environment_conditions`, `None` means no relevant environment value was captured; a non-empty tuple contains only trusted captured conditions and does not imply that absent keys are false. An empty tuple means a trustworthy complete snapshot was available and contained no relevant captured conditions. The separate `environment_snapshot_complete` flag in the immutable event-time context records whether the source WorldState declared its environment collection complete. `WorldState.load_environment_data()` adds a partial entry and does not claim that absent entries are known empty. Initialization/restoration code may call `WorldState.load_environment_snapshot(mapping)` to declare the entire environment collection known, including an explicitly empty mapping. EventProcessor captures supported typed values such as a room light or `DoorState`; if none are available, it records `()` only when WorldState marks the environment snapshot complete, and otherwise records `None`. A legacy WorldState-compatible adapter without `environment_snapshot_complete` is treated as incomplete; the missing marker never implies a known-empty environment. `apply_event()` remains required for actual processing, while missing optional observer/environment snapshot accessors are handled as unknown and therefore fail closed. VisibilityPolicy must continue to deny when a required condition is `None`.

## 18.1 Phase 12.0c-R Event Reliability and Observation Idempotency

`EventHistory` retains in-process processing markers keyed by stable Event ID: `PREPARING`, `APPLYING_WORLD_UPDATE`, `RECOVERY_REQUIRED`, `RECORDED`, `OBSERVATIONS_PENDING`, and `COMPLETE`. `EventProcessor` reserves the ID before handler work. A pre-application handler/validation failure releases only the `PREPARING` reservation and may be retried. Once `WorldState.apply_event()` is entered, any failure before Event plus processing evidence are recorded is marked `RECOVERY_REQUIRED`; replay is rejected because the system has no safe rollback or durable recovery record. A matching Event already recorded reuses its trusted evidence and does not re-run its handler or WorldState update. An Event ID paired with different content is rejected.

The intended in-process order is: reserve ID → prepare handler result/drafts → mark update boundary → apply WorldState update → issue bound evidence → append Event/evidence to EventHistory → mark Observation delivery pending → generate and save authorized Observations → mark complete. EventHistory recording and WorldState mutation are not an atomic transaction. If the History append fails, the Event remains recovery-required and must not be replayed; the current implementation reports the failure but cannot automatically reconstruct missing evidence or roll back state. If Observation generation/save fails after History recording, retrying dispatch reuses stored evidence and retries only Observation delivery. Stable Observation IDs make duplicate saves overwrite the same record in ObservationStore.

These markers are process-local. They do not survive process loss, provide crash recovery, or coordinate multiple EventProcessor instances. Deployments that persist WorldState and History separately still need a durable reconciliation policy before claiming crash-safe exactly-once processing.

`CognitiveRuntime` de-duplicates WorkingMemory percept references by `percept:{observation_id}`. Repeated consumption of that Observation does not append another percept reference. Different Observation IDs, including same-content facts from distinct Events or separate Agents, remain distinct. CognitiveEvolutionEngine still returns proposals without applying them; Belief/Goal mutations continue through CognitiveUpdateValidator and CognitiveUpdateApplier and their stale-state checks. Memory writes continue through the existing decision and persistence boundary. This is not a general exactly-once guarantee for arbitrary external consumers.

### Owner-scoped SelfModel evolution (narrow, opt-in)

`AgentTurn` may be explicitly configured with a `self_model_review_provider`; `SimulationRuntime.self_model_review_provider` is the normal host assembly point and is passed to the existing `AgentActionLoop`/`AgentTurn` per turn without modifying shared decision objects. Its existing `CognitiveRuntime.process()` output supplies only newly ingested L1 Percept IDs; `CognitiveEvolutionEngine.propose_self_model_update()` rebinds those IDs to intact trusted Observations and checks the runtime-local L1 consumption receipts before building `SelfModelReviewInput`. The input is limited to that owner's Observation payloads and existing `self_beliefs`; Event IDs are provenance labels and do not expose EventHistory content. A provider can return at most one bounded `SelfModelEvolutionSuggestion`, citing only supplied Observation IDs. The engine forms a `SelfModelUpdateProposal`; it does not write a Store.

`CognitiveUpdateValidator` checks the proposal owner, authorized Observation references, exact Observation-to-source-Event bindings, and validator-issued integrity snapshot. `CognitiveUpdateApplier` compares the canonical SelfModel snapshot, enforces an entry bound, and appends one `tentative` self-belief with its Observation and Event references. `SelfModelStore.add()` is initialization-only for each owner; replacement requires the validated update path. Repeated L1 consumption is not reviewed again in the same runtime, and the Store also rejects reuse of an already-applied Observation reference. The subsequent DecisionContext rereads the canonical SelfModel. This is an in-process guard, not durable exactly-once processing.

The candidate is explicitly tentative; its source provenance does not prove its semantic interpretation. Provider output does not carry an authority-granting confidence score, cannot change identity, capabilities, limitations, Personality, Memory, Beliefs, Goals, Emotion, WorldState, or EventHistory. Provider absence, failure, malformed output, stale state, unauthorized sources, or insufficient evidence leaves the existing SelfModel unchanged. `OllamaSelfModelReviewProvider` is a loopback-only, bounded, explicit adapter reusing Dialogue's transport. Nothing instantiates it automatically, and no live Ollama call is implied by Fake Provider tests. Personality's stable traits/preferences/values still have no governed evolution contract.

`AgentTurn` adds an opt-in Cognitive Causality path for newly consumed L1 evidence. `build_review_input` accepts only percept IDs newly returned by that `CognitiveRuntime` call, matches each to an unchanged trusted Observation for the same owner, and projects only the Observation payload plus separately named Observation/Event IDs. The request contains snapshots of that owner's existing Beliefs; it omits Event metadata, other Agents' cognition, WorldState, and Stores. A `CognitiveReviewProvider` may return bounded assessment/uncertainty text and at most one proposed revision to an existing supplied Belief. The provider cannot create Beliefs or choose an owner. The runtime derives the owner and source Event IDs, requires the cited Observation IDs to be a subset of this request, and validates owner plus exact authorized source refs before the existing `CognitiveUpdateApplier` checks the old value and writes the canonical BeliefStore. The Belief's `source_refs` for this revision are Observation IDs; separately derived source Event IDs are retained in metadata and are never substituted for those Observation IDs. The updated owner snapshot is then used by decision-context assembly. Replayed Observations do not trigger another review because only newly ingested percept IDs are considered. A missing provider performs no semantic update; provider failure, malformed suggestions, or insufficient evidence preserve existing Beliefs. Confidence remains the character's subjective confidence, not objective truth. This path performs no Event, WorldState, EventHistory, MemoryStore, GoalStore, or Emotion update.

`OpenAICompatibleCognitiveReviewProvider` reuses the existing bounded `complete_structured` transport, requires explicit host injection, and does not select an endpoint. `OllamaCognitiveReviewProvider` is an optional local adapter: the host must explicitly set `COGNITIVEWORLD_COGNITIVE_REVIEW_PROVIDER=ollama` or inject a provider into `SimulationRuntime`. It shares `COGNITIVEWORLD_OLLAMA_MODEL`, `COGNITIVEWORLD_OLLAMA_BASE_URL`, `COGNITIVEWORLD_OLLAMA_TIMEOUT`, and `COGNITIVEWORLD_OLLAMA_MAX_TOKENS` with Dialogue; the cognitive selector is separate so dialogue enablement alone cannot send cognition data. Transport accepts loopback HTTP only, pins the validated loopback address, bounds timeout/body/output/token use, and rejects redirects. Calls occur only during a turn with newly consumed trusted Observation evidence; there is no import/startup request and no remote fallback. Fake transport tests verify schema, provenance, governance, and data flow. The opt-in synthetic live-model test has passed against a local Ollama service. Its 30-second timeout remains a per-request guard; a prior timeout was not reproduced in the current measurements. This narrow test does not establish general cognitive reliability or a worst-case latency bound.

For stepwise continuation, the existing CognitiveRuntime additionally keeps an in-process receipt for an Observation only after owner/provenance validation, PerceptionProcessor conversion, and WorkingMemory update succeed. The receipt binds Agent ID, Observation ID and unchanged payload, source Event ID, that CognitiveRuntime instance, and its existing WorkingMemoryStore; validation also confirms the percept reference remains in that owner's WorkingMemory. `CognitionState.percept_ids` lists only newly ingested IDs, so repeat processing may return no ID while the receipt still proves prior consumption. Stepwise execution may accept either a valid prior receipt or a newly issued receipt from its current L1 ingestion. ObservationStore membership, cross-Agent processing, and hand-written percept ID strings do not create a receipt. These receipts are process-local and non-durable.

Objective world facts, observer-available facts, NPC private cognition, and player-visible facts remain distinct. Presentation must not read Cognition or Memory Stores.

### Perspective and output

The intended output chain is trusted Event and necessary event-time state → trusted perspective resolution → shared observable-fact evaluation → restricted visible input → Composer → message validation → ChatOutputGateway → player chat. A trusted application context supplies identity and role/mode; callers and players cannot supply their own visibility scopes. Missing or ambiguous authority data denies output. No full authentication server or permission database is required by this design.

`ChatOutputGateway` is now the sole approved player-chat sending interface. The in-memory adapter is callable and validates a batch against the current RuntimeContext session. The former optional CWUI live adapter remains in the untouched source backup. The fresh-world desktop host reads its recipient-scoped, already validated batches and exposes only `DisplayEntry(kind, text, request_id=None)` values; fact, clarification and literary narrative remain separate kinds. The optional request ID binds applicable non-fact delivery to its request, not to Event authority; see [the current desktop host contract](#current-anchor-desktop-host-contract). It does not hand Event, Observation, Runtime or credentials to Qt. A hand-built `PlayerVisibleMessage` is not proof of authorization; only a validator-issued, unchanged batch bound to the active recipient/session is accepted. In-process Python seals only limit accidental misuse and do not protect against malicious same-process code.

For the current desktop interaction stream, an already authorized message with Presentation `visibility_scope == "dialogue"` projects as the separate `dialogue` display kind; other authorized fact messages remain `fact`. Clarification and narrative remain separate. The UI does not infer a speaker name from an internal identity or reinterpret message text as a new Event. Unknown kinds are discarded, and the world-state page reads only the existing bounded `WorldProjection`, without receiving WorldState, EventHistory or cognition records. This is a UI layout and projection constraint, not a new authorization credential or complete dialogue capability.

## 19. Open-ended Actions and Five-layer Cognition (Approved Design)

These rules are approved design, not fully implemented behavior:

- **Open-ended Action Semantics:** Player and NPC actions are not restricted to a fixed behavior enum.
- **Action-Only Interpretation:** Natural-language interpretation preserves behavior, intent, target, tools, method, conditions, and sequence. Player claims of success, world changes, or NPC reactions have no factual authority.
- **Method-Based Resolution:** A concrete, feasible, creative method may improve the actual conditions assessed by Resolution. Novel methods are not rejected only because they are unknown. Description length, rhetoric, and token count do not independently improve success.
- **Multi-step Action Execution:** Plans are not pre-confirmed. Evaluate steps against actual intermediate results; those results may change or terminate later steps.
- **Player Agency Boundary:** Players control their own attempts. NPC responses are determined by NPC cognition and world events. Resolution determines world outcomes. Unreasonable attempts are allowed; their failure and consequences follow world rules, not wording penalties.
- **Cognition and Emotion:** NPC decisions use L1 Perception, L2 Working Memory, L3 Long-term Memory, L4 Beliefs & Self-Model, and L5 Metacognition with bounded feedback. Emotion and Motivation modulate across layers. Individual emotion thresholds, irrational-action probability ceilings, and growth curves come from character cognition; irrational candidates remain grounded in cognition and context. Decision produces Proposals only; Resolution determines results.
- **Perception and Presentation Boundary:** Objective facts, observer-available information, and player-visible information are distinct. Internal cognition, emotion parameters, probabilities, decision analysis, Prompts, and debug data are prohibited from player chat.

Current `ActionProposal` and `Attempt` use string action types and open mappings, but this does not implement natural-language interpretation or fair Resolution.

## Phase 12.3 Emotion and Motivation Contracts

**Implemented core; execution of this phase's tests is pending.** `Emotion` is
the canonical dynamic state owned by `CognitionContainer`. It carries open
string dimension labels, finite `[0,1]` intensities, a last SimulationClock
tick, and processed source Event IDs. Legacy `state` and `intensity` fields
remain readable; constructing a legacy single-state record migrates that value
to one entry in `levels` without discarding it. No EmotionStore is introduced.

`EmotionProfile` is an optional, owner-bound typed field of `Personality`, read
through the existing PersonalityStore. It holds per-dimension sensitivity,
activation threshold, growth rate, recovery-per-simulation-tick, regulation,
exact typed-fact reactions, explicit cross-dimension suppression, goal-drive
weights/conflicts/capability requirements, and bounded modulation affinities.
Normalized parameters retain their finite documented bounds. A goal-drive
multiplier is separately bounded to `[0,2]`: `1.0` leaves the stored
`Goal.priority` contribution unchanged, `0.0` suppresses that base contribution,
and values above `1.0` amplify it up to two times. Motivation computes
`Goal.priority * multiplier + configured emotion contribution`; it does not
write back to `Goal.priority`. Profiles are supplied by trusted character
initialization; metadata and free text are not parsed.
An absent profile/dimension means neutral/no corresponding reaction or decay.
Profile changes are blocked until a governed growth update is implemented.

`EmotionAppraisal` records an Agent's subjective match to a profile rule and
retains Percept and source Event IDs; it does not certify the rule's subjective
meaning as an objective world fact. `DeterministicEmotionAppraisalPolicy`
accepts only the owner's frozen DecisionContext and compares exact typed
ObservableFact fields. Optional gates can require an active Goal, a Belief,
retrieved owner-scoped Memory, a SelfModel statement, or a WorkingMemory
Percept reference. Missing or mismatching evidence yields no appraisal.
This deterministic strategy is an engineering baseline, not a
psychologically validated model.

`EmotionProposal` snapshots the previous and proposed dimensions, old/new
simulation ticks, appraisals, authorized source references, and idempotency
history. The evolution rule is: first apply elapsed-tick retention
`(1 - recovery_per_tick) ** (elapsed_ticks * (1 + regulation))`; then for each
new matching appraisal apply saturating growth
`old + ((strength - threshold) * sensitivity * growth_rate) * (1 - old)`;
then apply explicitly configured pairwise suppression. All values are clamped
to `[0,1]` or rejected as invalid. Same-source Events cannot activate twice.
No SimulationTime means no Emotion update; backwards time is rejected. The
clock unit is one integer SimulationClock tick, not wall-clock seconds.

The write chain is `EmotionProposal -> EmotionUpdateValidator ->
EmotionUpdateApplier -> CognitionContainer canonical Emotion`. Validation binds
owner, same-turn verified Percept/Event IDs, appraisal provenance, captured
SimulationTime, and previous processed-source history. Apply rechecks the
proposal receipt, old levels/tick, source history, and current tick before
replacing state. This is an in-process application-misuse guard and not
malicious same-process security or durable crash recovery.

`MotivationAssessment` is turn-local and keeps Goal scores, explicitly declared
conflicts, and profile-declared missing capability requirements separate from
stored `Goal.priority`. `DecisionModulation` is an immutable owner-scoped
snapshot with bounded `attention_bias`, `risk_bias`, `impulse_bias`,
`impulse_probability_ceiling`, `review_bias`, and per-Goal priority adjustments.
It is not a calibrated action probability or a Resolution modifier. Phase 12.4
consumes this snapshot during candidate evaluation; the modulation alone does
not create an ActionProposal, Event, or WorldState update. Presentation
contracts must never include it or Emotion internals.

## Phase 12.4 Agent Decision Contracts

`SituationAssessment` is a turn-local immutable view built from the current
Agent's frozen `DecisionContext`. It keeps verified Percept facts separate
from subjective Beliefs and retrieved recollections, and represents missing
world knowledge as uncertainty. A fact's optional `subject_ref` is retained;
`authorized_target_refs` is the sorted set of those owner-observed subjects and
the current observed affordance targets. It contains no Store or WorldState
reference and is never a Presentation input.

`ActionCandidate` is an open-ended attempt proposal, not an action enum. Its
fields are `intent`, optional `target`, `method`, `tools`,
`required_capabilities`, `preconditions`, ordered `steps`, prospective
`expected_result`, `uncertainties`, optional bounded subjective `estimated_risk`
and `estimated_cost`, a commitment estimate, and locally supplied source
references. Candidate IDs and owner identity are assigned/checked by the
application. At most six candidates, five steps per candidate, eight values
per auxiliary list, and 480 normalized characters per text field are accepted.

The deterministic generation baseline derives attempts from active Goal text
and may generate an information-seeking alternative when uncertainty exists.
It is a limited no-model fallback, not a claim of general open-ended language
generation. A replaceable `DecisionLanguageModelProvider` can propose open
methods. The optional standard-library `OpenAICompatibleDecisionProvider` is
disabled unless explicitly injected. The per-turn call budget is one, the
request context is bounded, and returned text is capped at 16,000 characters.
Unavailable providers and malformed/unauthorized output fall back to the
deterministic policy.

Model JSON accepts only candidate attempt fields. Explicit `success`,
`confirmed`, `outcome`, `result`, and `world_changes` fields are rejected with
`PermissionError`; they are never silently stripped and reused. NPC reaction,
identity/owner, authorization, observation, private cognition, Prompt/debug,
and unsupported fields reject the model batch. Authority-shaped rejection is
surfaced to the caller; ordinary provider/format failures use the documented
deterministic fallback. The parser assigns
candidate/owner/source identifiers locally, checks Goal ownership, validates
finite numeric ranges and text/list/step budgets, and never trusts the model to
set a permission or source reference. A non-null model `target` must exactly
match one of the current SituationAssessment's `authorized_target_refs`; an
invented or merely plausible identifier is rejected before ActionProposal
creation. This is reference membership, not semantic disambiguation, target
existence, permission, or a success claim. Explicitly injected host candidate
policies and separately governed dialogue candidates retain their own trust
and target-validation contracts. Language inside descriptive fields is still
a proposal for Resolution to evaluate, never a confirmed result.

`CandidateEvaluation` is subjective ranking only. The deterministic baseline
uses Motivation goal scores/conflicts, available SelfModel capability
declarations and limitations, relevance to owner-local Percepts/WorkingMemory/
Memory/Beliefs, Personality terms, risk/cost uncertainty, and
DecisionModulation. Belief confidence and model risk/cost estimates do not
establish world truth. Scores and factors remain internal and are not included
in the selected ActionProposal or Presentation.

One bounded decision review can re-evaluate a conflict/uncertainty-sensitive
candidate set. Phase 12.2 retrieval continues to obey its existing maximum of
two retrievals, two L5 feedback rounds, and five results per query. Phase 12.4
adds at most one model call and one decision review per proposal call. No model
response can increase any budget.

The selected output reuses `ActionProposal`: `agent_id`, locally generated
`proposal_id`, open-string `action_type` containing the selected intent,
optional `target_refs`, and `parameters` for method/tools/capabilities/
preconditions/steps/expected result/uncertainties/subjective estimates.
`reasoning_refs` contains only source IDs collected from the current Agent's
authorized context. `metadata` contains only non-sensitive candidate strategy
labels and IDs. The proposal indicates an attempt, not success. ActionPipeline
maps it to the existing Attempt; ActionResolutionFlow and EventFactory remain
the only path to a Resolution-confirmed Event, with EventProcessor remaining
the normal runtime WorldState writer. The default ResolutionEngine remains
unresolved when no policy is installed.

## Phase 12.5A Causal Contracts (Implemented door slice)

`ActionInterpreter` consumes an existing `ActionProposal` and returns the existing immutable `Attempt` snapshot; it does not introduce a parallel ActionAttempt model. It preserves open-ended action/method text and bounded JSON-like attempt parameters, rejects authority-shaped fields such as `success`, `world_changes`, `npc_reactions`, permissions, observations, Prompt/debug data, and checks an optional trusted actor binding. Success claims in ordinary prose remain non-authoritative and do not add a penalty.

`DoorState` is an immutable typed record stored under its door ID in the existing `WorldState.environment` collection. It includes exact interaction location, open/locked flags, manual operability, and optional key ID. `Entity.physical_capabilities` and `Entity.owner_id` are typed authoritative fields; absent capability or ownership data is unknown. A key is usable only when an authoritative `tool` Entity has `owner_id` equal to the actor, the attempt names that key, and the method describes using/unlocking with it. Position/co-location is not ownership.

`InteractionStateAggregator` is the per-Attempt, ephemeral state reader used by `MethodBasedResolutionEngine`. It requires an intact `Attempt`, canonical `WorldState`, and clock-issued `SimulationTime`. It reads only the actor Entity, actor location, actor-owned Entities needed to derive held tool IDs, and the one explicitly addressed typed environment entry. `WorldState.get_entity`, `get_location`, `get_owned_entities`, and `get_environment_entry` return detached targeted values; the aggregator does not copy the full WorldState maps. The output is bound to the Attempt ID/content fingerprint, target reference, simulation tick, read-source references, and explicit unknown fields. It is recalculated per Resolution call and is not persisted.

The existing `CausalWorldContext` is the physical-only view passed to `CausalAssessmentPolicy`: actor identity/location/capabilities, one typed DoorState or PassageState if known, and held authoritative tool IDs. Its `source_refs` identify current canonical WorldState collections, not an Event provenance credential. For addressable slots, `WorldStateSlotRead` separately carries the current-value fingerprint and origin; an Event source ID is exposed only after verification against intact EventHistory and processing evidence. This is limited latest-changing-event provenance, not a general historical lineage for arbitrary values. Assessments distinguish feasible, infeasible, partial, and insufficient-information; insufficient information leaves Resolution unresolved. Door and known-passage policies continue to use the same WorldState and Resolution path.

When a matching `AuthorizedStateQuery` is explicitly supplied, the aggregate can additionally include a `CognitiveInteractionView` for the Attempt owner. It queries at most the existing `MAX_QUERIES` target references and returns only unchanged, trusted ObservableFacts from that owner's authorized Observations, retaining fact, Observation, and source Event IDs. Hidden, unknown, unobserved, unsupported, or over-budget targets remain unknown. The view is not a second cognition snapshot and does not contain another Agent's private records. Full Belief/Goal/Memory/Emotion reasoning remains within the existing owner-scoped `DecisionContext` and is not currently a Cognitive Causality Resolution domain. Neither view mutates WorldState, EventHistory, ObservationStore, or cognition Stores. The optional `CausalReasoningProvider` may suggest evidence questions only; no model response can produce a trusted effect or authorize a state query.

`ResolutionDecision.world_effects` is accepted only from the installed ResolutionEngine policy and is covered by the signed `ResolutionResult` snapshot, including the complete Attempt snapshot. EventFactory moves the typed effect into Event changes. `DoorResolutionHandler` validates source, exact effect schema, expected old DoorState, current actor position/capability, and held key before returning a WorldUpdate. The normal EventProcessor then applies the update and issues a `door_open` ObservableFact. Registered sight-capable observers at the exact interaction location can receive a trusted Observation through the existing VisibilityPolicy and ObservationStore path. Missing trusted SimulationTime, relevant state, or observation inputs means unresolved or no Observation.

This Phase 12.5A section describes the original door-only implementation. Phase 12.5B below adds bounded stepwise execution and a processor-only ordinary-call write capability; neither addition provides durable or same-process malicious-code isolation.

## Phase 12.5B Open-ended Causal Contracts (Implemented; validation pending)

The Phase 12.5A limitations above describe the original door slice and are superseded here where noted.

`ActionInterpreter` still returns the existing immutable `Attempt`. It consumes the replaceable `ActionInterpretationProvider` contract; its optional OpenAI-compatible implementation may extract only `target_refs`, `method`, `tools`, `preconditions`, `steps`, and `uncertainty`. Ordered steps may be bounded text or typed method/target/observable-condition records. Nested fields use strict allowlists. Actor identity and proposal ID remain locally assigned, and target references and conditions must still be checked against trusted state or authorized Observations. Input is capped at 12,000 serialized characters, output at 8,000 characters, timeout at 20 seconds, and a stepwise plan permits at most one provider call across its life in the running executor, including after a retryable exception. Network unavailability leaves the submitted proposal as the safe deterministic attempt; malformed or authority-shaped responses are rejected. A model's causal advice is strictly typed suggestion text and cannot issue effects or make unknown conditions true.

`PassageState` is an immutable typed route record in the existing `WorldState.environment`. The passage policy requires a known route, exact source location, and confirmed locomotion capability. A successful policy result emits an `actor_location_changed` effect bound to the Attempt by ResolutionResult. Its handler rechecks the typed result summary, expected route, actor state, and capability before updating the existing `locations` collection; a failed result carrying any effect is rejected. An explicitly partial result may carry only its Resolution-authorized effects. The processor may issue an `actor_arrived` ObservableFact; a registered sight-capable observer whose event-bound post-update location matches the destination may receive the Observation through the existing store and cognition path. Unknown route/capability/time remains unresolved.

`StepwisePlanExecutor` allows at most five steps and processes only one per call. A step can contain method, target and an optional exact observable-fact condition. Conditions are checked only against trusted facts in this actor's trusted Observations and their source Events. Subsequent steps require an owner-scoped CognitionContext containing an Observation of the prior Event and an L1 consumption receipt from the injected Runtime CognitiveRuntime. The executor may perform the first valid ingestion or accept an intact prior receipt; `CognitionState.percept_ids` alone is not a historical receipt because it lists only newly ingested IDs. Missing or cross-owner evidence stops; a verified condition mismatch stops the plan. Each step identity includes a deterministic content digest, and the existing EventHistory prevents duplicate world application. Progress is immutable and integrity-bound to the issuing executor, WorldState, EventHistory and proposal content before status is examined. The executor retains the one-call provider budget across retryable failures. Both progress and consumption receipts are in-memory only and not durable. No later step is submitted before its predecessor is confirmed, and earlier confirmed effects are not rolled back.

`WorldState.apply_event()` requires EventProcessor's short-lived capability scope bound to the exact WorldState, intact Event snapshot, and WorldUpdate snapshot. Initialization `load_*` methods close when SimulationRuntime starts or before EventProcessor invokes its first handler, preventing a handler from using initialization loaders as a runtime write path. This blocks ordinary direct application misuse; Python private APIs do not defend against malicious same-process code. There is no global transaction or crash-recovery guarantee. The implemented domains are still limited to direct door operations and known passage traversal. Partial result status is representable but no production partial-effect policy is installed. General natural-language condition evaluation, general physical/social causality, durable plan storage, and live endpoint validation remain unimplemented.

## Phase 12.5C Safety Assessment and WorldNorms Contracts

`SafetyInput` is a bounded immutable snapshot containing actor ID, ingress source, submitted intent, target references, method, contextual text, and ordered steps. Its canonical digest binds the exact assessment input. `SemanticSafetyAssessment` contains interpreted intent/method/context, multi-step purpose, subject references, model-assessed subject attributes (explicitly untrusted descriptions), risk categories/level, disposition (`allow`, `restrict_presentation`, `refuse`, `clarify_or_safe_degrade`), basis category, uncertainty, digest, and fixed policy version. Subject descriptions never become authoritative identity facts. At the original Phase 12.5C point, Entity had no typed age/consent profile; Phase 12.5D adds the limited profile described below, without a consent fact source.

`SafetyInput.target_refs` and `ordered_steps` must be tuples, not mutable lists. All safety decisions bind the bounded canonical snapshot and are recomputed at each enforcement boundary.

`SafetyInput.source` describes a host-selected route; it cannot select an exemption. Action gates reject presentation/norm-only source labels, and presentation gates accept only declared presentation routes. `UniversalSafetyGovernance` is not an extension point for replacing the invariant gate; providers supply untrusted assessment labels behind its fixed checks.

The OpenAI-compatible safety adapter reuses the existing provider transport. It accepts only an exact allowlisted JSON shape with bounded fields and finite uncertainty. Model output supplies semantic assessment only; actor, targets, context digest, and policy version are bound locally. Static invariant checks cannot be weakened by provider results or WorldNorms. Provider failure does not become an Event or outcome. Current deterministic fallback is deliberately narrow and must not be described as comprehensive semantic detection.

`WorldNorms` is an immutable WorldState-owned snapshot, not another Store. It includes `world_id`, explicit governance status (`formal_law`, `customary_governance`, `mixed`, `no_formal_law`), lawmaking authority, jurisdictions, responsibility/process, enforcement/governance bodies, law/morality distinction, current version and version history, a concise pre-entry notice, and content hints. Each `NormRule` has a stable ID, title, summary, detail, jurisdiction IDs, status, explicit public visibility, children, open conduct scope, and normative force. Normative force is rule modality, not an action enum. Each `NormVersion` has an effective simulation-tick interval and typed law/social rule collections. A formal-law-free WorldNorms cannot contain formal legal rules or name a formal lawmaking body.

`WorldNormsGenerationPipeline` accepts a structured mapping or a bounded world seed through the shared provider transport. Generated text is only a draft; exact schema, world identity, ranges, depth/node counts, jurisdiction references, version consistency, and safety checks must pass before returning WorldNorms. Additional fields such as `safety_disabled`, `director_exemptions`, or arbitrary metadata are rejected. `WorldState.load_world_norms()` is initialization-only. Runtime version changes use `world_norms_updated` System Events through EventProcessor; update payloads bind expected current version and replacement snapshot, preserve old versions, append one version, and require the current trusted simulation tick. Processing that Event does not imply any Agent has observed the law change.

`applicable_norm_rules(norms, jurisdiction_id, simulation_tick)` returns effective objective legal/social rule records for a known jurisdiction and tick. It does not decide guilt, establish character knowledge, trigger enforcement, or alter the causal result. Those effects must use existing Observation/Cognition/AgentDecision/Resolution/EventProcessor boundaries.

`WorldNormsProjection` is a closed immutable UI DTO. It contains only world notice, governance summary, requested version ID, public active legal rules, public active social norms, applicable region ID/name pairs, current status, normative force, children, and safe content hints. Hidden rules and hidden children are omitted; UI expansion state is not part of this contract. Historical versions may be queried only through public entries. CWUI currently has a legacy `public_rules: tuple[str, ...]` field and has not yet migrated to this richer DTO. Never serialize WorldState or complete WorldNorms directly to CWUI.

`project_public_norms()` requires the caller's configured `UniversalSafetyGovernance`; it does not construct a fallback policy for a public-output route.

Safety and norms outputs are not cognition/world facts by themselves. A safety refusal has no Event ID, Event authority, punishment effect, or Memory proposal. A WorldNorms projection is disclosure data only. Rule changes are trusted state changes only after the controlled system Event is processed.

## Phase 12.5D Trusted Safety Context and Runtime Composition

`Entity.safety_profile` is optional `SafetySubjectProfile(age_years, profile_revision)`. It is immutable, validates exact age in `[0,150]` or `None`, and is part of the existing Entity/WorldState authority; it is not a second character database. `None` means unknown. The resolver ignores generic `Entity.attributes`, names, appearance, player statements, and provider descriptions. Current supported source is trusted WorldState initialization; no dedicated runtime profile-update handler exists. `Entity.type` is passed as identity context but is not used to infer age. Relationship and current interaction-consent facts do not yet have a typed trusted contract.

`SafetySubjectContext` is constructed inside `UniversalSafetyGovernance` from the current WorldState Entity records for the actor and target references. Its age/profile revision are not accepted from `SafetyInput`. `consent_status` remains `unknown`; an adult claim or consent sentence cannot change it. Sensitive actions needing unknown age or consent return clarification, while age-unknown ordinary dialogue, trade, conflict, crime, and combat attempts remain eligible for normal Resolution. A trusted underage subject in sensitive sexual context is refused. The current absence of a typed pair/activity consent source means this version cannot positively authorize consent-dependent adult action.

`SemanticSafetyAssessment.world_context_digest` binds the exact bounded SafetyInput to the active WorldState identity, current simulation tick, actor/target identity, and typed safety profile snapshot. Assessments are recomputed at each application boundary, not cached as reusable permissions. Input, owner, target, policy version, or bound world-context changes therefore cannot reuse an earlier approval. This is process-local binding, not malicious same-process authentication.

`RuntimeContext.safety_governance` is the single governance instance for built-in runtime composition. `SimulationRuntime` binds it into the built-in `AgentActionLoop`; that loop performs checks outside injectable Pipeline overrides and on the resulting Attempt. `ActionResolutionFlow` shares it with its EventFactory and installed MethodBasedResolutionEngine. `StepwisePlanExecutor` must share the Flow instance. `PresentationPipeline.for_runtime` requires the RuntimeContext instance. Runtime hosts may configure the shared instance with the existing `OpenAICompatibleSafetyProvider`; provider switching cannot remove deterministic checks. Standalone components have an explicit deterministic-only default, not a claim of semantic readiness. `SafetyReadiness` distinguishes `deterministic_only_unvalidated` from `provider_configured_unvalidated`; the latter does not claim endpoint health or safety effectiveness. No production Director Intervention endpoint or separately authenticated Player Action host currently exists.

The provider receives the resolved subject snapshot as context, but its JSON remains an untrusted assessment. Exact schema, bounds, local identity/context binding, deterministic hard restrictions, and fail-closed handling remain in code. Mock/simulated provider tests establish contract behavior only. Live model integration and adversarial effectiveness are separate, currently unvalidated categories. Universal safety is therefore not fully accepted by Phase 12.5D.

## Phase 12.6 Autonomous Runtime Contracts

`ObservedAffordance` is an immutable, owner-local decision projection derived
only from that Agent's trusted `DecisionContext.percepts`. It carries an
installed causal domain label, target reference, location, method hint,
required capability names, and source Percept/Event references. It is neither
a capability grant nor a closed action enum. Current deterministic affordance
producers cover only an observed closed door or known passage; Resolution
independently checks current WorldState, actor position, and authoritative
Entity capability before confirming an effect.

`AgentTurnExecution` groups the existing `ActionProposal`, immutable `Attempt`,
`ResolutionResult`, and optional Event for Runtime diagnostics; it adds no
result authority. `AgentRuntimeTurnRecord` records one turn, received
Observation IDs, newly consumed Percept IDs, commit status, and failure type.
`AutonomousWorldReport` and its round/action summaries contain developer
diagnostics, including bounded candidate scores/factors and Proposal/Attempt
summaries. They are not Presentation inputs and must never be sent to player
chat.

`AutonomousWorldRunner` reuses `RuntimeContext`, its `AgentRegistry`,
`AgentScheduler`, `ObservationStore`, shared safety governance, and canonical
`SimulationRuntime`. Its bounds are round-, Agent-, and Event-level limits;
each Agent is scheduled once per requested round and committed Event dispatch
occurs between Agent turns. Stable ID ordering is a scheduling rule, not an
action-selection feature. Confirmed state changes still require a
Resolution-issued result, EventFactory, and EventProcessor. No parallel World,
EventHistory, cognition, or Observation store is introduced.

## Phase 13 reusable content contracts

`GenerationProposal` holds tuples of `CharacterTemplate`, `LocationTemplate` and `ScenarioTemplate`. `ContentValidator` validates bounded schema, template/local references, mechanism destinations, seed participants/follow-ups, nonempty branch value links and P0 safety before `ContentRegistry.register`. The registry stores only definitions. `ContentInstantiator` returns `ScenarioInstance` with immutable `LocationInstance` and `CharacterInstance` identity receipts; live entity locations and mechanisms are held by `WorldState`, while owner goals, self-model and personality use the existing cognition stores and AgentRegistry. An instance receipt does not authorize runtime world writes.

`EventSeed` contains `seed_id`, `trigger_predicate`, scalar `trigger_value`, participant local keys, possible-effect descriptions, importance, follow-up seed IDs and constraints. It has no Event provenance or world-update authority. `observed_seed_opportunities` requires an EventHistory record with intact processor evidence and a provenance-checked owner Observation whose fact matches the trigger; it returns an immutable `SeedOpportunity` containing source Observation/Event IDs. The opportunity is an input hook for future owner-scoped planning and cannot itself create an ActionProposal or Event.

`ScenarioTemplate.entry_key` and `exit_keys` identify local locations. `ScenarioInstance.contains_actor` and `at_exit` read current authoritative WorldState location; neither moves an actor. Mechanism templates currently instantiate only supported DoorState and PassageState through WorldState initialization. Entering or leaving during runtime remains subject to installed passage/Resolution rules; the location references do not teleport an actor. No full scenario lifecycle or arbitrary environment adapter is claimed.

## Phase 14 model proposal boundary

`ContentGenerationRequest` is a bounded creative brief (`theme`, `purpose`, constraints), not a world or cognition snapshot. `LLMContentGenerator` uses an injected `complete_structured` provider and a locally enforced call budget. The built-in OpenAI-compatible construction reuses the existing bounded provider transport and its timeout. A missing/failed provider raises `ContentGenerationUnavailable`; invalid content raises `ContentGenerationError` or a Phase 13 schema/validation error. Neither failure returns a substitute story or changes a Store.

The JSON root has exactly `schema_version: 1`, `content_type: generation_proposal`, and `characters`, `locations`, `scenarios` arrays. Nested records have only the exact Phase 13 template fields. Unknown fields, including `world_state`, `event`, `resolution`, `observation`, `safety_profile` and `instance_id`, fail closed. The parser caps response length, tree depth/node count, collection size, identifier syntax and prose length; it rejects duplicate JSON keys and non-finite values. Parsing yields the existing immutable `GenerationProposal`. `ContentValidator` remains mandatory before `ContentRegistry` registration and independently enforces P0 safety and content references. EventSeed descriptions are potential hooks only; they are not WorldUpdate payloads.

## Phase 15 Scenario runtime contracts

`ScenarioRuntimeState` is an immutable, typed value in canonical `WorldState.facts`, keyed by world and instance. It binds template/world/instance IDs, phase, entry/exit location IDs, optional trusted creation tick, latest transition tick, revision, entrant, last Event ID and the entry mechanism snapshot. `None` creation time means no trusted clock was supplied at installation. `ScenarioInstance` remains an immutable identity receipt and carries side-branch/value references; it is not a mutable runtime state store.

`ScenarioEntryProposal(instance_id, actor_id, expected_revision)` and `ScenarioExitProposal(..., abort)` are requests, not Events or location changes. `ScenarioLifecycle` verifies the canonical runtime actor/location, revision, current trusted clock and in-process issued transition before its Handler returns a `WorldUpdate` to `EventProcessor`. It cannot apply an Event itself. Exit completion records lifecycle status after the actor actually reaches an exit through the ordinary causal route; it does not move the actor. `ScenarioSeedScheduler.poll` returns existing `SeedOpportunity` records and schedules only eligible local Agents whose matching Observation has trusted EventProcessor evidence. It is not a source of Event, WorldState, Memory or cognitive authority. Entry mechanism Observations use the existing visibility and L1 consumption contracts. No new CWUI write contract is introduced.

## Phase 16 runtime installation contracts

`ContentInstantiator.prepare` returns a `ContentInstallationPlan` containing isolated existing-model `ScenarioInstance`, Entity, location, typed environment, initial owner cognition and Agent records. The plan has no write authority. Pre-runtime `instantiate` reuses the same plan, preserving Phase 13 initialization behavior. `RuntimeContentInstaller` accepts a validated `GenerationProposal` or an existing registered template, requires the exact RuntimeContext/EventProcessor/WorldState/AgentRegistry and shared `UniversalSafetyGovernance`, and issues bounded, source-bound installation Events through the existing `SystemEventFactory` and `EventProcessor`.

`WorldContentBatch` is a typed payload for one processor-gated `WorldUpdate(target_id="runtime_content", operation="install")`. It adds the prepared entities, actor locations, door/passage states and `ContentInstallationRecord` to the existing WorldState collections only after conflict and reference checks. `ContentInstallationRecord` holds world/instance/template IDs, bounded source label, optional SHA-256 proposal digest, trusted installation tick, status and Event IDs. `world_installed` records a first committed world batch; `ready` plus an `AVAILABLE` `ScenarioRuntimeState` follows a separate controlled completion Event after cognition and template registration. A pending world installation is not a completed Scenario. No generic Event metadata, generated prose or UI state grants installation permission. This is in-process application authorization, not protection from hostile code executing in the same Python process.

Completion and delivery are distinct. Registration through ready dispatch holds RuntimeWriteFence (when bound), then AgentRegistry's existing membership lock, matching checkpoint lock order. A pre-ready failure cleans only this request's still-owned registrations. If the exact ready Event is already committed, a dispatch error retains the Agents and formal ready/AVAILABLE state and leaves its actual delivery marker untouched. Proactive expansion reports `observations_pending` for committed ready Events still awaiting delivery, rather than rejected or complete; it does not automatically retry or resume installation. Existing EventProcessor permit rules still govern explicit delivery retry, including rejection of a new operation reusing an old Event's permit.

The Scenario persistence codec explicitly registers only the existing `ContentInstallationRecord` and `WorldContentBatch` in addition to its previous types. Their existing fields and identities are unchanged; constructors reject malformed identities, status/tick/digest bindings and batch shapes. Unknown types and fields remain rejected by the closed codec. Prior supported Scenario values retain their canonical bytes. Completed signed installation save/restore preserves world records, cognition/Agent manifests and historical Event attestations without reissuing old Events. No snapshot version or signing purpose changes; partial-installation checkpoint policy, generated-template/lifecycle reconstruction and operator-directed recovery remain outside this repair.

## Host-bound player request and UI boundary (current narrow slice)

`PlayerActionRequest` is an immutable, bounded request carrying a host-session ID, world ID, request ID, untrusted intent/method text and optional target reference. `PlayerInputRequest` is the bounded raw-text ingress; `PlayerInputAssessment` is a closed, non-authoritative result with `ACTION`, `OBSERVE`, `UNPARSEABLE`, `CLARIFICATION_REQUIRED`, and pending-clarification control outcomes. The exact raw text is first screened through shared Safety before interpretation. An unparseable assessment carries no action fields. A clarification assessment carries a recognized intent, method, specific necessary missing-information slots and a question, but no executable target. Provider exceptions, malformed results, unavailable configuration, and unauthorized proposed targets are `reasoning_unavailable`, not player-input failure. `PlayerActionService` resolves the actor from the existing trusted `RuntimeContext.player_session`; it accepts a target only if that exact roleplay observer has a provenance-checked Observation whose typed fact survives `VisibilityFilter`. It binds the existing runtime SafetyGovernance to the action and resolution flows. `PlayerActionOutcome` keeps result status separate from fact-backed `messages`, optional `NoResultNarrativeMessage`, and optional `PlayerClarificationMessage`. Only ACTION candidates enter the existing action path and undergo target, Safety, Resolution and EventProcessor checks. A clarification request creates no ActionProposal/Attempt; a later player response can supplement only a still-valid, service-owned pending clarification bound to the original request, player session and Runtime generation; target and action authority must be rechecked. The pending state is process-local and not saved.

`NoResultState` is request-fingerprint-bound and records one of the explicit no-result reasons. `NarrativeFallbackProvider` receives the no-result reason and the player's own bounded intent/method text; for `UNPARSEABLE_INPUT` it may also receive bounded raw player text marked as untrusted. Its JSON generation is structurally bounded, and a separate bounded semantic review must allow literary text before the Presentation safety gate issues the display-only contract. The optional Ollama adapter is explicitly injected and loopback-only; generation/review are limited to two attempts. Model review is a fail-closed quality filter, not a trust root or proof of semantic truth. If it rejects, fails, or returns invalid output, no narrative is issued and the caller receives `clarify_or_retry`. The hard authority guarantee comes from the isolated output type and absence of world, event, and cognition write interfaces—not from the prompt or reviewer. `PlayerClarificationMessage` uses a separate receipt-bound `send_clarification` channel and carries only the missing slots and question; it is not accepted by the ordinary fact gateway. Player input classification and clarification are currently connected only through the narrow PlayerActionService path. Neither output type constitutes an Event, Observation, action, memory, belief, goal, or relationship update. In-process request ID replay records are not durable transaction records.

`VisibleInput` additionally carries the typed fact's optional `subject_ref` and `location_id`, both included in the immutable receipt snapshot and revalidated against the original ObservableFact. The current generic environment-state rendering consumes only this filtered record; it does not receive Event metadata or cognition. The former optional CWUI `CognitiveWorldEngineGateway` remains in the preserved source; it is not the M0.5 product adapter. The narrow input interpreter receives only the player text and the current authorized target projection; it cannot access global state or grant target access. Open-ended semantic grounding and general conversational repair are not established.

## Client DTO and asynchronous operation contracts (approved constraint; implementation partial)

**Historical Anchor M0.5 desktop boundary (not the current product gateway):** `src/anchor_desktop/models.py` contains provisional immutable UI view shapes inherited from the CWUI prototype. It omits the unused character-traits field, and the optional action/effect display value has only explicit `subject`, `action` and `effect` fields rather than an arbitrary payload dictionary. These are not an authorized serialization of `WorldState`, `Event`, `Observation`, `Memory`, `Runtime`, or signing credentials; merely constructing a UI value proves no authorization. At that phase there was no Core-to-desktop live projection producer. The prototype `EngineGateway` exposed read-only view methods only. That phase's product launcher listed two local world definitions through bounded parsing and `ContentValidator`, while `UnavailableEngineGateway` provides an empty-catalog fallback when package validation fails. Catalog fields are not live-world observations; neither prototype gateway provided saves, timelines or commands. The then-future M1–M3 host adapters were required to create consumer-specific allowlisted projections after the relevant authorization, include distinct fact/clarification/narrative/progress/error types, and use a non-blocking command path. A source Event ID or arbitrary string from a client is not an authorization credential. The legacy `public_rules` string tuple must not be populated from full WorldNorms; structured public-only projection requires separate review. The old no-command/no-save statement is historical, not a restriction on today's product adapter; see [the current host contract](#current-anchor-desktop-host-contract).

### World-pack opening and local model warm-up

The existing bounded desktop manifest retains its six required text fields. Optional `opening` (nonempty text, at most 2000 characters), `english_title` (nonempty text, at most 1000 characters) and `listed` (strict boolean, default true) are backward-compatible extensions; unknown fields and duplicate keys still reject, the complete manifest remains limited to 4000 characters, and public text including the opening passes the package Safety review. `listed=false` removes a package from new-world selection, not from signed save recovery. Gray Domain Beyond is the sole listed world; its historical `rain-harbor`, scenario, role, location and mechanism identifiers remain unchanged. The internal unlisted `clockwork-library` definition remains a compatibility fixture, not a public sample world. Its catalog title is a neutral compatibility label; its stable world/scenario/role/mechanism IDs and content remain available for verified recovery without rewriting saved identities or descriptions.

After a genuinely new session is published, `DesktopProductGateway.take_opening()` returns the reviewed package opening once. Cold restore never supplies it; cached stage navigation does not replay it. Qt renders only this authored plain text during the opening. Its initial display read consumes startup fact deliveries without appending them to the narrative or saving them for later replay. The underlying authorized Observations and interaction candidates remain intact. An explicit OBSERVE request revalidates current evidence through the existing read-only Presentation path; it does not create another environment Event merely to display that evidence. Skip reveals only the remaining prologue, once; submitting an admitted input also completes it before appending the player line. Runtime initialization and model work do not wait for animation. Restore does not request authored prose or historical observations for UI decoration; the initial display read likewise withholds its startup scene deliveries until an explicit current observation request. It is not model output, an authorized Observation, character experience, or a `PlayerVisibleMessage`; it does not enter input interpretation or the Core chat-output stream. Actual initial mechanism facts continue through EventProcessor, Observation and Presentation. There is no optional model-reference/context field or automatic prompt injection contract in this schema; any future context extension must specify recipient, use, authorization and validation independently of authored display prose.

`LocalModelWarmup` is a desktop-only provider lifecycle operation. Entry and restore start a bounded synthetic inference concurrently with Runtime construction using the injected local Ollama interpreter or a captured copy of its four existing environment settings. The provider factory accepts that explicit configuration snapshot without changing its default environment behavior. The request uses the existing loopback-only OpenAI-compatible chat transport, the configured model/endpoint/timeout, eight output tokens, and no world or player content. Readiness requires a completed, nonempty chat response with a terminal finish reason; health, connection or import success is insufficient. The entire response is discarded.

The host reports only `not_started`, `not_configured`, `not_required`, `warming`, `ready`, `failed` or `closed`, with bounded non-sensitive failure codes. One process shares a job per provider/endpoint/model; polling and world switches do not retry failed jobs. A user may explicitly retry a failed warm-up, with concurrent retries still deduplicated. Custom injected interpreters without this local lifecycle retain their ordinary behavior. `ready` means the warm-up inference completed, not that later requests cannot fail or that model residency is permanent. While a configured local model is warming or has failed warm-up, input admission raises bounded `ModelNotReady` before creating a player request or handle. Qt retains the draft, shows a recoverable status and never automatically resubmits it. The user submits once ready through the unchanged player action chain.

Closing or leaving detaches the session's warm-up view. An already running HTTP request may finish within its configured timeout; its daemon worker has no UI/Runtime callback or state-writing capability and cannot publish a stale result into a new session. Warm-up state, authored animation state and draft UI state are not added to snapshots. No warm-up operation creates Attempts, Events, Observations, Memory or Belief updates.

### Desktop management and confirmation boundary

Desktop package removal currently means reversible hiding of an application-owned bundled definition in the existing per-user Qt settings (`catalog/hidden_world_ids`). Source assets are never deleted. This is a client catalog preference, not a second package registry or world authority. There is no user-install/uninstall registry. Management lists all listed packages, including hidden ones. An unlisted compatibility definition appears only when its local `catalog.json` exists or its session is active. This presence check grants no trust: even an invalid catalog retains its recovery entry, and existing listing/restore verification still applies. No stored state or compatibility asset is removed. Persisted world-instance deletion is not supported: scenario identity and Timeline progress exist inside signed saves, without an independent instance ownership/deletion catalog. The supported instance operation closes the selected live session, cancels its pending input, freezes writes and discards only unsaved progress; all saves and branches remain.

Removal previews are detached display values bound to an opaque, single-use host token. They name the operation, resource identity, removed/retained data, dependencies and reversibility. Preparing or cancelling a preview does not mutate resources. Signed preview verification runs on the host worker; Qt receives only the detached preview and opens a plain-text confirmation dialog defaulting to Cancel. The confirmed result is polled by its token, so a later management operation cannot supply an earlier view's result. Confirmation revalidates the selected package/session and current signed catalog, rejects busy save/restore/removal operations and stale selections, then executes through the host's serialized worker. Manual-save deletion rechecks the preview catalog digest inside SaveManager's existing cross-process lock, retains referenced checkpoint/ancestor/Runtime-lease resources, and keeps its existing catalog commit and cleanup recovery semantics. A post-commit cleanup failure is reported as committed-with-maintenance-pending, never as rollback. The running-instance identifier is its Timeline in the one active host, privately bound to the exact Runtime session/generation; saved ScenarioRuntimeState identities are not deleted. These are not fictional Events or cognitive updates. A local host cannot claim an atomic multi-instance cascade or detect arbitrary external hosts beyond existing SaveManager locks and leases.

The interaction scroll area follows the tail only while the reader remains within 16 pixels of the bottom. Scrollbar range/layout changes coalesce into a single deferred update; animation advances do not reset the position on every character. Scrolling upward suspends following, and returning to the bottom resumes it. Existing labels remain intact, preserving selection and message order.

### Current Anchor desktop host contract

`DesktopProductGateway` (`anchor_desktop/product_gateway.py`) is the current product adapter. It calls the validated world host, `PlayerInputTaskCoordinator`, signed SaveManager and cold-resume host paths; it supports world entry/close, bounded input status and authorized output, verified save listings, save and restore. `begin_world`/`begin_restore` are observed through `entry_status`; `begin_save_listing` returns a request ID for `save_listing_status`, while `begin_save` is observed through `save_status`. `submit_input` returns an admission request ID, and `input_status` returns the coordinator's `PlayerInputTaskSnapshot`, not a completed world result. `retry_display` retries Presentation for that request without rerunning a completed action. The inherited prototype `EngineGateway` protocol and its `list_timelines`/`subscribe_performance` methods are not a claim that the current adapter provides general timeline browsing or a live performance stream.

Current desktop DTO ownership is split: `models.py` defines immutable catalog/view values such as `WorldProjection` and `SaveSlot`; `product_gateway.py` defines `EntryStatus(state, error_code)`, `SaveStatus(state, save_id, error_code)`, `SaveListingStatus(state, slots)` and `DisplayEntry(kind, text, request_id)`; the input coordinator defines `PlayerInputTaskSnapshot`. The current entry states are `not_started`/`starting`/`ready`/`failed`; save states are `not_started`/`saving`/`saved`/`failed`; save-listing states are `expired`/`loading`/`ready`/`unavailable`. These report operation status, not world-event outcomes. `read_world_projection` remains package-derived metadata, not a live-world Observation; a save ID requires an active session for the same world, but the returned projection is not save content. `read_display` returns only new recipient-scoped entries from the validated output gateway, with distinct `fact`, `dialogue`, `narrative`, `clarification`, `observation` and `action_feedback` kinds. The desktop page consumes these kinds but receives no Event, Observation, Runtime, WorldState or cognition object. Progress and recovery are read from task/status DTOs, not inferred from display text. These are consumer-specific allowlists, not serialized Core objects. NPC dialogue and independent authorized EventHistory browsing remain incomplete; see [the product boundary](ARCHITECTURE.md#unified-cwcwui-product-boundary) and the recorded scope in [the roadmap](DEVELOPMENT_ROADMAP.md). The historical M0.5 paragraph above retains only that phase's scope.

**In-process delivery recovery (2026-10-20):** Both player request entry points retain the same request fingerprint and pending Event after a presentation exception. A replay with changed content rejects. If canonical EventHistory marks processing COMPLETE, replay does not re-enter action interpretation, Resolution or dispatch the completed action Event. For a committed passage arrival, delivery also checks the destination's typed mechanism snapshots and may issue missing `environment_state_observed` Events through EventProcessor before Presentation; observation Event IDs are stable per arrival and mechanism, so replay does not duplicate a completed observation or the movement action. Presentation still applies current evidence/visibility/Safety checks and the deduplicating Gateway. An incomplete action Event follows the existing EventProcessor recovery/fence checks; this does not authorize a stale operation or repair partial world application. This is same-service, in-process recovery, not a durable client acknowledgement or restart/reconnect protocol.

**ANCHOR-M2-01 bounded interaction records (working-tree implementation):** `AuthorizedTargetCandidate` contains a request-local handle, bounded player-readable description and generic observed type; the canonical target reference stays only in the service mapping. Candidates come from currently local, provenance-checked authorized Observations, not model text or an unfiltered world enumeration. The optional Ollama candidate interpreter returns a handle that the service maps and rechecks before action. `PlayerInputAssessment(OBSERVE)` is a read-only result-layer classification, not an Event or world write. Its Presentation result is a separate request-identified delivery of validator-issued fact messages, revalidated against their original Observations and Safety checks; Gateway deduplicates by request. The client sees only allowlisted text. A pending clarification is process-local: original request, partial typed assessment, allowed answer mode/options, player session, Runtime session/generation, deadline and original cancellation signal. A continuation `PlayerInputRequest.clarification_id` names that original request; a missing or mismatched ID cannot answer a pending question, while explicit `new_request` starts an independent input. Choice answers must resolve within the displayed `option_handles`; a numeric answer also retains its original ordinal mapping. A later input can supplement the clarification only while all bindings remain valid, and all candidate authority is checked again. The pending state retains the original candidate-handle → canonical-identity pairs, not regenerated ordinals, and existing WorldState slot reads for the actor location and only the already authorized candidate objects. Resume compares canonical identities, visible descriptions/types/operations and current authorization independently of enumeration order, and revalidates slot continuity before and after interpretation and at the existing fence-protected Event dispatch boundary. Movement, absent/replaced targets or changed relevant state expire the old clarification; equal names do not establish equal identity. Slot fingerprints are continuity guards, not Observation evidence or permanent authorization. The original permit, session/generation checks, Resolution and EventProcessor remain required. No pending state or read-only result is added to Bundle or persistent EventHistory. Provider schema failures remain `reasoning_unavailable`; model text never confirms facts or effects.

`AuthorizedTargetCandidate.supported_methods` is an immutable bounded tuple supplied by the installed Resolution adapter for that typed observed mechanism. Candidate-based providers must return a selected target handle and a method exactly present in that candidate's tuple; a missing/unsupported method fails closed before ActionProposal creation. The service repeats the method membership check after mapping the handle to its current canonical target. The method phrase is an Attempt expression only: it is not evidence, an authorization grant, a result, or a state transition. Existing door/passage policies remain the sole source of accepted method phrases and continue to adjudicate independently.

**State-aware action feedback:** `VisibleInput.source_event_changed_state` is issued and revalidated by `VisibilityFilter` from the trusted Resolution Event and its typed processed fact; it lets the Composer distinguish a current state snapshot from a confirmed Resolution change without exposing Event metadata to the UI. A processed `actor_arrived` movement fact is eligible for the existing environment Presentation scope only when its recipient-authorized Observation and trusted changed-state evidence agree on the arrival location; the Composer renders a bounded arrival message through the fact channel, without exposing location or actor IDs. The movement fact does not become an action target. After a completed passage move, the service reads typed mechanisms at the actor's committed destination and sends their references through the existing `environment_state_observed` EventProcessor path; visibility still controls which resulting Observations the player may use as candidates. This is a local observation refresh, not another movement Resolution or a UI-generated fact. `PlayerActionFeedbackMessage` is a separate receipt-bound projection of a finite `ActionResultKind`, tied to the completed Resolution Event and active player session. It is not a `PlayerVisibleMessage`, Observation, or world fact. The in-memory Gateway deduplicates it by session and request ID. Successful changes with player-visible Observations use the existing fact channel; confirmed failure and already-satisfied results use typed action feedback. Free-form outcome explanations are not projected.

**PlayerInputTaskCoordinator (implemented narrowly):** `submit_input(PlayerInputRequest)` returns an opaque process-local `PlayerInputTaskHandle` as an admission acknowledgement. `completion(handle)` and `get_status(handle)` expose only `PlayerInputTaskSnapshot`: request ID, bounded execution state, delivery state, allowlisted outcome status and bounded recovery code. The snapshot contains no Event, Observation, Runtime, permit, provider output, Prompt, traceback, or cognition object. Same request ID and same canonical request digest returns the original handle; changed content is rejected. One background worker serializes requests for a coordinator in admission order.

For `reasoning_unavailable`, the snapshot may carry one allowlisted input-provider recovery category: `input_provider_unavailable`, `input_provider_configuration_invalid`, `input_provider_timeout`, `input_provider_invalid_response`, `input_provider_unreachable`, or `input_reasoning_unavailable`. These are diagnostic categories, not facts about the player's intent. Provider exception text, raw response and Prompt remain internal. The optional local Ollama input interpreter reads `COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT` (default 8 seconds, bounded to 0.1–10 seconds); this setting does not alter the task's Runtime-generation or world-write authority.

The returned completion Future is a cancellable observation view; cancelling that view does not cancel the task. Operation cancellation must go through `PlayerInputTaskCoordinator.cancel(handle)`, which applies the write-fence revocation rule below.

At admission, the coordinator captures the player session and actor, RuntimeWriteFence session/generation and original permit. It explicitly propagates that permit context to the worker. At task start the worker computes the authorized target allowlist inside the original permit's snapshot scope, keeping the Observation/Event authorization scan off the submitting thread; interpretation receives that fixed task-start allowlist, and target, Safety and Resolution checks still run in the service path. The final EventProcessor mutation uses the captured permit and ordinary fence commit boundary. Cancellation, timeout and close revoke that individual permit only before EventProcessor enters `commit_scope`; a failed revocation means the non-cancellable commit section has begun. Provider execution may continue after revocation, but its late result cannot obtain a replacement permit or commit. This is an in-process capability and task lifecycle, not hostile same-process isolation.

Execution status and Presentation delivery status are separate. A completed action Event with failed Presentation can be retried only through the coordinator's `retry_presentation(handle)`, which requires canonical EventHistory COMPLETE status and re-enters current Presentation authorization and Gateway deduplication without repeating interpretation, Resolution or action Event dispatch. The passage-arrival path may complete a missing destination-mechanism observation through its separate, stable-ID system Event; it never resubmits the action Event. The retry uses the admission-time permit in `RuntimeWriteFence.snapshot_scope()`: if delivery enters first, restore waits for that bounded projection/send to finish; if restore advances first, the stale permit is rejected and delivery becomes stale. A retry cancelled while queued by coordinator close resolves its Future with delivery still pending and `coordinator_closed`; no durable or replacement-service recovery is implied. Clarification/Narrative Fallback presentation failures remain pending for higher-level interaction recovery and are not retried by this Event-only operation. There is no durable queue or process-restart recovery.

A client DTO is a purpose-built projection for one recipient, not a dump or generic serialization of a domain object. Its constructor must name an explicit field allowlist and apply authorization before populating it. DTOs must be detached and immutable at the boundary. Do not expose full `Event`, `Observation`, `EventHistory`, `WorldState`, `RuntimeContext`, cognition records, Store objects, signatures, internal provenance, or arbitrary metadata to a UI. When a client needs a fact, pass the smallest authorized typed projection and its safe display references; raw source objects remain inside CW.

Keep result kinds distinct in both type and delivery channel: confirmed world-fact projection; an owner-authorized Observation projection; a clarification request; display-only Narrative Fallback; task progress; and error/recovery status. Clarification and narrative DTOs are not facts and carry no Event authority. Progress and recovery DTOs contain bounded status codes and safe user-facing text only, never stack traces, prompts, provider payloads, decision traces, or internal state. A status message cannot stand in for a committed Event or imply an unconfirmed outcome. Any new DTO field requires a necessity, authorization, safety, and compatibility review.

Long-running work is submitted and observed through an asynchronous application contract outside the UI toolkit. A task request/result should be bound to a stable request ID and, for Runtime work, the issuing Runtime session and restore generation. Implementations must define duplicate-request behavior, cancellation, timeout, failure, shutdown, and stale completion after restore. Cancellation is advisory once a non-cancellable commit section begins; it cannot reverse a committed Event. An asynchronous task result has no implicit permission to write: state changes must re-enter the original authorization and write-fence path. The player-input coordinator is a narrow implementation; it does not make the synchronous `PlayerActionService` API non-blocking and is not a universal task protocol.

Progress updates may be coalesced. A confirmed Event notification may not be silently discarded: clients must be able to reconcile through an authorized projection or ordered cursor. UI disconnect or rendering failure changes delivery status only; it does not change committed WorldState or EventHistory. Current same-process retry covers a submitted player's completed Event; it does not provide a general client acknowledgement/reconnect protocol, durable client DTO family, or reliable UI event stream.

### Local causal evidence query contracts (implemented; model loop pending)

`StateQueryProposal` contains a target reference and optional bounded predicate; it has no scope, permission or world-update field. `QueryIntent` projects only actor, intent, method and target references from an immutable Attempt. `AuthorizedStateQuery` binds an owner through the trusted Runtime player session or owner CognitionContext and returns `ObservedStateEvidence` only after Observation, Event, processing-evidence, visibility, target and tick checks. Evidence carries fact/Observation/Event IDs and the event tick; absent evidence is not a negative world fact. `AuthorizedQuerySession` enforces two distinct queries and at most four retained facts per Attempt; repeated queries terminate without spending budget. `CausalEvidenceAnalysis` accepts only bounded text and citations to supplied fact IDs. These DTOs do not authorize ResolutionDecision, Event or WorldState updates. No production model call consumes these contracts yet.

### Candidate evidence review (optional local integration)

`SituationFact.fact_id` is an optional provenance reference copied from an owner-authorized L1 Percept. `EvidenceAwareEvaluationPolicy` accepts the existing `SituationAssessment` and `ActionCandidate` batch, uses an unsubmitted Attempt only to scope an `AuthorizedQuerySession`, and returns existing `CandidateEvaluation` records. It supplies a local injected adapter with evidence only when that exact fact ID appears in the current owner's L1 situation. Analysis citations must name returned fact IDs. Added score factors are bounded subjective diagnostics; they are neither world truth nor success probability, and remain outside Presentation. The optional adapter has no registered network implementation or Event authority.

### Runtime evidence-review assembly

For the canonical AgentDecision, `SimulationRuntime` creates an owner/tick-bound evaluation policy per turn. `RuntimeContext` and that turn's `CognitionContext` must reference the same ObservationStore; query permission also requires the registered owner and unchanged EventProcessor evidence. The optional `evidence_review_provider` is a trusted host injection point and is never selected from player/model output; absent injection, a deterministic local provider proposes the candidate target and reports only observed citations or missing evidence. The policy changes subjective `CandidateEvaluation` fields only. The original AgentDecision and all authority Stores remain unmodified by the assembly step.

### Conflict and opportunity scheduling (implemented, partial)

`ConflictOpportunityScheduler.discover(situation, candidates, simulation_tick=...)` receives the same owner-scoped immutable `SituationAssessment` and candidate tuple already used by `AgentDecision`. It returns bounded immutable `ConflictOpportunityCandidate` values. Each finding has a stable owner-local issue ID, kind, Goal/target/candidate references, typed `SchedulerEvidenceRef` provenance, bounded importance/relevance, uncertainty, and process-local `first_seen_tick`, `last_seen_tick`, `sightings`, `revision`, and `active`/`dormant` lifecycle. It is diagnostic attention state, not a second Store or world authority.

The deterministic producer currently supports only (a) subjective tension pairs present in the current owner's Motivation assessment and (b) a candidate/Goal/target backed by that owner's observed affordance and cited Percept/Event source. It does not infer a global conflict from other Agents' beliefs, Goals or memories. `SimulationRuntime` binds the scheduler to each canonical AgentDecision turn and trusted simulation tick; findings can affect the existing bounded `scheduler_relevance` evaluation factor. Linked IDs remain in the Proposal trace and Event Tree candidate branch. A finding neither creates a candidate/action nor modifies its expected result.

`ConflictOpportunityAnalysisProvider` is optional explicit host injection and is absent by default. Its `ConflictOpportunityProviderContext` is a bounded projection without WorldState, other-owner data, or private Memory/Belief/Emotion content. Exact schema and allowlists constrain references to supplied Goals, targets, candidates and owner observations. Even valid provider output is an unverified interpretation and cannot authorize reads or writes. Fake Provider tests validate this contract only; no live model or external data transmission is part of the default Runtime path. Lifecycle is in-process and non-durable. Cross-Agent Goal resource-demand discovery is separately described below; broader resource/relationship discovery remains future work.

#### Cross-Agent Goal resource-demand projection (implemented, narrow)

`GoalResourceDemand` is an optional typed part of the canonical `Goal` record, not a second Goal registry. It contains an explicit `object:{id}` resource reference, optional shared scope reference, and an `exclusive_use` declaration. Goal free text and generic metadata are never parsed to infer resource semantics. Validated Goal status/priority updates preserve these claims; they cannot silently rewrite them.

Before registered Agent turns, `SimulationRuntime` visits registered Agents in stable ID order and reads only each Agent's linked, owner-matched active Goals from its `CognitionContext`/canonical `GoalStore`. It projects only owner/Goal identity and revision, typed resource demand, current tick, and a verified `WorldStateSlotRead` for the referenced Entity's `type` slot. The total is bounded to 512 projections per tick; budget overflow clears the batch and suppresses cross-owner findings for that tick. That read must still match `WorldState` and have `initialization` or EventHistory-verified Event provenance. Unknown, absent, stale, malformed, or unsupported references do not support a finding. This cross-owner comparison occurs only in the trusted Runtime/Scheduler boundary; no whole Goal or cognition snapshot is shared with another Agent or an optional provider.

Status semantics: `supported_conflict` requires distinct owners, the same grounded resource, two explicit exclusive-use demands, and the same non-empty scope. `potential_conflict` records incomplete/different exclusive-use scope evidence. `shared_target_only` records a common grounded resource with no exclusive demand and has zero evaluation relevance. These statuses describe declared Goal requirements, not resource capacity/possession, actual competition, awareness, hostility, or an enacted event. No generic resource capacity contract is installed.

The scheduler emits per-owner `ConflictOpportunityCandidate` projections containing only that owner's Goal ID and source refs (`goal`, an opaque Goal-revision digest, and an opaque verified slot-receipt digest). Partner IDs, descriptions, priorities and private reasoning are omitted. Opaque internal issue identity is derived from participant identities/revisions, resource/scope and verified slot state; outward finding identity is owner-specific. Existing per-owner de-duplication and bounded active/dormant lifecycle apply in process. Linked finding IDs may affect the existing bounded candidate score and are retained in ActionProposal/Event Tree diagnostics; they do not create or force candidates. Findings are not Events and do not mutate WorldState, GoalStore, or cognition. This lifecycle is not persistent and has no timeline-generation/restore fencing.

### Proactive content expansion (Runtime integration; opt-in)

`ProactiveContentExpansion` is an optional composition on `SimulationRuntime`. Its input is bounded to scheduler finding objects from the same `ConflictOpportunityScheduler`, owner, and simulation tick. Runtime queues findings only after the corresponding Agent Event has successfully passed the configured EventProcessor dispatch. A finding is still an owner-local hypothesis/attention signal. A re-created equal value is not accepted as an issued signal.

`ContentExpansionNeed` is an immutable, non-world record carrying the finding ID, owner, kind, typed source-reference pairs, bounded importance/relevance, uncertainty, and trusted tick. `ContentNeedPolicy.request_for(need)` returns the existing `ContentGenerationRequest` or `None`; `None` means no new content is warranted. The policy and a `ContentGeneratorFactory` are mandatory host injections. No generator is called when no request is returned. The factory adapts the existing `ContentGenerator` contract, and its proposal still passes `ContentValidator` and `RuntimeContentInstaller`; the expansion integration creates no alternate Store or write API.

The runtime attempts at most one proposal/install per tick. It requires exactly one selected ScenarioTemplate in the proposal. A stable world/finding-derived instance ID makes repeated demand idempotent: ready records return `already_installed`, while an existing `world_installed` receipt returns `recovery_required` without replay. Exact definitions already present in `ContentRegistry` are reused through `install_registered`; conflicting IDs are rejected. After the installer reaches ready, the resulting `ScenarioInstance` is registered with the same `ScenarioLifecycle`. The `ContentInstallationRecord` retains the finding and source-reference pairs for audit traceability; these references do not by themselves prove semantic relevance. The existing installation's multiple-authority partial failure semantics remain: a failure after the world batch may leave `world_installed`, is surfaced as recovery-required, and is not automatically resumed.

The expansion policy receives only the finding projection, not WorldState or a full DecisionContext. Any content-generation brief is created by the explicit host policy. External model/network use is not enabled by default and requires separate host endpoint and data-scope configuration. Automated vertical-slice tests use an in-process static generator; they verify Runtime-to-installer data flow, not live model quality, efficacy, or approval.

## Player dialogue ingress and delegated Agent attempts

`DialogueRequest(request_id, recipient_id, utterance)` contains no sender identity. `PlayerDialogueService` resolves the sender only from the host-bound roleplay `PlayerSessionBinding`, requires a registered recipient at the same known location, and runs Safety before recording delivery. The host does not accept model-provided identity, permission, result, or world-state fields.

Delivery is represented by a trusted `dialogue_input` system Event whose sole change carries the raw utterance and whose participants/metadata bind the sender, recipient, and shared location. `DialogueInputHandler` rechecks that both remain at the location and emits a typed `social_input / utterance_delivered` ObservableFact addressed to the recipient. It requests an empty `facts` update; the EventProcessor's canonical `EventHistory` records the utterance Event, while no objective state is changed. `ObservationGenerator` issues the Observation only to the registered event-time recipient named by the fact. The text proves delivery only; it does not prove claims made in the utterance.

`DialogueInterpretationProvider` is optional and explicitly injected. Its bounded `DialogueInterpretation` fields are `meaning`, optional `possible_action_request`, and `uncertainty`; these are untrusted, turn-local cues, not a reply or decision. With no interpretation or no possible action request, the recipient L1 consumes the Observation and this service creates no Attempt. With an action request candidate, the service runs the recipient's existing `AgentTurn` and `AgentDecision`; a returned Attempt is required to bind `agent_id` to the recipient and `initiator_id` to the host-resolved sender. `initiator_id` participates in the Attempt content snapshot/fingerprint and is carried into Resolution-sourced Event metadata by EventFactory. It does not change actor authority.

When no response candidate source is configured, the compatibility route still only delivers and perceives speech (or runs the prior interpreted action path); it invents no reply text. A host may inject `DialogueResponseCandidateProvider`, or explicitly select `OllamaDialogueResponseCandidateProvider` by setting `COGNITIVEWORLD_DIALOGUE_PROVIDER=ollama` and `COGNITIVEWORLD_OLLAMA_MODEL`. Optional `COGNITIVEWORLD_OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434/v1`; `COGNITIVEWORLD_OLLAMA_TIMEOUT` defaults to 30 seconds and is bounded to 0.1–30 seconds; `COGNITIVEWORLD_OLLAMA_MAX_OUTPUT_CHARS` and `COGNITIVEWORLD_OLLAMA_MAX_TOKENS` configure bounded generation budgets. Only plain HTTP loopback addresses are accepted; the socket connects to a validated numeric loopback address and redirects are rejected. No request is sent at import or service construction.

The Ollama adapter receives a bounded allowlisted projection of the recipient's `SituationAssessment`: the current inbound utterance fact and Event source, recipient-local Working Memory, retrieved personal memories, beliefs, goals, capabilities/limitations, values/preferences, emotion levels, uncertainties, optional untrusted interpretation, and already authorized target references. It does not serialize Runtime, Agent, WorldState, full Stores, or another Agent's cognition. The input cap is 24,000 characters; output is capped at 12,000 characters and six candidates; each request has a configured timeout. The model cannot provide identity, owner, source references, permissions, observations, Events, NPC reactions, scores, confidence, or arbitrary targets. Owner and inbound source are stamped locally; target must match the original sender or a current authorized affordance target. Invalid envelopes/schema, authority fields, ungrounded targets, timeout, connection failure, and unavailable models yield `response_generation_failed`; there is no default script or external fallback.

Each accepted structured candidate becomes a `DialogueResponseCandidate` bound to the inbound Event and recipient owner. `AgentTurn.prepare_decision_context` assembles the same owner-scoped frozen snapshot used for action decisions; `AgentDecision.propose_from_candidates` applies the existing situation, candidate evaluation, bounded review, and selection rules. Model confidence and ranking are not accepted. A semantic interpreter or model cannot choose the NPC response. The selected candidate carries open response semantics and a *delegated-request lifecycle* outcome (`accept`, `reject`, `clarify`, `undecided`, or `not_applicable`), not a closed taxonomy of speech acts. `accept` requires an interpreted request candidate; the selected proposal then uses the existing NPC-as-actor, original-sender-as-initiator Safety/Attempt/Resolution path.

Only `accept` submits the selected ActionProposal through the existing guarded `AgentActionLoop`/Resolution path, binding the Attempt actor to the NPC and initiator to the host-resolved player. `reject`, `clarify`, and ordinary conversation do not create that Attempt. A clarification follow-up must name a prior, successfully delivered clarification from the same sender and recipient; the new input Event cites the earlier reply Event as cause. It does not automatically approve the prior request. An undecided choice produces no reply or action.

A decided, bounded reply passes shared P0 Presentation safety, then a trusted `dialogue_reply` system Event records only that the NPC uttered the selected text. The reply handler checks the stored trusted inbound Event, reversed speaker/recipient pair, selected candidate reference, shared location and non-retrograde simulation tick. The internal result retains the selected candidate ID and owner-checked source references; private decision details are not player Presentation inputs. Its typed `social_output / utterance_delivered` fact is observable solely by the addressed, registered player Agent at the event-time shared location. `PerspectiveResolver → VisibilityFilter → MinimalComposer → PresentationValidator → ChatOutputGateway` checks that Observation and the host-bound player session before delivering the exact selected semantics. The statement's contents are subjective speech, not established world truth. The optional expression adapter may fail or return the exact approved text; a changed text is rejected because this narrow validator cannot prove semantic equivalence. Ollama calls require explicit local provider selection and loopback-only transport; this is not a live-cloud integration.

Inbound and reply Events, candidate decision, expression, and output delivery have distinct statuses. The reply handler requires an exact process-local binding to the NPC-selected ActionProposal before it will accept a reply Event; a handmade system Event with a made-up candidate ID is refused. Request IDs and immutable input fingerprints shared by services on one EventProcessor prevent sequential duplicate submissions from replaying either Event. `retry_delivery` retries only the recorded reply Event through Presentation; the in-memory Gateway suppresses an identical duplicate and rejects changed content for the same Event. A reply Event left in `RECOVERY_REQUIRED` or `OBSERVATIONS_PENDING` remains explicitly flagged and is not automatically reissued. These are process-local, sequential guarantees, not durable transactions, concurrent-host exclusion, same-process adversarial isolation, or delivery guarantees for arbitrary external adapters. Open-ended response generation, automatic disclosure checking of free-form prose, general target grounding, real-model semantic quality, and complete dialogue host authentication remain unvalidated.

### NPC-origin communication candidate and delivery (v0.1 narrow path)

`NpcCommunicationDraft(recipient_id, utterance, source_refs)` is an untrusted provider result, not a message Store entry. The provider is explicitly injected into `SimulationRuntime`; it receives the current sender's bounded `SituationAssessment`, currently registered co-located recipient IDs, and a one-candidate bound. The Runtime augments the normal ActionCandidate batch with at most one communication option, and the canonical `AgentDecision` evaluates and selects across both that option and ordinary actions. Invalid provider output drops only the optional communication candidate. A valid draft cites source references already present in the sender's situation; at delivery, the service rechecks the proposal's selected decision-trace row, exact owner and recipient, source references against the sender's trusted consumed Observations/Beliefs, current tick, co-location, Safety and original RuntimeWriteFence permit.

The selected proposal is delivered as the existing `dialogue_input` Event through EventProcessor and its no-op WorldUpdate handler. The Event binds sender/recipient/location and uses the Proposal ID as `cause`; the issued `NpcDialogueDelivery` records proposal, sender, recipient, Event, Observation, tick and a `delivered_pending_recipient_turn` status. There is no separate queue or second event history. A trusted Observation is addressed only to the recipient, and is not recipient knowledge until that Agent's own L1 consumes it. Delivery neither changes WorldState nor creates an Attempt/Resolution nor updates cognition. Duplicate delivery in the process returns the cached result for the same Proposal ID; this is not a durable exactly-once guarantee.

On the recipient's subsequent AgentTurn, generic cognitive review can mark one newly consumed `social_input / utterance_delivered` Observation as `speech_observation_id`. The evidence builder excludes all other social testimony from corroboration. `CognitiveBeliefReview` also checks the designated evidence is actually a speech fact and rejects any other cited social input as independent support. A revision must cite the speech and at least one non-social recipient Observation in the same newly consumed evidence batch, target an existing owner Belief, then pass the unchanged validator/applier/store path and write fence. `CognitiveReview.outcome` accepts `accept`, `reject`, and `defer`; backward-compatible provider JSON without `outcome` maps a revision to accept and no revision to defer. `reject`/`defer` cannot contain a revision. These dispositions are subjective review results, not truth labels. No independent evidence, stale authorization, provider error, reject or defer leaves canonical Belief unchanged.

The current snapshot does not persist Observations or WorkingMemory. Restoring a save may retain the speech Event in EventHistory while not restoring its recipient Observation or its consumption status. NPC speech continuity across saves/branches is therefore unsupported in this slice; it must not be inferred from Event ID existence.

## Remaining social causality contracts (PARTIAL / DESIGN)

The narrow NPC-origin communication path is implemented in-process as described above. This does not implement general NPC-to-NPC social causality, durable messaging, automatic replies, or objective relationship effects. The broader contracts below remain design constraints, not implemented guarantees.

The receiver-owned existing-Belief speech review is **IMPLEMENTED in process** as `CognitiveReviewInput` with a `speech_observation_id`. It can follow addressed player speech or the narrow NPC-origin communication path above. That ID must belong to the bounded, receiver-owned evidence set and be newly consumed by the receiver's L1. Other evidence is limited to that receiver's L1-consumed, processor-backed objective Observations; other utterances are not independent objective support. A model may return zero or one `BeliefRevisionSuggestion`, never a Store write. A revision must cite both the speech and independent evidence, name an existing receiver Belief, and survive a current-tick, Event/Observation source, L1 receipt and old-Belief snapshot recheck before the existing `CognitiveBeliefReview → CognitiveUpdateValidator → CognitiveUpdateApplier` route. The source IDs prove provenance and permission, not arbitrary semantic entailment. Provider absence/failure or insufficient evidence leaves the Belief unchanged. The request has the existing cognitive-review item/size bounds and at most one Provider call per delivered speech. This write path uses the in-process RuntimeWriteFence: the original operation permit is rechecked under the final Store commit lock, so freezing or advancing the restore generation invalidates stale permits and candidates. This does not provide cross-process or persisted generation fencing; semantic model quality acceptance remains absent.

The proposed shared social context binds a trusted timeline ID and restore
generation when available, simulation tick, grounded participants, owner,
source Event/Observation IDs, L1 consumption proof, any objective slot-read
receipts, exact prior cognition snapshot/version, uncertainty, and a bounded
consumption key. These are future issuance and validation requirements, not
fields already carried by every existing dialogue or scheduler object.
Speech delivery, independent claim support, and recipient acceptance are
distinct records. An Event ID alone grants no read scope or semantic truth.

Persuasion proposals belong only to the receiver's cognition. Existing
`BeliefUpdateProposal` revises an existing Belief through the canonical
validator/applier after receiver-owned assessment and exact Observation/Event
and L1 checks at the dialogue boundary; the generic validator alone does not
enforce every persuasion-specific proof. Existing `GoalUpdateProposal` changes only status
or priority of an existing Goal. Goal creation/description change and any
objective relationship transition need separately validated contracts. No
provider, sender, or scheduler may write a cognition Store directly.

Cross-Agent conflict findings require a trusted system-level, narrow
projection of Goal demands and grounded objective constraints. The shared
internal finding may identify multiple owners, but each owner-facing
projection contains only evidence that owner is authorized to know. A shared
target alone is not scarcity proof; a finding is neither an Event nor an
Agent's Observation. Reuse the current Scheduler's bounded evaluation and
Event Tree links after the necessary cross-owner authorization and stable
issue identity are designed. Restore must invalidate stale provider output
and candidate applications before any write; Context Freeze and Timeline
Generation fencing are planned, not implemented. Detailed ownership,
failure, and acceptance contracts are in
[SOCIAL_CAUSAL_DESIGN.md](SOCIAL_CAUSAL_DESIGN.md).

## Player “灵光一闪” backend contract (partial)

**Offline Claim-Evidence audit (not a presentation grant):** `ClaimEvidenceDraft` binds original text to bounded `EvidenceClaim` entries. A claim records an ID, semantic dimension (`state`, `event`, `actor`, `method`, `time`, `cause`, or `hypothesis`), assertion/presupposition/hypothesis mode, subject, predicate, value, local evidence indices and triggering text span. `audit_claim_evidence` accepts only intact `VisibleInput` entries revalidated against a resolver-issued perspective, their stored Observation and an allowed simulation tick. Model-supplied source IDs are never read grants. Per-claim `ClaimCheck` distinguishes direct support, an explicitly unconfirmed hypothesis, unsupported content and unknown semantic entailment; source fact IDs remain traceable. An environment-state fact can directly support a matching state, and an explicitly visible social-output delivery can directly support that delivery, not the truth of speech. State facts alone cannot prove a closing/locking event, actor, method, event time or cause. The original text may contain omitted implicit claims even if its declared spans cover it: `ClaimEvidenceAudit.text_coverage` is therefore always `unverified` and `may_authorize_presentation` is false. This contract is for independent evaluation and has not replaced the current production reviewer.

`insight_generation.py` is an **offline protocol comparison**, not another insight provider or display authority. `inspect_free_text_extraction` audits claims extracted after free prose; `inspect_claim_first` audits claims declared before unrestricted final wording; `inspect_constrained_units` requires a bounded list of `SemanticContentUnit` values and exact, program-controlled joining of selected unit surfaces. All three recheck claims against the same `VisibleInput` authority and return `GenerationProtocolAudit` with unverified text coverage and `may_authorize_presentation=False`. Exact joining only constrains the final assembly bytes. A unit's own prose, a model's incomplete claim list, or a semantic paraphrase remains unproven. No Event/WorldState/Observation permission is created.

`InsightRequest` names a request, host-bound session/world and current simulation tick. The service resolves the actual roleplay perspective from `RuntimeContext`; request values and model output cannot choose the observer. It projects at most twelve `VisibleInput` facts after rechecking Event processing evidence, Observation owner and visibility. `InsightFact.index` is a local citation number, not an Event ID or read grant. At most four `InsightHint` records expose only eligible current-tick, same-owner branch/finding attention metadata whose target and Event basis are already visible; private Goal/scheduler details, scores, branch prose and other owners' records are omitted. An absent eligible hint stays absent.

The optional `OllamaInsightProvider` is constructed explicitly or through `COGNITIVEWORLD_INSIGHT_PROVIDER=ollama` plus the shared local Ollama model/address variables. It uses the existing pinned-loopback transport, bounded input/output and a fifteen-second maximum timeout per call. No request occurs on import, startup, ordinary AgentTurn or without the player's explicit `explore` call. Each request has at most two model calls (generation plus semantic review); each session/tick has at most two requests and four calls. Changed content under a reused request ID is rejected; an unchanged request with unchanged projection returns its in-process result without a new call.

Provider JSON is exactly `suggestions: [{text, basis, uncertainty}]`, at most three. Basis entries are indices into the supplied visible facts, not model-signed source references. The entire batch must pass field/size/index checks and P0 presentation safety before `InsightSuggestion` maps basis to trusted Event/fact IDs and a `visible_basis` projection of the same already-authorized predicates/values/subjects. Suggestion text must be a question, cannot contain raw typed entity/Event references, and carries `unverified_exploration` status plus non-empty uncertainty. `InsightResult` is a separate read-only service return, **not** `PlayerVisibleMessage`, a trusted Event fact, or a gateway-issued batch. No partial batch is returned on failure. No ActionProposal, Attempt, Event, WorldUpdate or cognition update is authorized by this contract.

Before returning a nonempty batch, a bounded `review(context, suggestions)` call assesses factual presuppositions against each suggestion's own cited visible facts. Its exact `reviews: [{index, verdict}]` schema permits only `supported`, `unsupported` or `uncertain`; missing rows, extra fields, unavailable review, and any non-supported verdict reject the entire batch. A well-formed unsupported/uncertain review returns `semantic_unverified`; malformed review returns `invalid_output`. Neither returns a partial suggestion batch. The review sees no raw Event IDs, private cognition or wider WorldState. A model verdict is a conservative output gate, **not** proof of entailment, a new evidence source, or permission to read more data. The backend has synthetic Fake Provider contract tests and local Ollama adversarial probes; broad semantic reliability, CWUI trigger/rendering, durable quotas and hypothetical branch-state simulation remain unvalidated or unimplemented.
## Memory record, provenance and snapshot compatibility (source-checked)

**Current implementation inventory, 2026-10-22; no tests run for this documentation repair.** Memory Schema, decision Provenance Schema, CognitiveStateSnapshot Schema and SnapshotBundle version are separate axes. Source: `cognition/memory.py`, `core/persistence.py`, `cognition/snapshot.py`, `cognition/memory_revision.py`, `memory/{memory_decision,memory_write_factory,memory_write,memory_persistence}.py`. A Python constructor, decoded record or valid content signature does not confer a current write capability or prove policy semantics.

| Memory Schema | Typed decision provenance | Admitted fields and read/restore scope | New canonical write scope |
|---|---|---|---|
| Memory/v1 | None | Persisted fields are exactly `id`, `owner_id`, `type`, `content`, `importance`, `source_event`, `metadata`. Legacy decode supplies internal defaults `schema_version=1` and the three new nullable fields as None; re-encoding retains seven-field bytes. Snapshot v2 and v3 can contain it. Metadata may contain legacy labels, but they are not typed D3 provenance or authorization. | Legacy Authority/Factory/Persistence writes remain supported with their source, snapshot and applicable fence/immutable-ID checks. Trusted system-proof issuance is a separate restricted path; no D3 provenance/grant is inferred for either. |
| Memory/v2 | `MemoryDecisionProvenance` with schema_version=1 | Supported representation/codec and signed Snapshot v3 capture/read/isolated-restore compatibility. Full eleven Memory fields are required, including typed provenance, nonempty `logical_record_id`, and optional `supersedes_record_id`. Existing fixtures exercise this combination and preserve it unchanged. Snapshot v2 rejects it. | **Not emitted by the current formal Factory/Persistence pipeline.** Construction or re-capture of admitted restored data is not a new authorized decision. No automatic migration or re-signing into Provenance/v2 is provided. |
| Memory/v2 | `MemoryDecisionProvenanceV2` with schema_version=2 | Supported full eleven-field codec and Snapshot v3 representation; same owner/source/predecessor and branch-local revision validation. `outcome` must be `accepted`. Snapshot v2 rejects it. | Current formal D3 path: explicitly installed policy → engine-only Authority result → Factory request → Persistence → Store, with intact policy-call/Proposal binding, original Runtime permit and fully verified fence-bound canonical EventHistory/revision lineage. Rejected/deferred calls do not persist Memory. |
| Unknown/incompatible combination | Any | Unknown Memory/provenance schema or registered type, extra/missing persisted fields, Memory/v1 carrying typed provenance/revision fields, Memory/v2 without a supported typed provenance, or Snapshot v2 containing Memory/v2 is rejected at the relevant constructor/codec/snapshot gate. | No automatic repair, quarantine-to-success or downgrade. A provenance object with schema 1 cannot become schema 2 merely by changing its version number; the concrete registered type and version must agree. |

Memory/v2's exact eleven persisted fields are the seven legacy fields plus `schema_version`, `decision_provenance`, `logical_record_id`, and `supersedes_record_id`. `Memory.id` is the immutable revision ID; `logical_record_id` groups a logical record; `supersedes_record_id` references another Memory/v2 revision. These links apply to **both** admitted v2 provenance combinations, not Memory/v1. Provenance owner must match Memory owner, `source_event` must occur in its unique nonempty source Event tuple, and predecessor must agree between record and provenance. Snapshot/revision validation checks same owner/logical identity, existing predecessors and no cycles; branch lineage additionally enforces exact inherited checkpoint bytes, authored Timeline, unique root/successor/tip. Model-supplied identity strings are not lineage evidence.

**Restored use is distinct from new issuance.** The v2/Provenance-v1 combination is not a read-only archival flag: admitted canonical records can be captured again and reconstructed into an isolated MemoryStore. After normal Runtime publication, `CognitionContext.get_memories()/get_relevant_memories()` can supply them as subjective decision inputs when their exact IDs are Character-linked, owner matches and content is semantically retrievable; canonical rechecks and query limits still apply. Those readers do not filter on Provenance/v1 versus v2, independently re-prove a past policy invocation, or implement D4's dynamic-grant/current-tip selection. `MemorySnapshot` projects the existing seven decision-view fields, not a provenance capability or a claim of formal issuance. Thus `schema_version=2` alone must never be interpreted as “created by today's formal D3 path.” The full canonical record retains the concrete provenance type/version; a new formal write still needs the current engine-bound decision/request. This read-path behavior is source-confirmed in `agent/cognition_context.py` and `cognition/memory_retrieval.py`; a dedicated restore-to-AgentDecision integration test for v2/Provenance-v1 and every mixed-chain variant has not been established by this review. Do not promote it to separately tested semantic acceptance.

Both Provenance types carry `schema_version`, decision/policy ID and policy version, Proposal ID and SHA-256 digest, input SHA-256 digest, reason code, owner, source Event IDs, Timeline, Runtime session, restore generation and optional predecessor. V1 requires its exact schema 1 and validates bounded reason syntax; V2 requires its distinct registered type/schema 2 and adds `outcome="accepted"`. The V2 data constructor checks nonempty reason text; the actual formal `MemoryPolicyOutput/v1` gate additionally enforces bounded reason syntax, exact accepted/rejected/deferred enum and finite [0,1] importance. Do not claim the two constructors have identical validation or that either is a standalone signature. Formal authorization is checked by the sealed invocation/request and final Store boundary; persisted provenance is bound by its containing snapshot signature, not independently signed proof of a past policy execution.

### Outer snapshot and verification boundaries

- `CognitiveSnapshotBody.schema_version` accepts 2 or 3. New captures use 3 and signature purpose `cognitive-world/cognitive-state-snapshot/v3`; legacy v2 uses its original `/v2` purpose and admits only Memory/v1. Snapshot v3 may contain Memory/v1, Memory/v2 + Provenance/v1 and Memory/v2 + Provenance/v2 together, subject to all record/owner/source/revision checks. It does not force inner records to version 2 or silently upgrade them.
- `CognitiveStateSnapshot.from_bytes()` first allowlist-decodes exact records (constructors reject unknown schemas), then checks body digest, the schema-specific signature when present, and structural/store/source metadata with Event-source and full Memory-lineage validation deferred. An unsigned, digest-only low-level snapshot can be represented; that is not a trusted cold-resume source. A decoded signed object without complete source/lineage context is not a published Runtime.
- `reconstruct_isolated()` requires the independent expected Agent/Character manifest and revalidates with supplied trust, EventHistory and applicable revision lineage before building new isolated canonical Stores. Sources marked `event_history_reference_present` must resolve when that context is required; explicitly unverified source statuses remain unverified rather than becoming proof. No policy is rerun and no L1 consumption receipt or missing decision evidence is invented.
- Bundle verification first checks its own signature/component byte digests, restores/verifies the world checkpoint and history, reads the cognition snapshot, reconstructs isolated cognition with source/lineage context, then checks other required components and cross-component Timeline/tick/roster/history bindings. SaveManager/ancestry and the cold/active Runtime reconstruction/publication paths impose their additional checks before use. Existing signed Bundle v2 membership/purpose is independent of cognition v3; a component digest alone does not establish understood schemas or historical truth.
- Migration is not implicit: v1 seven-field decode adds only neutral in-memory defaults; v2/v1 provenance stays v1 provenance on round-trip. Unknown/incompatible values fail the supported path rather than being reinterpreted as verified legacy data. A future migration needs its own approved contract and evidence.

**Evidence limits:** `test_cognitive_state_snapshot.py` explicitly covers legacy seven-field bytes, v2/v1-provenance codec round-trip, Snapshot v2 purpose/Memory-v1-only behavior, Snapshot v3 provenance tamper and revision rejection, plus a Windows DPAPI independent-process Bundle test. Its `_add_memory_v2_chain` helper directly seeds synthetic v2/v1 records for compatibility tests; it is not an endorsed production write API. `test_memory_decision_policy.py` covers formal v2/v2 writes, legacy v1 fallback, closed policy outputs and forged/direct-write rejection; save/restore tests cover formal branch lineage and canonical-history checks. These source assertions are not a new run or exhaustive acceptance of every mixed-provenance branch/restore combination. Broader combinations remain follow-up verification within existing D3.2/recovery work; D4 grants/social-experience effects remain unimplemented, and D3.2.4 ancestor debt stays open.

# Unified CognitiveStateSnapshot (schema v2/v3; isolated staging only)

`cognitive_world.cognition.snapshot.CognitiveStateSnapshot` captures the supported canonical records as one immutable body: simulation tick, explicit timeline ID, Runtime session and Restore Generation, Agent/Character links, six canonical store snapshots, source references, owner coverage, exclusions, and a SHA-256 content digest. Each store's `state_version` is a digest of its canonical encoded contents (`canonical-content-digest`), not a monotonic revision counter. Capture fails rather than returning a partial snapshot when a supported record cannot be encoded or when Agent links/owners do not agree.

Capture is permitted only for canonical `SimulationRuntime`, `CognitionContainer`, `MemoryStore`, and Agent `CognitionContext` instances whose final write boundaries share the Runtime's `RuntimeWriteFence`, and requires the Runtime's canonical `AgentRegistry`. The expected Agent/Character manifest is read from that registry, and supplied contexts must match its exact Agent set and identity pairs. Capture holds `RuntimeWriteFence.snapshot_scope()` and `AgentRegistry.snapshot_scope()` together across manifest, context links, tick, and Store reads. The registry has a separate membership lock; `register`/`remove` use it, but registry mutations are not implicitly protected by RuntimeWriteFence, and direct private `_agents` mutation bypasses the lock. Neither lock protects unbound callbacks or direct Store private-field mutation.

Included stores: BeliefStore, GoalStore, SelfModelStore, MemoryStore, Emotion records held by CognitionContainer, and PersonalityStore. Excluded transient/derived/diagnostic data: WorkingMemory, Observation/Percept inputs, DecisionContext, proposals and traces, Event Tree/scheduler diagnostics, CognitiveRuntime/provider cursors, and AgentRegistry scheduling metadata. No canonical relationship Store currently exists. An excluded or unsupported canonical Store must not be silently treated as captured; the current capture contract is limited to the six named stores.

Source metadata distinguishes `no_source_recorded`, `unverified_reference`, and `event_history_reference_present`. The last status proves only ID presence in the supplied EventHistory; it is not a persisted EventProcessor receipt or semantic validation. Reconstruction checks EventHistory membership when that status is asserted. Digest validation proves encoded content consistency only. Optional signatures use the injected `PersistenceTrust`; the local Windows adapter is `WindowsDpapiPersistenceTrust`, and verification fails closed if the host has not explicitly initialized/opened its protected key ring. Ordinary JSON, IDs, and hashes do not prove historical authenticity.

`reconstruct_isolated()` requires a host-supplied expected Agent/Character manifest independent of the snapshot, then revalidates schema, manifest equality, exact captured links, record types/identity/owner, six-store coverage, per-store digests, source references, and Agent-linked required records before building unpublished fresh stores. It returns only a `complete-for-verified-Agent-manifest-and-supported-stores` staging result and does not publish or mutate active Runtime state. The caller must obtain the expected manifest from a trusted source; an unsigned embedded roster is not independent evidence. This is not a complete cognitive/runtime save, active restore, cross-process authenticity guarantee, or timeline isolation. Timeline ID and Restore Generation are captured metadata; old-task fencing across a restore still requires a future coordinated restore transaction.


## Signed timeline fork metadata (staging only)

`TimelineForkManifest` v1 separates child `timeline_id`, `parent_timeline_id`, `fork_checkpoint_id` (SHA-256 of exact signed `SnapshotBundleManifest` bytes), inherited Event-chain head, and simulation tick. The externally injected `PersistenceTrust` verifies both the fork and source bundle manifest. Event processing credential v2 signs the Event's immutable owning Timeline ID alongside its content/evidence/update digests, tick, changed slots and predecessor credential digest. Version 1 Event credentials have no Timeline ownership and are rejected for persisted-history restoration; they are never silently promoted.

Persisted `EventHistory` state v1 represents a root as one timeline-owned local chain. A branch stores its signed fork manifest, signed source bundle manifest, and only the child-local Event suffix. The child resolves the fork checkpoint to the corresponding immutable parent EventHistory prefix. Its first local credential points to the inherited chain head; later local credentials point to the prior child credential. Validation recursively verifies the parent's own lineage, checks the signed fork boundary against the resolved parent's exact head and verifies the child-local chain under the child Timeline ID. Event IDs cannot repeat in the ancestry. Exported flat Event tuples are read views; they do not reassign ancestor ownership. Parent appends after the fork are excluded from the child's immutable prefix, and child appends do not modify the parent.

For a branch checkpoint restore, the host must provide `event_history_resolver(fork_checkpoint_id)` that resolves the exact EventHistory at that signed checkpoint, not a later mutable parent head. Missing or mismatched ancestry, credential, owner, predecessor, event content or checkpoint association fails closed. Old flat checkpoint schemas/credentials are unsupported for this timeline-aware restore path. Recovery remains staging-only: no branch is activated and no SimulationRuntime dependencies are atomically published. `RuntimeWriteFence.freeze_writes()` is not a recovery transaction.

## Staged Runtime reconstruction contract

`RuntimeDependencyManifest` requires an explicit resolution for each host-owned dependency role. Resolutions identify verified snapshot input, reconstruction from verified state/current code, explicit host reinjection, or an explicitly disabled optional service. The manifest is a host declaration, not proof of trust. Character/runtime metadata, pending scheduler queues, handler registrations, decision/action policies, cognition-context construction, Safety and Observation policies, provider selection, player session and optional content services are not encoded in the current snapshot bundle. A missing or unsupported required dependency prevents staging.

`IsolatedRuntimeReconstructionFactory.stage(...)` accepts signed checkpoint/cognition bytes, their signed `SnapshotBundleManifest`, an independent Agent manifest, a signed `TimelineForkManifest`, the external trust verifier, and an explicit assembler. It repeats snapshot and lineage verification instead of trusting a mutable previously staged object. `RuntimeAssemblyInputs` provides the isolated WorldState, child EventHistory, rebuilt six-store cognition, MemoryStore, verified roster/links, checkpoint clock and a fresh staged-only fence to the host assembler. The returned `SimulationRuntime` is checked for exact state references and owner bindings. `StagedRuntime` is always stopped and permanently write-frozen. No API in this phase activates it.

The four statuses are distinct: component snapshots verified; isolated state rebuilt; Runtime assembled and cross-validated as staged; Runtime activated. Only the first three can be reached here. A source strategy label, content hash, Timeline metadata or successful serialization does not establish omitted runtime configuration, durable task state, or activation safety.

Strict isolated assembly sets `strict_dependency_binding=True`: the Runtime constructor checks processor/action-flow object identity and does not repair mismatches by rebinding. Staged construction also sets `allow_environment_provider_discovery=False`; this prevents ambient Cognitive Review provider selection. Existing non-staged Runtime construction retains its compatibility defaults.


The factory requires the current active Runtime for post-assembly alias detection, but does not place it in `RuntimeAssemblyInputs`. Directly held mutable services and handler registrations must not be shared; active owner cognition contexts are inspected when available. The assembler is still trusted host code and Python identity checks do not sandbox side effects or hidden closures.


## RestoreCoordinator and Active Runtime publication

`ActiveRuntimeSlot` is the host's synchronized read/publication reference; only its single bound `RestoreCoordinator` can replace the reference. Restore states are `ACTIVE`, `PREPARING`, `FROZEN`, `PUBLISHING`, `ACTIVE_NEW`, and `RECOVERY_REQUIRED`. The slot exposes the currently published Runtime and publication generation; it does not itself restore data.

`RestoreCoordinator.activate(staged)` accepts only a `StagedRuntime` issued by `IsolatedRuntimeReconstructionFactory`. Before freeze it re-verifies the retained signed bundle, staged WorldState contents and six canonical Store contents, signed EventHistory lineage, assembly bindings, staged RuntimeSession ID, Timeline ID, parent Timeline/checkpoint binding, tick and empty child suffix. It then freezes/advances the old Runtime under its write-fence lock. Staged activation and active-pointer publication happen under the staged fence lock, so new operations cannot start before the pointer swap. The old fence is retired before the new pointer is made visible.

The host `pre_publish_hook` executes before final validation. Under the staged fence and AgentRegistry membership locks, the coordinator repeats the staged checks before activation, after `start()`, and after old-fence retirement immediately before publishing. The post-start WorldState comparison permits only the initialization seal transition. If any of these checks finds changed canonical content, clock, lineage, roster, owner, or dependency binding, publication is refused and the slot enters `RECOVERY_REQUIRED`; neither old nor staged writer is silently reopened. The checks do not establish process-crash atomicity or protect arbitrary private mutation by uncoordinated host code.

Pre-publication failures leave the current pointer unchanged. After a successful old-generation invalidation, rollback may resume the old Runtime only with newly captured permits in its advanced generation; old permits are never restored. If the old fence has been retired or publication status is uncertain, the coordinator reports `RECOVERY_REQUIRED` and does not enable either Runtime as a writer. A staged fence cannot be activated through public `unfreeze()`; only the coordinator's internal capability can perform its one-shot activation.

This guarantee applies to known EventProcessor, CognitiveUpdateApplier/Store, MemoryPersistence and other write paths bound to RuntimeWriteFence. Custom callbacks or stores that bypass the fence remain outside coverage and must be disabled or separately integrated by the host. The synchronization is in-process only; it does not coordinate another process, survive a crash as a transaction, persist scheduler queues, or implement save slots. Fake trust and deterministic thread tests validate contracts, not production key lifecycle or all OS scheduling behavior.

### L1ConsumptionProof/v1

`L1ConsumptionProof` records one owner having consumed one exact `utterance_delivered` Observation on one consumption Timeline. Its stable ID hashes consumption Timeline, owner, Observation ID and canonical Observation digest. The signed body also binds source Event/fact IDs, source Timeline, Event/consumption ticks and `addressed-utterance-delivered/v1`. Signing uses fixed purpose `cognitive-world/l1-consumption-proof/v1` and existing PersistenceTrust; the signature does not itself prove L1 creation. The dedicated Runtime issuer requires a matching process-local consumption receipt and source processing evidence before signing. A reserved `system_l1_consumption_proof_v1` MemoryStore record is the canonical holder, written under RuntimeWriteFence and excluded from ordinary Character memories. Duplicate identical proof IDs are idempotent; conflicting records fail closed.

The existing signed cognition snapshot covers this record in its Memory Store component. `from_bytes` verifies schema, content and signature while deferring Event source resolution; `reconstruct_isolated` requires EventHistory and revalidates the proof purpose signature, source attestation, lineage and historical directed visibility. This is a phased verification result, not a single trusted flag. The schema remains v2 and old snapshots do not gain proof records. A proof signed or committed only in memory has no cross-restart guarantee until an immutable published checkpoint includes it.

When a signed parent checkpoint is staged on a child Timeline, proof verification accepts the checkpoint Timeline only if it is in the child EventHistory's verified ancestry. The inherited proof retains its source and consumption Timeline IDs. A snapshot from an unrelated Timeline remains invalid. A signed outer cognition snapshot does not replace the inner fixed-purpose proof signature or its source checks; both are verified during isolated reconstruction and again before active publication.

### OpenAI-compatible Provider transport contract

The shared transport accepts plain HTTP only for an IP loopback literal or `localhost` when standard-library address resolution returns only loopback addresses; it connects to the selected numeric address. Arbitrary hostnames are not accepted for HTTP even if they might resolve locally. All non-loopback endpoints require HTTPS with standard TLS certificate verification. Redirects are rejected for both HTTP and HTTPS. `Authorization` headers, including Bearer API keys, are never sent over HTTP. Endpoint rejection, TLS failure, redirect rejection, timeout, and response errors do not fall back to HTTP or another remote endpoint. The Decision and Causal OpenAI-compatible adapters remain opt-in through explicit host injection; no remote provider discovery was added.

The Decision request may disclose the bounded current-owner view: trusted Observations, WorkingMemory, retrieved Memory, subjective Beliefs, Goals, SelfModel-derived capabilities/limitations, Personality fields, Emotion levels, motivation/modulation and uncertainty. Direct Causal requests contain bounded submitted Attempt/proposal data and the verified context supplied to that operation. Existing wrappers on the same adapter send their bounded task payloads: Safety sends SafetyInput plus trusted subject context, WorldNorms generation sends its world seed, and content generation sends its creative brief and schema constraints. The host owns destination approval and data-disclosure authorization for each payload. Encryption protects data in transit but does not constrain provider retention/use or prove semantic correctness. The adapters do not log API keys or full request bodies.

## NPC Socialization v0.2 contracts — Stage 0 freeze and Stage 1 implementation

Stage 0 froze the contracts below. Stage 1 implements D1 and a limited D2 slice; Stage 2.1 implements the D3 formal decision/write boundary, while D4–D9 remain design only. Current production supports ordinary speech with optional Stage 1 typed claims, L1 proof v1 for addressed utterance delivery, the narrow Stage 1 non-verbal proof described below, explicit Character-linked Memory retrieval, and an opt-in existing-Belief review. Belief-to-candidate matching remains lexical.

### Typed claim and source binding

**Stage 1 status:** `AttributedClaim/v1` is implemented as optional versioned `DialoguePayload/v1`. The selected communication candidate carries a canonical, versioned claim draft; at delivery, the host's registered property contract checks its declared type and trusted sender-local Observation references ground its subject. The final `SystemEventFactory` Event binds speaker, recipient, claim digest, exact utterance digest, applicability interval/scope and Event ID. Event processing evidence and persistence signatures cover the Event payload. The claim is testimony, is not placed in `Event.changes`, and cannot update WorldState. Legacy Events decode with no dialogue payload and are never inferred or upgraded. Restore validates the claim-to-Event binding after authenticating the persisted Event. This proves signed attribution and structural binding, not the asserted proposition's truth or continued availability of an arbitrary host property registry.

A claim is testimony, not an ObservableFact, WorldState change or Resolution result. Do not place it in Event.changes or use untyped Event metadata as an authority extension. An unknown version or malformed claim rejects that structured communication; it is never silently downgraded to ordinary speech. The sender may explicitly submit speech with no claim. Unknown versions are never reinterpreted.

### Consumption proof separation

**Stage 1 status:** Existing `L1ConsumptionProof/v1` is unchanged. A separate `NonverbalL1ConsumptionProof/v1` and fixed purpose are implemented for the registered `room-light-on-colocated-sight/v1` historical rule. The trusted `HistoricalObservationRuleRegistry` resolves a canonical rule reference (rule identity plus version) to its configured verifier; the generic proof core does not name a domain rule. The current domain rule requires trusted Event processing evidence, a complete captured event-time environment snapshot, the registered observer's co-location and known sight, and a matching typed fact. The issuer signs only after actual owner L1 consumption and commits through the existing fenced system-record Store path. Snapshot reconstruction rechecks signature, owner, stable identity, source Event/fact, timeline ancestry, event tick and invokes the same configured historical rule verifier. Incomplete historical snapshots may still yield ordinary supported Observations but fail closed for durable proof issuance. This is one production-supported rule, not authorization for all `environment_state` facts. Stage 1.2 now verifies a published SaveManager checkpoint, independent Windows DPAPI process reopening, isolated reconstruction and RestoreCoordinator activation for this proof; it also verifies parent/child suffix isolation and ancestor resource retention after parent-slot deletion and GC. The tested restore path uses the built-in production registry; arbitrary host-defined registries are not persisted or dynamically recovered.

The implemented non-verbal proof family is limited to the registered event-time rule above. The general Observation generator continues to support other narrow forms, but they do not thereby become eligible for durable L1 proof. Unknown rule versions, source evidence and owner evidence fail closed. Old EventHistory cannot be re-signed. Stage 1.2.1 adds D2-specific Windows child-process exit tests at consumption-before-proof, post-L1/pre-signature, signed/pre-Store-commit, post-Store-commit/pre-save, and catalog-published/pre-commit-journal windows. It also tests both RuntimeWriteFence snapshot/commit orders, failed canonical Store commit, and a delayed old-generation issuance across RestoreCoordinator activation. These tests establish process-exit and in-process synchronization behavior for the supported synthetic host; they do not establish OS power-loss durability, cross-host coordination, or arbitrary host isolation.

Proof states are distinct: issued, canonical-store committed, captured in a published signed checkpoint, reverified on restore. Only committed records are canonical Runtime state; only published and verified saves provide corresponding checkpoint durability. Restore never synthesizes missing proof records.

### Social-experience Memory and authorization

Proposed AttributedSocialExperience/v1 is a typed Memory value with stable experience ID and immutable revision ID. It binds recipient owner, speaker, claim Event/digest, proof references for speech and independent evidence, source/consumption timeline and ticks, comparison result, evidence-set digest, prior revision and reason. It is a bounded subjective assessment, not objective truth, reputation, consent or relationship state.

Use the existing lifecycle: MemoryProposal → MemoryDecision → MemoryWriteRequest → MemoryPersistence → MemoryStore. A replaceable policy evaluates; Authority seals the authorized decision; Factory constructs the bounded request; Persistence checks source, owner, original permit, policy result and immutable identity; Store remains canonical. Without a policy there is no social Memory write. deferred has no write effect. Same proposal/evidence retry is idempotent; same identity with conflicting content rejects; new evidence creates a new revision. Metadata is not authorization.

A new social Memory receives a typed Character association only after final authorized persistence. Retrieval verifies owner, registered Character link, type, source and active Timeline lineage. Existing explicit memory_ids remain compatible. Any index is derived from verified canonical records and registry links and rebuilt in isolated restore; no owner-wide scan grants access.

### Temporal comparison and decision influence

Definite supported or contradicted requires exact typed subject/property/value compatibility, valid claim interval, verified source and consumption provenance, Timeline lineage, complete EventHistory/checkpoint coverage and a domain mapping to canonical state reads. Same-tick order follows authenticated EventHistory sequence. Relevant changes within the interval must be resolved against claim scope. Missing mapping, incomplete interval, unknown values, ambiguous order or unrelated Timeline yields insufficient or temporally_incomparable; absence of a matching Event is never proof of unchanged state.

Social experience may propose a subjective Belief change only through existing Validator, Applier and owner Store. To claim decision effect, add a reusable typed Belief-to-candidate/precondition relationship. Current lexical Belief matching does not establish object-specific truth influence. An A/B acceptance test fixes owner, context, candidates, configuration and seed, varies only governed Belief, and reports source, base score, cognitive factor, final score, AgentDecision selection and Resolution/EventProcessor result. No fixed scene weight or forced answer.

### Schema compatibility matrix

| Component | Proposed boundary | Compatibility and refusal |
|---|---|---|
| Dialogue payload/claim | Optional DialoguePayload/v1; AttributedClaim/v1 | Legacy speech is claim-free; unknown schema unsupported; no inference or re-signing. |
| L1 proof | Preserve v1; new non-verbal schema and fixed purpose | v1 unchanged; unknown proof/rule rejects. |
| Visibility rule | Stable historical ID/version | Restore uses registered historical verifier, not current WorldState. |
| Social experience | AttributedSocialExperience/v1 | Old Memory remains ordinary; unknown type is not evidence. |
| Memory access | Typed owner/Character link, derived index | Explicit old Character IDs remain; no metadata permission or owner-wide scan. |
| Cognitive snapshot | Stage 0 proposed v3; now implemented by Stage 2.1 Phase 1 | v2 retains its original purpose and Memory/v1-only meaning; current v3 inner-record compatibility is specified by the source-checked matrix above. Unknown types/versions reject. |
| Snapshot Bundle | Keep v2 only if signed manifest semantics stay the same; otherwise v3 | Existing versions remain version-specific. A digest does not imply the component schema is understood. |

Every durable type requires codec allow-list, schema refusal, signature, isolated reconstruction, bundle compatibility and branch-resource tests. Digest integrity, authenticity, source traceability and semantic truth are separate properties.

## NPC Socialization v0.2 Stage 2.0 — D3/D4 契约冻结（仅设计）

本节冻结 D3/D4 契约并记录其分阶段实现状态。D3 已实现受宿主显式装配的策略调用与正式 Memory/v2 写入；D4 的动态 Character 授权尚未实现。旧 `MemoryDecisionAuthority.issue(accepted=...)` 保留为 Memory/v1 兼容路径，不构成正式 Memory/v2 授权。D4 当前检索仍只遍历 `CognitionContext` 捕获的 `Character.memory_ids`，没有动态授权索引；不得据此声称 D4 已满足。

### D3 — 正式 MemoryDecision/v1

- **安装与策略所有者：** 策略由宿主显式注入，具备非空 `policy_id` 与 `policy_version`，不得从 Proposal、模型输出、Memory 内容或待恢复文件动态加载。当前 Engine 检查依赖、策略接口/身份及闭合输出 schema，但没有策略版本注册表；宿主负责选择受支持的实现。未安装策略、依赖缺失、策略异常或输出结构无效，不产生可写 accepted 决定。该框架不是默认的 NPC 自主巩固策略。
- **职责与授权：** 调用方/模型只能提供 `MemoryProposal`。Engine 将受限输入交给已安装策略；Authority 仅能封装与该次已安装策略调用绑定的类型化结果，不能接受任意调用方自报的 accepted 布尔值。Python 同进程对象能力只约束受支持调用路径，不防御拥有任意代码执行权的恶意同进程代码。`accepted` 是进入写入流程的必要条件而非写权限；Factory 和 Persistence 仍须独立校验。
- **有限输入（当前实现与冻结目标分开）：** 当前 `MemoryDecisionInput/v1` 包含 owner、memory_type、Proposal 身份/schema/摘要、有界规范 JSON content、source Event ID 集合及 `event_history_reference_present` 状态、Timeline/session/generation、逻辑记录与前序及输入摘要。metadata 受规范摘要约束，但不是任意 Store 视图。Agent/Character 身份对、访问范围及 grant 属于下述未落地 D4 扩展；策略 ID/版本由宿主安装并在决定/provenance 中绑定，不是当前 Input 的字段。决策阶段的 Event 存在检查不等于最终 Persistence 的完整验签。不得默认传入全部认知 Store 或其他 Agent 数据；外部披露仍需宿主明确授权。
- **决定结构与结果：** 当前决定绑定 Proposal、owner、来源、策略身份/版本、原始 Runtime 上下文和调用结果。实际 `MemoryPolicyOutput/v1` 仅有受支持三态结果、有限 importance、受限 reason_code 和 schema_version；没有 Character grant。accepted 的正式 provenance 绑定唯一调用 ID 及输入/Proposal 摘要，rejected/deferred 不生成可持久化的 accepted provenance。Character 与 grant 的扩展仍待 D4；metadata、自由文本和策略版本字符串本身均不是授权。Engine 检查宿主策略身份/版本非空，不提供通用策略版本注册/协商器。
- **状态语义：** rejected 与 deferred 不写 MemoryStore；本阶段不另建决定/待办 Store，因此它们仅是本次调用的非持久结果。deferred 不自动重试、不自动升级；宿主若以后重新审议，须显式提交当前 Proposal 并重新执行策略。只有 accepted 的规范 Memory 才进入后续检索。若要求跨重启审计所有拒绝/延后决定，须另行批准持久审计需求，本契约不隐含此能力。
- **最终提交与幂等：** 当前 Factory/Persistence 在最终栅栏内复核原始 permit、决定与 Proposal 绑定、owner、来源和规范 EventHistory/修订谱系，提交正式 Memory/v2 + `MemoryDecisionProvenance/v2`；Character grant 校验是 D4 目标，当前没有该授权字段或动态 grant 写入。完全相同的提交重试幂等；同一 revision ID 异内容/授权冲突拒绝；新修订使用新 ID 与明确前序。Provenance/v1 是前一数据兼容阶段保留的形状，不能称为当前正式签发版本。详见上方兼容矩阵；两种 provenance 都不是独立写许可，快照签名也不证明策略语义正确。

### D4 — 动态、owner/Character 限定检索

- **规范授权：** 新正式 Memory 记录携带类型化 `MemoryCharacterGrant/v1` 关联（owner、Character ID、grant/schema 身份），属于 Memory 规范记录的一部分，而非 metadata 或单独授权 Store。授权须由 D3 策略结果明确批准；最终 Persistence 以当前 Runtime 的受信 Agent/Character 清单复核 owner 与 Character。当前 RuntimeRegistry 表达每个 Agent 一个 Character 身份；本契约首版只支持同一 owner 的受注册 Character，不定义跨 owner 分享或一 Agent 多 Character，超出该模型时必须拒绝，待未来明确扩展清单契约。
- **检索身份：** AgentTurn 从当前 Runtime Registry、当前 Character 身份、owner、活动 Timeline/EventHistory 和当前写入代次构造受信检索主体。查询文本、owner 字符串或调用方提供的 ID 列表不构成授权。检索候选来自 `(owner_id, character_id)` 的派生索引并与旧 `Character.memory_ids` 显式引用合并；不扫描 owner 的全部 Memory 作为 Character 候选。每个候选都要从规范 Store 重读，并核验 owner、schema、语义记录类型、有效授权、来源 Event 在当前已验证历史/祖先中的存在以及当前修订资格；读取在与规范写入兼容的快照同步范围内完成。索引只用于定位，不是授权来源。
- **系统记录隔离：** L1 消费证明属于 system-only 证据，不得进入 Character 语义 Memory 视图，即使 Character ID 列表显式引用其记录 ID。证明 payload 通过类型化 system-only 标记分类；已知系统记录类型与 payload 不一致时也不可检索，未知的 system-only payload 标记不会被降级为普通 Memory。普通 Memory 检索不验证或展示证明为社会经历，也不授权 Belief、Goal 或 WorldState 写入。规范 MemoryStore、L1 验证器及快照仍保留其内部读取和验证能力。
- **索引生命周期：** 索引完全由已验证的规范 Memory 记录与受信 Agent/Character 清单派生，不独立持久化。新增/修订 Memory 时，规范记录与索引更新/失效须在同一个写入栅栏提交区间内完成；无法同步时标记索引不可用并拒绝动态检索，或在同一快照边界内从规范记录重建，不能返回过期结果。恢复时先逐条验证 Memory、owner、授权关联、来源和谱系，再于隔离 Store 重建索引；直到 RestoreCoordinator 发布后才可供新 Runtime 使用。
- **旧数据与时间线：** 旧 Memory 及旧快照保留原义。既有 `Character.memory_ids` 仍是显式的 legacy 引用授权，只适用于原记录并继续经过 owner、来源、类型和当前历史核验；不迁移成新 grant。无授权关联的新旧记录不因 owner 相同而获得动态访问。子线只继承经验证祖先中已有的记录及其原始 grant；父线分叉后缀不进入子线，子线新增/撤销/修订不反写父线。来源资格从已验证 EventHistory 谱系判断，不用恢复时的当前 WorldState 重解释历史可见性。

### D3/D4 事务与快照版本

以下联合事务描述保留 D4 的目标约束；其中 Registry grant、动态授权关联及派生授权索引尚未实现。当前 D3 写入范围以 Phase 2/3 和上方兼容矩阵为准，不得把本段规划当作已运行的 grant/index 事务。

写路径顺序为：受信策略对有界输入决策 → Authority 封装绑定结果 → Factory 生成请求 → 在最终栅栏内复核原始许可、来源、Registry grant 和冲突 → MemoryStore 提交规范记录并原子更新/使派生索引失效。失败不得留下可检索的索引项。读路径在一致性读取边界内取得当前授权主体与派生候选，逐条重验规范记录。快照捕获继续复用 `RuntimeWriteFence.snapshot_scope()` 和 Registry 清单快照；因此只会捕获提交前或完整提交后的 Memory，不接受“记录已写但授权索引仍显示旧状态”的中间结果。恢复及分叉继续走签名 Bundle、隔离重建及 RestoreCoordinator，不补签旧记录。

**Stage 2.1 Phase 1 历史状态（仅数据兼容；不是当前正式写入版本）：** `Memory/v1` 继续按原七字段规范编码；旧解码结果保持 `schema_version=1`，不补 provenance 或修订引用。`Memory/v2` 增加 `MemoryDecisionProvenance/v1`、`logical_record_id` 和可选 `supersedes_record_id`；`Memory.id` 是不可变版本记录身份，`logical_record_id` 标识其逻辑记录，前序引用指向另一条版本记录。v3 快照要求前序记录存在于同一快照，且 owner 与逻辑身份一致，并拒绝循环或跨记录链；不推断 v1 记录的逻辑身份。provenance 的类型化字段及 source Event 引用/验证状态进入快照摘要与签名；这只证明快照绑定了这些数据，不证明策略确实运行或结果有授权效力，也不是写入许可。D3 仍须通过受信策略、Authority、Factory、Persistence 和 RuntimeWriteFence 验证。`CognitiveStateSnapshot/v2` 仍以旧字段编码及 v2 purpose 验签，且只接受 Memory/v1；新捕获使用 v3 schema 与独立 v3 purpose，v3 对 Memory/v2 的所有字段执行 allowlist 编码、摘要和签名覆盖。隔离重建不会补签、运行策略或推导缺失凭据。SnapshotBundle v2 的组件集合、清单和 purpose 未改变，仍通过精确认知组件摘要绑定 v3；验证器实际解码并验证内部认知 schema，未知版本失败关闭。此阶段不实现 D3 决策、正式写入或 D4 授权检索。
**Stage 2.1 Phase 1 兼容摘要（保留原语义；当前矩阵见上）：** `Memory/v1` 继续按原七字段规范编码；旧解码结果保持 `schema_version=1`，不补 provenance 或修订引用。`Memory/v2` 增加类型化决策 provenance、`logical_record_id` 和可选 `supersedes_record_id`；`Memory.id` 是不可变版本记录身份，`logical_record_id` 标识其逻辑记录，前序引用指向另一条版本记录。v3 快照要求前序记录存在于同一快照，且 owner 与逻辑身份一致，并拒绝循环或跨记录链；不推断 v1 记录的逻辑身份。provenance 的类型化字段及 source Event 引用/验证状态进入快照摘要与签名；这只证明快照绑定了这些数据，不证明策略确实运行或结果有授权效力，也不是写入许可。`CognitiveStateSnapshot/v2` 仍以旧字段编码及 v2 purpose 验签，且只接受 Memory/v1；新捕获使用 v3 schema 与独立 v3 purpose。SnapshotBundle v2 的组件集合、清单和 purpose 未改变，仍通过精确认知组件摘要绑定 v3；验证器实际解码并验证内部认知 schema，未知版本失败关闭。隔离重建不会补签、运行策略或推导缺失凭据。

**Stage 2.1 Phase 2 状态（D3 正式 MemoryDecision 授权）：** 宿主必须显式构造 `MemoryDecisionEngine` 并注入策略、`MemoryDecisionAuthority`、EventHistory 与当前 `RuntimeWriteFence`；没有策略/边界时拒绝决策。Engine 只向策略提供有界规范 JSON Proposal 投影、owner、来源 Event、Timeline、原 Session/Restore Generation 和修订身份。输入摘要在构造与 Authority 签发时复核；输出必须是受支持的 `MemoryPolicyOutput/v1` 三态类型。策略异常、非法输出、Proposal 变更及不匹配上下文均失败关闭。`accepted` 由 Authority 绑定到本次调用身份和策略版本；`rejected`/`deferred` 不进入 Store。

正式写入经 Factory 与 MemoryPersistence 形成 Memory/v2，并携带 `MemoryDecisionProvenance/v2`（包括 accepted 结果、调用 ID、策略 ID/版本、Proposal/输入摘要、owner、来源和原运行代次）。MemoryPersistence 在最终 fence 区间复核原始许可、Event 存在及 Timeline；MemoryStore 低层 v2 提交要求来自 Persistence 的请求和授权边界，拒绝仅凭数据类/provenance 自提交。相同请求重试幂等；同一 revision ID 的不同内容或授权冲突拒绝；新修订使用新 ID 和明确前序。旧 `Authority.issue(accepted=True)` 只保留 v1 兼容行为，不能签发正式 v2 provenance。Memory/v1 的历史解释和写入兼容不变。

该契约是 Python 进程内受支持调用路径的授权边界，不防御拥有任意同进程代码执行能力者。Snapshot v3 可编码并签名绑定新增 provenance 类型，但恢复只验证签名/结构/来源，不重新运行策略，也不能仅凭快照证明策略语义正确。D3.1 不含跨 Timeline 修订谱系能力；该能力由下述 D3.2 增补，不表示已实现 D4 Character 动态授权、社会经历归因或拒绝/延后决定的持久审计。

**Stage 2.1 Phase 3 状态（D3.2 分支局部修订）：** `MemoryRevisionLineage` 是运行时临时验证上下文，不是新 Store 或持久化组件。当前 Timeline 的新修订必须带有匹配的 Memory/v2 provenance Timeline；继承修订必须与精确签名 Bundle 中认知快照的规范 Memory 编码逐字节一致。SaveManager 递归验证被保留的父检查点 Bundle、快照和 EventHistory 后，才为分支建立该视图。Snapshot v3 的正常校验、隔离重建、SaveManager 加载/暂存恢复与最终 MemoryStore 写入使用同一修订图规则：owner/逻辑记录分组内要求唯一根、无缺失前序、无循环、单后继和唯一链 tip。父、兄弟 Timeline 的分叉后缀不在当前可见集合内；两个子 Timeline 可独立从同一祖先修订产生不同后继。缺少 Bundle、祖先认知快照或完整谱系时失败关闭。Memory/v1、Memory/v2、Snapshot v2/v3 编码与签名用途及 Bundle v2 清单语义不变；快照签名绑定内容，不单独证明修订谱系，恢复不重跑策略或补造来源。该契约不提供跨主机协调、断电级事务或任意恶意同进程代码隔离保证。

**D3.2.3.3 正式 Memory/v2 的规范 EventHistory 边界：** Runtime 装配将其规范 `EventHistory` 对象、Timeline、codec 和 trust 绑定到当前 `RuntimeWriteFence`。最终 `MemoryPersistence.save()` 在同一提交栅栏内先复核原始 permit 与 `MemoryRevisionLineage` 的 Timeline/Fork 结构绑定，再要求候选历史与 Fence 绑定的规范历史为同一对象，并用该绑定的 codec/trust 验证完整的本地签名链及分支父历史；来源 Event ID 还必须出现在完整验证返回的 Event 集合中。仅有相同 Timeline ID、相同信任根、独立历史的有效签名或 Lineage 结构匹配，均不足以取得该 Runtime 的正式写入资格。非规范历史在身份检查处失败关闭；对它单独调用 `verify_persisted_lineage()` 仍可检验其自身的谱系缺陷。此约束是进程内正式写入边界，不改变持久化编码、签名用途或 Memory/v1 兼容路径，也不关闭独立的时间线祖先校验盲区。

**D3.2.1 分支继承边界修正：** MemoryStore 的 Memory/v1 最终提交现在在同一 RuntimeWriteFence 提交范围内执行不可变身份冲突检查，并对已绑定分支视图重新验证候选记录；同 ID 精确重试幂等，同 ID 异内容拒绝，因此 v1 兼容路径不能覆写签名祖先检查点中继承的记录。由 `SnapshotBundleManifest.verify_and_stage()` 产生的 `VerifiedSnapshotBundle` 另携带仅运行时的精确清单摘要绑定；分叉清单验证及 `MemoryRevisionLineage.fork_from_verified_bundle()` 要求该摘要与传入签名清单完全一致。此运行时凭据不进入持久化编码，也不改变 Bundle v2 或任何快照签名用途。**时间线祖先校验仍列为显式技术债**：当前修正只覆盖本次审计的 v1 覆写和已验证 Bundle/清单交叉配对；在祖先包含证明、所有写入路径不可变性以及递归恢复验证均有完整端到端证据前，不宣称该债务整体关闭。

**Stage 2.0.1 已关闭的边界：** `CognitionContext.get_memories()`、`get_relevant_memories()`、`MemoryRetriever` 和 `MemorySnapshot.from_memory()` 现在共用 MemoryStore 的语义可检索性判定。言语与非言语 L1 证明以类型化 system-only payload 分类，显式 Character ID 不会使其进入语义视图；不匹配的已知系统记录类型和未知的 system-only payload 也失败关闭。快照保留规范证明记录并按原验证规则恢复；Runtime 重建将 Character 链接与实际语义可见子集比较。此修改不实现 D3/D4。现有 RuntimeRegistry 仍只提供 Agent→单一 Character 映射，不支持跨 owner 分享或多 Character 授权。

### D4 revision and revocation resolution

授权绑定到精确的不可变 Memory revision。每个 revision 具有稳定的逻辑记录 ID、唯一 revision ID 和可选的 `supersedes_record_id`；创建新 revision 不覆盖旧记录。检索只考虑当前 Timeline 上从已验证祖先延伸出的有效 revision 链末端。经 D3 接受的撤销 revision 不含有效 Character grant，因此撤销后不再可检索；更换授权也必须通过新 revision。循环、缺失前序、同一时间线多条互相冲突的链末端、owner/来源不一致或无法确定当前末端时，对该逻辑记录失败关闭，不猜测最新项。父子 Timeline 各自解析自己的有效末端，子线修订不改变父线结果。该 revision 关系属于实现 D4 所需的最小身份/生命周期契约，不代表本轮实现 D5 的社会经历比较。


## Social experience v1 and Goal creation

`SocialExperience/v1` is a closed frozen payload, held only by formal Memory/v2 with type `attributed_social_experience_v1`. Fields are `version`, `experience_id`, `owner_id`, `character_id`, `speaker_id`, `claim_digest`, `speech_memory_id`, `evidence_memory_id`, `subject_ref`, `property_ref`, `value_type`, `claimed_value`, `observed_value`, `evidence_event_tick` and `comparison`. Unknown versions, foreign owners, unsupported/mismatched wrappers, absent proof records and changed bindings reject. The initial comparison results are `supported` and `contradicted`; unsupported, missing or temporally incomparable evidence produces no new experience.

Both referenced canonical system records are independently verified: the addressed-utterance v1 proof and an existing registered nonverbal v1 proof. Comparison requires a signed AttributedClaim for that recipient, exact subject/predicate/value-type compatibility, `valid_from_tick == valid_through_tick == evidence Event tick`, and `scope_ref == "event:" + evidence source Event ID`. This scope denotes that exact Event's fact, not the entire tick or an interval; unrelated later state does not reinterpret it. No natural-language mapping, current-world truth lookup, B2 result-rule expansion or general D6 interval inference is introduced.

The experience ID is `social:` plus SHA-256 of compact UTF-8 JSON `[1, creation Timeline, owner, Character, claim digest, speech Memory ID, evidence Memory ID]`. The canonical record ID and logical ID are `memory:` plus that experience ID. Superseding these records is unsupported in v1. Repeated review reuses the same verified record, including inherited ancestor records; child review of the same proof pair must not create another experience. A different evidence set is a distinct bounded assessment, not an overwrite or a global speaker reputation.

MemoryProposal → installed MemoryDecision policy → MemoryWriteFactory → MemoryPersistence → MemoryStore remains the write path. Final persistence and snapshot reconstruction verify the referenced proofs and bindings. The explicit Character grant resides in the verified payload, not metadata. `with_social_memory_grants` derives only same-owner/same-Character verified grants into a newly assembled Character/context; it does not mutate frozen contexts or authorize all owner Memories. Legacy explicit links remain compatible; proof records remain system-only. Snapshot manifests additionally check the experience Character against the registered owner. Generic Memory/v2 policy authorization does not itself prove a social comparison.

The codec explicitly registers only the new payload type. Existing Goal fields, Memory/v1/v2 schemas, supported cognition snapshot envelopes and Bundle v2 signing purposes remain unchanged. Old records are not migrated, re-signed or supplemented with inferred experience. Readers lacking the new closed type reject a checkpoint containing it; supported older checkpoints retain their original meaning.

`GoalCreationProposal` is a transient separate candidate; existing `GoalUpdateProposal` still only updates status/priority. Creation requires bounded description/priority, explicit authorized source references, matching owner, a sealed CognitiveUpdateValidator result and the exact Runtime origin. CognitiveUpdateApplier and GoalStore.create recheck the exact proposal and immutable identity. The social entry accepts only verified Character-authorized experience IDs selected by an explicit host policy. It registers the new Goal link on the canonical Agent under the same fence and Registry lock; publication failure freezes protected writes/checkpoint capture rather than pretending cross-Store rollback. The next context must rebuild Goal links from that Registry. Transient SituationGoal now retains the existing Goal status so a content policy can decline completed/abandoned goals. Description revision, general autonomous goal invention and historical policy-execution attestations are not supplied.

Memory publication uncertainty likewise enters existing recovery-required protection. Canonical in-memory commit is not checkpoint durability; only a verified published checkpoint supplies that guarantee. Recovery revalidates existing records, does not rerun the original action, and does not re-sign consumption. See [scope and runnable composition](SOCIAL_CAUSAL_DESIGN.md#social-physical-room-slice).


## Owner specific room policy

RoomSocialPolicy/v2 uses the existing Personality.preferences entry `act_on_verified_testimony` only as an owner-local content preference for proposing a new Goal. A true value permits the configured opportunity; false or absent does not. It does not authorize information, establish truth, diagnose irrationality or alter comparison results. Root content explicitly initializes the preference; restore reads the saved canonical Personality. Legacy missing preferences are not inferred from host flags, and existing Goals are not rewritten. Memory/v2 retains the policy ID/version that actually issued each record; no v1 experience/proof or historical policy record is upgraded.

RecipientDefinition is transient content-host configuration for additional recipients, their initial preference, sight capability and prior Belief value. It is not a new persistence codec type or Runtime installation protocol. The strict assembler checks the saved roster against explicitly supplied content IDs and restores cognition from the verified snapshot. Actor/object identity collisions in this configuration reject before world construction.

RoomAssessment is a read-only host diagnostic, not a Gateway/Presentation DTO or cognitive authority. It reports a consumed speech's source Event, supported/contradicted comparison and linked active Goal IDs. Without a qualifying comparison it distinguishes insufficient evidence from `awaiting_review` when a verified proof pair exists but no accepted experience has been committed; ambiguous multiple matches are unresolved. Before an eligible speech consumption proof exists, no assessment is emitted. The diagnostic cannot reconstruct a missing audit of rejected versus deferred policy decisions. It reuses the existing verifier without creating Percepts, receipts, proofs, Memories or Events. Query it between bounded host rounds; no new concurrent-read transaction guarantee is claimed. It must not be forwarded as NPC private cognition to player chat.


## Consumed result Goal completion

`GoalCompletionCondition` version 1 uses the existing Goal.metadata value under `cognitive_world.goal_completion`. Its exact closed keys are version, target_ref, fact_type, predicate, subject_ref and expected_value. For this legacy condition, version must be integer 1; references are nonempty bounded strings; target_ref uses the existing InteractionReference parser; expected_value is a finite scalar with exact type equality (bool is not int). Unknown fields/versions and malformed definitions reject at governed creation. There is no expression evaluator, script, free-text projection or inferred threshold. Existing Goal status/priority updates cannot add or replace this condition. Existing Goal IDs, codec types, snapshot envelopes, Bundle v2, signature payloads and historical proofs do not change; no condition is inferred for older Goals.

`ConsumedResultGoalCompletion` is a transient, explicitly installed AgentTurn adapter, currently used by social_room with canonical signed history. It reuses B3 record verification over the canonical MemoryStore and current verified lineage, then, for actor-action conditions, binds the result to the same owner, registered Goal link, final Attempt goal_id and exact target. A trusted processing fact must uniquely match the declared type/predicate/subject; its value must satisfy the condition. The matching authorized Observation must have actually passed this owner's ordinary L1 with a live receipt and Percept. This check neither issues nor upgrades a B2 consumption proof.

The transient review outcome distinguishes uncommitted/unresolved result, unbound Goal, action failure, awaiting consumption, successful-but-unmet condition, governance refusal, completion and duplicate completion. It is an internal diagnostic, not a player DTO, persistent fact or new public process() return type. Complete proposals retain priority/description/resource demands; source_refs retain prior sources plus the canonical result Event, and proposal evidence_refs name the actual consumed Observation and Event. No extra Event is emitted to represent a cognitive Goal update.

GoalUpdateProposal, the existing validator, applier and fenced GoalStore remain the write path. A duplicate result that already completed this Goal is a no-op. An uncertain application marks the existing Runtime recovery-required flag and prevents checkpoint capture rather than claiming rollback or replaying the action. Only a published checkpoint makes the resulting cognition durable. Restore verifies saved state and historical B3 records, never re-signs ancestor evidence or reconsumes missing history. A pre-completion checkpoint without recoverable consumption evidence cannot invent completion. This slice adds no separately signed completion-policy audit or resume protocol. See [architecture](ARCHITECTURE.md#consumed-result-goal-completion-slice).


## JSON object content v2 and appearance v1

`parse_generation_proposal` supports exact root versions 1 and 2. Existing v1 fields/default behavior and the current LLM generator's v1 request remain unchanged. V2 requires the additional root `objects` array, additional `objects` arrays on scenarios and `key_ref` on each mechanism (null for unused references; passage cannot have a key). All other original required fields remain required. Existing size/depth/node limits, duplicate-field rejection, strict identifiers, P0 content validation and unknown-field/version/mechanism rejection apply. No open JSON attributes/state map is accepted.

Each object template has exactly `template_id`, `description`, `kind` and `appearance`. Kind is object or tool. Appearance is ObjectAppearance/v1 with exactly `version`, `shape`, `detail`, `visible`, `detail_visible`: integer version 1; shape small/box/flat; detail notched/striped/plain; exact boolean visibility flags. These are bounded authored visual features, not inferred physical capabilities or a material model. Description remains content-validation input and is not copied into visible facts. The canonical Entity reserves attributes.appearance for the exact typed record; an arbitrary mapping at that key has no observation eligibility.

Scenario object placements are four-element arrays `[local_key, object_template_id, location_ref, owner_ref]`. Location is `location:<local-location-key>` or `actor:<local-character-key>`; owner is null or `actor:<local-character-key>`. References must resolve in the same scenario. Object keys are unique and cannot collide with location/character keys. Runtime object identity is `<world>:<instance>:object:<local-key>`; actors and locations use their existing namespaces. A door key_ref names a placed local object whose template kind is tool. Missing owners/templates/keys, duplicate identities and cross-collection runtime collisions reject before installation. Placement under an actor and legal ownership are separate checks. Existing side-branch value_refs semantics are not expanded into arbitrary object relationships.

`object_observed` is a controlled SystemEvent with exactly one change `{entity_id, observer_id, precision}` and participants `[observer_id]`; precision is coarse or detail. Its handler reads canonical typed appearance and returns an empty environment update, never an Entity mutation. The read-only `EventHandler.observable_facts_with_world_state` hook defaults to the original hook for existing handlers. Supported facts are object_appearance/object_shape and object_appearance/object_detail, with scalar closed values and exact subject/location bindings. EventProcessor captures only the necessary typed appearance, location, matched holder and known-light conditions in signed processing evidence, with existing AFTER_WORLD_UPDATE sampling semantics. No historical evidence is migrated.

Authorization checks original event-time observer position/sight, target binding, visibility and light. Detail additionally needs matched actual object location/ownership and detail_visible; a requested precision is not a grant. A room-shared object alone is insufficient evidence of inspection reach. Valid coarse fallback is allowed, otherwise no fact is delivered. Observation generation and Presentation independently retain their existing provenance/receipt gates; without a real authorized Observation, event evidence alone does not render a message. No new B2 historical rule or consumption proof is issued for these visual facts.

ObjectAppearance is explicitly registered in the existing closed core persistence codec; unsupported versions/types reject. Entity, WorldState, installation-batch fields, cognition snapshot envelopes, Event attestations and outer Bundle v2 are unchanged. Updated readers retain old saves; readers without this registered type reject saves containing it. SaveManager tests preserve installed identity/owner/location, formal door state, exact Event attestations and state-slot origins in a child Timeline without replay. Runtime session permits and generation remain transient. Existing partial-install/checkpoint recovery limitations are not upgraded.

The developer entry `py -3.14 run_json_objects.py examples/data/json_objects.json --scenario visit` loads the actual JSON through the content pipeline and executes authorized coarse/detail observations plus the installed door method. Its host explicitly initializes lit rooms before processing; it is not a lighting-generation or player-input contract. JSON and host policies cannot manufacture a successful action. [Architecture](ARCHITECTURE.md#json-objects-and-bounded-visual-projection-implemented-narrow-slice).


## Position observation contracts v1 and JSON v3

Content schema v3 retains all v2 fields and adds the required nullable `observation_zone` field to each location template and required nullable `observation_policy` to each object template. V1/v2 input keeps its previous exact schemas and defaults. A zone object has exactly version=1, frame_id and offset_m; in JSON frame_id references a scenario-local location key acting as the observation-domain anchor. A range policy has exactly version=1, coarse_distance_m, detail_distance_m and detail_observers, the latter a bounded unique array of placed local character keys. Validation rejects missing frames/recipients, unsupported fields/versions and malformed numbers before installation. No runtime ID, script or inferred prose relationship is accepted as a local reference.

Installed ObservationZone/v1 resolves frame_id to the anchor's canonical location identity; installed ObservationRangePolicy/v1 resolves recipients to canonical Agent IDs. Offset and distance units are meters. Supported coordinates and limits are finite numeric values of absolute magnitude at most 1,000,000; booleans are not numbers. Limits must satisfy 0 <= detail_distance_m <= coarse_distance_m, with inclusive eligibility boundaries. This magnitude bound is an implementation validity bound, not a calibrated visual threshold. Values come from validated content, not scattered entity-specific constants. Two existing projection categories remain supported: shape and detail; this is not a generic extensible level table.

Canonical location Entity.attributes.observation_zone and object Entity.attributes.observation_policy accept only their exact typed records at the projection boundary. The input template's local references are not world authority until the existing instantiator validates and resolves them. The codec explicitly allowlists these two new versioned records. Entity/WorldState fields, ObjectAppearance/v1, historical Event payloads, cognition snapshots and Bundle v2 retain their existing schemas. Old saves without these values keep legacy carried-object semantics; readers lacking the new types fail closed on new saves. No historical records are rewritten or re-signed.

The existing object_observed request remains `{entity_id, observer_id, precision}` with its exact recipient. For a configured range policy the producer records the actual target and observer locations, zone frames/offsets, known light at both nodes, applicable limits and an independently derived detail-authorized boolean in current processing evidence. Observation authorization recomputes precision from that captured evidence, not current WorldState or a caller's claimed distance. Missing or mismatched zones, different domains and invalid parameters cannot become zero distance or legacy permission. Without a range policy, the original carried-object rule remains in effect.

Within one supported domain, d=abs(observer_offset_m-target_offset_m). A visible, sighted, lit observation can disclose shape only when d <= coarse_distance_m. Detail additionally needs the explicitly authorized receiver, requested detail, detail_visible and d <= detail_distance_m. Otherwise valid coarse evidence may be returned; outside coarse eligibility no fact is delivered. Threshold eligibility never overrides disclosure permission. The same shared rule is used before typed fact creation and at VisibilityPolicy/Observation issuance. Presentation still validates the actual owner Observation and its original facts; it receives no coordinate, grant list, attributes map or private cognition.

Signed save/restore preserves the canonical zone/policy values and actual actor location. The tested child restore verifies exact ancestor Event attestations without calling the Event attestation issuer, starts with no reconstructed ObservationStore entries, then issues a fresh authorized observation from restored state. An old far observation remains far evidence even after movement; neither retrieval nor presentation retry upgrades it or repeats the committed movement. This adds no durable task, geometry journal, B2 visual-consumption rule or stronger checkpoint recovery guarantee. [Scope](ARCHITECTURE.md#position-driven-observation-precision-bounded-implementation).

## Independent reach contract and feedback compatibility boundary

GoalCompletionCondition/v2 adds exactly completion_kind to the v1 keys; supported values are state and actor_action. V2 target_ref must identify the exact subject_ref. State conditions accept only environment_state facts: a canonical committed Event and its trusted unique matching fact, exact typed value, authorized owner Observation and actual qualified owner L1 receipt are required. A Resolution failure cannot satisfy it. The fact must be the latest matching canonical processing projection in EventHistory order (ticks can tie); valid older historical intake does not establish a current state. A later projection, even of the same value, conservatively defers older evidence until the owner consumes an applicable current projection. This is bounded typed-projection semantics, not a general mapping from arbitrary state slots to facts. Completion still uses GoalUpdateProposal, CognitiveUpdateValidator, CognitiveUpdateApplier and RuntimeWriteFence. Delivery alone, missing consumption, uncommitted results or governance refusal cannot complete it. State completion needs no B3 association belonging to the producing actor. Actor-action retains the v1 B3 owner/Attempt/Goal/target checks. V1 encoding omits completion_kind and keeps its previous interpretation; legacy no-condition Goals remain unresolved. No new Goal Store, completion ledger, proof or snapshot envelope is added. Existing saved completed state is restored, not re-derived from unavailable live receipts.

Generation-proposal JSON v4 retains v3 fields and adds two required nullable fields on each mechanism: interaction_policy and appearance_ref. Only the installed door adapter accepts non-null values. appearance_ref names an existing ObjectTemplate definition, not a new placed object, and its recipient references must resolve within the scenario. The instantiator creates the mechanism's optional Entity representation with exactly the same canonical ID as its DoorState, with appearance, observation_policy and/or interaction_policy as exact typed reserved values. This is not an open attribute/component permission system. V1/v2/v3 schemas and defaults remain unchanged; unknown fields, versions and references reject.

InteractionRangePolicy/v1 has exactly version=1 and maximum_distance_m. The limit is a finite number in [0, 1000000] metres; bool is rejected. Its codec type is explicitly allowlisted and round-trips without changing Bundle v2 or DoorState. Older readers lacking the new type fail closed; existing historical records are not migrated or re-signed. The physical reader reuses only canonical zone frames/offsets as coordinates, never ObservationRangePolicy thresholds or its disclosure grants. Same supported frame and abs(actor_offset-target_offset) <= maximum_distance_m permit reach; absent/mismatched zones are unknown. Legacy absent interaction_policy keeps exact co-location. Slot receipts bind actor location, mechanism policy/location and both coordinate records; EventProcessor revalidates them before commitment. A successful effect carries the actual actor location, not an invented target location.

For known out-of-reach conditions the existing generic confirmed-attempt-failure/v1 envelope carries the exact new condition interaction_out_of_reach and its read receipts. EventProcessor checks it against current canonical reach before append and alone issues action_result/interaction_out_of_reach=true. Its subject is the canonical target, location is the actor's actual position, and authorization requires the same committed Event/evidence, owner and captured event-time location/conditions. No bystander obtains the private result or unrelated facts. B1's exact locked-door result and historical B2 rule are unchanged; this result has ordinary L1 intake, not a new B2 durable proof.

**V1 compatibility boundary:** the original lock-only component still cannot represent consumed reach feedback, and its rejection regression remains intact. The explicitly versioned extension below uses the existing nonverbal proof capability instead of reinterpreting v1 or bypassing B2.


## Consumed physical failure feedback v2

The initial additional category is exactly action_result/interaction_out_of_reach=true, issued by EventProcessor after its configured-range checks. The trusted historical registry adds interaction-out-of-reach-owner-result/v1. It verifies the Resolution source/Attempt, original owner, exact fact, event-time position and context, and the complete set of actor/target/policy/coordinate slot-receipt bindings. The signed processing evidence attests the original reach check; restore does not evaluate the old failure using current geometry or turn fingerprints into invented geometry values.

Actual ordinary L1 remains mandatory. In the canonical signed Runtime, AgentTurn uses the existing RuntimeWriteFence commit scope across actual L1 acceptance, L1ConsumptionIssuer.issue_after_l1 and feedback publication. Only first qualified intake of a newly committed source can start this path. The existing NonverbalL1ConsumptionProof/v1 and system-only MemoryStore write authority provide persistent consumption evidence; no new proof payload, purpose, ID formula, B2 instance, cognition schema or Store is introduced. Proofs remain non-semantic system records. Live receipts are checked before issuance and are not serialized or treated as durable credentials. Within this supported fenced path the trusted clock cannot advance between acceptance and proof publication; B2's separate first-instance identity/time contract is unchanged.

BehaviorFeedback remains the single Runtime-owned history. A consumed row carries ConsumedFailureBinding/v1 with exactly version=1 and proof_id. Its existing owner/action/target/method/Event/tick/condition fields must match the referenced canonical signed proof and its exact historical source; conditions are actor_location and the typed failure category. Tick is the retained proof eligibility tick. The new snapshot root version is 2; every row explicitly declares record_version=1 (unchanged legacy fields/meaning) or 2 (those fields plus the closed consumption binding). Captures containing only legacy rows still emit the original v1 shape. V1 decoding is preserved, unknown versions/fields/types and duplicate/conflicting Event records reject. There is no fallback that drops an unsupported row or converts it to a v1 record.

SaveManager captures feedback and cognition under the same existing snapshot fence. SnapshotBundle v2 retains its component set, digest/signature meaning and outer version. Feedback capture and isolated Bundle verification resolve the proof against the canonical MemoryStore from the same verified cognition component, including signature, source/consumption Timeline ancestry, Observation identity/digest, fact and owner. A missing or mismatched proof rejects publication/restore; the feedback JSON or a matching Event alone is insufficient. Older readers without v2 feedback or the new historical rule fail closed. In-memory proof/feedback commitment is not durable until a checkpoint is published. Restore verifies bytes and rebuilds no L1 receipt, consumes no Observation and re-signs no historical evidence.

The existing bounded penalty/decay applies only to the exact owner, intent, target and method after consumed feedback publication. Target comparison uses the existing InteractionReference namespace/identifier, including equivalent bare object addresses; signed original target references are never rewritten. Intent/method strings remain exact: semantic paraphrase matching is not implemented. Applicability rechecks the original reach-condition slot receipts against canonical WorldState; movement, policy or coordinate changes can make the old penalty inapplicable while retaining the immutable historical row. This is an internal applicability fence, not information disclosure or new NPC knowledge. It does not consult visual-distance thresholds. Reach feedback does not add the legacy lock-frustration cue to unrelated candidates; legacy lock penalties remain available. Repeated consumption returns duplicate status without refreshing the proof, tick or penalty.

An existing source present at Runtime assembly with no applied feedback is conservatively ambiguous, even if ordinary historical L1 is allowed. A duplicate ordinary intake without the protected proof also cannot be promoted later. These candidates are deferred with transient structured CognitionState metadata, not guessed into feedback and not automatically frozen. This call's structured L1 source/history qualification gates every candidate, even when an old live receipt exists; temporarily unavailable historical verification defers without reinterpreting that receipt as current qualification. Restore never infers a missing feedback row from a proof alone. There is no automatic old-action replay or pending-result reconstruction. A stale operation is rejected before protected writes. A possibly partial L1 mutation or any failure during the new proof/feedback write sequence marks the existing recovery-required fence, preventing subsequent protected writes and checkpoint capture; recovery uses the last published checkpoint, not blind retries or rollback.

Limits: one configured door-reach result category, bounded one-dimensional geometry, the existing decay policy, checkpoint-only durability, and signed canonical Runtime assembly. This is not general physical-outcome learning, semantic Belief/Goal revision, B4, a journal, a shared coordinator or desktop/real-model acceptance.


## Physical state and transition contracts v1, JSON v5

**Implemented bounded contract.** The closed codec explicitly registers `PhysicalPropertyDefinition`, `PhysicalValue`, `PhysicalStateSet`, `PhysicalRelation`, `PhysicalCondition`, `PhysicalTransitionRule`, and `CandidateStateDelta`. It does not persist an engine, permit, host, or arbitrary plugin class. State/property/relation/rule versions accept exactly integer 1; unknown fields, types and versions reject. Embedded value/condition/delta meaning is supplied by the enclosing v1 contract. Encoding and decoding validate typed scalar constraints; cross-record validation runs during content preparation, formal application, checkpoint capture and verified WorldState restoration.

- `PhysicalPropertyDefinition`: version, name, value_type, unit, minimum, maximum. Boolean requires `unit=minimum=maximum=None` and exact bool values. Numeric requires finite int/float (not bool), unit from `1`, `kg`, `m`, `K`, `N`, finite optional ordered bounds and a value within them. These are supported declaration units, not implemented unit-conversion or dynamics models.
- `PhysicalValue`: definition and value. `PhysicalStateSet`: version, entity_id, properties (immutable tuple, at most 32, unique property names). Entity identity must match its canonical record key. A declared number cannot be used as the v1 boolean transition receiver.
- `PhysicalRelation`: version, source, target, kinds. The existing `(source,target)` key remains authoritative; kinds are a unique nonempty tuple from the five approved kinds. Endpoints must exist and differ. `part_of` has one parent and no cycles; `owned_by` has one owner and agrees with Entity.owner_id; `held_by` has one holder and agrees with the canonical location link. `attached_to` and `controls` are directed declarations with no implicit propagation or cardinality beyond the pair identity. They neither imply visibility nor change ownership.
- `PhysicalCondition`: entity_id, property_name, exact typed scalar value. `PhysicalTransitionRule`: version, rule_id, operation, receiver_id, property_name, expected, replacement, capability, conditions, relations. Conditions and required relations are immutable bounded tuples (at most 16 each). Expected/replacement are distinct bools. All referenced receiver properties, condition definitions and relation endpoints must resolve. Required relations may be absent in current state: that is a verified failed precondition, not permission to fabricate them. Rules are installed content, never executable scripts or model-issued authority.
Full-world validation checks every installed rule and the complete physical relation graph. Interaction-local validation reuses the same rule-dependency checks for the selected rule only; unrelated rules on its receiver or inputs do not expand the engine context or become dangling references merely because their dependencies are outside that context. The receiver and condition state sets, active rule declaration, capabilities, entry locations and required relation reads are the captured causal dependencies. Full-world validation is not removed from installation, formal application, checkpoint capture or restore.

- `CandidateStateDelta`: entity_id, expected, replacement. The pure engine returns it with a changed/rejected/unsupported outcome and bounded diagnostic evidence. It is not a write capability or an Observation. The Resolution effect `physical_state_transition_v1` binds actor, target, operation, rule ID, trusted tick, canonical leaf-slot read records and exact delta. The controlled Resolution/EventFactory source and EventProcessor rule/read revalidation are required before world mutation.

Generation-proposal JSON **v5** keeps v4 requirements and adds required nullable `physical_state` on ObjectTemplate plus `physical_relations` and `physical_rules` on ScenarioTemplate. A physical state has exactly version/properties; each property has definition/value. Boolean JSON definitions use exactly version/name/value_type (unit/bounds are canonically None); numeric definitions use all six definition fields above. Relations use source/target/kinds: the v5 enclosing schema fixes relation version 1. Rules are flat entries: target_ref plus all rule fields above. Conditions and relations use their closed shapes. The flat layout preserves the existing parser depth/node/size limits; large proposals remain rejected. Local `object:`, `actor:` and `location:` references resolve through the existing content instance identities, not runtime IDs supplied by JSON. Existing object placement remains the four-element list. See [the runnable JSON fixture](../examples/data/physical_assembly.json).

New failed v1 Boolean candidates carry the same captured dependency reads in the existing physical_effect_provenance metadata as read-only state_slot_reads entries. Each entry retains the existing 32-read limit, with at most four entries; v1 requires at most 119 reads (17 receiver/condition sets with three leaf fields, 16 required relations with four fields, and four entry slots). These entries are not PhysicalEffectProposal records, effects, confirmed_attempt_failure result facts or B2 consumption proofs. The generic pre-commit read guard already accepts and checks this envelope, including no-effect Resolution events. Relevant changed values or origins reject the pending current-result candidate before WorldState application or formal append; unchanged reads permit unrelated intervening work. A rejected candidate is not automatically evaluated again.

A committed failed event is historical evidence, not a request to revalidate that past failure against current state during restore. Existing signature and codec checks continue to verify its original payload. Legacy events without these bindings retain their existing compatibility meaning; no historical rewrite, re-signing or new historical-outcome submission API is added. The regression reopens a receiver after a failure, checkpoints it, and cold-restores both the newer state and unchanged signed failure history.

The transient installation plan carries relations; the unchanged WorldContentBatch is committed with typed relations in existing WorldUpdate metadata. Its signed update digest and changed relationship leaf slots bind the installation. No Event/Entity/WorldContentBatch persisted field set, signing purpose, WorldState checkpoint version or outer Bundle v2 format changes. Legacy v1–v4 JSON and records without the newly reserved physical entries retain their original decoding. Untyped values in those reserved entries are unsupported and fail closed; they are not inferred or migrated. Older readers missing new types fail closed on new content. Recovery verifies historical bytes without engine re-execution or re-signing. No ordinary L1, B2 proof or cognition semantics change. Idempotent Event delivery reuses committed processing evidence; it does not execute the transition twice. New physical outcomes have no new authorized fact projection in this slice, and developer diagnostics must not be routed as player-facing facts.


## Committed Boolean result Observation

This narrow extension uses the existing ObservableFact/Observation and processing-evidence envelopes, not a new persisted record or schema. For `physical_state_transition_v1` only, the already validated adapter projects exactly one changed Boolean property as `fact_type=action_result`, `predicate=boolean_transition_applied`, `value=(property_name, Boolean)`, `subject_ref=receiver_id`, with the actor's captured interaction location. It does not serialize the full delta, rules, dependencies or Entity attributes into the Observation.

Issuance requires the exact controlled Resolution Event and trusted processing evidence in the canonical EventHistory, and original actor identity and position in its event-time context. Only that registered actor receives this result; being nearby or having sight is not a separate grant. The existing VisibilityPolicy/ObservationGenerator implements this recipient rule; unrelated sensory facts gain no authority. Presentation has no new scope/composer mapping for this private result and remains default-deny. The output is evidence of that specific historical transition, not current omniscient state or automatic Belief truth.

Before formal append, a draft/candidate cannot yield an authorized Observation. Failed/unsupported/stale candidates have no success fact. Repeated dispatch under the original permitted operation reuses processing evidence without applying the transition again. Observation IDs remain exact Event/fact/owner-derived identities; ordinary L1 rechecks history on every delivery and deduplicates Percepts/receipts. No ordinary receipt substitutes for history qualification and no new B2 proof eligibility is introduced.

Verified restore keeps original signed fact bytes. Canonical restored local records have RECORDED status; inherited verified prefixes have no local delivery status. Exact recorded Event/evidence plus the existing persisted ancestor record permit explicit authorized historical delivery; this does not assert that UI delivery was restored. Ordinary L1 independently verifies signed lineage and authorized fact binding before intake. ObservationStore and process-local receipts remain transient; neither restoration nor delivery manufactures durable consumption. Missing context defers ingestion; foreign history fails qualification. No old record is rewritten, re-signed or upgraded with a new fact. Checkpoint-only durability and existing branch isolation remain unchanged.


## Typed contextual Belief decision view

`ContextualBeliefBinding/v1` is an ephemeral, issuer-sealed immutable decision view, not a persisted type. It binds the exact Belief snapshot, owner, target reference with namespace/identity matching, action type, method, location, evidence tick, Event/fact/Observation identities, canonical history Timeline context, typed fact selector/value and the `unchanged_history_frontier` scope. It is derived only when the current existing Belief content equals the existing five-field CognitiveReview Observation projection with exact field types, and existing source/Observation metadata agrees. Integer 1 is not Boolean true. Metadata or an old receipt alone is never authority.

Derivation holds the existing Runtime snapshot fence when bound and reuses L1HistoryContext's canonical-history verification and exact authorization fingerprint check, then verifies actual consumption with CognitiveRuntime.has_consumed_observation. The first slice requires a verified confirmed failure, one target, a Boolean result and the source Event at the current canonical history head. The captured decision tick must lie within the configured age. No historical signatures or rule meaning are reinterpreted. The binding is valid as of the newly assembled decision snapshot; it is not permission to reuse an old DecisionContext for a new operation. Final current-action authorization and EventProcessor checks remain mandatory.

`ContextualBeliefRule/v1` is a host-injected closed frozen configuration: exactly version, fact_type, predicate, value (Boolean), adjustment (finite [-1,1]) and max_age_ticks (integer [0,32], default 0). At most eight typed rules are accepted. Unknown versions, invalid parameters and conflicting/duplicate matches fail closed. Engine code defines safety and matching, not door/NPC identities or domain-specific outcomes. Configuration is absent by default and must be supplied by the trusted host after reconstruction; it is not model-generated authority or a new persisted policy.

Exact target namespace/identity, action type and method are required; this first matcher does not support tool-bearing candidates. One unambiguous eligible binding contributes adjustment multiplied by that Belief's existing confidence. Multiple matching Beliefs do not accumulate an ambiguous preference. The central AgentDecision path applies this factor after ordinary review and before the separate BehaviorFeedback adapter. Structured Observation-shaped judgments are not counted by the legacy lexical Belief-alignment factor, including unsupported contextual matches; free-text legacy Beliefs retain their existing heuristic behavior.

Belief changes still use CognitiveBeliefReview -> BeliefUpdateProposal -> CognitiveUpdateValidator -> CognitiveUpdateApplier -> existing BeliefStore. No binding, receipt or rule is serialized. Existing bounded JSON content and source metadata, cognition snapshot, codecs, signatures, B2 and Bundle versions remain unchanged. Restore preserves the governed Belief but creates no consumption receipt or matching view; missing evidence/receipt defers matching. Any new Event, changed physical conditions or expired age prevents the old binding from controlling a newly assembled decision. This deliberately conservative policy may omit useful old knowledge; selective dependency invalidation and durable contextual inference semantics remain future work.
