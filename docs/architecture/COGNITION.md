# CognitiveWorld — Owner Cognition and Decision

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Owner cognition and decision.

## Authority and scope

**Frozen authority level:** Domain architecture; Memory and social semantics stay specialized owners.

**Assigned responsibility:** Store responsibility, qualification/consumption, governed belief/goal changes, bounded scoring.

Only marked Phase 3B/3C excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A16 — Belief meaning and contextual use in decisions**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A23 — Governed Goal updates and completion**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A27 — Cognitive functional and compute levels**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A29 — Egocentric spatial representation**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A30 — Allocentric representation and subjective spatial cognition**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A36 — Operation-specific cognitive governance architecture**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- Canonical world facts and formal world-event submission.
- Detailed Memory and social-causality definitions owned by their existing specialized documents.
- Record formats, durable consumption-proof protocols and persistence guarantees.

## Migrated excerpts and pending section outline

Marked Phase 3B and Phase 3C sections contain only approved source excerpts. All other ranges remain pending. Original stage/status labels are not new capability or test claims.

### ID 4 — Behavior Adaptation — current verified boundary

<a id="arch-source-4"></a>

<!-- phase3c-begin:C-4-29-33 -->

<a id="arch-source-4-part-1"></a>

**Phase 3C source excerpt:** ID 4, lines 29–33 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-4-29-33:29-33 -->

Behavior Adaptation v0.1–v0.3a established a narrow locked-door failure signal: only a Resolution-confirmed, EventProcessor-committed failed Attempt may affect the acting owner's feedback; the failed Event has no WorldUpdate and does not alter WorldState slot provenance. Its signed Attempt projection and cited condition evidence are checked before commit. Event commit and feedback application share the RuntimeWriteFence commit scope; an application failure after Event append enters recovery-required isolation.

v0.3b adds BehaviorFeedbackSnapshot v1 as a signed SnapshotBundle v2 component. SaveManager captures it under the same snapshot scope; isolated reconstruction verifies each failure against the signed Event/Attempt projection and the cited processor-issued observation evidence. Legacy Bundle v1 is explicitly legacy_not_captured, not interpreted as a failure-free past. Child timelines reconstruct independent mutable feedback state.


<!-- phase3c-end:C-4-29-33 -->

<!-- phase3c-begin:C-4-35-37 -->

**Phase 3C source excerpt:** ID 4, lines 35–37 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-4-35-37:35-37 -->

