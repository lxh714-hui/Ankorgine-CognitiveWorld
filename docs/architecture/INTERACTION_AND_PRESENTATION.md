# CognitiveWorld — Input, Meaning and Safe Output

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Input/meaning and safe output.

## Authority and scope

**Frozen authority level:** Domain architecture; UI not fact authority.

**Assigned responsibility:** Player intent, Worldbook, host sessions, perspective/render/validate boundaries.

Only marked architectural excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A14 — Presentation disclosure and Worldbook boundary**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- WorldState authority, causal result adjudication and formal submission.
- Private cognitive records and sensory evidence generation.
- Detailed schema, signature and recovery protocols.

## Migrated excerpts and pending section outline

Only marked approved excerpts have migrated. Other entries remain pending. Source titles retain their original stage/status; no title is new acceptance evidence.

### ID 9 — Natural-Language-Driven World Interaction (approved architectural requirement)

<a id="arch-source-9"></a>

<!-- phase3c-begin:C-9-106-126 -->

<a id="arch-source-9-part-1"></a>

**Phase 3C source excerpt:** ID 9, lines 106–126 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-9-106-126:106-126 -->

Natural language is the player's primary interaction interface. Translating player intent into valid world interactions and communicating outcomes through evidence-grounded narrative is an architectural requirement, not an optional UX enhancement. The action-oriented diagram above is one branch, not a requirement that every question or observation create an Attempt or Event.

- **Intent over command syntax:** players express goals, observations, questions and actions naturally. They need not understand internal APIs, LOD parameters, scheduling policy or simulation implementation.
- **Context-sensitive interpretation:** proceed when intent is sufficiently clear, using only authorized context to resolve minor ambiguity. Clarify when remaining ambiguity could materially change the target, action or consequences. Lower interaction friction never permits unsupported target substitution or bypassing the existing clarification identity and validity checks.
- **Evidence-grounded execution:** interpretation may propose actions, request computations and organize feedback, but cannot establish world facts, authorize disclosure or bypass applicable authoritative validation and Event processing.
- **Experience-oriented fidelity adaptation:** the target design selects suitable computational fidelity from player intent and interaction requirements. Players request what to perceive or accomplish, not a compute level. This preserves the independent cognitive, perceptual and physical-computation axes; it does not claim an implemented shared coordinator. Higher fidelity grants neither more information permissions nor guaranteed discoveries.
- **Truthful, informative feedback:** distinguish attempted actions, accepted requests/actions, authoritative world changes, observed information, uncertainty and unresolved results. Acceptance is not success; proposals, inferences and unverified outputs cannot be narrated as established facts. Keep confirmed facts and non-fact clarification/fallback feedback within their existing separate Presentation contracts.
- **Player agency and optional narrative opportunities:** environmental cues, character behavior and discovered evidence may draw attention to consequential opportunities without forcing a predetermined route. Optional opportunities may genuinely be missed when the player does not pursue them; that does not license omission of required authoritative causal consequences or rewriting established history.
- **Separation of interpretation and authority:** LLM interpretation remains separate from WorldState, owner cognition, causal validation, information authorization and EventProcessor. Interaction coordinates those capabilities; narrative representation and Presentation do not replace them.

The conceptual responsibility flow is:

```text
Player intent -> contextual interpretation -> authorized computation/action proposals
 -> authoritative validation and execution where applicable
 -> evidence-grounded narrative feedback
```

