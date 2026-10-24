# CognitiveWorld Memory Design

Version: 1.0

---

# 1. Purpose

This document defines the memory architecture of CognitiveWorld.

The purpose of memory is to:

- maintain continuity between interactions;
- preserve important world history;
- support consistent character behavior;
- simulate human-like forgetting.

Memory is not simply conversation storage. Memory is the structured preservation of meaningful experience.

---

# 2. Core Principle

CognitiveWorld separates Short-term Memory and Long-term Memory. They serve different purposes.

---

# 3. Memory Flow

The intended memory lifecycle is:

```text
Experience
  ↓
Short-term Memory
  ↓
Proposal and decision boundaries
  ↓
Long-term Memory
  ↓
Future Decision Support
```

The current implementation provides data models and boundary components. Automatic selection, compression, and forgetting remain unimplemented. Phase 12.2 adds bounded relevance retrieval over the existing MemoryStore; candidate IDs must be referenced by the current Character and match the Agent owner. This does not introduce a second Memory store.

## B2 system-only consumption evidence

[B2](DATA_CONTRACTS.md#b2-durable-l1-identity-and-instance-bound-proof) stores only
its exact instance-bound proof in the existing MemoryStore system-record path.
The instance and proof are system-only content, never Character-semantic Memory,
and cannot be written by ordinary MemoryDecision/MemoryPersistence. Their
checkpoint verification preserves original owner, Timeline, tick, source and
signature. Missing historical consumption is not inferred from Memory absence
or reconstructed input. Consumption proof does not revise semantic Memory,
Belief, Goal or SelfModel; expectation association and learning remain B3/B4.

## Cognitive feedback and evidence provenance (architectural direction)

The intended [hybrid cognition loop](ARCHITECTURE.md#hybrid-cognition-execution-levels-architectural-direction-unified-policy-not-implemented) distinguishes an owner's authorized evidence, subjective Belief, Goal, intention/plan, proposed method and expected outcome from the actual Resolution/Event/WorldState outcome. After a confirmed action, only an authorized Observation and its verified source can become that owner's evidence of what happened; absence of an Observation is not proof that the Event did not occur. Comparison may identify partial success, failure, unexpected effects or unresolved uncertainty, but it is a proposed review, not an automatic Memory or Belief write.

Any durable update must cite the specific owner, relevant evidence/source Event, prior cognitive record and the belief, expectation, method or causal assumption being revised. It must preserve the difference between testimony, the fact of hearing it, interpretation and independently verified outcome. A mismatched expectation should not indiscriminately lower confidence in every related Belief. The existing cognition validators and MemoryDecision/Factory/Persistence chain remain the only supported write paths for their respective records; historical support follows verified EventHistory and Timeline ancestry. Current locked-door BehaviorFeedback is a narrow separately persisted adaptation, not a general expectation-result learner or new Memory authority. General expectation capture, comparison, targeted learning and replayable feedback semantics remain future design work.

---

# 4. Short-term Memory

## Definition

Short-term Memory represents recent experiences and current context. It exists to help AI understand the current interaction.

## Format

Short-term Memory uses natural language.

Example:

```text
The player talked with the guard.
The player appeared nervous.
The guard noticed unusual behavior.
The conversation ended without conflict.
```

## Purpose

Short-term Memory preserves:

- recent events;
- emotional atmosphere;
- conversational context;
- temporary details.

## Characteristics

Short-term Memory should be rich, flexible, and human-readable. It does not require complete structure.

---

# 5. Short-term Memory Lifecycle

Short-term Memory is temporary.

```text
New Experience
  ↓
Append Context
  ↓
Compress When Necessary
  ↓
Remove Low-value Details
```

Can be forgotten:

```text
Player stood near the door for five seconds.
```

Should be preserved:

```text
Player showed distrust toward the NPC.
```

---

# 6. Long-term Memory

## Definition

Long-term Memory stores information that affects future world consistency. It represents: “What should the world remember?”

## Format

Long-term Memory uses structured data.

Example:

```json
{
  "type": "relationship",
  "subject": "npc_001",
  "content": {
    "trust": 70
  }
}
```

---

# 7. Long-term Memory Types

Long-term Memory contains several categories.

## 7.1 Fact Memory

Represents confirmed facts.

```json
{
  "type": "fact",
  "content": "Player helped NPC escape."
}
```

## 7.2 Relationship Memory

Represents changes between entities.

```json
{
  "type": "relationship",
  "source": "player",
  "target": "npc",
  "change": {
    "trust": 20
  }
}
```

## 7.3 Experience Memory

Represents important personal experiences.

Example: NPC remembers being rescued by the player.

## 7.4 Causal Memory

Represents why something happened.

```text
Player helped NPC
  ↓
NPC trusts player more
```

Stored as:

```json
{
  "cause": "helped_npc",
  "effect": "trust_increased"
}
```

---

# 8. Memory Consolidation

The planned consolidation flow converts confirmed experience into a candidate and then an authorized write. The current policy interfaces do not automatically select or accept memories.

```text
Confirmed Event
  ↓
MemoryProposal
  ↓
Host-installed MemoryDecisionEngine policy (formal D3; opt-in)
  ↓
MemoryDecisionAuthority-issued decision
  ↓
MemoryWriteRequest
  ↓
MemoryPersistence
  ↓
Long-term Storage
```

**Formal D3 is implemented, without a default autonomous policy.** `cognition/consolidator.py::MemoryDecisionEngine.decide()` invokes an explicitly supplied policy with a stable ID/version, `MemoryDecisionAuthority`, timeline-bound EventHistory and RuntimeWriteFence. No installed policy still raises `NotImplementedError`; missing boundaries, absent source Event, invalid original permit, mutated Proposal, policy exception or unsupported output fail without an accepted write. The engine is no longer an unconditional placeholder.

The installed policy receives immutable `MemoryDecisionInput/v1`: owner/type, Proposal identity/schema/digests, bounded canonical JSON content, source Event references with the narrow `event_history_reference_present` status, Timeline/session/generation, logical identity and predecessor. JSON content/metadata normalization is bounded to 4,096 nodes, depth 24 and 65,536 UTF-8 bytes per encoded value; metadata is digest-bound but is not supplied as an unrestricted Store view. Source presence at decision time is not full historical verification; final formal persistence verifies the fence-bound canonical EventHistory lineage. No Character grant, all-owner Store scan or default semantic importance algorithm is implemented by this input.

Only exact `MemoryPolicyOutput/v1` with `accepted`, `rejected` or `deferred`, finite importance in [0, 1] and a bounded reason code is admitted. Accepted calls are sealed by the engine-only Authority path with typed `MemoryDecisionProvenance/v2`; Factory and Persistence independently revalidate before a Memory/v2 write. Rejected/deferred calls create no Memory, durable decision log or automatic retry. Policy identity/version must be nonempty host-installed values; the engine does not provide a general policy-version registry or prove policy semantics.

**Separate compatibility interfaces:** `ImportanceEvaluator.evaluate()` still raises `NotImplementedError` until replaced. The old `MemoryConsolidationPipeline` uses that interface and, even with an injected evaluator, returns an unsealed non-accepted MemoryDecision; it is not the formal D3 orchestrator. `MemoryDecisionAuthority.issue(accepted=...)` remains a caller-outcome compatibility capability used by legacy Memory/v1 write paths and tests. It does not run a policy or produce formal v2 provenance. These are process-local issuance seals, not standalone cryptographic signatures; persistence/snapshot signatures are separate.

Source checks and formal/legacy behavior are exercised by existing `test_memory_decision_policy.py`, `test_memory_write_factory.py`, `test_memory_persistence.py` and `test_save_restore_end_to_end.py`. This documentation repair inspects those tests without running them. Automatic consolidation, compression, forgetting and a general production importance policy remain absent.

---

# 9. Importance Evaluation

Future importance policies may consider:

- emotional impact;
- relationship change;
- world impact;
- future relevance;
- causal importance.

Low importance example: Player drank water. It may disappear.

High importance example: Player saved NPC's life. It should become permanent memory.

---

# 10. Memory Does Not Create Facts

Memory cannot invent history.

Incorrect:

```text
AI thinks NPC likes player
  ↓
Save as fact
```

Correct:

```text
Confirmed Event
  ↓
Memory Consolidation
  ↓
Long-term Memory
```

MemoryPersistence requires the source Event to exist in EventHistory before committing. EventMemoryProposalFactory itself accepts an Event and explicit context without querying EventHistory; MemoryFormer and ShortTermMemoryFormation do verify their Event against history. ObservationMemoryFormer preserves the source Event reference, with existence checked at persistence.

---

# 11. Event Source Preservation

Important memories must maintain their source.

```json
{
  "type": "relationship_change",
  "content": {
    "trust": 30
  },
  "source_event": "event_001"
}
```

Purpose: allow the system to answer, “Why does this NPC trust me?”

---

# 12. Causal Preservation

Causal relationships must not disappear during compression.

Original:

```text
Player rescued NPC.
NPC became grateful.
NPC later helps player.
```

Compressed memory:

```text
NPC trusts player because player previously rescued them.
```

The causal chain remains.

---

# 13. Forgetting Mechanism

CognitiveWorld simulates human-like forgetting. Forgetting applies mainly to short-term details and low-value memories.

Memory decay factors:

```text
Importance
+ Frequency
+ Future relevance
- Time decay
```

---

# 14. Memory Deletion Rules

Memory may be:

## Deleted

For meaningless details. Example: Player walked through hallway.

## Compressed

For repeated experiences.

Before:

```text
Player visited shop three times.
Player bought items.
Player talked with owner.
```

After:

```text
Player has a familiar relationship with the shop owner.
```

## Preserved

For:

- major events;
- relationship changes;
- world facts;
- causal links.

---

# 15. Character Memory vs World Memory

These must be separated.

## World Memory

Objective reality.

Example: Player did not betray NPC.

## Character Memory

A character's belief.

Example: NPC believes player betrayed them.

Characters may have misunderstandings, incorrect beliefs, and incomplete information.

---

# 16. Memory Access

Memory retrieval is relevance-based and bounded to the active Character's references.

Not:

```text
Load all history
```

Instead:

```text
Current Situation
  ↓
Relevant Memory Search
  ↓
Context Injection
```

When the player meets an NPC, retrieve previous meetings, relationship changes, and important events; ignore unrelated history.

## 16.1 Phase 12.2 Retrieval Contract

`MemoryRetriever` is a replaceable read strategy over the canonical `MemoryStore`. The production call path is `AgentTurn` → `CognitionContext` → Retriever: CognitionContext supplies only IDs referenced by its bound Character and revalidates every returned ID, owner, and canonical source before producing immutable `MemorySnapshot` values. The snapshot retains the Memory ID, owner, type, content, importance, metadata, and complete `source_event` ID. Retrieval cannot mutate the Store or consult WorldState. The low-level Retriever consumes an ID scope supplied by its caller; this is an application boundary, not authentication against malicious code in the same process.

The initial ranking is deterministic and explainable: lexical token overlap between the query and explicit textual Memory content is primary. For equal overlap, the existing finite `importance` is compared only when every candidate in that tie group has a valid value; otherwise stable Memory ID order breaks the tie. This is not a truth score or confidence estimate. Memory has no reliable creation-time or emotional-salience field, so the strategy does not invent recency or emotional scores. Missing optional attributes never become synthetic ranking values.

Memory content remains subjective recollection or belief. Its source Event ID records provenance but does not make the content objectively true. Retriever results remain L3 inputs and do not create WorldState facts or new Memory records.

`AgentTurn` can form a query from current Percepts, WorkingMemory cues, active Goals, and Beliefs. The replaceable L5 policy may request a distinct follow-up only when an earlier search returned no match. The default policy permits at most two retrievals and two review rounds, and caps each result batch at five; repeated queries are skipped. Missing cues, exhausted budgets, or no match preserve uncertainty. L5 has no persistent Store and cannot directly update Beliefs, Goals, Memory, or SelfModel.

---

# 17. Memory Authority

Authority order:

```text
Confirmed Events
  ↓
Long-term Memory
  ↓
Short-term Memory
  ↓
AI Interpretation
```

AI interpretation cannot override confirmed history.

The ordering above describes how confirmed Events may support governed Memory formation; it does not mean every Memory's subjective content is objectively true. `source_event` is provenance, not a truth certificate. Relevance ranking determines what may be recalled for a DecisionContext, not what happened in WorldState.

## 17.1 Implemented Write Authority

`MemoryProposal` is the sole candidate data model. `MemoryCandidate` and the result property `memory_candidates` are compatibility aliases over this type.

Formation adapters have separate inputs but converge on that one model:

- `EventMemoryProposalFactory`: Event plus explicit owner/context to MemoryProposal; no EventHistory lookup at this boundary.
- `MemoryFormer`: EventHistory-confirmed Event to a raw MemoryProposal.
- `ObservationMemoryFormer`: Observation to MemoryProposal while retaining observer and source Event references.
- `ShortTermMemoryFormation`: EventHistory-confirmed Event to ShortTermMemory; it does not create long-term Memory.

The protected persistence path is:

```text
MemoryProposal
  ↓
MemoryDecisionAuthority-issued accepted MemoryDecision
  ↓
MemoryWriteFactory-issued MemoryWriteRequest
  ↓
MemoryPersistence validates snapshots and EventHistory source
  ↓
MemoryStore internal commit
```

The write request snapshots the proposal, decision fields, source references, and Memory fields. Modifications or mismatches are rejected before persistence. For formal D3, the Authority seals only the engine-bound policy call; the legacy public `issue(accepted=...)` has the narrower Memory/v1 role described in section 8. `MemoryConsolidator` remains two compatibility names: `memory.consolidation` aliases EventMemoryProposalFactory; `cognition.consolidator` aliases the implemented, explicitly configured MemoryDecisionEngine. Neither alias adds automatic consolidation.

Memory remains separate from WorldState and EventHistory. **SelfModel has a narrow opt-in, owner-scoped tentative evolution path; Personality still has no governed runtime evolution path.** AgentTurn invokes an explicitly injected SelfModel review only over this turn's newly L1-consumed trusted Observations. The builder checks observer, Observation provenance, Percept/content/source pairing and the CognitiveRuntime consumption receipt. An untrusted review may propose a self-belief, not establish a fact or change identity/capabilities/limitations.

The production path is `SelfModelUpdateProposal → CognitiveUpdateValidator → CognitiveUpdateApplier → SelfModelStore.update`. AgentTurn supplies allowed Observation/Event pairs; the validator issues proposal-bound authorization, and Applier/Store check owner, unchanged prior self-beliefs, original permit when Runtime-bound, capacity and duplicate evidence. Only a source-linked `status="tentative"` self-belief is appended; other fields and Personality stay unchanged. Provider absence/failure or invalid/unsupported evidence preserves the prior model. Existing `test_self_model_evolution.py` covers owner/new-L1/forgery/replay/failure and Personality isolation; `test_runtime_write_fence.py` covers current versus stale SelfModel permits. A validator call with an arbitrary context is not by itself proof of trusted L1 consumption.

Persisted SelfModel fields use the existing canonical snapshot/owner/source and isolated restore checks; transient review work, Observations and consumption cursors are excluded. A real restored Runtime still requires its existing Timeline/session/generation and publication boundaries. The tests above are not a SelfModel-specific real-model, cross-process delayed-review/restore acceptance or a proof that tentative claims are true. Broader evolution/restore acceptance remains future work in the existing cognition/recovery roadmap; it is not inferred from Personality storage or snapshot round-trip.

WorldState initialization methods remain reserved for trusted initialization/restoration and close when SimulationRuntime starts or before EventProcessor invokes its first handler; runtime Event updates require the EventProcessor capability. These boundaries constrain supported application calls, not malicious same-process Python.

## 17.2 Record, provenance and snapshot versions

Use the source-checked [compatibility matrix in DATA_CONTRACTS.md](DATA_CONTRACTS.md#memory-record-provenance-and-snapshot-compatibility-source-checked) as the version reference. Memory/v1 keeps its seven-field persisted representation and no decision provenance/revision links. Memory/v2 carries the full eleven-field representation and may decode either typed Provenance/v1 or Provenance/v2; the former is retained representation/snapshot compatibility, while current formal Factory/Persistence writes issue only Provenance/v2. Constructor/codec acceptance or a signed snapshot never substitutes for current write authorization. Both v2 combinations carry logical/revision identity rules; neither upgrades old Memory/v1.

CognitiveStateSnapshot v3 is an outer cognition container version, not a synonym for Memory/v2 or Provenance/v2. It can preserve mixed admitted Memory records; the legacy Snapshot v2 reader accepts Memory/v1 only. Decoding, signature/structure validation, Event/owner/revision checks, isolated reconstruction and Runtime publication are separate gates. No restore replays a policy call, fabricates provenance or rewrites old signed bytes. The matrix identifies exactly where compatibility tests use trusted synthetic snapshot fixtures instead of a formal new-write path.

Compatibility is not archival-only: a restored v2/Provenance-v1 record may be re-captured and, when explicitly Character-linked, owner-matched and semantically retrievable, read as subjective Memory by the normal decision-context path. That path has no provenance-version exclusion and does not turn the record into a new D3 authorization; its MemorySnapshot projection is not an issuance proof. Source permits this use, while a dedicated post-restore AgentDecision test for this exact combination remains unverified. Keep codec/capture/restore, decision input and formal new-write claims separate as specified in the matrix.

---

# Final Principle

> Remember what changes the future.

> Forget what does not matter.

> Preserve causes, not just results.

> Memory supports the world; memory does not create the world.

## Phase 12.3 Emotion Use of Memory

Emotion appraisal may use only owner-scoped `MemorySnapshot` records already
retrieved through `CognitionContext`/`MemoryStore` and included in that Agent's
frozen `DecisionContext`. An individual typed EmotionReaction may require an
exact Memory ID as contextual support. The policy does not search another
Agent's records, read `WorldState`, create Memory, or treat Memory relevance or
subjective content as objective truth. Memory IDs and source Event provenance
remain attached to the snapshot; appraisal proposals retain the current
Percept and source Event references that actually triggered the evaluation.
Emotion remains dynamic cognition state and is not written as a new Memory by
this phase. Longer-term emotional learning requires a separately governed
Memory/Cognition proposal and is not implemented here.

## Phase 12.4 Decision Use of Memory

`AgentDecision` receives only the immutable `DecisionContext` assembled by
`AgentTurn`. Long-term recollections are the owner- and Character-scoped
`MemorySnapshot` values returned through the existing `CognitionContext` and
`MemoryStore` retrieval path; Phase 12.4 adds no Memory Store or alternate
retrieval authority. Situation assessment retains each Memory ID and source
Event ID while presenting its content as that Agent's recollection.

Memory may influence candidate relevance and a character's subjective
expectations. It does not prove that the recollection is objectively true,
change WorldState, create an Observation, or establish another Agent's
knowledge. The evaluator uses deterministic lexical overlap only; it does not
invent recency, emotional salience, or confidence fields that Memory does not
provide. An optional language-model provider receives only the bounded
character-local decision view supplied for that turn, never direct Store or
WorldState access. Model output remains an untrusted attempt proposal and
cannot write Memory or upgrade a recollection into a world fact.

## Phase 12.5 Resolution and Memory Boundary

Resolution may consult only objective world-state evidence needed for the current attempt. It does not read private MemoryStore records and does not write memories. After EventProcessor confirms an effect, each Agent receives only an Observation authorized for that Agent; memory formation remains within the existing owner-scoped Perception/Cognition and Memory proposal/write path. A failed, unresolved, or merely expected outcome is not an experience to consolidate as a confirmed fact. Subjective recollection may inform a character's proposal, but it cannot replace current WorldState evidence during causal adjudication.

Phase 12.5B stepwise plans retain intended methods and conditions only. They do not become Memory or confirmed experience. A later step is gated on an owner-scoped CognitionContext containing a trusted Observation of the prior Event; any recollection remains within the existing Observation-to-Cognition and Memory governance path. Resolution providers receive no MemoryStore or other Agent's private cognition.

This ownership boundary also applies to future Entity-state causal domains: a cognitive/physiological domain cannot bypass owner-scoped Observation and cognition proposal/validation/apply governance, and physical adjudication cannot use another Agent's private recollection as objective evidence. The future domain direction is recorded in `docs/ARCHITECTURE.md`; it does not create a new Memory or cognition authority.

## Phase 12.5C Safety, Norms, and Character Knowledge

Universal content-safety assessment is not a character experience. A blocked or clarification-required input must not be added to WorkingMemory/Long-term Memory as an Event, crime, punishment, NPC reaction, or confirmed consequence. It may be retained only as non-world operational telemetry outside character cognition if a future host adds a separate privacy-reviewed channel.

WorldNorms are objective world rules, not automatically shared character knowledge. Even a public law entry does not become every NPC's Belief, Memory, or Percept. An Agent may rely on a norm only through its own initialized knowledge or an Observation authorized for that Agent, followed by the normal five-layer cognition path. Hidden laws and other Agents' private knowledge must not be copied into another Agent's DecisionContext. A norm change Event alone does not imply every character observed it.

Safety is independent of in-world legality and moral judgment. A lawful or unlawful act can be considered by character Cognition and Resolution without Safety creating a moral belief, shame, guilt, forgiveness, or reconciliation. Resolution never writes those subjective updates; they remain within owner-scoped cognition proposal/validation/application governance.

Phase 12.5D safety identity fields are objective WorldState Entity configuration, not Personality, Belief, Memory, SelfModel, or Observation. A safety block/clarification must not be recorded as an experienced Event, crime, punishment, relationship change, or character memory. Safety reads only the bound actor/target identity and typed profile; a character learns about laws or another person's attributes only through its own authorized cognition path. The P0 and cross-project narrative policies are defined in `docs/ARCHITECTURE.md` and the contracts in `docs/DATA_CONTRACTS.md`.

## Phase 12.6 Autonomous Turn Isolation

`AutonomousWorldRunner` requests an owner-specific `CognitionContext` for each
registered Agent and delegates snapshot assembly and cognition updates to the
existing `AgentTurn`/`CognitiveRuntime`. It does not construct a shared
DecisionContext or inspect another Agent's private Memory, Belief, Goal,
Emotion, or SelfModel records. Runtime reports contain IDs/counts and bounded
proposal diagnostics only; they are developer-facing, not Memory or player
projections. A committed Event becomes another Agent's experience only through
that Agent's separately authorized Observation and L1 consumption. An
unresolved attempt is not a confirmed experience.
## Phase 13 template and instance isolation

Character templates may propose initial goal descriptions and capabilities, but cannot contain another instance's Memory, Belief, Emotion, Relationship or private experiences. Each instance initializes an owner identity in the existing cognition authority. `SeedOpportunity` is derived only from that owner's authorized Observation; it is not a Memory record or an objective Event. Event seeds do not add experiences until the established Observation and cognitive update path does so.

Phase 14 model content input remains a creative brief rather than an Agent DecisionContext or WorldState dump. Its strict output schema contains reusable template definitions and has no Memory, Belief, Emotion or perceived-event fields. Generated initial Goal text is instantiated per owner; it does not copy another character's experiences. Model prose cannot create a Percept or assert that an Agent learned a fact. Each Agent still needs authorized Observation and normal cognitive governance.

## Phase 15 Scenario knowledge boundary

Scenario lifecycle state and `EventSeed` definitions are world/content records, not an Agent's knowledge. Entry mechanism facts reach a character only after the existing VisibilityPolicy authorizes an Observation and L1 consumes it. `ScenarioSeedScheduler` reads only that owner's authorized Observation to schedule attention; the Seed does not create a Memory, Belief or chosen action. Exiting or aborting a Scenario does not erase already confirmed experiences. Runtime instance state must never flow backward into reusable templates or into another Agent's private cognition.

## Phase 16 dynamic character cognition

Runtime installation prepares fresh Personality, SelfModel and Goal records for each new CharacterInstance, then places them in the existing owner Stores. A new Agent is registered only after its owner cognition is prepared. No Memory, Belief, Emotion, Relationship, injury, DecisionContext or private experience is copied from the CharacterTemplate or another instance. The installation Event is a world-content admission record, not a character's perceived experience; the EventProcessor produces no automatic Observation for it. Only subsequently authorized entry/environment or causal Observations may reach L1 and later Memory governance. Provider output and installation audit labels must never be treated as character knowledge or player-facing narration.