The legacy v1 branch remains a narrow, exact-structure locked-door adaptation mechanism. The additional [consumed physical-failure feedback v2](../DATA_CONTRACTS.md#consumed-physical-failure-feedback-v2) branch handles the configured door interaction-reach result only after owner-authorized Observation, current per-item L1 qualification, actual consumption and verified proof publication. An old receipt cannot replace current qualification. Its scoring applicability is rechecked against canonical current state; restore validates the saved proof bindings without re-consuming or re-signing history. It does not establish general behavioral learning, semantic action similarity, broad outcome feedback, or personality change. Feedback does not write Goal, Emotion, WorldState or EventHistory. See DATA_CONTRACTS.md and REPOSITORY_STATUS.md for the persistence and acceptance boundary.


<!-- phase3c-end:C-4-35-37 -->


### ID 22 — Endogenous dynamics: the current Why path

<a id="arch-source-22"></a>

<!-- phase3c-begin:C-22-246-252 -->

<a id="arch-source-22-part-1"></a>

**Phase 3C source excerpt:** ID 22, lines 246–252 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-22-246-252:246-252 -->

`Goal` is an owner-held objective with priority/status and optional structured resource demands. It is one input to dynamics, not a complete state of need, intent, pressure or objective distance-to-goal. `AgentTurn.prepare_decision_context` reads owner-authorized cognition, performs bounded retrieval, and derives `MotivationAssessment` and `DecisionModulation`. The current policy uses active Goal priorities, configured personality/emotion weights, configured Goal-tension pairs and SelfModel capability requirements. “Blocked” therefore describes that narrow subjective capability test, not a general proof of physical obstruction or a measurement of resource/time pressure.

`AgentDecision` forms a `SituationAssessment` and candidates, then the installed `ConflictOpportunityScheduler` discovers configured owner-local Goal tensions, observed affordance opportunities and the separate Runtime-verified cross-Agent resource-demand comparisons. The scheduler can add bounded relevance to existing linked candidates. It cannot create a Goal, force a candidate, decide another NPC's beliefs or guarantee an opportunity succeeds. Shared resource identity/exclusive demand is not proof of actual scarcity, occupancy, hostility or cooperation. Knowledge asymmetry remains: a trusted system comparison does not grant an NPC the other owner's private Goal or evidence.

The existing Core has a narrow scheduled loop: due Agent → authorized context → motivation/candidates/findings → AgentDecision selection → ordinary Attempt/Resolution/EventProcessor → new state and authorized Observation → later scheduled turn. The host must drive `SimulationRuntime.run_step` and schedule subsequent turns; the desktop host currently creates schedulers but does not implement a continuous autonomous-world driver. General goal-versus-reality gap measurement, resource/deadline pressure, Event-driven Goal lifecycle updates, cooperation discovery, durable finding lifecycle and a unified endogenous-dynamics loop are not established. The earlier Narrative Pressure Layer is a design umbrella; the concrete scheduler and opt-in `content.expansion` coordinator are partial foundations, not an installed global narrative director. Content expansion requires an explicit host need policy/factory and uses existing content validation/installation Events; no default policy generates a plot or new entity.


<!-- phase3c-end:C-22-246-252 -->


### ID 24 — Task-driven information and production context

<a id="arch-source-24"></a>

<!-- phase3c-begin:C-24-264-278 -->

<a id="arch-source-24-part-1"></a>

**Phase 3C source excerpt:** ID 24, lines 264–278 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-24-264-278:264-278 -->

The approved flow is **task/recipient binding → need analysis → scoped retrieval → authorization and freshness checks → relevance/sufficiency review → bounded structured model context → explicit gap disposition**. Authorization restricts searchable sources before any private text reaches a Provider and is rechecked on returned candidates and before use. Finding one relevant Memory is not proof that all task preconditions are known. No uniform production-context service currently implements this full flow.

| Existing seam | What can be reused | Contract still needed |
|---|---|---|
| `AgentTurn` / `CognitionContext` / immutable `DecisionContext` | L1-consumed owner Observations, linked canonical cognition and bounded L5 Memory queries; no Store reference enters the decision snapshot | General task identity/need vocabulary, per-condition sufficiency and aggregate context/Token accounting. Current L5 stops after a matching query and retains uncertainty when none matches. |
| `MemoryRetriever`, `HybridMemoryRetriever`, `MemoryEventIndex` | Owner/Character ID scope, canonical Store rechecks, optional local embeddings and verified current L1 Event anchors | General entity/temporal/causal retrieval, semantic sufficiency, cross-channel evidence fusion and spreading activation. An index hit is not truth, a grant or a mechanism. |
| `AuthorizedStateQuery` / `AuthorizedQuerySession` | Bounded current-actor Observation evidence for an Attempt; source/tick/visibility checks | A task-wide source plan and gap lifecycle. EventHistory verification authenticates history; it does not expose all Events to the NPC/model. |
| `InteractionStateAggregator` / installed causal policies | CPU-only Attempt-bound canonical physical reads and verified effect preconditions | General structure/material/force models and safe review of unmodeled mechanisms. These internal objective reads do not grant NPC knowledge. |
| Player service / pending clarification / read-only Presentation result | Session/generation-bound handles, finite follow-up state and trusted Observation re-projection | A generic information planner must preserve these contracts rather than using UI text concatenation or a new parallel result path. |

NPC decision tasks may receive only the owner's current authorized knowledge and explicitly distinguished beliefs/inferences. A system/world-planning task needs a separately host-issued purpose and source capability; even a wider system view cannot be copied into an NPC prompt or treated as an Observation. The current cross-Agent resource projection is one narrow system capability, not a general world-model prompt. Keep objective evidence, subjective cognition, installed causal rules, hypotheses and candidate futures distinct, with provenance, temporal scope and uncertainty. Narrative text cannot supply authoritative state. Database presence is neither permission nor relevance; relevance is not permission either. Context construction must bound query work, candidates and model input; the general Token/latency envelope remains proposed.

Future LLM-proposed information needs are a later extension to this CPU foundation: the model may request a structured information type, while CPU policy checks caller, source class, necessity, cost and permissions, performs or declines retrieval, and filters the result again. The requestor gains no access by asking. Optional dual-LLM isolation does not replace this policy and is not a current MVP dependency. Task/context/exploration state is transient unless an explicitly reviewed persistence contract includes it; current Bundle v2 excludes provider work, scheduler/tree diagnostics and pending clarification. World replacement or restore invalidates old results under the original Runtime permits. The signed Event/ancestor, cold-resume and publication contracts remain mandatory for every real effect.


<!-- phase3c-end:C-24-264-278 -->


### ID 27 — Cognition Layer

<a id="arch-source-27"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 27, lines 337–339. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 337–339

<!-- phase3b-source:27:337-339 -->

The Cognition Layer simulates the cognitive structures of individual characters. It does not store world state, execute events, or directly modify reality.

### ID 28 — Personality

<a id="arch-source-28"></a>

<!-- phase3c-begin:C-28-341-349 -->

<a id="arch-source-28-part-1"></a>

**Phase 3C source excerpt:** ID 28, lines 341–349 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-28-341-349:341-349 -->

Personality describes a character's relatively stable tendencies, including:

- personality traits;
- behavior preferences;
- value orientations.

Personality is not an Entity field. Entity represents an existence in the world; personality belongs to a character with cognitive capabilities.


<!-- phase3c-end:C-28-341-349 -->


### ID 30 — Belief

<a id="arch-source-30"></a>

<!-- phase3c-begin:C-30-360-362 -->

<a id="arch-source-30-part-1"></a>

**Phase 3C source excerpt:** ID 30, lines 360–362 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-30-360-362:360-362 -->

Belief represents a character's cognition of the world. A character's belief may differ from the actual WorldState.


<!-- phase3c-end:C-30-360-362 -->


### ID 31 — Cognitive governance: three independent judgments

<a id="arch-source-31"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 31, lines 364–374. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 364–374

<!-- phase3b-source:31:364-374 -->

Approved architectural principle: keep **rule compatibility**, **cognitive credibility**, and **world-fact qualification** independent. The aim is to govern the consequences of cognition, not to eliminate every mistaken Belief or imaginative thought.

- **Rule compatibility:** determine whether a proposed world claim or executable effect is compatible with applicable hard constraints and declared capabilities. A contradiction cannot be accepted as a valid world-state claim or authorized executable effect. The occurrence of that thought in a character's cognition is a different matter: impossible or irrational ideas may remain subjective cognitive/narrative content unless an explicit applicable constraint prohibits them. A character's mistaken intention is not permission to bypass a hard rule. Distinguish attempting an allowed action whose desired outcome cannot succeed from asserting that the impossible outcome occurred.
- **Cognitive credibility:** assess what this character has reason to believe from its own information and applicable interpretation policy. A rule-compatible, plausible hypothesis may remain unverified. Eligible uncertainty, imagination and mistaken interpretations may influence attention, risk, Goals, information-seeking or action selection without becoming established facts. Model confidence, plausibility, repetition and lexical similarity are not independent factual evidence; subjective confidence is not calibrated truth probability.
- **World-fact qualification:** only applicable authorized, validated formal world-transition mechanisms can commit canonical changes. Neither compatibility, confidence nor supporting evidence substitutes for source, owner, information authorization, history, Runtime and EventProcessor requirements. Cognitive governance acceptance authorizes the supported cognitive update; it does not certify its content as objective truth.

The conceptual lifecycle is hypothesis/interpretation/intention or action-candidate generation (possibly by an LLM) -> applicable compatibility and cognitive governance -> eligible subjective influence -> ActionProposal/Attempt -> Resolution -> valid formal Event submission and EventProcessor commit -> recipient-authorized Observation -> actual qualified consumption -> supported cognitive review/revision -> later decisions. These are responsibility boundaries, not a new universal API or schema. Imagined events, intended actions, attempted actions, committed outcomes, received evidence and interpretations remain distinguishable. Revision cannot retroactively rewrite the source facts, evidence or historical authorization.

Current implementation is narrower than this principle. Typed contextual Belief matching handles exact owner-consumed, history-qualified confirmed-failure bindings with bounded scope/age; formal physical candidate revalidation, private physical-result Observations, ordinary L1 qualification and opt-in existing-Belief Validator/Applier review provide real separate boundaries. The contextual matcher intentionally gives unsupported/ambiguous matches no typed score; the principle does not relax that gate or add a hypothesis write path. General compatibility checking for arbitrary natural-language hypotheses, calibrated credibility and comprehensive handling of impossible or irrational cognitive content remain incomplete. This is not a complete scientific cognition model or a claim to eliminate LLM hallucinations. [Current typed matching contract](../DATA_CONTRACTS.md#typed-contextual-belief-decision-view).

### ID 32 — Goal

<a id="arch-source-32"></a>

<!-- phase3c-begin:C-32-376-378 -->

<a id="arch-source-32-part-1"></a>

**Phase 3C source excerpt:** ID 32, lines 376–378 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-32-376-378:376-378 -->

Goal represents a character's current objectives and motivations.


<!-- phase3c-end:C-32-376-378 -->


### ID 33 — Emotion

<a id="arch-source-33"></a>

<!-- phase3c-begin:C-33-380-382 -->

<a id="arch-source-33-part-1"></a>

**Phase 3C source excerpt:** ID 33, lines 380–382 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-33-380-382:380-382 -->

Emotion represents a character's short-term psychological state.


<!-- phase3c-end:C-33-380-382 -->


### ID 34 — Cognition Store Ownership

<a id="arch-source-34"></a>

**Phase 3B migration:** direct body only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 34, lines 384–386. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 384–386

<!-- phase3b-source:34:384-386 -->

`CognitionContainer` is a compatibility facade: Personality, Belief, Goal, and SelfModel records are owned by their dedicated authoritative Stores and the container delegates reads/writes instead of keeping duplicate copies. Emotion remains container-owned. Long-term Memory is owned only by `MemoryStore`; CognitionContainer does not store Memory. `CognitiveRuntime` builds transient CognitionState and maintains WorkingMemory through its WorkingMemoryStore. Its optional direct Belief/Goal/SelfModel Store inputs remain for legacy callers; AgentTurn obtains authoritative snapshots through CognitionContext.

### ID 35 — Cognitive LOD (Approved Design, Not Implemented)

<a id="arch-source-35"></a>

<!-- phase3c-begin:C-35-388-394 -->

<a id="arch-source-35-part-1"></a>

**Phase 3C source excerpt:** ID 35, lines 388–394 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-35-388-394:388-394 -->

Cognitive Level of Detail allocates reasoning resources dynamically according to NPC importance, player interaction needs, relevance to current events, and available cognition-compute budget. Future scheduling may include a reasoning priority queue, dynamic NPC wake-up, batched background updates, and upgrades or downgrades in reasoning precision.

All precision levels operate on the same authoritative cognition Stores and canonical state. Lower precision may reduce update frequency or reasoning granularity, but must not discard an already-confirmed important Event or its resulting experience. Returning to higher precision may reconstruct analysis from recorded facts and existing cognition, but must not invent objective Events or character experiences that did not occur. LOD controls computation only; it grants no authority to alter WorldState or confirm Events.

Cognitive LOD does not add or redefine cognition layers: L1 Perception, L2 Working Memory, L3 Long-term Memory, L4 Beliefs & Self-Model, and L5 Metacognition remain the same. Emotion and Motivation remain cross-layer modulators. Cognitive LOD and Causal LOD are separate design concerns and must not be conflated. Every item in this section is approved future design, not implemented behavior.


<!-- phase3c-end:C-35-388-394 -->


### ID 36 — Cognition Update Validation Layer

<a id="arch-source-36"></a>

**Phase 3B migration:** selected direct-body ranges only. Source: [ARCHITECTURE.md](../ARCHITECTURE.md), ID 36, lines 396–428. Child sections and deferred lines are not included.

#### Migrated excerpt — source lines 396–428

<!-- phase3b-source:36:396-428 -->

Cognition state changes must not directly modify stored cognition data. Changes are first represented as proposals and then checked before applying them:

```text
BeliefUpdateProposal
  ↓
CognitiveUpdateValidator
  ↓
CognitiveUpdateApplier
  ↓
BeliefStore
```

```text
GoalUpdateProposal
  ↓
CognitiveUpdateValidator
  ↓
CognitiveUpdateApplier
  ↓
GoalStore
```

```text
MemoryProposal
  ↓
Memory decision and write authorization
  ↓
MemoryPersistence
  ↓
MemoryStore
```

### ID 40 — Agent Decision

<a id="arch-source-40"></a>

<!-- phase3c-begin:C-40-472-500 -->

<a id="arch-source-40-part-1"></a>

**Phase 3C source excerpt:** ID 40, lines 472–500 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-40-472-500:472-500 -->

Agent Decision receives Cognition State, Goal, Emotion, Relationship, and Belief:

```text
Cognition
  ↓
Action Proposal
  ↓
Attempt
```

Both flows continue through:

```text
Attempt
  ↓
Resolution
  ↓
Event
```

Player Decision and Agent Decision remain distinct up to their common Attempt boundary.

Phase 12.1 extends `AgentTurn`'s owner check into a deep immutable `DecisionContext` snapshot. L1 is populated only from Percepts created from verified, owner-matched Observations; L2 is the owner's isolated WorkingMemory snapshot; the initial L3 input included Memory records referenced by that Character and owned by the same Agent; L4 includes owner-scoped Beliefs, Goals, Personality, and SelfModel; Emotion remains cross-layer input. Source references remain attached to Percepts, Memories, Beliefs, and Goals so subjective claims are not reclassified as objective world facts. The snapshot contains no Store or WorldState references and rejects mixed-owner records.

Phase 12.2 adds owner- and Character-reference-scoped retrieval over the existing `MemoryStore`. `MemoryRetriever` ranks only supplied Character-linked IDs by deterministic lexical overlap, then by stored finite importance when every record in an equal-overlap group has a valid value, and otherwise by ID; it returns immutable snapshots preserving each source Event ID. Importance and relevance do not establish truth or confidence. No time or emotional-salience scoring is claimed because `Memory` has no such fields.

`AgentTurn` now provides bounded L5 retrieval feedback through a replaceable `MetacognitionPolicy`; the default `BoundedMetacognitionPolicy` may request a distinct second query only when the first search found no matching memory. A per-turn hard bound is two retrievals, two feedback rounds, and five results per query; duplicate queries are skipped, and exhausted/no-cue cases preserve uncertainty. Feedback is turn-local and cannot write cognition Stores. Memory retrieval reads the canonical Store without mutation. Phase 12.2 represented Motivation through Goals; Phase 12.3 adds a derived MotivationAssessment and DecisionModulation without changing persistent Goal values or adding a cognition layer. Phase 12.4 adds a bounded autonomous proposal policy for `DecisionContext`. Direct `CognitionState` and Mapping inputs retain the legacy placeholder proposal. `AgentActionLoop` preserves its historical placeholder path for an uncustomized base `AgentDecision`; explicitly supplied policies and AgentDecision subclasses use the DecisionContext strategy path. `AgentTurn` continues owner-scoped snapshot assembly before dispatch.


<!-- phase3c-end:C-40-472-500 -->


### ID 41 — Hybrid associative retrieval (Approved Design; Narrow Channels Implemented)

<a id="arch-source-41"></a>

<!-- phase3c-begin:C-41-502-520 -->

<a id="arch-source-41-part-1"></a>

**Phase 3C source excerpt:** ID 41, lines 502–520 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-41-502-520:502-520 -->

The approved direction extends the current lexical retriever with complementary, selectively invoked retrieval channels: exact lexical/entity lookup; semantic similarity; time/event lookup; entity and evidence-constrained causal lookup; and bounded activation spreading over a rebuildable associative index. A query need not invoke every channel. Direct and associative candidates are merged, deduplicated, and reranked with provenance and evidence state retained. A bounded metacognitive follow-up may request another search when the current evidence is missing, conflicting, or insufficient for the response need.

Keep four scopes distinct: what the current Agent is authorized to know; which derived indexes may be searched for that Agent; which records entered this query's candidate set; and which candidates fit the current DecisionContext budget. A record omitted from this turn's context is not thereby nonexistent, permanently unsearchable, or evidence of absence. Index scope never expands authorization: every candidate is re-read from canonical Memory and rechecked against the active owner/Character access contract before it can enter cognition.

The derived graph may contain entity nodes (people, places, objects, organizations, and concepts), event nodes (source, participants, time, and linked Memory records), directed causal relations, and semantic labels/relations for aliases, paraphrases, and indirect association. Anchors may come from authorized entities/events, semantic labels, and the current query. Bounded activation may spread over typed edges, but the graph is a discovery index: it does not replace canonical Memory, EventHistory, or world-fact storage and cannot establish a new fact or causal claim.

Keep record attributes separate from query-time node activation, edge propagation weight, context fit, temporal validity, and evidence reliability. A future implementation may bound hop count, fan-out, repeated-path contribution, cycle revisits, visited-node state, and total compute. Causal edges must follow direction, time, and verified source constraints; semantic edges only expand candidates and never prove causality. Activation decay is not forgetting; a low score is not permanent exclusion; a traversed path is not proof that a causal relation holds; and retrieval failure is not proof that a fact does not exist. Exact formulas and weights remain experimental rather than frozen architecture.

Candidate ranking must preserve source IDs, association path, time, authorization scope, evidence status, and known conflicts. Similarity, activation, and stored importance are relevance signals, not truth or confidence. Metacognition may request bounded additional retrieval rounds/candidates under explicit per-turn and aggregate compute budgets; it cannot write Memory or silently fill evidentiary gaps. If evidence or budget is insufficient, keep the answer uncertain or unresolved.

The index is derived and rebuildable from validated canonical records and authorized identity links. Retrieval and association do not give an NPC global WorldState access and do not mutate WorldState, EventHistory, Memory, Belief, Goal, or relationship state. Confirmed world changes still follow the existing Resolution → EventFactory → EventProcessor → WorldState path. This design may later request cognitive LOD budget, but retrieval, perception, and physical-computation policies remain separate responsibilities.

Current capability includes the Phase 12.2 lexical `MemoryRetriever` over Character-linked IDs, with immutable source-preserving snapshots and a bounded L5 follow-up. An opt-in `HybridMemoryRetriever` adds a narrow, disposable semantic candidate channel through a host-injected `EmbeddingProvider`. It rebuilds from at most 64 current authorized Memory IDs per query, keeps lexical results in their existing order, then fills unused result slots by cosine similarity with stable ID ties. The provider receives only text from owner-matched, Character-linked, semantically retrievable canonical Memory; no network or model adapter is installed by default. A timeout, invalid vector, or Runtime-generation change leaves lexical results intact. An explicitly injected `OllamaEmbeddingProvider` now supports only a validated local HTTP loopback origin and Ollama `/api/embed`; it uses bounded native batches and supplies only authorized Memory content text or the bounded query text. It does not make AgentTurn asynchronous, enable remote disclosure, or change Event/Memory authority. The index is rebuilt for each query, retains only IDs, source references, text digests and vectors, and re-reads current canonical Memory before returning a detached snapshot. This is candidate discovery, not source Event verification, a read grant, or a factual or causal judgment. A host using a slow or remote provider must separately approve its data scope and schedule the AgentTurn away from a UI main thread; the retrieval slice has no general background AgentTurn executor.

The separate narrow Event-anchored candidate locator used by `AgentTurn` is rebuilt from the current authorized Memory IDs and a completely verified Runtime EventHistory. Its anchors are issued only from a trusted Observation that matches the verified source Event and Timeline, carries the issuing Runtime's session and restore-generation binding, and has passed this turn's L1 consumption receipt. An Observation from another Runtime or an earlier restore generation cannot anchor retrieval even when its Event ID and Timeline match. Event-linked candidates are re-read from canonical MemoryStore and merged after lexical and optional semantic results under the existing result limit. Without a verified anchor, this Event channel adds nothing; a consumed Observation that cannot produce a valid anchor, or a later Runtime/history binding failure, marks it unavailable in metacognitive feedback and retains the authorized direct retrieval results. This slice does not provide natural-language event-anchor extraction, temporal search, general entity/causal links, activation spreading, cross-channel evidence ranking, or a shared global retrieval-budget coordinator. Those remain approved design only and are not implemented or tested as production capabilities.

The task-driven information section above defines the proposed need-analysis, sufficiency, context and gap lifecycle that these retrieval channels may serve. Existing bounded L5 queries are its reusable foundation, not a completed general planner. Roadmap `POST-MVP-01` stages CPU-only governance before optional model-proposed information needs; `POST-MVP-02` owns bounded alternative/future exploration. Neither depends on dual-LLM deployment or extends NPC access.


<!-- phase3c-end:C-41-502-520 -->


### ID 49 — 3.2 Cognitive Process Model

<a id="arch-source-49"></a>

<!-- phase3c-begin:C-49-618-638 -->

<a id="arch-source-49-part-1"></a>

**Phase 3C source excerpt:** ID 49, lines 618–638 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-49-618-638:618-638 -->

The cognitive process is modeled as:

```text
L1 Perception
  ↓
L2 Working Memory
  ↓
L3 Long-term Memory
  ↓
L4 Belief / Self Model
  ↓
L5 Metacognition
```

This is a process model, not a strict one-way pipeline. Bounded feedback is allowed during a decision turn (for example, a Goal may focus Perception, or Metacognition may request another relevant retrieval). Turn-local recalculation is distinct from persistent cognition evolution, which must use the existing authoritative Stores and their update governance. Existing Personality, Goal, Emotion, Belief, and Memory data models remain cross-cutting state; the process model does not replace them.

Emotion and Motivation are cross-layer modulators, not additional cognition layers. NPC decisions use all five layers through the Phase 12.4 owner-scoped SituationAssessment. Individual emotion thresholds, impulse ceilings, and growth curves come from character cognition; irrational tendencies remain bounded and context-grounded. Decision emits proposals only; Resolution determines outcomes. Phase 12.4 implements a bounded proposal policy, while the default ResolutionEngine remains unresolved without an installed world-rule policy.

The Phase 12.2 retrieval/review baseline is context preparation, not itself an autonomous action policy. Phase 12.4 adds bounded Emotion/Motivation-aware candidate ranking, but does not implement Belief/Memory truth evaluation, general contradiction resolution, persistent metacognitive learning, or changes to Resolution.


<!-- phase3c-end:C-49-618-638 -->


### ID 50 — Hybrid cognition execution levels (architectural direction; unified policy not implemented)

<a id="arch-source-50"></a>

<!-- phase3c-begin:C-50-640-644 -->

<a id="arch-source-50-part-1"></a>

**Phase 3C source excerpt:** ID 50, lines 640–644 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-50-640-644:640-644 -->

The five layers above describe **cognitive functions**, not mandatory compute tiers. A complementary three-level allocation view is: (1) deterministic fast paths for authorized fact queries, installed rule checks, known-state operations and inexpensive reactions; (2) structured cognition over owner-held Beliefs, Goals, intentions, plans, expectations, Memory retrieval, conflicts and execution monitoring; and (3) optional LLM-assisted interpretation, hypotheses, complex planning or contextual social reasoning when uncertainty, complexity, importance or causal impact warrants the cost. These levels can cooperate within one turn; they do not require separate packages, a model call for every NPC action, or a second cognition Store. A model receives only the task's authorized context and returns a proposal, never a fact or decision authority. Current deterministic decisions, bounded retrieval and opt-in model adapters are partial foundations, not a unified level-selection policy.

The intended feedback loop is authorized Perception/evidence → owner-governed Belief and Goal assessment → intention/plan and ActionProposal → authorization/Resolution → formal Event and any applicable WorldState update → authorized Observation of the actual outcome where available → comparison with the proposal's expected result → targeted Memory/Belief or method-assumption review → later decision. Its trace must retain the relevant evidence, owner, expected result, Attempt and confirmed outcome, including partial failure, unexpected effects and unresolved uncertainty. A discrepancy is a review signal, not permission to rewrite every related Belief: each update must identify the specific claim or method assumption it addresses and pass that Store's existing governance. The current locked-door BehaviorFeedback slice above establishes one narrow, persisted decision effect; it is not this general learning loop. Historical evidence and causal links needed after restore must follow the existing signed EventHistory, cognition snapshot and Timeline contracts; transient expectations or plans are not thereby durable.


<!-- phase3c-end:C-50-640-644 -->


### ID 65 — Agent Context Layer

Pending content migration. Frozen primary source identity: **65**.

### ID 92 — Cognitive Runtime

<a id="arch-source-92"></a>

<!-- phase3c-begin:C-92-1367-1393 -->

<a id="arch-source-92-part-1"></a>

**Phase 3C source excerpt:** ID 92, lines 1367–1393 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-92-1367-1393:1367-1393 -->

Cognitive Runtime manages cognitive processes. Its inputs are Observation and Cognition State. It processes:

- Perception;
- Memory Retrieval;
- Belief Evaluation;
- Goal Evaluation;
- Emotion Influence.

It produces Action Proposals and Cognitive Update Proposals. Cognitive Runtime does not modify WorldState, create Events, or execute Actions.

Any proposed reality change must follow:

```text
Action Proposal
  ↓
Attempt
  ↓
Resolution
  ↓
Event
  ↓
WorldState
```

---


<!-- phase3c-end:C-92-1367-1393 -->


### ID 104 — Remaining Cognition Governance

Pending content migration. Frozen primary source identity: **104**.

### ID 125 — Phase 12.3 Emotion and Motivation Core

Pending content migration. Frozen primary source identity: **125**.

### ID 126 — Phase 12.4 Cognition-driven Open-ended Agent Decision

Pending content migration. Frozen primary source identity: **126**.

### ID 168 — Candidate evidence review integration (local, optional)

<a id="arch-source-168"></a>

<!-- phase3c-begin:C-168-2405-2407 -->

<a id="arch-source-168-part-1"></a>

**Phase 3C source excerpt:** ID 168, lines 2405–2407 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

Compatibility reference: this source-stage evidence-review description does not supersede the existing Reference Policy v0.1 contract in [DATA_CONTRACTS.md](../DATA_CONTRACTS.md).

<!-- phase3c-source:C-168-2405-2407:2405-2407 -->

The existing `AgentDecision` pipeline generates bounded `ActionCandidate` records, evaluates them through an injectable evaluation policy, performs bounded review, selects one, and emits `ActionProposal`. An explicitly injected `EvidenceAwareEvaluationPolicy` reuses that evaluation seam: for each targeted candidate it builds an unsubmitted Attempt snapshot, accepts a bounded query proposal from a local host adapter, reads only that owner's authorized Observation evidence through `AuthorizedQuerySession`, verifies each returned fact ID was actually consumed into this turn's L1 situation, and parses a citation-checked analysis before making a small, bounded subjective score/uncertainty adjustment. This is candidate evaluation only; it does not confirm an effect, submit an Event, or change the deterministic Resolution policies. No external model transport is registered for this policy. A bare `AgentDecision` retains its deterministic evaluation policy unless a caller supplies an evidence-aware policy. In the canonical `SimulationRuntime` Agent-turn path, Runtime assembles a fresh owner/tick-bound `EvidenceAwareEvaluationPolicy` around the existing base policy and uses the deterministic local provider when neither the Runtime nor an existing evidence-aware policy supplies a provider. This local Runtime assembly does not configure an external model transport; see the Runtime assembly section below.


<!-- phase3c-end:C-168-2405-2407 -->


### ID 169 — Runtime assembly of candidate evidence review

<a id="arch-source-169"></a>

<!-- phase3c-begin:C-169-2413-2415 -->

<a id="arch-source-169-part-1"></a>

**Phase 3C source excerpt:** ID 169, lines 2413–2415 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

Compatibility reference: this source-stage evidence-review description does not supersede the existing Reference Policy v0.1 contract in [DATA_CONTRACTS.md](../DATA_CONTRACTS.md).

<!-- phase3c-source:C-169-2413-2415:2413-2415 -->

`SimulationRuntime` now binds a fresh `EvidenceAwareEvaluationPolicy` for each canonical `AgentDecision` turn, using that Agent's `CognitionContext`, the existing RuntimeContext and current SimulationClock tick. The shared AgentDecision is not mutated or left bound to another owner's query service. The default review provider is deterministic and local; a trusted host can supply a local adapter through `SimulationRuntime.evidence_review_provider`. Existing injected base evaluation policies remain in use, and an already configured evidence policy is unwrapped before turn binding. This is a candidate scoring/uncertainty input, not Safety, Resolution or Event authority. Production runner tests exercise Observation → L1 → bounded query → candidate score → ActionProposal → existing Resolution/EventProcessor. The candidate-only Event Tree snapshot is attached to runtime diagnostics and has no authority in this chain. No network evidence provider or Event Tree proposal provider is configured or approved.


<!-- phase3c-end:C-169-2413-2415 -->


### ID 180 — B2 owner-result L1 consumption boundary

<a id="arch-source-180"></a>

<!-- phase3c-begin:C-180-2585-2595 -->

<a id="arch-source-180-part-1"></a>

**Phase 3C source excerpt:** ID 180, lines 2585–2595 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-180-2585-2595:2585-2595 -->

The [B2 contract](../DATA_CONTRACTS.md#b2-durable-l1-identity-and-instance-bound-proof)
adds an immutable Timeline/owner/Observation default identity and original
acceptance tick for the B1 locked-door result. The same CognitiveRuntime accepts
it under the Runtime fence; a separate v2 system proof follows actual L1, never
delivery. Post-L1 failure freezes writes/capture and halts Runtime; durability
still begins at published checkpoints. Missing historical consumption remains
ambiguous after original-Timeline resume. Verified new forks have independent
scopes. Legacy v1 proofs, sensory access and world-event authority are unchanged;
B3/B4 and independent-instance creation are not enabled.


<!-- phase3c-end:C-180-2585-2595 -->


### ID 181 — L1 utterance consumption evidence v0.1

<a id="arch-source-181"></a>

<!-- phase3c-begin:C-181-2597-2601 -->

<a id="arch-source-181-part-1"></a>

**Phase 3C source excerpt:** ID 181, lines 2597–2601 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-181-2597-2601:2597-2601 -->

For a trusted, addressed `utterance_delivered` Observation, the receiver's AgentTurn issues an `L1ConsumptionProof` only after CognitiveRuntime puts its Percept in the owner's WorkingMemory. The issuer checks the process-local receipt, signed source Event, processing evidence, event-time receiver position and fixed visibility rule. It signs a canonical proof body with the existing PersistenceTrust root and commits under the original RuntimeWriteFence permit.

The proof is a reserved system record in the existing MemoryStore with a dedicated write path. Ordinary MemoryDecision/MemoryPersistence cannot create it; CognitionContext excludes it from semantic memory. Unified cognition snapshot capture includes the record and isolated reconstruction checks it against EventHistory lineage and event-time evidence. It creates no Event or WorldState change. CognitiveStateSnapshot v3 now adds explicit Memory schema/provenance encoding while retaining a v2 reader and its original signing purpose; SnapshotBundle v2 remains unchanged because its signed component set and manifest meaning are unchanged and it binds the exact cognition bytes. Old snapshots contain no proof and are not upgraded. In-memory signing is not durable until a published save captures the record. Arbitrary hostile in-process code with access to the trust key remains outside this issuer boundary.


<!-- phase3c-end:C-181-2597-2601 -->


### ID 185 — Consumed result Goal completion slice

<a id="arch-source-185"></a>

<!-- phase3c-begin:C-185-2638-2647 -->

<a id="arch-source-185-part-1"></a>

**Phase 3C source excerpt:** ID 185, lines 2638–2647 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-185-2638-2647:2638-2647 -->

The opt-in social-room host now closes its declared objective through the existing cognition boundary. Actor-action Goals may carry a closed, version-1 completion condition in existing metadata: one explicit action target and one exact typed fact predicate/subject/value. This is configured content, not an inference from the Goal description or an LLM prediction. Legacy Goals without that condition are not upgraded. Status/priority updates cannot replace it.

For actor-action conditions, a later AgentTurn first performs ordinary qualified L1 intake, then the optional completion adapter verifies canonical signed B3 selection/result bindings and the final Attempt's exact Goal ID and target. Only a formally committed successful result whose matching fact was actually consumed by this owner can produce GoalUpdateProposal(completed). Existing validation, CognitiveUpdateApplier, GoalStore and Runtime fence perform the write. Delivery, selection, Resolution success alone and narrative output cannot complete the Goal. Failure, unmet conditions, missing evidence and governance refusal leave it active.

The next decision rebuilds its Goal view. Room candidates and the conflict/opportunity scheduler use active Goals; completed objectives remain cognitive history rather than executable scheduler inputs. Duplicate review retains the completed state without another Goal write or world action. An uncertain Goal write freezes the existing recovery/capture boundary; no action replay or new recovery subsystem is introduced.

Signed saved Goal state and its condition survive strict reconstruction and forks. An already completed Goal needs no historical consumption to be recreated. An active Goal saved after delivery but before consumption is not silently completed during restore: missing live evidence remains unresolved. There is no new persistent completion ledger, B4 revision protocol, general planner or independently durable policy-execution proof. See [exact conditions and limits](../DATA_CONTRACTS.md#consumed-result-goal-completion) and [behavioral scope](../SOCIAL_CAUSAL_DESIGN.md#goal-completion-in-the-room).



<!-- phase3c-end:C-185-2638-2647 -->


### ID 191 — Typed contextual Belief matching

<a id="arch-source-191"></a>

<!-- phase3c-begin:C-191-2705-2709 -->

<a id="arch-source-191-part-1"></a>

**Phase 3C source excerpt:** ID 191, lines 2705–2709 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-191-2705-2709:2705-2709 -->

An opt-in, transient decision extension now derives `ContextualBeliefBinding/v1` from an existing governed Belief and its exact actually consumed result Observation. AgentTurn reuses ordinary L1 history qualification, rechecks the receipt and canonical fact, and supplies immutable bindings through DecisionContext and SituationBelief. The current supported source is a formally confirmed failure with one target and a Boolean result. No prose is parsed into a physical rule.

Host-provided `ContextualBeliefRule/v1` definitions declare an exact fact type/predicate/Boolean selector, bounded subjective score adjustment and evidence age. The generic decision layer matches the exact target, action type and method; tool-bearing, ambiguous or unsupported matches add nothing. Applicability requires an unchanged canonical history frontier and an unexpired evidence tick. Any intervening Event conservatively invalidates applicability, including unrelated Events. The Belief remains historical; it does not become a permanent claim about an object.


<!-- phase3c-end:C-191-2705-2709 -->


### Content received from coordinated splits

- Original ID **188**, source lines **2674–2676**: approved excerpt copied in Phase 3C below; other parts and final coordination remain pending. The original heading keeps its separate primary assignment.
- Original ID **188**, source lines **2679–2681**: pending coordinated migration; the original heading keeps its separate primary assignment.
- Original ID **194**, source lines **2735–2735**: approved excerpt copied in Phase 3C below; other parts and final coordination remain pending. The original heading keeps its separate primary assignment.

### Split source ID 188 — Explicit state commitments and independent interaction reach (partial integration) / Consumed state-Goal completion and actor-action distinction

<!-- phase3c-begin:C-188-2674-2676 -->

<a id="arch-source-188-part-1"></a>

**Phase 3C source excerpt:** ID 188, lines 2674–2676 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-188-2674-2676:2674-2676 -->

GoalCompletionCondition/v2 explicitly distinguishes state from actor_action. A state commitment compares an exact authorized environment-state fact actually consumed by its owner against the configured typed value, then uses the existing Goal update governance and fence. An older matching projection superseded in formal processing order cannot complete a state Goal merely because it is valid historical intake. The producing actor need not own that Goal, and no foreign B3 proof is transferred to the observer. Actor-action conditions retain the precise own Attempt/Goal/target binding. V1 stays actor-action; absent conditions remain unsupported, never inferred from prose. Completed state Goals survive signed reconstruction and remain isolated from active parent/sibling Goals. This is not general planning or B4.


<!-- phase3c-end:C-188-2674-2676 -->


### Split source ID 194 — Subjective spatial representation — approved principle only

<!-- phase3c-begin:C-194-2735-2735 -->

<a id="arch-source-194-part-2"></a>

**Phase 3C source excerpt:** ID 194, lines 2735–2735 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

This is the approved representation distinction only. The central principle and non-implementation limit remain in the unchanged [ARCHITECTURE.md](../ARCHITECTURE.md); no general spatial cognition implementation is asserted.

<!-- phase3c-source:C-194-2735-2735:2735-2735 -->
An egocentric spatial representation is relative to the observer's position, orientation or body; an allocentric representation is organized around environmental landmarks, objects or relationships. Polar coordinates are one optional representation, not a requirement. Different observers may represent the same environment differently, incompletely, uncertainly, inaccurately or using outdated information.

<!-- phase3c-end:C-194-2735-2735 -->


## Existing canonical definitions retained by reference

- Source ID **29**, original lines **351–358**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **98**, original lines **1477–1479**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **99**, original lines **1481–1489**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **100**, original lines **1491–1502**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **101**, original lines **1504–1521**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **102**, original lines **1523–1537**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **103**, original lines **1539–1570**: [MEMORY_DESIGN.md](../MEMORY_DESIGN.md). Reference only; original source retained, no definition body copied.
- Source ID **104**, original lines **1572–1576**: [DATA_CONTRACTS.md](../DATA_CONTRACTS.md). Reference only; original source retained, no definition body copied.

## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [ARCHITECTURE.md](../ARCHITECTURE.md) — canonical owner for A02.
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) — canonical owner for A06, A13, A17, A18, A19, A20, A22, A32, A34, A38.
- [MEMORY_DESIGN.md](../MEMORY_DESIGN.md) — canonical owner for A15.
- [META_CONTRACTS.md](../META_CONTRACTS.md) — canonical owner for A35.
- [SOCIAL_CAUSAL_DESIGN.md](../SOCIAL_CAUSAL_DESIGN.md) — canonical owner for A21.
- [EXECUTION.md](EXECUTION.md) — canonical owner for A09, A10.
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md) — canonical owner for A14.
- [PERCEPTION.md](PERCEPTION.md) — canonical owner for A12, A26.
- [PERSISTENCE.md](PERSISTENCE.md) — canonical owner for A31, A33.
- [SAFETY_AND_NORMS.md](SAFETY_AND_NORMS.md) — canonical owner for A37.
- [WORLD_MODEL.md](WORLD_MODEL.md) — canonical owner for A28.
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md) — canonical owner for A25.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [MEMORY_DESIGN.md](../MEMORY_DESIGN.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [SOCIAL_CAUSAL_DESIGN.md](../SOCIAL_CAUSAL_DESIGN.md)
- [EXECUTION.md](EXECUTION.md)
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md)
- [PERCEPTION.md](PERCEPTION.md)
- [PERSISTENCE.md](PERSISTENCE.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md)

## Historical and implementation-status handling

Only the explicitly marked Phase 3D historical quotations below have migrated. Other historical or mixed content remains pending. These source-stage records establish no new runtime capability, current test result or normative definition.

<a id="arch-history-h-4-34-34"></a>
### Historical source record — Behavior Adaptation — current verified boundary

**Historical record — Historical implementation snapshots.** This is an original-stage quotation, not a current normative definition, current implementation inventory or newly executed test result.

Source: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), original heading ID **4**, lines **34–34**; original heading: **Behavior Adaptation — current verified boundary**.
Source document SHA-256: `d111ce446dcdf8a16182dc465f42a851177a569547b3a0cfc6519d6e8653f751`. Captured from the working tree based on `838e6913e6e6d6deefcaa6bbf126cad2139550b7`; the quoted bytes are not asserted to be the committed version.

Original context: Behavior Adaptation v0.4 source reports deterministic A/B and restore-related regression coverage.
Chronology: Explicit v0.4 marker; no calendar date stated. Calendar date: not stated in the source.

Temporal words such as “now”, “currently”, “here”, “this document”, “below” and “at this stage” retain their original source context. Legacy paths are historical evidence, not current repository instructions. The full quoted limitations and original validation status remain attached; no broader supersession or present-day acceptance is inferred.

Current normative definitions remain with their frozen owners, including [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) and [META_CONTRACTS.md](../META_CONTRACTS.md); this quotation creates no additional authority.

<!-- Phase 3D exact source quotation begins: H-4-34-34 -->
> v0.4 has a deterministic production-decision comparison in tests/test_autonomous_world_runner.py: with the same owner, DecisionContext, candidates and configuration, changing only trusted feedback changes the adjusted score and selected candidate. The penalized action remains available. tests/test_save_restore_end_to_end.py checks checkpoint score/choice equivalence after restoration, time-based decay, and parent/child isolation; its post-restore decision re-establishes equivalent authorized observations rather than restoring old L1/WorkingMemory caches.
<!-- Phase 3D exact source quotation ends: H-4-34-34 -->


Contact: ankorgine@outlook.com