This is not an API, schema or assertion of a complete production pipeline. The bounded installed player path remains as described in the system-structure section below and [DATA_CONTRACTS.md](../DATA_CONTRACTS.md). General questions, goal-level orchestration, modality computation and intent-driven fidelity selection are not made executable by this principle. Narrative Intelligence suggests possibilities rather than forced outcomes; [hybrid Lazy World Expansion](../ARCHITECTURE.md#hybrid-lazy-world-expansion-selected-direction-acceptance-boundary-unresolved) retains its unresolved structure-acceptance boundary. Inspect existing production entry points before extending them; preserve WorldState, cognition, narrative and Presentation separation.


<!-- phase3c-end:C-9-106-126 -->


### ID 10 — Contextual interaction and bounded autonomous investigation (design consensus; not implemented as a general workflow)

<a id="arch-source-10"></a>

<!-- phase3c-begin:C-10-128-146 -->

<a id="arch-source-10-part-1"></a>

**Phase 3C source excerpt:** ID 10, lines 128–146 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-10-128-146:128-146 -->

Free text remains available for arbitrary player intentions; displayed choices never define the complete set of permitted expressions or guarantee that every expression is executable. Clickable narrative objects, contextual shortcuts and action suggestions are complementary inputs that reduce typing. They must converge on the existing interpretation/proposal, decision and applicable Resolution/EventProcessor boundaries, rather than a parallel UI execution authority. A click establishes neither a world fact nor operation permission. A broad goal does not authorize major or irreversible actions by implication.

**Default object click: express attention/observation intent -> use the minimum justified supported adjustment, if any -> observe -> return evidence-grounded feedback.** It is not an unconditional turn command, automatic investigation, pickup, opening or attack. If the target is adequately observable, do not reorient unnecessarily; a small gaze adjustment must not silently become a head/body turn. Where orientation, position and observation mechanisms exist, use them without inventing unsupported geometry; a UI highlight cannot turn or move an actor. If stronger reorientation or approach is required but not implied by the input, retain the distinction between requesting observation and authorizing that additional action. If a target is invisible, unreachable, unmaterialized or insufficiently evidenced, apply existing denial/limited-feedback rules or a separately authorized expansion path, without promising discovery or creating structure from the click. Subsequent explicit text may ask to inspect a lock, listen behind a wall or attempt opening; those examples approve no new mechanism.

**Manner-sensitive observation:** preserve peripheral glance (no automatic formal body turn), brief glance (minimum gaze/attention adjustment), looking toward (attention and necessary gaze/head adjustment), explicit head turn, explicit body turn, close inspection (possibly more time/position/detail), and discreet peeking/watching (intended limited exposure where supported). These are semantic distinctions, not newly installed action classes. Conceptually separate attention, gaze, head orientation, body orientation, position/approach and perceptual computation. They may differ in duration, conspicuousness, exposure and causal effects; choose no stronger action than the expressed intent justifies. Unsupported mechanics remain explicitly unsupported, not silently substituted.

Observation manner may request different perceptual effort: a peripheral glance can support coarse information, while sustained inspection can request more detail under available evidence/mechanisms. It grants no access, identification or discovery guarantee. Missing geometry/history/lighting stays unresolved; do not upgrade manner merely to obtain richer output or expose internal LOD controls. Discreet observation is not automatically undetectable, and overt observation is not automatically noticed: other characters' perception, inference and responses require their supported rules, capabilities, environment and authorized evidence. Text, clicks and shortcuts preserve these same distinctions and applicable execution boundaries.

An interaction entry must be grounded in the player's current permitted context. Clickability does not prove that the character discovered, understood or may operate the referenced object. Coarser presentation may offer a scene, direction, salient object or observation entry; finer presentation may expose more specific objects/details only when supported computation, evidence and authorization permit. Unknown stays unknown. Highlighting, feedback and object lists must not enumerate the latent world or treat an LOD upgrade as an information grant. These examples are presentation granularity, not fixed levels or new DTO/schema fields. Cognitive, perceptual and physical-computation LOD retain separate responsibilities.

**Long-lived goals are not unlimited execution permission.** The design permits low-risk, reversible investigation while the player temporarily does not intervene, but each autonomous round must have a strict bound. A prototype may experiment with 2–3 consecutive steps; that is not an architecture constant or an approved default. Every round reports meaningful evidence-backed progress and returns continuation control to the player; it must not automatically renew itself indefinitely. Pause early for a major clue, contradiction, increasing risk, a permission boundary, irreversible choice, insufficient evidence or goal completion. The player must be able to interrupt, redirect, pause or abandon investigation. Each new action re-evaluates current state, evidence, feasibility and constraints; low risk alone is not authorization. Later opportunities are new work, not restoration/retry of old actions. Interruption respects existing non-cancellable commit/recovery boundaries and does not undo committed facts.

Cross-scene/time goal continuity is a product requirement, not a new durable task, Goal-write or resume contract. Current bounded Agent turns and caller-driven stepwise execution are partial foundations; they do not implement this player-goal investigation workflow. Action counts, risk criteria, pause triggers, continuation/interrupt semantics and any required persistence remain separately reviewable decisions. No general executor or automated player Agent is approved here.

The [hybrid Lazy World Expansion direction](../ARCHITECTURE.md#hybrid-lazy-world-expansion-selected-direction-acceptance-boundary-unresolved) remains authoritative: prefer minimal runnable structure for the present need and add detail on demand, while allowing complete generation for special scenarios. A known object need not have materialized internals; a new goal cannot create facts satisfying the player's wishes. Seeds, hints, clues and authored content retain their own provenance and explicitly approved effect. Causal use, dependencies and potential downstream effects distinguish derived artifacts from accepted structure; current apparent irrelevance alone does not make accepted detail disposable. Initial acceptance versus materialization versus later formal change remain distinct, and structure acceptance authority is still unresolved. Narrative cues can lead toward consequential possibilities, but optional opportunities may be genuinely missed; do not force a return to a planned plot or omit required authoritative consequences.

Narrative is not world truth; intent is not execution; a clickable entry is not authorization; Observation is not automatic Belief; candidate structure is not accepted structure. LOD is not disclosure authority, and goal persistence is not an action budget. Existing Safety, decision, Resolution, EventProcessor, owner cognition, Timeline, generation and recovery checks apply to all input forms. This consensus freezes no API, schema, coordinator or lifecycle and claims no production implementation.


<!-- phase3c-end:C-10-128-146 -->


### ID 39 — Player Decision

<a id="arch-source-39"></a>

<!-- phase3c-begin:C-39-462-470 -->

<a id="arch-source-39-part-1"></a>

**Phase 3C source excerpt:** ID 39, lines 462–470 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-39-462-470:462-470 -->

```text
Natural Language
  ↓
Intent
  ↓
Attempt
```


<!-- phase3c-end:C-39-462-470 -->


### ID 43 — Worldbook Layer

<a id="arch-source-43"></a>

<!-- phase3c-begin:C-43-526-558 -->

<a id="arch-source-43-part-1"></a>

**Phase 3C source excerpt:** ID 43, lines 526–558 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-43-526-558:526-558 -->

The Worldbook Layer is an emotional connection layer between the player and the world. It is a special user-facing entry point that supports emotional connection, a sense of belonging to the world, and a long-term sense of companionship.

It preserves the player's long-term understanding, creations, and emotional accumulation related to the world, including:

- World Lore;
- Player Notes;
- Archives;
- Collections;
- Meaningful Records.

Worldbook is an external layer for collecting the meaning the player gives to the world. It is not WorldState, Memory, Entity data, or an AI Prompt.

These concepts have distinct roles:

- **WorldState** represents the world's current true state.
- **Memory** represents experiences of a character or system.
- **Worldbook** represents meaning the player gives to the world and what they choose to collect over time.

Worldbook does not directly affect world operation. Any desired world change must follow the normal flow:

```text
Intent
  ↓
Attempt
  ↓
Resolution
  ↓
Event
  ↓
WorldState
```


<!-- phase3c-end:C-43-526-558 -->


### ID 48 — 3.1 Semantic Understanding

<a id="arch-source-48"></a>

<!-- phase3c-begin:C-48-599-616 -->

<a id="arch-source-48-part-1"></a>

**Phase 3C source excerpt:** ID 48, lines 599–616 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-48-599-616:599-616 -->

Input: player natural language.

Example:

```text
"I want to convince the guard to let me enter."
```

Output meaning representation:

- goal;
- target;
- motivation;
- method preference.

It does not execute actions.


<!-- phase3c-end:C-48-599-616 -->


### ID 52 — 3.3 Intent

<a id="arch-source-52"></a>

<!-- phase3c-begin:C-52-656-666 -->

<a id="arch-source-52-part-1"></a>

**Phase 3C source excerpt:** ID 52, lines 656–666 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-52-656-666:656-666 -->

Intent represents what the player wants to achieve.

Example:

```text
Goal: enter_castle
```

Intent does not contain a specific method.


<!-- phase3c-end:C-52-656-666 -->


### ID 84 — Presentation Safety Foundation (Phase 12.0)

Pending content migration. Frozen primary source identity: **84**.

### ID 85 — Trusted Player Presentation and Chat Output (Phase 12.0d, narrow slice)

<a id="arch-source-85"></a>

<!-- phase3c-begin:C-85-1247-1271 -->

<a id="arch-source-85-part-1"></a>

**Phase 3C source excerpt:** ID 85, lines 1247–1271 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-85-1247-1271:1247-1271 -->

```text
RuntimeContext host-bound PlayerSessionBinding
  → PerspectiveResolver + AgentRegistry/Character binding
  → EventHistory Event + EventProcessingEvidence
  → existing authorized Observation for the resolved Agent
  → restricted visible input
  → deterministic MinimalComposer
  → PresentationValidator-issued ValidatedMessageBatch
  → ChatOutputGateway
  → InMemoryChatOutputGateway (current adapter)
```

`RuntimeContext.player_session` is optional and defaults to absent; no session is synthesized. The host must supply a `PlayerSessionBinding` from its trusted session setup. Roleplay resolves the bound registered `RuntimeAgent` and requires its Character ID. Observer mode uses only its host-bound registered view Agent and grants no action-control capability. Director mode is denied because no director visibility policy exists. The resolver accepts no recipient, observer, mode, audience, or scope arguments from the presentation caller; current visible scope is a policy-derived environment scope. This is an application contract, not network authentication or a same-process security boundary.

The filter ignores `Event.metadata`, including legacy `presentation_facts`. It requires an intact trusted Event and its EventProcessor evidence, then reads only an unchanged Observation from the existing ObservationStore whose observer and source Event match, whose ObservableFact is included in that evidence, and whose authorization still passes the shared `VisibilityPolicy`. The Observation is the existing per-Agent authorization result; Presentation does not read cognition or memory. Unknown/missing session, event evidence, Observation, or view-agent binding denies output. This historical Phase 12.0d slice began with room-light-on; later trusted door and passage facts are documented in their respective phases.

`VisibleInput` contains closed typed fact data and source IDs, not backend objects or arbitrary text. `MinimalComposer` renders only explicitly supported typed facts. Door open/closed/locked and passage presence use generic nouns when no verified display-name contract exists; internal subject IDs, location IDs, predicates and raw values never become fallback prose. Unknown facts fail closed. It cannot invent dialogue, inner thoughts, outcomes, or other facts. `PresentationValidator` rechecks the source Observation and exact deterministic text, binds recipient/session/view/source snapshots, and issues `ValidatedMessageBatch`; a `PlayerVisibleMessage` alone is not accepted by the gateway. The private Python receipts address ordinary misuse only and do not resist malicious same-process code.

`ChatOutputGateway` is the sole approved player-chat send interface. `InMemoryChatOutputGateway` is the current callable Core adapter and stores validated batches. The former CWUI live adapter remains in the untouched source backup. After M0.5, the `anchor_desktop` host consumes this adapter through narrow display entries for a fresh world session; this is an in-process projection, not durable delivery. The Core adapter rejects raw strings, Events, Observations, manually built messages/batches, session mismatches, and post-validation mutation. It records only a non-sensitive error code. Presentation does not modify WorldState, EventHistory, ObservationStore, or cognition stores.

Player chat must never receive backend cognition, private memory, EmotionState or parameters, probabilities, decision analysis/traces, Prompts, debug output, or internal state objects. A Python in-process seal or type check is an application misuse guard, not protection from malicious code in the same process. Stronger adversarial isolation would require a separate security boundary and is long-term planning, not a current capability.

Within Core, `InMemoryChatOutputGateway` is the callable adapter. The desktop launcher is no longer Demo-backed; its host starts either validated local world definition and projects observed initial Events and later committed action facts as typed display entries. Clarification and narrative entries retain distinct channels. The desktop back action closes the original session before returning to world selection; Qt polls a request-scoped, allowlisted task snapshot on the UI thread without waiting for the worker and discards the old page on world switch. A completed task with pending non-Event delivery terminates its temporary progress display. Local player input echo is marked as player speech, never a confirmed Event. Signed cold resume has a separate verified first-publication path. This in-process display connection does not provide general NPC dialogue, director policy, durable delivery, or full observer simulation. Narrow LLM-backed input understanding, clarification, and no-result narrative generation are documented in the later D3.3.1 section. The narrow visibility path is not a general player-visibility system. Event metadata, caller scopes, private cognition, EmotionState, thresholds, probabilities, scores, prompts, decision trajectory, and debug data are excluded from player-chat inputs.


<!-- phase3c-end:C-85-1247-1271 -->


### ID 86 — Framework-neutral Core and asynchronous host boundary (approved constraint; implementation partial)

Pending content migration. Frozen primary source identity: **86**.

### ID 87 — First player-input async slice (implemented narrowly; in-process)

<a id="arch-source-87"></a>

<!-- phase3c-begin:C-87-1275-1285 -->

<a id="arch-source-87-part-1"></a>

**Phase 3C source excerpt:** ID 87, lines 1275–1285 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-87-1275-1285:1275-1285 -->

The synchronous player chain remains input classification → target/Safety authorization → ActionPipeline → Resolution/EventFactory → EventProcessor → authorized Presentation → Gateway. `PlayerInputTaskCoordinator` is a framework-neutral host boundary around `PlayerActionService.submit_input`; it does not create a Runtime, Store, alternate Resolution path, or UI adapter. Hosts that use the coordinator receive an opaque handle at admission and can observe an allowlisted `PlayerInputTaskSnapshot` through a `concurrent.futures.Future`. Callbacks run on the worker thread and client adapters must marshal them to their own UI thread. The original synchronous service entry point remains available and still blocks its caller.

The coordinator uses one `ThreadPoolExecutor` worker per coordinator. Admission is serialized and captures the request fingerprint, player session/actor, RuntimeWriteFence session and restore generation, and the original write permit. It explicitly copies the permit's `ContextVar` context into the worker. The potentially expensive authorized-target projection is computed by the worker at task start inside the original permit's snapshot scope, then passed to interpretation; current target/Safety/Resolution checks still run before action. Identical request IDs and content join the same in-process task; changed content conflicts. The single worker gives that coordinator a defined admission-order execution sequence but can suffer head-of-line delay when a provider cannot be interrupted. A submission acknowledgement means accepted for processing, not action success. Authority objects, target snapshots and provider inputs are not fields in the client status projection.

Blocking input interpretation and fallback work run on the worker, outside the Runtime commit lock. `PlayerActionService` uses the admission-time target allowlist, checks the task binding after provider work, and still applies current target/Safety/Resolution validation. EventProcessor receives the original propagated permit; no fresh permit is minted for a returning result. RuntimeWriteFence can revoke that individual permit until its `commit_scope` begins. Cancellation, timeout, shutdown, generation advance and commit therefore serialize at the fence: if revocation wins, late work cannot commit; once `commit_scope` begins, cancellation returns false and the already-authorized commit is allowed to finish. Provider computation itself is advisory and may continue after cancellation or timeout.

Execution state and Presentation delivery state are tracked independently. Execution states include accepted, running, completed, cancelled, expired, stale and failed; delivery states include pending, delivered, retryable and stale. They are application statuses, not world Events. If EventHistory reports a request Event as COMPLETE after Presentation throws, execution is completed and delivery is retryable. `retry_presentation` re-reads that request's canonical Event, requires COMPLETE processing, and re-enters current Presentation authorization, Safety/visibility checks and Gateway deduplication; it does not reinterpret input, rerun Resolution or dispatch the Event. The retry runs under the original permit's Runtime snapshot scope: if it acquires the scope first, delivery completes before restore can advance the generation; if restore wins, the retry is stale. A queued retry cancelled by coordinator close resolves its Future and remains pending for higher-level recovery. Recovery is same-service and in-process; replacement Runtime/application-service recovery is not implemented. Cancellation and shutdown do not roll back a committed Event; uncertain partial application retains the existing recovery-required protocol. Client status exposes only bounded outcome/recovery codes, never exceptions or domain objects.

The coordinator itself provides no durable outbox, restart recovery of tasks, client acknowledgement protocol, cross-process task cancellation, or arbitrary subscriber stream. The later `anchor_desktop` host integrates it through a separate thin adapter. EventHistory remains the fact authority, not a task or subscription ledger. Replaying every Event to a client is not safe: current recipient authorization, branch identity, retention and cursor semantics must be defined first. Durable delivery would require a separate reviewed publication/transaction contract; do not claim atomic outbox-plus-world writes from today's in-memory EventProcessor.


<!-- phase3c-end:C-87-1275-1285 -->


### ID 88 — Established boundary requirements

<a id="arch-source-88"></a>

<!-- phase3c-begin:C-88-1289-1299 -->

<a id="arch-source-88-part-1"></a>

**Phase 3C source excerpt:** ID 88, lines 1289–1299 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-88-1289-1299:1289-1299 -->

The CW Core and domain packages must remain independent of PySide6, Qt, Web frameworks, and UI controls. A client integration depends on typed application interfaces and consumer-specific projections; Core must not import a client toolkit or call UI code. M0.5 places the desktop client in a separate `anchor_desktop` package within this repository; the package boundary and read-only authorized projection contract remain in force.

LLM inference, memory retrieval, and physical computation that may exceed a short deterministic interaction budget must not run synchronously on a UI main thread. The application/host boundary must provide an asynchronous submission and result-notification contract. The host may choose an event loop, thread, process, or another mechanism according to the runtime; this architecture does not prescribe one. UI toolkit Signals, Web callbacks, and similar mechanisms belong in client adapters, not Core.

An asynchronous operation is not a write capability. Task inputs and results must bind to the initiating request and the Runtime session/restore generation when they can affect a Runtime. Cancellation, timeout, duplicate submission, provider failure, shutdown, and stale completion after restore must have explicit outcomes. A stale result cannot continue into an action, cognitive write, or Event commit; any accepted state change re-enters the existing RuntimeWriteFence, authorization, Resolution, and EventProcessor boundaries. This contract does not claim that such a general task manager currently exists.

Progress may be coalesced or rate-limited. Confirmed Event delivery and UI projection refresh are separate concerns: a slow or disconnected subscriber cannot roll back a committed Event, and a committed Event cannot be silently lost from the authoritative history. Adapters must be able to reconcile from an authorized current projection or an ordered Event cursor after reconnect. Presentation failure is a delivery failure, not a world-state result.

Client DTOs are explicit, immutable, consumer-specific allowlisted projections, never a serialization of full Event, Observation, EventHistory, WorldState, RuntimeContext, or internal cognition objects. Each projection is authorized before construction and exposes only fields necessary for that recipient. Confirmed fact projections, owner-authorized Observation projections, clarification requests, Narrative Fallback asides, generation progress, and error/recovery notifications remain distinct types and channels. Internal provenance, signatures, cognition analysis, hidden metadata, and mutable domain references are excluded unless a separately reviewed contract explicitly authorizes a safe projection. Current Presentation message contracts are narrow examples; a universal client DTO and task-result protocol remain unimplemented.


<!-- phase3c-end:C-88-1289-1299 -->


### ID 130 — One product, two implementation projects

Pending content migration. Frozen primary source identity: **130**.

### ID 133 — Presentation and factual integrity

Pending content migration. Frozen primary source identity: **133**.

### ID 136 — Unified CW/CWUI product boundary

<a id="arch-source-136"></a>

<!-- phase3c-begin:C-136-1963-1964 -->

<a id="arch-source-136-part-1"></a>

**Phase 3C source excerpt:** ID 136, lines 1963–1964 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-136-1963-1964:1963-1964 -->
The current desktop layout uses a single chronological interaction stream as the live stage. The opening animates authored worldbuilding only; authorized scene facts are shown through explicit observation rather than appended automatically. Prose and scene facts retain separate provenance and share narrative text metrics; tail following yields to a reader scrolling upward. Desktop management uses confirmation-bound host operations: bundled visibility is only a Qt preference, live-instance disposal closes/fences a session while preserving saves, and manual-slot deletion uses SaveManager's signed catalog and dependency retention. There is no user-install registry or independent persistent-instance deletion catalog; see [management boundaries](../DATA_CONTRACTS.md#desktop-management-and-confirmation-boundary). It appends a separately labelled, safety-reviewed authored opening for new sessions, locally submitted player text, recipient-scoped Presentation output, and bounded task-status messages; it does not construct world facts from Runtime objects. The existing world projection is shown on a separate state page, opened from the stage and returned through the cached navigation route without recreating the live Runtime. This page still has the provisional package-metadata limits above and is not an authorized historical Event browser or structured public-law projection. Unsupported history and timeline controls remain unavailable.


<!-- phase3c-end:C-136-1963-1964 -->


### ID 138 — Composable Portrait Presentation (Future Design)

<a id="arch-source-138"></a>

<!-- phase3c-begin:C-138-2008-2034 -->

<a id="arch-source-138-part-1"></a>

**Phase 3C source excerpt:** ID 138, lines 2008–2034 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-138-2008-2034:2008-2034 -->

The planned character visual is a portrait/avatar only, assembled from
independent presentation layers rather than a complete image for every
character and condition. The initial conceptual layers are Hair (style and
color), Skin, Face (expression), Age characteristics, and Condition (for
example, dusty, tired, or injured). A future Presentation Resolver may select
layers from the Entity state that is confirmed and permitted for the current
presentation view, producing a composed portrait:

`Entity State → Presentation Resolver → Avatar Layer Selection → Composed Portrait`

This is presentation output, never a World Fact or state writer. A layer may
change only after an applicable state change is confirmed and the resulting
state is available to that presentation view. Temporary conditions select or
remove their corresponding visual layer without changing Entity identity or
type. Age characteristics must come from trusted, presentation-authorized
attributes; they must not be inferred from names, skin, hairstyle, or other
appearance layers. Hidden cognition and other private state are not layer
inputs.

The design does not call for a separate full portrait asset for every state,
full-body character art, general body modeling, equipment rendering, or a
universal appearance system. Live2D, full-body illustration, and other richer
visual forms are separate future Presentation extensions. No
`AvatarComposer`, asset-loading API, or concrete resource pipeline is
implemented or specified by this note.


<!-- phase3c-end:C-138-2008-2034 -->


### ID 140 — Narrative Causal Relevance (planned)

<a id="arch-source-140"></a>

<!-- phase3c-begin:C-140-2107-2121 -->

<a id="arch-source-140-part-1"></a>

**Phase 3C source excerpt:** ID 140, lines 2107–2121 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-140-2107-2121:2107-2121 -->

Outside necessary introductions, environmental tone, and natural transitions,
specific narrative content should have credible world support and preferably
an interaction or causal use. Any NPC, object, investigable clue, scene
mechanism, character action, or world-state change presented as a concrete
world element must exist in authoritative world data or be committed through
the trusted Event path. If the player can reasonably attempt an interaction,
the world needs a state or mechanism capable of receiving that attempt.
Presentation may not invent an entity or Event. This does not require an Event
for every sentence or leaf, a main-plot connection for every detail, or an
immediate trigger for every clue. This is a future Presentation/Narrative
Planning requirement; no narrative engine is added here.

Narrative emergence is the interpreted consequence of separately owned character beliefs, goals and plans interacting with installed physical mechanisms, environmental conditions, information propagation, relationships and confirmed Events. Narrative objectives may prioritize candidate exploration and simulation effort; they cannot choose an Agent's action, install a missing mechanism, override Resolution or make an uncommitted branch part of EventHistory. Authorized Presentation remains the only route from confirmed facts to player-facing prose. This is an architectural constraint on future narrative work, not a claim that a general emergent-narrative system is installed.


<!-- phase3c-end:C-140-2107-2121 -->


### ID 143 — Player “灵光一闪” contextual exploration (partial backend slice)

Pending content migration. Frozen primary source identity: **143**.

### ID 156 — Output Anti-Enumeration

<a id="arch-source-156"></a>

<!-- phase3c-begin:C-156-2320-2322 -->

<a id="arch-source-156-part-1"></a>

**Phase 3C source excerpt:** ID 156, lines 2320–2322 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-156-2320-2322:2320-2322 -->

World facts, causal results, and authorized Observations are structured data, not prose. Presentation consumes those permitted structured results and expresses them for the current viewpoint; a future LLM may translate them into natural language within the existing factual and visibility constraints. Natural-language output never becomes a World Fact by being generated, and Presentation cannot feed its wording back as a Resolution result. Do not add a new fixed text template for every new world circumstance. The same authorized structured result may receive different wording according to observer, context, and narrative purpose, while every expression remains grounded in that result. This is a design principle, not an implementation of a general LLM narrator; the current Composer remains a narrow, deterministic prototype.


<!-- phase3c-end:C-156-2320-2322 -->


### ID 162 — Host-bound player action to CWUI vertical slice (implemented narrow path)

<a id="arch-source-162"></a>

<!-- phase3c-begin:C-162-2355-2359 -->

<a id="arch-source-162-part-1"></a>

**Phase 3C source excerpt:** ID 162, lines 2355–2359 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-162-2355-2359:2355-2359 -->

A trusted host may compose one `PlayerActionService` from the canonical `RuntimeContext`, `EventProcessor`, `ActionPipeline`, `ActionResolutionFlow` and `ChatOutputGateway`. A roleplay `PlayerSessionBinding` fixes the controlled Agent and recipient; the UI supplies neither identity nor authority. The UI's optional target reference must come from that session's unchanged, authorized Observation. A request flows through the existing safety, ActionProposal/Attempt, Resolution, EventFactory, EventProcessor, Observation and Presentation boundaries. Confirmed results use the fact-backed Presentation channel. An unresolved attempt creates no Event and may return a separately typed, display-only no-result narrative; rejected requests do not enter that channel. An ID-bound in-process request record prevents an ordinary retry from submitting the same attempt twice; it is not durable exactly-once recovery.

**Typed action feedback (narrow implementation):** Installed Resolution policies may attach a closed `ActionResultKind` to the issued result; EventFactory binds its value into the trusted Resolution Event metadata. It is an interpretation of that adjudication, not an independent effect or world fact. After EventProcessor completion, Presentation verifies the recorded Event and processing evidence before issuing a separate `PlayerActionFeedbackMessage` for already-satisfied goals, confirmed failures, or successful results without an authorized visible fact. A successful state change with an authorized Observation continues through the fact-backed channel. The desktop renders these Presentation outputs and uses its task snapshot only for lifecycle status. It never parses the Resolution explanation or player text to infer success. The current installed door policy distinguishes an already-open target; generic unsupported/unresolved attempts remain unresolved. No persistence format changed. There is no tested action-feedback humor system; the no-result narrative prompt's optional tone guidance is not an action-feedback subsystem.


<!-- phase3c-end:C-162-2355-2359 -->


### ID 163 — No-result narrative fallback (implemented narrow path)

<a id="arch-source-163"></a>

<!-- phase3c-begin:C-163-2363-2367 -->

<a id="arch-source-163-part-1"></a>

**Phase 3C source excerpt:** ID 163, lines 2363–2367 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-163-2363-2367:2363-2367 -->

`PlayerActionService` fixes `NoResultState(UNRESOLVED_ATTEMPT)` only after `ActionResolutionFlow` returns no confirmed Event and binds it to the exact request fingerprint. An explicitly injected `NarrativeFallbackProvider` may then generate bounded, context-specific wording and separately review it for unsupported result claims. The optional `OllamaNarrativeFallbackProvider` uses the existing loopback-only transport and is never selected implicitly. Generation and review are limited to two attempts; absent, failed, malformed, rejected, or unsafe output produces no narrative and returns a non-text `clarify_or_retry` recovery action. Internal diagnostics retain stable failure codes and exception types, not exception messages in player output.

The provider receives only the no-result code and the player's own bounded intent/method text; for an unparseable input it may receive that same player's bounded raw text as untrusted content. It receives no WorldState, EventProcessor, EventHistory, ObservationStore, cognition Store, action executor, or write capability. `NoResultNarrativeMessage` has no Event or fact references, uses a distinct gateway method and is never accepted by the fact-backed `send(ValidatedMessageBatch)` path. The normal Presentation safety gate still applies. Replayed request IDs return the stored outcome and do not repeat generation or delivery. This is an application-level side-effect boundary; it is not a sandbox against hostile same-process code.


<!-- phase3c-end:C-163-2363-2367 -->


### ID 164 — Raw input classification and clarification (D3.3.1 narrow slice)

<a id="arch-source-164"></a>

<!-- phase3c-begin:C-164-2369-2381 -->

<a id="arch-source-164-part-1"></a>

**Phase 3C source excerpt:** ID 164, lines 2369–2381 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-164-2369-2381:2369-2381 -->

`PlayerActionService.submit_input` accepts a bounded host-session request and screens the raw proposal through shared Safety before delegating interpretation to an explicitly configured provider. The closed `PlayerInputAssessment` result distinguishes `UNPARSEABLE`, `CLARIFICATION_REQUIRED`, and `ACTION`; provider failure is `reasoning_unavailable`, not an invented unparseable result. An unparseable result cannot carry intent, method, target, or guessed clarification data. A clarification result must identify a necessary missing field and provide a context-specific question. It creates no `ActionProposal` or Attempt. `PlayerClarificationMessage` is receipt-bound to the trusted no-result state and delivered through its own gateway channel, separate from fact messages and literary fallback.

Only a typed ACTION candidate proceeds to the existing Safety → ActionProposal/Attempt → Resolution → EventFactory → EventProcessor path. Host-authorized Observation targets are rechecked; model output is not permission. A follow-up may resume the original request only through a bounded, service-owned pending interaction. The follow-up must identify a permitted answer, remain in the same player session and Runtime session/generation, and recheck current authorized Observations and the ordinary action boundary before execution. A new independent request, cancellation, expiry, world switch or restore invalidates the pending interaction. Pending interactions are process-local and are not saved. No-result statuses and clarification text do not write WorldState, EventHistory, Observation, Memory, Belief, Goal, trust, or relationship state. Provider absence/failure returns a non-text recovery signal; the optional Ollama interpreter is bounded, loopback-only, and explicitly selected. Model-generated wording remains fallible: the separate display channel removes world-write capability, while Presentation safety and bounded schemas reduce misleading output but do not prove arbitrary natural-language factuality. The slice does not implement universal conversational repair, persistent request transactions, or production CWUI rendering.

**Approved ANCHOR-M2-01 interaction contract:** Input understanding receives request-scoped candidate handles with descriptions drawn solely from currently authorized, provenance-checked Observations and verified player-visible content metadata. A handle maps to a canonical object only inside the player service; model output supplies no object authority. An absent or ambiguous candidate remains unresolved. Read-only inspection obtains current authorized facts and passes them through a separately typed Presentation result. It creates no World Event and never converts model prose into a fact. This is an approved contract, not a claim that the entire interaction loop is implemented or tested.

**Causal-method projection for physical input:** For candidate-based interpretation, each visible target also receives the bounded method phrases exposed by the currently installed typed causal adapter for that observed mechanism kind. The provider must select an exact offered phrase; it cannot invent a method string and thereby expand Resolution support. The player service rechecks the selected candidate and method before constructing the ordinary ActionProposal. These phrases are the input vocabulary of existing Resolution policies, not effects or permissions. Resolution still independently checks current typed state, actor position/capability, locks, source reads and Runtime write authority before EventFactory/EventProcessor. Unsupported mechanism kinds offer no executable method. This closes an action-language adapter gap for the currently installed door and passage policies only; it is not general natural-language or physical-mechanism support.

The semantic review is a model-dependent presentation filter, not proof that arbitrary free text is factually grounded; real-model detection quality is not yet validated. The hard guarantee is that this path cannot issue an Event, WorldUpdate, Observation, Memory, Belief, Goal or action proposal. No-result categories other than unresolved player attempts, presence/audibility-qualified NPC reactions, natural-language clarification flows, and CWUI rendering of the separate narrative channel remain outside this slice. A Consumer must preserve the separate channel and never display it as an Event result.

This slice preserves **State Anti-Enumeration**: no new temporary Entity-state field or world writer was added. It also exposes a current **Output Anti-Enumeration** limitation: `MinimalComposer` still renders a small typed fact family deterministically. Its generic environment-state wording is a bounded bridge, not a scalable prose strategy; future translation must remain downstream of authorization and factual validation.


<!-- phase3c-end:C-164-2369-2381 -->


## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [ARCHITECTURE.md](../ARCHITECTURE.md) — canonical owner for A02.
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) — canonical owner for A06, A13, A38.
- [EXECUTION.md](EXECUTION.md) — canonical owner for A09.
- [PERCEPTION.md](PERCEPTION.md) — canonical owner for A12, A26.
- [SAFETY_AND_NORMS.md](SAFETY_AND_NORMS.md) — canonical owner for A37.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [MEMORY_DESIGN.md](../MEMORY_DESIGN.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [COGNITION.md](COGNITION.md)
- [EXECUTION.md](EXECUTION.md)
- [PERCEPTION.md](PERCEPTION.md)
- [PERSISTENCE.md](PERSISTENCE.md)
- [SAFETY_AND_NORMS.md](SAFETY_AND_NORMS.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md)

## Historical and implementation-status handling

Only the explicitly marked Phase 3D historical quotations below have migrated. Other historical or mixed content remains pending. These source-stage records establish no new runtime capability, current test result or normative definition.

<a id="arch-history-h-130-1909-1909"></a>
### Historical source record — One product, two implementation projects

**Historical record — Historical architectural decisions.** This is an original-stage quotation, not a current normative definition, current implementation inventory or newly executed test result.

Source: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), original heading ID **130**, lines **1909–1909**; original heading: **One product, two implementation projects**.
Source document SHA-256: `d111ce446dcdf8a16182dc465f42a851177a569547b3a0cfc6519d6e8653f751`. Captured from the working tree based on `838e6913e6e6d6deefcaa6bbf126cad2139550b7`; the quoted bytes are not asserted to be the committed version.

Original context: M0.5 product/repository layout decision with still-valid division of authority and an abandoned checkout path.
Chronology: M0.5 is explicit; no calendar date inferred. Calendar date: not stated in the source.

Temporal words such as “now”, “currently”, “here”, “this document”, “below” and “at this stage” retain their original source context. Legacy paths are historical evidence, not current repository instructions. The full quoted limitations and original validation status remain attached; no broader supersession or present-day acceptance is inferred.

Current normative definitions remain with their frozen owners, including [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) and [META_CONTRACTS.md](../META_CONTRACTS.md); this quotation creates no additional authority.

<!-- Phase 3D exact source quotation begins: H-130-1909-1909 -->
> CognitiveWorld is one product. M0.5 migrates the former `D:\CWUI` prototype source to the independent `src/anchor_desktop/` package inside `D:\CognitiveWorld`; the original directory is retained as a recoverable source backup. This document remains the shared architecture authority. CW is the final authority for generated worlds, WorldState, NPC cognition/decisions, causal Resolution, trusted Events, safety, WorldNorms, saves/restores, and branches. The desktop package owns world selection, page/navigation return depth, composited avatars, narrative stage, archive interaction, save/restore interaction, and law accordion state. It must consume closed read-only projections; it must not import or mutate CW WorldState, cognition Stores, EventHistory, or saves directly. The first UI uses composited avatars rather than character portraits. Navigation and expanded/collapsed state belong to the desktop package.
<!-- Phase 3D exact source quotation ends: H-130-1909-1909 -->


<a id="arch-history-h-130-1911-1911"></a>
### Historical source record — One product, two implementation projects

**Historical record — Historical implementation snapshots.** This is an original-stage quotation, not a current normative definition, current implementation inventory or newly executed test result.

Source: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), original heading ID **130**, lines **1911–1911**; original heading: **One product, two implementation projects**.
Source document SHA-256: `d111ce446dcdf8a16182dc465f42a851177a569547b3a0cfc6519d6e8653f751`. Captured from the working tree based on `838e6913e6e6d6deefcaa6bbf126cad2139550b7`; the quoted bytes are not asserted to be the committed version.

Original context: Original prototype projection/demo/integration inventory.
Chronology: Original prototype/current-in-that-source-stage; no calendar date stated. Calendar date: not stated in the source.

Temporal words such as “now”, “currently”, “here”, “this document”, “below” and “at this stage” retain their original source context. Legacy paths are historical evidence, not current repository instructions. The full quoted limitations and original validation status remain attached; no broader supersession or present-day acceptance is inferred.

Current normative definitions remain with their frozen owners, including [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) and [META_CONTRACTS.md](../META_CONTRACTS.md); this quotation creates no additional authority.

<!-- Phase 3D exact source quotation begins: H-130-1911-1911 -->
> The CWUI prototype currently exposes a `WorldProjection` with `public_rules: tuple[str, ...]` and a local `EngineGateway`; its demo gateway is not a CW runtime integration. CW now defines the richer `WorldNormsProjection` below. Adapting CWUI to it is a later integration task; no CWUI files were changed in this phase.
<!-- Phase 3D exact source quotation ends: H-130-1911-1911 -->


Contact: ankorgine@outlook.com
