# CognitiveWorld — Execution and Final Submission

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Execution and final submission.

## Authority and scope

**Frozen authority level:** Domain architecture; cannot supersede operation contracts.

**Assigned responsibility:** Decision output to Attempt/Resolution/Factory/Processor, operation handlers, Runtime loop/fences.

Only marked Phase 3B/3C excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A09 — Adjudication authority and outcome separation**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A10 — EventFactory confirmation and live entry**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A11 — EventProcessor final validation and world application**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- Canonical world-record schemas and private cognitive state definitions.
- Sensory disclosure, player-facing presentation and subjective interpretation.
- Save formats, universal arbitration and cross-Store transaction guarantees.

## Migrated excerpts and pending section outline

Marked Phase 3B and Phase 3C sections contain only approved source excerpts. All other ranges remain pending. Original stage/status labels are not new capability or test claims.

### ID 2 — B3 execution expectation boundary

<a id="arch-source-2"></a>

<!-- phase3c-begin:C-2-4-17 -->

<a id="arch-source-2-part-1"></a>

**Phase 3C source excerpt:** ID 2, lines 4–17 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-2-4-17:4-17 -->

The [B3 contract](../DATA_CONTRACTS.md#b3-immutable-expectation-and-authoritative-result-association)
adds a selected-Attempt expectation frozen before Resolution and a separate
immutable association issued after canonical Event commit. Both use the existing
system MemoryStore, signed snapshots and Runtime fence; predictions remain
subjective. Event/association failures freeze writes/capture without replaying
world actions. Checkpoint-only durability and exact ancestor membership remain
required. B3 supplies neither actor knowledge nor B4 cognitive revision.
Its [trusted entry source](../DATA_CONTRACTS.md#trusted-action-expectation-source-binding-v1)
is signed before the final Attempt, whose existing fingerprint covers the
source ID/digest. Source-bound cognition uses v5; unbound historical B3 remains
ambiguous. No Runtime capability is serialized and no second Store is created.



<!-- phase3c-end:C-2-4-17 -->


### ID 16 — Pure calculation and effect ownership

<a id="arch-source-16"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 16, lines 204–208. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 204–208

<!-- phase3b-source:16:204-208 -->

Prefer explicit immutable inputs → candidate changes, assessments or uncertainty. Inputs include only necessary trusted state reads, request/Attempt identity, mechanism parameters/version, units and the relevant tick/state revision. With identical inputs and mechanism versions, deterministic Systems must reproduce their output. Inject any clock sample or seeded random sample explicitly; LLM/network calls, random draws, clocks, I/O, scheduling, persistence and commits remain separately bounded side effects. Capturing an input or producing a deterministic delta does not establish authorization or applicability.

Calculation cannot mutate canonical state, issue a permit or submit an Event. Validate mechanism applicability, evidence, hard constraints, affected slots and expected prior values at the existing adjudication/commit boundary; stale state requires fresh assessment or an unresolved outcome, never a replacement permit for an old result. Composed mechanisms must make ordering, read/write dependencies and incompatible deltas explicit; conflicting proposals cannot be silently resolved by last-writer-wins. No claim is made that current Systems/policies are all pure, or that a generic multi-component atomic update handler already exists.

### ID 21 — CPU governance and open unknown paths

<a id="arch-source-21"></a>

**Phase 3B migration:** selected direct-body ranges only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 21, lines 234–242. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 234–242

<!-- phase3b-source:21:234-242 -->

**严格限制不可能的结果，开放对未知可行路径的探索。** CPU governance includes retrieving known evidence, identifying missing conditions, preparing authorized model context, managing candidates and budgets, and deciding whether another query or candidate evaluation is worthwhile. Enforcing authority at commit does not require treating the installed mechanism vocabulary as a complete catalogue of possible reality.

| Evidence at the decision boundary | Required handling | Current implementation and remaining gap |
|---|---|---|
| A verified applicable hard constraint rules out the candidate, or authorization/P0 denies it | Reject that candidate/effect with the appropriate bounded reason. A P0 refusal creates no punishment, relationship change or NPC memory. | Existing authorization, Safety and typed causal checks remain binding. A subjective belief or speculative constraint is not a verified physical prohibition. |
| A path is not described by the installed model, but no verified constraint excludes it | It may enter a budgeted proposal, mechanism/condition review or alternative-path search; it cannot commit an unverified effect. | Optional effect suggestions can be translated only into already installed typed semantics. No general mechanism discovery/installation or recursive alternative-path planner is implemented. |
| Critical evidence is missing, conflicting or stale | Keep the gap explicit; query, ask, defer, lower optional exploration detail or finish unresolved according to scope and budget. | `AssessmentStatus.INSUFFICIENT_INFORMATION` and unconfirmed `ResolutionResult(outcome="unresolved")` exist. They do not establish impossibility. No-match, no-budget and no-answer remain different from confirmed failure. |

<!-- phase3c-begin:C-21-243-244 -->

<a id="arch-source-21-part-1"></a>

**Phase 3C source excerpt:** ID 21, lines 243–244 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-21-243-244:243-244 -->
The candidate-mode desktop interpreter currently selects only offered handles/methods. This is the capability boundary of the MVP adapter, not proof that every unoffered natural-language action is impossible. A future completion proposal must name its assumptions, evidence gaps and needed installed capability; CPU validation must reject invented authority, effect claims and unsupported execution. Reducing compute may end this attempt without declaring all alternatives infeasible. Failure diagnostics may preserve safe next information needs internally; Presentation must not invent a reason or expose private evidence.


<!-- phase3c-end:C-21-243-244 -->


### ID 51 — Open-ended Action Semantics (Approved Design; NPC Proposal Support Implemented)

<a id="arch-source-51"></a>

<!-- phase3c-begin:C-51-646-654 -->

<a id="arch-source-51-part-1"></a>

**Phase 3C source excerpt:** ID 51, lines 646–654 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-51-646-654:646-654 -->

Player and NPC behavior is not constrained to a fixed action enum. Natural-language interpretation should preserve the described behavior, intent, target, tools, method, conditions, and sequence as open-ended attempt data. This interpretation does not establish outcomes.

Player claims that an action succeeded, changed world state, or caused an NPC reaction are not facts. A novel method must not be rejected solely because it is absent from a predefined action category. A concrete, feasible method may affect the conditions Resolution evaluates; verbosity, rhetoric, or token count must not independently increase success.

Phase 12.4's NPC ActionCandidate retains open text intent, target, method, tools, preconditions, conditional steps, expected result, and uncertainties. The no-model fallback is intentionally a small deterministic baseline, not general open-ended language generation. An optional provider may propose varied methods; programmatic schema, owner, length, step, and candidate-count validation runs before evaluation. Provider output remains an untrusted proposal and cannot become a fact.

Multi-step plans are proposals, not pre-confirmed outcomes. Each step is evaluated against actual prior results; intermediate results may change or terminate later steps. Players control their own attempts; NPC cognition determines NPC responses; Resolution determines world outcomes. Players may attempt unreasonable actions, whose failure and consequences follow world rules rather than wording penalties.


<!-- phase3c-end:C-51-646-654 -->


### ID 53 — 3.4 Attempt

<a id="arch-source-53"></a>

<!-- phase3c-begin:C-53-668-682 -->

<a id="arch-source-53-part-1"></a>

**Phase 3C source excerpt:** ID 53, lines 668–682 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-53-668-682:668-682 -->

Attempt represents how the player tries to achieve the goal.

Example intent: Enter castle.

Possible attempts:

- Persuade guard
- Climb wall
- Steal key

Different attempts under the same intent may create different consequences.

---


<!-- phase3c-end:C-53-668-682 -->


### ID 59 — Runtime World Mutation

<a id="arch-source-59"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 59, lines 735–747. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 735–747

<!-- phase3b-source:59:735-747 -->

Runtime world changes must follow:

```text
Event
  ↓
WorldState Update
```

No runtime system may directly modify WorldState. Events are the only record of runtime world changes, and WorldState stores the resulting state after those changes.

The current code provides the `EventProcessor.process()` path: a registered `EventHandler` returns a `WorldUpdate`, the processor passes it to `WorldState.apply_event()` inside a short-lived, content-bound process-local capability scope, and successful processing may append the Event to `EventHistory`. Caller-supplied causal links can also be recorded; causes are not inferred. Direct `apply_event()` without that scope is rejected. Initialization `load_*` methods close when SimulationRuntime starts or before EventProcessor invokes the first handler. These are application-level misuse guards, not protection against malicious code in the same Python process; EventProcessor and SystemEventFactory remain trusted application composition boundaries.

### ID 66 — 5. Resolution System

Pending content migration. Frozen primary source identity: **66**.

### ID 67 — Resolution Engine

Pending content migration. Frozen primary source identity: **67**.

### ID 68 — Import and Dependency Direction

<a id="arch-source-68"></a>

**Phase 3B migration:** selected direct-body ranges only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 68, lines 839–869. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 839–869

<!-- phase3b-source:68:839-869 -->

Resolution is a lower-level adjudication boundary. It may validate the
`SimulationTime` value issued by the simulation clock, but it must not import
RuntimeContext, SimulationRuntime, Agent orchestration, or Decision policy as a
side effect of importing core Resolution result/engine types. Runtime issues
trusted clock values and invokes Resolution through explicit orchestration;
Resolution returns a bound result for EventFactory/EventProcessor and does not
call back into Runtime. Package `__init__` modules are public API facades and
must keep optional higher-level exports lazy when eager exports would reverse
this dependency direction. This changes import loading only; it does not
weaken trusted clock validation or the ActionProposal → Attempt → Resolution →
EventFactory → EventProcessor → WorldState authority chain.

The Resolution Engine produces a Resolution based on an Attempt, WorldState, rules, and context.

```text
Attempt
  ↓
Resolution Engine
  ↓
Resolution
```

The Resolution Engine does not:

- modify WorldState;
- generate final history;
- replace the Event System;
- directly control characters.

A Resolution describes a judgement result. The result is later converted into a world change by the Event Pipeline.

<!-- phase3c-begin:C-68-870-879 -->

<a id="arch-source-68-part-3"></a>

<a id="arch-source-68-part-4"></a>

**Phase 3C source excerpt:** ID 68, lines 870–879 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-68-870-879:870-879 -->

Future implementations may support:

- deterministic rules;
- probability;
- threshold judgement;
- AI-assisted interpretation.

AI cannot directly determine or modify world state. Any interpreted result remains subject to the Event Pipeline and WorldState authority rules.


<!-- phase3c-end:C-68-870-879 -->


### ID 69 — Attempt-bound physical effect proposals (implemented narrow slice)

<a id="arch-source-69"></a>

<!-- phase3c-begin:C-69-883-894 -->

<a id="arch-source-69-part-1"></a>

**Phase 3C source excerpt:** ID 69, lines 883–894 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-69-883-894:883-894 -->

The current door and known-passage policies express a supported change as an
immutable `PhysicalEffectProposal`, bound to the Attempt fingerprint, target,
clock-issued simulation tick, the exact aggregate read-source references, and
the conditions the policy verified. This is still a proposal: the Resolution
engine rejects stale/unbound proposals and does not write state. The issued
Resolution receipt binds its effect payload; EventFactory carries a bounded
provenance record into the Resolution Event; the installed Event handler checks
that binding and rechecks the current typed state and actor conditions before
EventProcessor applies the WorldUpdate. The resulting processing evidence then
binds the confirmed Observation to the Resolution Event.


<!-- phase3c-end:C-69-883-894 -->

<!-- phase3c-begin:C-69-929-940 -->

<a id="arch-source-69-part-3"></a>

**Phase 3C source excerpt:** ID 69, lines 929–940 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-69-929-940:929-940 -->
Effect-local participant relations and the global participant summary are
untrusted model claims. WorldState aggregation verifies identity only for the
current actor, target, owned tools, and bounded references explicitly present
on the Attempt; it does not disclose unrelated entity state. A successful
single-target compatibility effect may retain actor/target relation claims as
`model_proposed_unverified` metadata in the signed Resolution/Event chain.
EventProcessor validates that metadata shape and scope, but it is not an
ObservableFact and cannot establish that a proposed causal relationship
occurred. Attempt initiator attribution remains separately bound. Other direct
causes, recipients, and cross-entity effects remain unresolved until trusted
state and transition contracts can verify each link.


<!-- phase3c-end:C-69-929-940 -->


### ID 70 — Trusted Event Confirmation (Phase 12.0b foundation implemented)

<a id="arch-source-70"></a>

**Phase 3B migration:** selected direct-body ranges only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 70, lines 942–948. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 942–948

<!-- phase3b-source:70:942-948 -->

For Agent actions, the authority chain is `Attempt → ResolutionEngine policy → ResolutionDecision → issued ResolutionResult → EventFactory → Resolution-sourced Event → EventProcessor → WorldState.apply_event()`. A confirmation receipt binds the concrete result snapshot; editing its outcome or other bound fields invalidates it. EventFactory rejects caller-constructed or modified results. EventProcessor independently checks intact provenance before any handler or world write.

`SystemEventFactory` is the explicit trusted-application ingress for Events that do not arise from an Attempt, including environment/system events. The subsystem that owns this factory is trusted application composition; the factory is not caller authentication. `EventScheduler` only schedules an already-issued Event and grants no provenance. A scheduled hand-built Event is rejected by EventProcessor when dispatched. `EventHistory` remains a record system, not an authentication system; inserting an Event there does not authorize it. No second EventHistory or WorldState was introduced.

This foundation does not evaluate whether an Attempt is feasible: the default ResolutionEngine still returns unresolved when no policy exists. Prose-supplied success, confirmation, outcome, and world-change claims are not consumed as trusted resolution decisions. Open-ended Attempts remain valid inputs; no fixed action enum was added.

<!-- phase3c-begin:C-70-949-966 -->

<a id="arch-source-70-part-2"></a>

**Phase 3C source excerpt:** ID 70, lines 949–966 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

Reading note: the following source descriptions are illustrative examples, not registered social effects or a requirement to mutate the world for every formal result. The controlled confirmation chain above and the existing [DATA_CONTRACTS.md](../DATA_CONTRACTS.md), including supported no-effect results, remain authoritative.

<!-- phase3c-source:C-70-949-966:949-966 -->
Resolution describes the judgement result and its consequences. It does not itself change the world. Example consequence descriptions include:

```text
Gate opened; guard remembers the actor.
```

Example attempt: Persuade guard.

Possible result descriptions:

- Success: gate opened; guard remembers player.
- Partial success: temporary permission; suspicion increased.
- Failure: access denied; relationship decreased.

The visible result may use RPG-style labels. The internal result must contain concrete world changes.

---


<!-- phase3c-end:C-70-949-966 -->


### ID 72 — Event Pipeline

<a id="arch-source-72"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 72, lines 970–986. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 970–986

<!-- phase3b-source:72:970-986 -->

An Event is the only record form for runtime world changes.

```text
Intent
  ↓
Attempt
  ↓
Resolution
  ↓
Event
  ↓
WorldState Update
  ↓
CausalGraph Update
```

### ID 73 — Pipeline Responsibilities

<a id="arch-source-73"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 73, lines 988–995. Child sections and deferred lines are not included.

Reading note: use this abbreviated role summary with [ID 70](#arch-source-70). EventFactory issues the controlled Event from the bound Resolution result; EventProcessor independently validates it before world application. The summary is not an alternative Event-issuance or commit path.

#### Migrated excerpt — source lines 988–995

<!-- phase3b-source:73:988-995 -->

- **Intent** represents a character's or player's purpose.
- **Attempt** represents a specific action try, including its method, target, and expected effect.
- **Resolution** determines the outcome of an Attempt. It does not directly modify the world; it produces an Event.
- **Event** records a fact that has already happened.
- **WorldState** stores the current state resulting from Events.
- **CausalGraph** stores causal relationships between events.

### ID 74 — Event Application

<a id="arch-source-74"></a>

**Phase 3B migration:** selected direct-body ranges only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 74, lines 997–1016, 1018–1022. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 997–1016

<!-- phase3b-source:74:997-1016 -->

```text
Event
  ↓
EventProcessor
  ↓
WorldState Update
```

**EventProcessor** interprets the effect of an Event on the world and produces a state change request. **WorldState** accepts valid updates and stores the resulting state.

EventProcessor:

- does not judge outcomes;
- does not generate Events;
- does not call AI;
- does not bypass WorldState to modify its internal data.

All runtime state changes must be traceable to an Event.


#### Migrated excerpt — source lines 1018–1022

<!-- phase3b-source:74:1018-1022 -->

AI cannot directly modify WorldState. AI may only propose Intent or Attempt data, or explain a result. Event is the sole source of runtime state changes.

Events are the only way reality changes.

### ID 75 — Runtime Architecture

<a id="arch-source-75"></a>

<!-- phase3c-begin:C-75-1024-1026 -->

<a id="arch-source-75-part-1"></a>

**Phase 3C source excerpt:** ID 75, lines 1024–1026 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-75-1024-1026:1024-1026 -->

This section describes the runtime lifecycle of CognitiveWorld.


<!-- phase3c-end:C-75-1024-1026 -->


### ID 78 — Runtime Loop

<a id="arch-source-78"></a>

<!-- phase3c-begin:C-78-1066-1128 -->

<a id="arch-source-78-part-1"></a>

**Phase 3C source excerpt:** ID 78, lines 1066–1128 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-78-1066-1128:1066-1128 -->

The implemented Agent action cycle provides orchestration across these boundaries when supplied with components that produce a confirmed result:

```text
Observation
  ↓
CognitionContext
  ↓
AgentDecision
  ↓
ActionProposal
  ↓
Attempt
  ↓
Resolution
  ↓
Event
  ↓
EventProcessor
  ↓
WorldState
```

AgentActionLoop coordinates the AgentDecision, ActionProposal-to-Attempt conversion, and
Attempt resolution through Event creation. The resulting Event is handed to EventProcessor;
it is not applied by AgentActionLoop or SimulationRuntime.

For `DecisionContext`, `AgentDecision` now selects a bounded cognition-grounded proposal. Its legacy `CognitionState`/Mapping inputs and the uncustomized built-in `AgentActionLoop` compatibility route retain the placeholder proposal. The default `ResolutionEngine` remains unresolved without an installed world rule, so no action outcome is confirmed by default. `SimulationRuntime` can advance time, poll Event and Agent schedulers, run due Agent turns, and dispatch generated Events. It does not itself apply Events or write EventHistory.

```text
Natural Language Input
  ↓
Semantic Understanding
  ↓
Intent
  ↓
Attempt
  ↓
Resolution Engine
  ↓
Resolution
  ↓
Event
  ↓
EventProcessor
  ↓
WorldState Update
  ↓
CausalGraph Update
  ↓
Memory Update
```

Responsibilities by stage:

- **Cognition** understands the input.
- **Decision** produces Intent and Attempt.
- **Resolution** produces a judgement result.
- **Event** records a fact that has already happened.
- **WorldState** stores the current state of reality.

No module may bypass Event to modify WorldState.


<!-- phase3c-end:C-78-1066-1128 -->


### ID 80 — Scheduled work responsibility (approved contract; no scheduling implementation change)

<a id="arch-source-80"></a>

**Phase 3B migration:** selected direct-body ranges only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 80, lines 1187–1188, 1193–1199. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 1187–1188

<!-- phase3b-source:80:1187-1188 -->

A host-submitted `ScheduledEvent` contains an execution time and a constructed Event. Scheduling or enqueueing it is not formal commitment to EventHistory. The current architecture guarantees neither eventual execution of every item, automatic retry after budget exhaustion, nor survival across checkpoint restore. Queue membership must not be the sole guarantee that a necessary authoritative causal consequence will occur. This establishes no universal retry-or-discard policy and does not authorize arbitrary discard: each producer remains subject to its applicable approved contract; undefined producer responsibilities remain unresolved.

#### Migrated excerpt — source lines 1193–1199

<!-- phase3b-source:80:1193-1199 -->

Committed-Event delivery retries remain separate from ScheduledEvent handling and Agent rescheduling. Their existing narrow checks for original request identity, committed Event evidence, current recipient/session authorization and other applicable requirements remain in force. Retrying delivery must not replay the committed world action. Existing arrival delivery may separately complete authorized local mechanism-observation Events; that does not repeat the original movement or broaden observation permissions.

Budget exhaustion is not cancellation; cancellation is not invalidation. Truncating or terminating an opportunity is not safe deferral, which requires the applicable validity and context guarantees. Approximate computation is not permission to omit required authoritative processing. Confirmed Events, hard constraints and necessary causal consequences remain protected, and scheduling budgets cannot silently bypass that processing. Conversely, neither the ScheduledEvent type nor queue membership establishes that an item represents a mandatory consequence. No generalized task lifecycle, state machine, API or schema is defined here.

The current SaveManager/RuntimeSnapshot contracts provide no general persistence of pending Runtime schedules. Reconstructing a new opportunity is distinct from restoring the identity and responsibility of an existing pending item. A specific recovery guarantee requires an explicitly approved contract; no pending-work journal, recovery queue or reconstruction protocol is added. See [existing recovery limits](../DATA_CONTRACTS.md) and the [current scheduling limitations](../REPOSITORY_STATUS.md#scheduled-work-responsibility-status-2026-10-25).

<!-- phase3c-begin:C-80-1189-1192 -->

<a id="arch-source-80-part-1"></a>

**Phase 3C source excerpt:** ID 80, lines 1189–1192 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-80-1189-1192:1189-1192 -->

A periodic Agent scheduling entry is an opportunity to decide under the applicable execution context, not a frozen action, ActionProposal or Attempt. A later `AutonomousWorldRunner` round creates a new opportunity rather than restoring an earlier one. Budget exhaustion carries no guarantee that every Agent receives an opportunity in every round, no automatic retry or fairness guarantee, and no new priority policy. A skipped opportunity must not be compensated by replaying an earlier action.

`ScenarioSeedScheduler` records scheduling/deduplication state when it arranges a content-triggered wakeup. That state proves neither that Agent decision processing started nor that it completed. The current mechanism does not guarantee automatic compensation for a skipped wakeup. Reliable wakeup delivery would require a separately approved contract; this clarification introduces no compensation protocol, deduplication-key reopening or persistent pending-work mechanism.

<!-- phase3c-end:C-80-1189-1192 -->


### ID 81 — Runtime write fencing (narrow in-process foundation)

<a id="arch-source-81"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 81, lines 1201–1231. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 1201–1231

<!-- phase3b-source:81:1201-1231 -->

`SimulationRuntime` owns one `RuntimeWriteFence` for its process-local session.
Each step captures a session/generation permit distinct from simulation tick
and any future timeline identity. Provider work inherits that permit through
Python task context; newly constructed ActionProposal, Event and cognitive
update proposals retain their originating permit. AgentActionLoop rejects an
old ActionProposal before creating an Attempt; EventProcessor,
CognitiveUpdateApplier and EmotionUpdateApplier validate the permit at their
final write boundaries.
The shared lock spans validation and commit, so a generation advance either
waits for an already-linearized commit or invalidates the operation before
write. Freezing blocks new steps and commits; unfreezing permits fresh work
without reviving old permits.

This covers the Runtime EventProcessor path; the final Belief/Goal/SelfModel
Store update boundaries; the Emotion container commit boundary; and Memory
proposal/request/persistence commits when the canonical MemoryStore has been
bound by AgentTurn or MemoryPersistence. Player dialogue also captures the
EventProcessor's fence before L1/provider work, so persuasion writes retain the
starting permit. Personality has no governed runtime evolution path; after
Runtime binding, its legacy `update` method rejects rather than opening one.
Initialization before binding remains supported.

Private-field mutation, unbound standalone Memory persistence, trusted
initialization APIs used outside an operation, custom callbacks/providers that
discard task context, and cross-process work remain outside this guarantee.
`freeze_writes()` is not a complete Context Freeze or restore transaction and
does not cancel model requests.

---

### ID 82 — Runtime Layer

<a id="arch-source-82"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 82, lines 1233–1235. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 1233–1235

<!-- phase3b-source:82:1233-1235 -->

The Runtime Layer coordinates simulation time and lifecycle, schedules existing Events, and calls the EventProcessor. It is a scheduling layer and does not own world or cognition rules.

### ID 89 — Components

<a id="arch-source-89"></a>

<!-- phase3c-begin:C-89-1301-1323 -->

<a id="arch-source-89-part-1"></a>

**Phase 3C source excerpt:** ID 89, lines 1301–1323 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-89-1301-1323:1301-1323 -->

- **SimulationClock** manages simulation time.
- **RuntimeContext** holds references to runtime dependencies.
- **EventScheduler** manages the scheduled execution times of future Events.
- **AgentScheduler** manages when registered Agents are due to take a turn.
- **AgentActionLoop** coordinates one Agent turn through Event creation.
- **SimulationRuntime** controls the `step()` and `run()` lifecycle.
- **RuntimeSnapshot** captures Runtime-owned state only.

The Runtime Layer does not:

- create Events;
- interpret Events;
- modify WorldState directly;
- make AI decisions;
- update Cognition;
- generate Memory.

SimulationRuntime supports clock progression, EventScheduler dispatch, AgentScheduler turn
triggers, AgentActionLoop execution, and EventProcessor dispatch. Runtime does not directly
modify WorldState or write EventHistory. EventProcessor remains responsible for applying
Events through WorldState and recording successfully processed Events in EventHistory.


<!-- phase3c-end:C-89-1301-1323 -->


### ID 90 — Future Runtime Architecture

<a id="arch-source-90"></a>

<!-- phase3c-begin:C-90-1325-1337 -->

<a id="arch-source-90-part-1"></a>

**Phase 3C source excerpt:** ID 90, lines 1325–1337 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-90-1325-1337:1325-1337 -->

The Runtime may later be separated into specialized runtime components:

```text
Runtime
├── Simulation Runtime
├── Cognitive Runtime
├── Narrative Runtime
└── World Runtime
```

The current implementation provides SimulationRuntime. Cognitive Runtime, Narrative Runtime, and World Runtime are future extensions only.


<!-- phase3c-end:C-90-1325-1337 -->


### ID 91 — Phase 12.6 Autonomous Multi-Agent Runtime

<a id="arch-source-91"></a>

<!-- phase3c-begin:C-91-1339-1365 -->

<a id="arch-source-91-part-1"></a>

**Phase 3C source excerpt:** ID 91, lines 1339–1365 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-91-1339-1365:1339-1365 -->

`AutonomousWorldRunner` is a bounded orchestration wrapper over the existing
`SimulationRuntime`, not a second Runtime or state authority. Each requested
round schedules every registered Agent once, in stable Agent ID order, and
delegates to the production AgentTurn, owner-scoped cognition snapshot,
AgentDecision, ActionPipeline, Resolution, EventFactory, and EventProcessor
chain. A confirmed Agent Event is processed and authorized Observations are
distributed before the next Agent turn, so a later Agent can react only
through its own Observation and cognition path. Per-Agent exceptions are
recorded; a recovery-required EventProcessor state stops the remaining work.
Round, Agent, and Event budgets are bounded. Stable ordering determines
scheduling only; it does not select an action.

The deterministic autonomy baseline derives a small set of installed-domain
affordances from the current Agent's trusted Percepts (currently a known
closed door and a known passage), then relates those affordances to that
Agent's active Goals. Candidate scores and factors are retained in a
developer-only report to explain Proposal selection. No Runner or demo branch
chooses an action based on Agent ID, list index, or round number. Resolution
rechecks current authoritative state and remains the only result authority.
This is a narrow production loop, not general autonomous behavior:
deterministic goal matching is limited, and causal outcomes are implemented
only for doors and known passage traversal. Unsupported methods remain
unresolved. The Runner currently submits one Proposal/Attempt per Agent turn;
the separate `StepwisePlanExecutor` remains caller-driven rather than
automatically scheduled here.


<!-- phase3c-end:C-91-1339-1365 -->


### ID 127 — Phase 12.5A Method-Based Causal Resolution (Narrow First Slice)

Pending content migration. Frozen primary source identity: **127**.

### ID 128 — Phase 12.5B Open-ended Causal Execution (Implemented; validation pending)

<a id="arch-source-128"></a>

<!-- phase3c-begin:C-128-1896-1904 -->

<a id="arch-source-128-part-1"></a>

**Phase 3C source excerpt:** ID 128, lines 1896–1904 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-128-1896-1904:1896-1904 -->

The existing `ActionProposal` and immutable `Attempt` remain the only proposal/attempt contracts. `ActionInterpreter` accepts open method text, rejects structured authority fields, and does not treat success prose as a result. The optional OpenAI-compatible provider extracts only allowlisted target references, method/tool/precondition/step/uncertainty fields; ordered steps can be bounded strings or structured method/target/observable-condition proposals with nested allowlists. Actor identity and proposal source remain locally assigned, and targets/conditions are checked against trusted state or authorized Observations. Input/output size and timeout are bounded; a stepwise plan allows at most one provider call in its running executor, including across retryable exceptions. Network unavailability falls back to the submitted attempt; malformed or authority-shaped output is rejected. The same replaceable provider can return causal suggestions, but these are never facts or effects. The adapter is opt-in and has not been validated against a live endpoint.

`MethodBasedResolutionEngine` remains the single engine and dispatches to typed door and passage policies through the shared ResolutionResult/EventFactory/EventProcessor chain. The non-door production slice uses a `PassageState` in the existing `WorldState.environment`, exact actor position and known locomotion capability. The signed prospective location effect is rechecked by its EventHandler, including a successful typed result summary, before the existing locations collection is updated. A typed arrival ObservableFact can enter the existing Observation path for a registered co-located observer with known sight. Unknown target, route, capability or time remains unresolved. Model output cannot grant routes, capabilities, world rules or outcomes.

`StepwisePlanExecutor` processes at most one ordered step per call, binds step identity to proposal content, routes effects through `ActionResolutionFlow` and `EventProcessor`, and requires a trusted owner-scoped Observation of the preceding Event that has an intact L1 consumption receipt before continuing. A first valid L1 ingestion during the continuation call is accepted; a prior ingestion is also accepted even though that call produces no new `CognitionState.percept_ids`. A missing Observation, another Agent's ingestion, or a caller-supplied percept ID is insufficient. It can check exact predicate/value/subject conditions against trusted ObservableFacts. A missing condition is unresolved; a confirmed mismatch stops the plan. Stable step IDs and EventHistory prevent reapplying a completed world update. Progress is integrity-bound to its issuing executor, WorldState, EventHistory, and proposal content before terminal status is considered; the executor also retains the one-call provider budget across retries after an exception. Progress and budget remain process-local, not durable. General natural-language condition evaluation and automatic replanning are not implemented.

`WorldState.apply_event()` now rejects calls outside EventProcessor's short-lived capability scope bound to the exact WorldState, intact Event snapshot, and WorldUpdate snapshot. Initialization `load_*` methods close when SimulationRuntime starts or before the first EventProcessor handler runs. This also prevents a handler from using initialization loaders as a runtime write path. These are ordinary application misuse protections, not a same-process Python security sandbox. State application, evidence/History writes, and Observation delivery remain non-atomic and rely on existing in-process recovery markers. Implemented causal coverage is still narrow (direct door and passage traversal); no production partial-effect rule, general physics/social reasoning, or live model validation exists.


<!-- phase3c-end:C-128-1896-1904 -->


### ID 154 — Open natural-language action representation

<a id="arch-source-154"></a>

<!-- phase3c-begin:C-154-2284-2292 -->

<a id="arch-source-154-part-1"></a>

**Phase 3C source excerpt:** ID 154, lines 2284–2292 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-154-2284-2292:2284-2292 -->

The long-term action representation is open-ended and semantic, not a closed action-type menu. An interpreted attempt may express an actor, predicate, arguments or referenced entities, method, constraints, preconditions, ordered or conditional steps, and uncertainty. These fields describe what the actor is attempting; they do not assert that the predicate is true or that an outcome occurred. ActionProposal and Attempt therefore remain distinct from objective Entity State and confirmed Events.

The future language-model interpreter's role is compilation from natural-language input to a language-independent structured Attempt proposal. Argument and object grounding must use the acting character's owner-authorized cognitive view and trusted references available to that character. The interpreter must not give the character a full WorldState view to resolve references. If a referent or required argument is ambiguous, unknown, or not available to that character, preserve that uncertainty and request clarification or leave the attempt unresolved; do not guess an identity or import hidden world facts. A language model may propose an interpretation, but cannot establish a referent, capability, world condition, or effect as fact, modify WorldState, create an Event, or authorize a Resolution.

The target-address convention is `object:{id}` for an objective target and `agent:{id}` for an agent reference. A namespace is addressing and adjudication-routing information, not the runtime entity's type, an action category, permission, or proof that the target exists. The current `InteractionReference` parser and Resolution entry implement only a narrow part of this convention: `object:{id}` may address an existing typed environment mechanism, while `agent:{id}` remains unresolved because no governed subject-target causal policy is installed. Historical bare references remain explicit object-address compatibility, including legacy IDs containing colons. A temporary condition never changes a reference namespace. `Attempt.target_refs` is still open text and does not itself ground or authorize any target; full observer-scoped grounding remains future work.

The structured action frame may be described as subject/actor + predicate/intent + target/object + optional parameters/modifiers and contextual constraints/supplementary information. This is an engineering abstraction for language-independent Attempt data, not a claim that all natural languages follow one universal grammatical structure. Critical semantics must not depend on a particular sentence form being retained. The current Attempt remains the canonical runtime contract; this conceptual frame is not a second Action or Attempt model.


<!-- phase3c-end:C-154-2284-2292 -->


### ID 155 — Stable interaction references and dynamic minimum interaction context

<a id="arch-source-155"></a>

<!-- phase3c-begin:C-155-2294-2318 -->

<a id="arch-source-155-part-1"></a>

**Phase 3C source excerpt:** ID 155, lines 2294–2318 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-155-2294-2318:2294-2318 -->

The minimum interactive unit is **not a second stable world entity** or a parallel WorldState. `Entity` and `InteractionReference` continue to provide stable identity/addressing; the minimum unit for one interaction is a transient aggregate bound to a specific immutable `Attempt`, its grounded target references, and a trusted simulation tick. It is assembled on demand from the existing authorities and discarded after use. `Attempt` remains an untrusted proposal; the aggregate neither confirms facts nor grants write authority.

`InteractionStateAggregator` is now used by `MethodBasedResolutionEngine` to assemble the physical `CausalWorldContext` through targeted `WorldState` readers: the acting entity, its current location and capabilities, its owned tool records, and the one addressed typed environment state used by the installed causal domain. The view carries the Attempt fingerprint, target reference, simulation tick, source collection references, and explicit unknown fields. It does not expose or cache full WorldState mappings. Re-aggregation reads the latest canonical state; there is no permanent aggregate or snapshot store. These `source_refs` identify authoritative read locations, not Event IDs. Where an exact addressable slot is read, its separate `WorldStateSlotRead` may carry verified latest-changing-Event provenance; the two references are not interchangeable.

An optional `CognitiveInteractionView` can be assembled only through the existing `AuthorizedStateQuery` for the same Attempt owner and tick. It contains only provenance-checked ObservableFacts already available to that observer, with their Observation/Event IDs; unknown, hidden, unsupported, or over-budget targets remain unknown. This view is not the character's full private cognition. Beliefs, Goals, Memories, Emotion, and SelfModel remain available only through the established owner-scoped `DecisionContext`/CognitionContext path; they are not mixed into the physical causal view. No cognitive/physiological Resolution policy currently consumes or mutates those records.

The aggregate is read-only and has no Event, WorldState, EventHistory, or cognition write methods. It is bound to the exact Attempt content and simulation tick and is not reused for another Attempt. The installed deterministic causal domains still support only typed door operation and known passage traversal; `agent:` targets and unsupported states remain unresolved. Model suggestions cannot choose targets, authorize queries, or turn missing evidence into a fact. This is a bounded aggregation foundation, not a universal state system, target-grounding service, or general physical/cognitive engine.

This is the current minimum interaction unit: an Attempt-bound, temporary set
of relevant state and evidence, not an Entity, persistent Store, or complete
WorldState copy. It is assembled on demand for the current interaction and
simulation time, with identity, relations, permissions, provenance, and
unknowns kept explicit. Physical and cognitive domains may reuse this
organization, but retain separate state ownership, adjudication rules, and
governed update paths. LLMs may propose relevant state, conditions, or
candidate changes; code independently verifies grounding, authorization,
source, binding, and supported transitions. Missing trusted state or an
installed adjudication contract remains unresolved; free text is never a
WorldUpdate. Event Tree assumptions remain isolated from real WorldState,
EventHistory, and actual cognition; current Event Tree is candidate exploration
only and has no hypothetical state store.

Current limitations: only typed door and passage targets have deterministic objective causal policies; `agent:` targets and other objects remain unresolved. Legacy bare IDs address objective environment records only. No generic Entity-state effect schema, agent-target adjudication, dynamic LLM state-query loop or universal interaction engine is implied by this narrow repair.


<!-- phase3c-end:C-155-2294-2318 -->


### ID 157 — Separate physical and cognitive/physiological causality

<a id="arch-source-157"></a>

<!-- phase3c-begin:C-157-2324-2333 -->

<a id="arch-source-157-part-1"></a>

**Phase 3C source excerpt:** ID 157, lines 2324–2333 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-157-2324-2333:2324-2333 -->

Future causal reasoning should distinguish two related **causal domains**, without creating two independent world simulators or large standalone engines:

- **Physical causal domain:** reads authorized objective state and proposes transitions only for its permitted objective state slots, potentially including position, containment, object/door state, structural integrity, movement consequences, physical damage, and environmental consequences.
- **Cognitive/physiological causal domain:** reads only authorized subject-scoped evidence and proposes transitions only for explicitly governed subject-internal or physiological state slots, potentially including consciousness, pain response, fear, attention, arousal, emotion, motivation, and physiological response.

These examples are not a complete state enum or implemented feature list. A causal domain is a bounded state reader and transition proposer, not an action taxonomy, an independent world writer, or a mandate to create a dedicated engine subsystem. Future causal reasoning must keep objective physical changes separate from private cognitive and physiological changes. Character cognition continues to change only through owner-scoped Perception/Cognition and existing proposal-validation-application governance. A future physiological domain, if introduced, requires its own explicit state semantics, evidence, and authorized update contract; it must not be smuggled into physical effects or inferred from narrative prose. Neither domain may read or propose writes outside its authorized state-slot set. No generic cognitive or physiological causal authority is established by this design record.

Both domains only contribute evidence-bounded proposals to the existing shared adjudication path. All objective effects continue through the single trusted `Resolution → EventFactory → EventProcessor → WorldState` chain; no domain directly commits an effect. Resolution may not directly decide an NPC's belief, emotion, goal, interpretation, or voluntary response. Those remain the NPC's own cognitive and decision outcomes. If an effect cannot be supported by an implemented policy and sufficient trusted state, Resolution remains unresolved.


<!-- phase3c-end:C-157-2324-2333 -->


### ID 159 — Combat as a causal stress case, not an action taxonomy

<a id="arch-source-159"></a>

<!-- phase3c-begin:C-159-2339-2343 -->

<a id="arch-source-159-part-1"></a>

**Phase 3C source excerpt:** ID 159, lines 2339–2343 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-159-2339-2343:2339-2343 -->

Combat is a useful stress case for testing open predicates, grounded arguments, capabilities, resources, time, competing actors, and consequences. It is not a requirement to create an exhaustive `attack/defend/dodge/...` action family or special world operation for each verb. For example, a future attempt to push someone down would be adjudicated from actor capability, positions, target state, method, resources, and environmental constraints, then express any supported result as changes to relevant state slots—not as an assumed `knock_down` operation. “Attack” is an attempted predicate, not a confirmed outcome. The current deterministic production domains remain typed door operation and known passage traversal. Unsupported combat, social, physiological, or other causal methods remain unresolved unless a separately designed and tested domain policy can adjudicate them from trusted evidence.

This state-transition approach is intended to reduce accumulating per-action `if/else` logic: new methods can be interpreted as open predicates and assessed against shared, typed evidence and domain rules. It does not eliminate the need for explicit domain policies, nor allow an unknown predicate/effect to pass without evidence.


<!-- phase3c-end:C-159-2339-2343 -->


### ID 161 — Explicitly not implemented by this design record

<a id="arch-source-161"></a>

<!-- phase3c-begin:C-161-2351-2353 -->

<a id="arch-source-161-part-1"></a>

**Phase 3C source excerpt:** ID 161, lines 2351–2353 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-161-2351-2353:2351-2353 -->

This direction does not implement physical or cognitive/physiological causal domains beyond currently documented policies, a full Physics/Cognition/Physiology/Combat engine, a fully open natural-language action system, or a universal `Predicate → Consequence` Resolution mechanism. Argument grounding across ambiguous or underspecified references remains incomplete. A general authority classification for arbitrary state predicates and effects is still to be designed. Social causality and complex physical or physiological domains require independent contracts, evidence rules, policies, and tests. No production capability beyond the currently documented door and passage domains should be inferred from this future direction.


<!-- phase3c-end:C-161-2351-2353 -->


### ID 188 — Explicit state commitments and independent interaction reach (partial integration)

<a id="arch-source-188"></a>

<!-- phase3c-begin:C-188-2677-2678 -->

<a id="arch-source-188-part-2"></a>

**Phase 3C source excerpt:** ID 188, lines 2677–2678 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-188-2677-2678:2677-2678 -->
JSON content v4 can independently configure InteractionRangePolicy/v1 on the installed door mechanism and reuse an ObjectTemplate appearance for that same canonical mechanism identity. Resolution evaluates actual canonical locations in the existing bounded one-dimensional coordinate domain; observation thresholds/permissions continue to govern disclosure separately. The final Event handler rechecks reach and the bound state-slot receipts. Missing geometry is unresolved, not zero distance or a confirmed physical failure. Legacy unconfigured doors retain their existing co-location rule.


<!-- phase3c-end:C-188-2677-2678 -->


### ID 192 — 首个受治理的物品拿取纵切（已实现，有限范围）

<a id="arch-source-192"></a>

<!-- phase3c-begin:C-192-2713-2721 -->

<a id="arch-source-192-part-1"></a>

**Phase 3C source excerpt:** ID 192, lines 2713–2721 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-192-2713-2721:2713-2721 -->

`items.take` 将经过验证的请求、有限只读物理视图和 `TakePolicy/v1` 交给可替换模型；模型不持有 WorldState 写权限。政策引用已有类型化 Boolean 物性及角色能力，不依赖物品名称。宿主须显式装配政策和 Resolution engine；尚未接入桌面自由输入的自动路由。

支持已注册 character（兼容既有 agent 身份）在同一规范地点取得独立、符合政策、当前无人持有的物品。所有权不是默认拿取权限：owner_id 及一致的 owned_by 保持不变；物品规范位置改为角色身份，并添加 held_by，角色位置不变。part_of、attached_to 和容器内物品不在范围内，不会被隐式拆离。

Resolution 候选绑定原 Attempt、配置和实际读取的状态来源；EventProcessor 在受保护提交边界重新验证相关依赖和全体当前持有关系的缺席。WorldState 先准备并验证完整的位置／关系映射，再联合发布并将两者来源绑定到同一 Event。竞争候选过期时拒绝，不补写失败事件、不重算、不自动重试；无关变化不自动使候选失效。这是现有围栏内的逻辑联合转移，不是跨 Store 或进程崩溃事务。

成功提交后，原行动者可取得私有 item_taken 结果，经既有 Observation、历史资格和实际 L1 消费链处理；仅交付不等于消费，不会自动修订 Belief 或 Goal，也不向玩家 Presentation 添加默认披露。历史交付验证原 Event，不根据当前世界重算成功。容器、搜索、容量、死亡掉落、放下及所有权转移仍未实现。


<!-- phase3c-end:C-192-2713-2721 -->


### ID 193 — 拿取失败候选的裁定上下文（有界修复）

<a id="arch-source-193"></a>

<!-- phase3c-begin:C-193-2723-2728 -->

<a id="arch-source-193-part-1"></a>

**Phase 3C source excerpt:** ID 193, lines 2723–2728 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-193-2723-2728:2723-2728 -->

新生成的成功与失败拿取候选都携带 TakeAdjudicationContext/v1。提交前统一核对原 Attempt、规范政策内容身份、读取值及来源、完整相关类型化关系集合和持有条件，不重新调用 provider 或对原 Attempt 重跑裁定。原上下文仍有效的失败才可提交无效果事件；政策或相关依赖已变化则拒绝候选，新独立请求另行裁定。无关世界变化不构成全局失效。历史恢复仅验证原签名记录及上下文绑定，不用当前配置或状态重裁过去。

专用拿取引擎保留早期上下文校验；共享 live 合约不再依赖引擎子类。EventFactory 从受控 Resolution 的原 Attempt 捕获现有显式操作身份（action_type=take、parameters.item_operation=take），并将身份、Attempt 指纹、owner 和 tick 绑定到进程内来源凭据。字段只标识操作，不单独授予世界写入权限。Factory 与 EventProcessor 新事件 apply 前共用验证器要求拿取上下文，后续 handler 独立复核当前政策、状态来源及完整关系。身份不来自 outcome 文本、任意 Event metadata 标签或转移对象的存在性。已记录的当前／祖先事件先复用原证据；历史读取不补造 live 来源绑定，也不能把历史签名本身当作新的执行许可。



<!-- phase3c-end:C-193-2723-2728 -->


### Content received from coordinated splits

- Original ID **189**, source lines **2688–2693**: approved excerpt copied in Phase 3C below; other parts and final coordination remain pending. The original heading keeps its separate primary assignment.

### Split source ID 189 — Minimal pluggable physical state — implemented v1 slice / Pure engine and installed Boolean current-source validation; older no-projection scope

<!-- phase3c-begin:C-189-2688-2693 -->

<a id="arch-source-189-part-2"></a>

**Phase 3C source excerpt:** ID 189, lines 2688–2693 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-189-2688-2693:2688-2693 -->
Strict generation-proposal JSON v5 supplies the new typed state and local-reference relations/rules. ContentValidator and ContentInstantiator prepare them; RuntimeContentInstaller commits them through its existing installation Event. A configured boolean transition rule selects required capabilities, exact typed state predicates and relation kinds. The pure replaceable engine returns a candidate delta and diagnostic evidence, never writes state. Full-world graph/reference validation remains at content preparation, formal WorldState application, checkpoint capture and verified restore. Interaction capture uses the shared single-rule validator for the active rule only; an input entity may have other valid rules whose dependencies are outside this interaction. Only the receiver and condition state sets are passed as state evidence to the pure engine. The Resolution adapter captures canonical leaf-slot origins; the EventProcessor handler independently checks the installed rule, current read bindings, reach and delta before applying the ordinary WorldUpdate. A stale or unjustified candidate cannot commit. Missing operation/rule/reach support stays unresolved; a verified unsatisfied rule precondition produces a confirmed failed Resolution without a new private result-observation category.

Newly issued failed Boolean candidates are current-result submissions, not a historical-admission API. They retain their captured reads in the existing physical_effect_provenance metadata, and the existing EventProcessor read guard rejects changed values/origins before applying even the empty update or appending history. Unrelated state changes do not by themselves invalidate those reads. Rejection does not retry an action or manufacture a new result. Already committed failures retain their historical meaning; older records without these bindings are not rewritten or retroactively upgraded. No new proof, result Observation, signing purpose or persistent envelope is introduced.

The v1 reach assumption is exact actor/interaction-target co-location, independent of visual range or detail permissions. The panel/handle/latch assembly is authored example data, not an engine branch. Alternative engines must satisfy the same installed v1 transition contract; new model semantics need a separately reviewed contract. The slice does not emit new physical fact/Observation projections or make internal state available to NPCs/UI. The developer host prints a commit diagnostic, not player narrative evidence.


<!-- phase3c-end:C-189-2688-2693 -->


## Existing canonical definitions retained by reference

- Source ID **46**, original lines **589–593**: [ENGINEERING_RULES.md](../ENGINEERING_RULES.md). Reference only; original source retained, no definition body copied.

## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) — canonical owner for A04, A05, A06, A07, A08, A18, A34, A38.
- [META_CONTRACTS.md](../META_CONTRACTS.md) — canonical owner for A35.
- [SOCIAL_CAUSAL_DESIGN.md](../SOCIAL_CAUSAL_DESIGN.md) — canonical owner for A21.
- [COGNITION.md](COGNITION.md) — canonical owner for A16, A23, A36.
- [PERCEPTION.md](PERCEPTION.md) — canonical owner for A12.
- [PERSISTENCE.md](PERSISTENCE.md) — canonical owner for A31, A33.
- [SAFETY_AND_NORMS.md](SAFETY_AND_NORMS.md) — canonical owner for A37.
- [WORLD_MODEL.md](WORLD_MODEL.md) — canonical owner for A03, A24, A28.
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md) — canonical owner for A25.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [COGNITION.md](COGNITION.md)
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md)
- [PERCEPTION.md](PERCEPTION.md)
- [PERSISTENCE.md](PERSISTENCE.md)
- [SAFETY_AND_NORMS.md](SAFETY_AND_NORMS.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md)

## Historical and implementation-status handling

Only the explicitly marked Phase 3D historical quotations below have migrated. Other historical or mixed content remains pending. These source-stage records establish no new runtime capability, current test result or normative definition.

<a id="arch-history-h-74-1017-1017"></a>
### Historical source record — Event Application

**Historical record — Historical implementation snapshots.** This is an original-stage quotation, not a current normative definition, current implementation inventory or newly executed test result.

Source: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), original heading ID **74**, lines **1017–1017**; original heading: **Event Application**.
Source document SHA-256: `d111ce446dcdf8a16182dc465f42a851177a569547b3a0cfc6519d6e8653f751`. Captured from the working tree based on `838e6913e6e6d6deefcaa6bbf126cad2139550b7`; the quoted bytes are not asserted to be the committed version.

Original context: Original Event Application foundation states generic dispatch implemented and concrete rules absent at that stage.
Chronology: At this stage is the only temporal language; do not invent a Phase number or date. Calendar date: not stated in the source.

Temporal words such as “now”, “currently”, “here”, “this document”, “below” and “at this stage” retain their original source context. Legacy paths are historical evidence, not current repository instructions. The full quoted limitations and original validation status remain attached; no broader supersession or present-day acceptance is inferred.

Current normative definitions remain with their frozen owners, including [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) and [META_CONTRACTS.md](../META_CONTRACTS.md); this quotation creates no additional authority.

<!-- Phase 3D exact source quotation begins: H-74-1017-1017 -->
> The generic handler registration and `WorldUpdate` dispatch boundary are implemented. Future Event Handlers may process different changes based on Event type. Concrete event rules are not implemented at this stage.
<!-- Phase 3D exact source quotation ends: H-74-1017-1017 -->


Contact: ankorgine@outlook.com
