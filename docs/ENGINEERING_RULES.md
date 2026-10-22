# CognitiveWorld Engineering Rules

Version: 1.0

---

# 1. Purpose

This document defines the engineering constraints of CognitiveWorld.

The purpose is to prevent architecture degradation during development.

All code changes, AI-assisted development, and system extensions must follow these rules.

If a new requirement conflicts with these rules, the architecture should be improved instead of bypassed.

---

# 2. No Hardcoded World Content

Core logic must not contain specific world content.

Forbidden:

- specific character names;
- specific locations;
- specific stories;
- specific events;
- specific keyword triggers.

Examples of forbidden patterns:

```python
if character_name == "specific_character":
    special_logic()
```

```python
if "keyword" in text:
    create_event()
```

```python
if world_id == "specific_world":
    special_behavior()
```

World content must be data-driven.

Examples:

- `scenarios/`
- `characters/`
- `rules/`
- `events/`

Core systems provide mechanisms. Scenario data provides content.

---

# 3. AI Boundary Rules

AI cannot directly modify reality.

AI may:

- understand language;
- extract intentions;
- generate proposals;
- summarize confirmed experiences.

AI may not:

- modify World State;
- create confirmed facts;
- directly write permanent memory;
- bypass Event System.

Required flow:

```text
AI
  ↓
Proposal
  ↓
Validation
  ↓
Event
  ↓
World State
  ↓
Memory
```

---

# 4. World Core Authority

World Core is the only authority of reality.

All state changes must happen through Events.

Forbidden:

```python
entity.relationship += 10
```

Required:

```text
Event
  ↓
World Update
  ↓
State Change
```

---

# 5. Natural Language Is Not Action

Natural language must not directly map to predefined actions.

Forbidden:

```text
Text
  ↓
Action ID
  ↓
Execution
```

Required:

```text
Natural Language
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
```

---

# 6. Intent and Attempt Separation

Intent represents: “What does the player want?”

Attempt represents: “How does the player try?”

Different attempts under the same intent must remain distinguishable.

Example:

Intent: Enter castle

Attempts:

- Persuade guard
- Climb wall
- Steal key

---

# 7. Resolution Rules

Resolution must produce concrete consequences.

Success/failure labels are only human-readable summaries.

The actual output must contain:

- time changes;
- relationship changes;
- location changes;
- information changes;
- environment changes.

---

# 8. Event First Architecture

Events are the only representation of confirmed world changes.

All of the following must become Events:

- player actions;
- NPC actions;
- environmental changes.

---

# 9. Memory Rules

Memory cannot invent facts.

Incorrect:

```text
AI assumes NPC likes player
  ↓
Save memory
```

Correct:

```text
Confirmed Event
  ↓
Memory Consolidation
  ↓
Long-term Memory
```

---

# 10. Module Independence

Modules must maintain clear boundaries.

Avoid:

- circular dependencies;
- hidden state modification;
- cross-layer shortcuts.

Recommended dependency:

```text
Presentation
  ↓
Application
  ↓
Domain
```

AI modules should be external capabilities.

---

# 11. Data Before Code

When adding functionality, prefer:

- data;
- configuration;
- rules.

Avoid adding special branches for individual cases.

---

# 12. Git and Documentation Safety

CognitiveWorld uses Git-first development.

Before major changes:

- create a checkpoint commit;
- verify repository status;
- avoid destructive batch operations.

Important assets must always have version history:

- architecture documents;
- data contracts;
- AI boundary definitions;
- core source code.

---

# 13. AI Coding Rules

AI coding assistants must:

- respect architecture documents;
- avoid hardcoded solutions;
- avoid bypassing validation;
- avoid modifying unrelated modules.

When architecture is insufficient, create a general mechanism.

Do not add special cases.

---

# Final Principle

CognitiveWorld grows through:

- general mechanisms;
- clear boundaries;
- controlled evolution.

Never solve a temporary problem by damaging the permanent architecture.

---

# 14. Runtime and Authority Boundaries

## World State

- `WorldState.load_*` is reserved for initialization and restoration.
- Runtime changes must flow through `EventProcessor` → `EventHandler` → `WorldUpdate` → `WorldState.apply_event()`.
- Runtime code must not write WorldState directly or use `load_*` as a mutation shortcut.
- EventProcessor records successfully applied Events in EventHistory when configured. Causal records require caller-supplied cause references; the processor does not infer causes.
- `apply_event()` is capability-gated to EventProcessor; initialization `load_*` closes when the Runtime starts or before EventProcessor invokes the first handler. Close loaders before handler execution so a handler cannot mutate runtime state through an initialization API. This is an application-level guard, not same-process isolation.

## Resolution and Agent Decision

- EventFactory may create an Event only from an intact ResolutionEngine-issued confirmation; `confirmed=True` alone is not authority.
- The default ResolutionEngine is unresolved and unconfirmed. Do not describe it as an implemented rules engine or autonomous outcome authority.
- AgentTurn must bind the RuntimeAgent identity to CognitionContext ownership before building DecisionContext.
- DecisionContext is a deeply immutable, owner-scoped snapshot of Percepts, WorkingMemory, Character-linked Memories, Beliefs, Goals, Personality, SelfModel, Emotion, and optional turn-local MetacognitiveFeedback.
- Relationship is not yet a DecisionContext input. Phase 12.2 retrieval is restricted to Character-linked owner records and the bounded turn-local L5 policy; it is not a complete cognitive reasoning strategy.
- For a `DecisionContext`, `AgentDecision` must use the bounded Phase 12.4 situation, candidate, evaluation, and review pipeline and emit only the existing `ActionProposal`. Legacy `CognitionState`/Mapping compatibility inputs may retain placeholder behavior and must not be described as the production policy.

## Cognition Updates

- Belief and Goal changes follow Proposal → CognitiveUpdateValidator → CognitiveUpdateApplier → authoritative Store.
- Validation results must be validator-issued and match the unchanged proposal before applying.
- Evolution orchestration creates proposals only; it does not apply them.
- SelfModel has a narrow, opt-in governed runtime evolution path for tentative owner-scoped entries derived from newly L1-consumed trusted Observations; it is not a general identity rewrite. Personality remains without a governed runtime evolution path and must not be described as evolving.

## Memory Authorization

- `MemoryProposal` is the only candidate model. Compatibility aliases must not create a parallel representation.
- A Memory write must originate from an accepted, authority-issued MemoryDecision, be converted by MemoryWriteFactory into a snapshot-protected MemoryWriteRequest, and be persisted by MemoryPersistence.
- MemoryPersistence validates the request snapshot and confirms that its source Event exists in EventHistory before writing to MemoryStore.
- MemoryDecisionAuthority only seals results from the explicitly installed, versioned policy call. `MemoryDecisionEngine` is implemented as the bounded policy orchestration path; it is not a default importance policy. Formal Memory/v2 writes must pass Factory, MemoryPersistence, MemoryStore, the original RuntimeWriteFence permit, and the current branch-local revision view.
- Memory/v2 revision visibility is checked against the exact signed ancestor checkpoint cognitive records and the current Timeline-local revision graph. Do not infer ancestry from Timeline IDs, Event presence, owner equality, or the active Store alone. Missing verified checkpoint ancestry fails closed.
- Event, Observation, and ShortTermMemory formation adapters must preserve the source Event reference. Persistence remains the source existence gate.

## Presentation Safety (Phase 12.0)

- Player chat may receive only the closed `PlayerVisibleMessage` contract through an approved Presentation output path.
- A no-result narrative is display-only and must use the separate `NoResultNarrativeMessage` channel; it has no Event/fact provenance and must never be merged into an Event result, action, Observation, or cognition update.
- No-result wording may be requested only after a typed result state has been fixed. LLM generation and semantic review are bounded; missing, invalid, rejected, or failed output must return a non-text recovery signal without exposing raw provider errors.
- Model prompts and semantic review do not grant world authority or prove arbitrary text true. Keep fallback providers disconnected from WorldState, EventProcessor, EventHistory, action execution, and cognition Stores; only EventProcessor may commit confirmed world changes.
- Filter backend information before generating player-visible text. Do not serialize Events, Observations, cognition records, diagnostics, or arbitrary metadata directly to chat.
- Never expose internal cognition analysis, EmotionState values, thresholds, probabilities, scores, decision traces, Prompts, debug data, or internal state objects.
- Event existence alone does not authorize every Event field for presentation. Actual spoken dialogue must be recorded as spoken and audible to the recipient; internal thoughts are not dialogue.
- Legacy `presentation_facts`, caller-supplied scopes/audiences, and manually constructed Presentation DTOs are never authorization. The current narrow Presentation path reads only existing Observation authorization results, typed ObservableFacts, and trusted RuntimeContext session bindings; Python receipts remain ordinary-misuse guards, not same-process security.
- Any UI/chat integration must fail closed and send only through `ChatOutputGateway` using the appropriate validator-issued typed contract. Within Core, `InMemoryChatOutputGateway` is the callable implementation; the M0.5 desktop package has no live player-chat adapter. Do not provide unvalidated fallback text.
- Action feedback must derive from a closed typed Resolution result and completed EventProcessor evidence, never from player wording, model self-report, or free-form Resolution explanation. Keep result feedback separate from fact-backed messages; an action summary cannot create or imply an unconfirmed state change.

## Core, UI, asynchronous work, and DTO boundary

- Core and domain modules must not import PySide6, Qt, Web frameworks, or UI controls. Client adapters depend on CW's application contracts and safe projections; Core never calls client code.
- Long-running LLM inference, retrieval, or physical computation must not execute synchronously on a UI main thread. Expose asynchronous submission/result interfaces at the application boundary; keep toolkit Signals and Web callbacks in adapters. Do not prescribe a thread/process model without a runtime requirement.
- Bind background task results to their request and relevant Runtime session/restore generation. Define cancellation, timeout, duplicate submission, exception, shutdown, and stale-result behavior. A task has no write authority and must re-enter RuntimeWriteFence, authorization, Resolution, and EventProcessor before committing state.
- A thread handoff must explicitly carry the original operation capability; do not capture a replacement permit after slow work. Cancellation must serialize with the final write boundary and state its linearization point. If the commit section has begun, cancellation cannot imply rollback.
- Potentially unbounded authorization/retrieval scans must not be hidden in a synchronous task-admission call. Perform them on the worker under a consistent view of the original Runtime generation, then revalidate any action target at the normal authority boundary.
- An embedding or other semantic retrieval provider receives only owner- and Character-authorized, semantically retrievable Memory text under an explicitly approved data destination. Derived vectors and similarity scores are candidate hints, never access grants, Event anchors, facts, or causal evidence. Recheck canonical Memory before use, bound added scans/results, and preserve lexical retrieval when the optional provider fails. A slow provider must run off the UI main thread.
- Keep execution completion independent from Presentation delivery. Re-delivery of a committed Event must read canonical completed history, repeat current Presentation authorization and Gateway deduplication, and never repeat interpretation, Resolution, or Event dispatch.
- Serialize an in-process Event Presentation retry against Runtime generation advancement using the original operation capability; do not mint a new permit for an old task. If shutdown cancels a queued retry, complete its public Future with an explicit pending-recovery status rather than leaving it unresolved. Keep synchronous Gateway work bounded because a generation-safe projection may hold the Runtime snapshot scope until delivery returns.
- Progress notifications may be coalesced or rate-limited. A committed Event must remain recoverable from authoritative history or an authorized ordered projection after a disconnected/slow subscriber reconnects. Presentation delivery failure must not roll back or reinterpret committed world facts.
- Construct client DTOs from explicit authorized field allowlists. Never serialize full Event, Observation, EventHistory, WorldState, RuntimeContext, cognition objects, Store objects, signatures, internal provenance, or arbitrary metadata. Keep confirmed facts, Observations, clarification, Narrative Fallback, progress, and error/recovery messages in distinct typed contracts.
- DTOs expose only recipient-necessary fields and detached values. Add fields only after a necessity, authorization, safety, and compatibility review. Internal errors and traces remain in diagnostics; client status uses bounded non-sensitive codes and safe text.
- Every cross-layer slice must review these dependency, async-lifecycle, projection, and failure-isolation rules and add tests for the affected boundaries. If a slice spans multiple modules or reveals contract drift, propose a bounded central review; do not expand a clear local change solely to satisfy process.

## Third-Party Implementation Independence

- Public projects and papers may be studied for general architecture ideas, algorithmic principles, and technical trade-offs. Record sources when using them to inform an independent design.
- Do not copy, translate, rewrite, port, or closely imitate third-party project code, Prompt templates, or distinctive implementations, including by reproducing them section by section. Do not copy third-party project-specific classes.
- Independent implementations must be designed for CognitiveWorld's own requirements, data contracts, architecture, and data authority boundaries. Borrow general ideas and algorithmic principles only.

## Decision Cognition Snapshot and Retrieval (Phase 12.1–12.2)

- AgentTurn must bind RuntimeAgent, CognitionContext, and Character identity before assembling the decision snapshot.
- DecisionContext contains only detached owner-scoped snapshots. Recursively freeze nested records, mappings, and sequences; never expose a Cognition Store, MemoryStore, ObservationStore, WorldState, or mutable authoritative record.
- L1 Percepts require trusted Observation provenance and matching observer identity. L2 WorkingMemory is owner-scoped. L3 Memory is restricted to Character references and matching owner IDs. L4 Belief, Goal, Personality, and SelfModel data must be owner-matched. Preserve source references and do not label subjective Beliefs or Memory as objective world facts.
- Emotion remains a cross-layer input. Memory retrieval must use the canonical MemoryStore and IDs authorized by the current Character reference list; recheck owner/source fields and return immutable detached snapshots. Relevance, importance, and subjective content do not establish objective truth or confidence.
- L5 feedback is owner-bound and turn-local. Use the replaceable metacognition policy with explicit retrieval, round, and result budgets; deduplicate repeated queries and preserve uncertainty on exhaustion. It cannot write Belief, Memory, or SelfModel directly; existing update validation and memory persistence boundaries remain mandatory. Do not create another cognition Store. Motivation continues through Goal data.
- DecisionContext may only support Proposal generation. It cannot mutate WorldState or EventHistory. Only Resolution confirmation and EventProcessor's controlled path may lead to runtime world changes.
- Presentation must not accept DecisionContext, private Memory, internal reasoning, or Prompt data.

## Cognitive LOD (Approved Design, Not Implemented)

- Cognitive LOD may allocate compute by NPC importance, player interaction demand, event relevance, and cognition budget; planned mechanisms include priority scheduling, dynamic wake-up, background batches, and reasoning precision upgrades/downgrades.
- All precision levels use the same authoritative cognition state. Lower precision cannot discard confirmed important Events; higher precision cannot invent objective Events or character experiences.
- LOD changes computation granularity, frequency, and resource allocation only. It cannot alter world facts or Event confirmation authority, and remains separate from Causal LOD.
- Cognitive LOD does not change L1 Perception, L2 Working Memory, L3 Long-term Memory, L4 Beliefs & Self-Model, L5 Metacognition. Emotion and Motivation remain cross-layer modulators.
- These are approved design constraints, not implementation claims.

## Phase 12.0b Trusted Event Foundation (Implemented, application-level only)

- Agent action Events must originate from a controlled ResolutionEngine-issued result. `ResolutionResult(confirmed=True)` alone is not proof; EventFactory verifies the result's bound confirmation snapshot.
- EventProcessor verifies intact Event provenance before handlers run or WorldState is written. Post-issuance edits to result/Event fields invalidate their receipts.
- `SystemEventFactory` is the explicit trusted-application ingress for scheduled, environment, and system Events that do not arise from an Attempt. EventScheduler controls timing only; it does not authorize Events. Dispatch still passes through EventProcessor.
- EventHistory is a record system, not an authentication system. Do not infer trust from EventHistory membership. Reuse existing EventHistory and WorldState; do not create parallel stores.
- These Python seals and snapshots address normal application misuse only. They do not protect against malicious code in the same Python process. SystemEventFactory must remain within trusted application composition.
- The default ResolutionEngine returns unresolved when no policy is installed. Do not treat player-provided `success`, `confirmed`, `outcome`, or `world_changes` claims as a Resolution decision. Attempts remain open-ended and are not restricted by a fixed action enum.

## Shared Observation and Presentation Rules (Narrow Agent and Player Slices Implemented)

- Agent Observation and player Presentation share observable-fact rules but have independent trusted identity/permission contexts. Use trusted Event facts, necessary event-time world state, observer identity, location/environment, and sensory rules. Missing required data means deny.
- Event provenance alone does not establish observability. Do not generate Agent Observation or player Presentation by copying an Event, its metadata, or EventHistory membership. Phase 12.0c-4 implements one narrow production path: `RoomLightChangedHandler` verifies a controlled system Event against authoritative room light state, then emits an explicit typed fact. SimulationRuntime supplies its clock and AgentRegistry to EventProcessor. EventProcessor captures observer locations and typed `Entity.sensory_capabilities` at the synchronous post-update event boundary. `VisibilityPolicy` authorizes only registered, co-located observers with known `sight`, for a confirmed room-light-on fact and known simulation time. Missing inputs deny. Do not infer sight, position, or visibility from defaults, Event metadata, participants, or cognition.
- `CognitiveEvolutionEngine` must reject untrusted Events and must not synthesize an Observation. No matching record returns `UNOBSERVED`; a matching record without a valid receipt returns `UNAUTHORIZED_OBSERVATION`; both return no event-driven belief, goal, or memory proposals. Matching observer/Event IDs and ObservationStore membership are not authorization.
- `CognitiveRuntime` is also a direct ingestion boundary: it may create Percepts only from Observations with valid unchanged provenance and an observer ID matching the requested Agent. Do not rely solely on AgentTurn or CognitionContext to enforce this.
- `PerceptionProcessor` is a direct conversion boundary too; require both valid provenance and the expected observer ID. Do not call it as an unchecked shortcut around CognitiveRuntime.
- ObservationStore remains copy-isolated storage. A manually constructed Observation stays untrusted after storage. Consumers must validate every retrieved or caller-supplied record; storage does not sign, repair, or authorize it.
- The controlled production Observation issuer accepts only trusted EventProcessor evidence and a successful `VisibilityPolicy` result; it signs only the typed fact content. The compatibility `ObservationGenerator.generate()` continues to fail closed. Tests must exercise the production handler/policy path for positive authorization and may use test-only fixtures only for unit-level boundary tests. Do not add a production test-signing API or use Event metadata/external input as issuance authority. The process-local receipt only addresses ordinary application misuse and is not a same-process security guarantee.
- EventHandler's typed ObservableFact hook defaults to empty. Generic WorldUpdate payloads and Event metadata must never be promoted automatically. EventProcessor validates Event provenance before and after handler work, validates drafts before state mutation, and may issue fact evidence only after a successful WorldState application.
- Preserve `EventProcessor.process()`'s existing `None` return contract. Use the additive `process_with_evidence()` method when a caller explicitly needs the immutable processing evidence.
- EventHistory may store EventProcessingEvidence alongside an Event but does not authenticate it. Consumers must validate the processor-issued evidence and its unchanged Event/fact snapshots; EventHistory membership alone is never authorization.
- Event processing uses the existing EventHistory for an in-process Event-ID progress marker. Reserve before handler work; do not apply a matching Event twice. Pre-WorldState failures may release the reservation. Once `WorldState.apply_event()` begins, failures must be surfaced as recovery-required and must not trigger automatic reapplication. Do not describe WorldState mutation, evidence issuance, EventHistory append, and Observation delivery as atomic.
- After Event plus evidence are recorded, Observation delivery may be retried from that evidence without rerunning the handler or WorldState update. Stable Observation IDs allow the existing ObservationStore to overwrite duplicate saves. A failed WorldState/History boundary without recorded evidence is not automatically recoverable; report it explicitly. Current progress markers are in-memory only and do not guarantee process-crash recovery or coordination across processors.
- `CognitiveRuntime` de-duplicates WorkingMemory percept references by stable Observation-derived Percept ID, not by text similarity. Keep Agent ownership in the WorkingMemory key and do not merge distinct Observation IDs, even when their content matches.
- Stepwise L1 proof must come from the existing `CognitiveRuntime`: record a bounded, process-local receipt only after the trusted Observation passes `PerceptionProcessor` and is reflected in the owning WorkingMemory. Bind it to owner, Observation snapshot, source Event, runtime instance, and existing WorkingMemoryStore. Do not treat `CognitionState.percept_ids` as a history list; it reports newly ingested IDs and can be empty on valid replay. A cross-Agent call or caller-supplied percept ID must not authorize continuation. Do not claim these receipts survive restart or resist malicious same-process code.
- Repeated CognitiveEvolutionEngine calls remain proposal generation. They must not directly mutate cognition; Belief/Goal updates still require the existing validator/applier and current-state checks, and Memory writes still require the existing decision/persistence path. Do not add a second cognition Store or claim arbitrary external proposal application is globally exactly-once.
- EventTimeObservationContext must state its capture phase. The supported vertical slice snapshots registered Agent location/sensory capability and the relevant environment condition at the synchronous post-update EventProcessor boundary; these are event-bound immutable values. Event.timestamp is not a SimulationClock snapshot. Outside a Runtime-bound EventProcessor, simulation time remains unknown and visibility denies. Do not infer historical state from a later mutable WorldState.
- ObservableFact values are immutable, limited typed values without permissions, presentation scopes, metadata bags, or private cognition. Fact types and predicates remain open descriptive strings and must not become a fixed action enum.
- Events cannot declare their own display permission. Do not use Event metadata or caller-supplied PerspectiveContext scopes/audiences as authority. Never copy full Event metadata into Observation or Presentation.
- `RuntimeContext.player_session` is the host-populated identity/view binding; it is optional and missing means deny. `PerspectiveResolver` must accept no caller-provided recipient, observer, mode, audience, or scopes. Roleplay requires a registered RuntimeAgent with a Character binding; Observer mode uses a separately bound view Agent; Director mode stays denied until an explicit policy is implemented. This in-process contract is not network authentication.
- Presentation may reuse an existing trusted Observation only when observer, source Event, content receipt, EventProcessingEvidence, and the shared VisibilityPolicy all validate. Do not read Cognition or Memory Stores for player output. Phase 12.0d currently supports only the room-light-on fact.
- `MinimalComposer` accepts only immutable filter-issued typed inputs and uses deterministic mappings. Output text must match the authorized fact; do not invent outcomes, dialogue, inner thoughts, or internal analysis. `PresentationValidator` rechecks source and text before issuing `ValidatedMessageBatch`; the message model alone is not authorization.
- `ChatOutputGateway` is the sole approved player-chat sending interface and accepts only validated, unmodified batches bound to the active RuntimeContext session. `InMemoryChatOutputGateway` is the current adapter; no PySide6/UI sender migration has occurred. It must reject raw strings, Events, Observations, and manually constructed message/batch objects. It may expose only non-sensitive error status.
- Open-ended actions must not be restricted by fixed behavior enums. Interpretation retains behavior, target, tools, method, conditions, order, and intent; player-stated outcomes are claims, not facts.
- Resolution evaluates feasibility and method-relevant conditions, not prose length, rhetoric, or token count. Unknown methods are not rejected solely for being unknown. Multi-step actions resolve incrementally against actual intermediate results.
- Players control their own attempts; NPC reactions follow NPC cognition and events; Resolution decides world outcomes. NPC decision design remains grounded in L1 Perception, L2 Working Memory, L3 Long-term Memory, L4 Beliefs & Self-Model, and L5 Metacognition. Emotion and Motivation are cross-layer modulators; individual thresholds, irrational-action ceilings, and growth curves are cognition-derived. Decision only proposes.
- The remaining items above are approved architecture requirements, not implemented capabilities. Do not make code or status claims implying otherwise.

## Emotion and Motivation Authority

- Keep dynamic Emotion in the existing `CognitionContainer` authority and individual `EmotionProfile` configuration in the existing owner-scoped `Personality` record/PersonalityStore. Do not create an Emotion/Profile/Motivation Store.
- Only trusted initialization may set profile parameters until a governed profile-growth proposal exists. Never infer parameter values from `Personality.metadata`, arbitrary SelfModel text, player text, Prompt output, or a global population template.
- Emotion appraisal consumes the current Agent's verified Percepts and frozen owner-scoped DecisionContext. A typed fact can support a subjective appraisal only through an explicit individual profile rule; Event text and metadata do not command an emotion.
- Persistent Emotion changes must use Proposal → Validation → Apply, bind source Observation/Percept/Event and captured SimulationClock time, check the old state, and deduplicate by stable source Event identity. Missing time means no time decay; reject backwards time.
- Emotion and Motivation policies are cross-layer computation, not additional cognition layers. They cannot access another Agent's private cognition, mutate WorldState, create Events, or change persistent Goal priority.
- DecisionModulation supplies bounded relative inputs to the Phase 12.4 Decision Policy. It must not itself generate actions, modify Resolution odds, or claim an uncalibrated ceiling is a measured probability.
- Never pass Emotion levels, profiles, thresholds, appraisals, Motivation scores, modulation values, or internal rationale to Presentation. Player-visible emotion must arise from separately confirmed and authorized observable behavior.

## Phase 12.4 Autonomous Agent Decision

- Decision policies may read only the current Agent's immutable `DecisionContext`; they must not read Stores or `WorldState`, write cognition, or depend on another Agent's private state.
- Keep observed Percept facts, subjective Beliefs, personal recollections, and unknown information distinct. Relevance or Belief confidence is not objective truth.
- Keep action semantics open-ended. A candidate describes an attempt through intent, target, method, resources, preconditions, steps, and uncertainty; do not impose a universal action enum or reject a method only because it is novel.
- Candidate ranking is a subjective preference estimate, never an outcome or success probability. Emotion, Motivation, and individual modulation must be capable of changing ranking, but cannot modify Resolution or grant capabilities.
- The deterministic candidate policy is a bounded fallback, not general open-ended generation. Optional language-model providers must be explicitly configured; parse outputs into the candidate schema, assign owner/source identifiers locally, enforce fixed candidate/step/context/output/call/review budgets, and fall back safely on provider or ordinary format failure. Authority-shaped fields must be rejected visibly and cannot be silently stripped then trusted.
- Model output is untrusted proposal text. It cannot grant authority, add observations or memories, assert NPC reactions, confirm success, mutate a Store, or create an Event. Programmatic schema checks are required; Prompt wording alone is not a boundary.
- `AgentDecision` may emit only the existing `ActionProposal`. Multi-step plans describe intended conditional steps; they are not pre-resolved. `ActionPipeline` may create an `Attempt`; only Resolution may confirm a result, EventFactory may create a confirmed Event, and EventProcessor remains the runtime WorldState update path.
- Candidate scores, internal rationale, cognition, Emotion/Motivation values, model prompts, and raw model output must never enter Presentation or player chat.

## Phase 12.5 Resolution Rules

- Keep import dependencies pointed toward lower-level contracts: core Resolution may validate the `SimulationTime` value issued by Runtime, but importing Resolution result/engine APIs must not eagerly load Runtime orchestration, AgentTurn, or AgentDecision. Runtime owns clock issuance and orchestration; Resolution adjudicates and returns a bound result without calling back into Runtime. Package `__init__` facades must defer optional higher-level exports where eager loading would create a cycle. Do not remove or weaken the runtime type/provenance check for clock-issued `SimulationTime`.
- Reuse `ActionProposal` and `Attempt`; do not add a closed action enum or parallel action model. Interpretation may reject structured authority fields, but ordinary prose claiming success is neither accepted as fact nor punished.
- Resolution policies may read only the smallest immutable owner/action-scoped objective context required for adjudication. Do not pass mutable WorldState or any NPC private cognition to a causal policy.
- A causal effect must be issued by the ResolutionEngine policy, bound to the full Attempt snapshot, carried by EventFactory, and revalidated against current relevant state by an EventHandler before EventProcessor applies its WorldUpdate.
- A Resolution-sourced Event carrying world effects must contain a valid successful or explicitly partial result summary. A confirmed failure may be recorded without effects; it may not smuggle a state change through an effect handler. A partial effect must still be explicitly issued by the Resolution policy and pass the domain handler's state checks.
- Unknown facts and unsupported methods remain unresolved. Do not convert missing position, capability, tool, target state, time, or world rule into permission or automatic failure. A known contradiction may be adjudicated infeasible.
- Ordered plans are intentions. Resolve at most the current eligible step, then read the newly confirmed state before considering later steps. Never submit a whole plan as completed effects.
- Causal/model reasoning may propose explanations or evidence needs. It cannot issue ResolutionDecision credentials, Events, WorldUpdates, NPC reactions, or success claims. No Prompt replaces structural and state validation.
- Resolution does not set another Agent's beliefs, Emotion, Goal, Memory, or future action. Such responses return through authorized Observation and that Agent's cognition/decision loop.
- Installed causal rules are typed domain adapters behind the shared MethodBasedResolutionEngine. Do not turn domain adapters into a closed action menu. Unknown facts and unsupported methods remain unresolved; model suggestions cannot supply authoritative premises or effects.
- `WorldState.apply_event()` requires EventProcessor's short-lived content-bound application capability. Initialization `load_*` methods close when SimulationRuntime starts or before EventProcessor invokes its first handler. This is an ordinary application misuse barrier only; do not present private Python capability code as same-process isolation.
- Ordered plans are executed one step at a time. Bind step IDs to proposal content, re-read current state, process results through EventProcessor, and require the actor's trusted Observation plus a valid L1 consumption receipt before continuing. Validate progress signature, runtime binding, proposal/content binding, and bounded counters before interpreting `COMPLETE`, `FAILED`, or `UNRESOLVED`. Reject manually constructed or modified progress; a frozen dataclass alone is not provenance. Keep the one-call provider budget in the executor across retries, not only in caller-carried progress. Progress is non-durable; never roll back earlier confirmed steps after a later failure.
- Bounded Attempt validation must reject cycles and excessive size/depth while permitting the same immutable or mutable child object to be referenced from separate sibling fields. Detect cycles on the active traversal path; repeated object identity by itself is not a cycle and must not reject a valid controlled `AgentDecision` proposal.
- The OpenAI-compatible causal adapter is optional, bounded, and strictly parsed. Keep actor identity locally assigned, reject unknown fields, cap input/output/time/calls, and treat model output as non-authoritative. Do not claim live model validation unless an endpoint was actually tested.
- Current deterministic causal support is the direct door slice and typed passage traversal slice. Partial outcomes are representable, but no production partial-effect rule exists. Do not claim general physical, social, or natural-language causal understanding.

## Hybrid Physical Engine and Independent LOD Axes (Approved Design, Not Implemented)

- Keep the world coordinate frame canonical and stable. Subject-centered polar/spherical coordinates are detached projections with explicit origin, axes, handedness, units, and transform version; switching observers or moving the frame origin never changes WorldState positions. Use one immutable world snapshot/tick when comparing simultaneous Agent projections.
- Keep cognitive, perceptual, and physical-computation LOD as separate policies and budget outputs. An aggregate coordinator may allocate total compute, but distance alone cannot set all three axes. Record each axis's inputs, chosen level, budget, uncertainty, and upgrade reason.
- Treat distance, collision proximity, velocity, energy, constraint sensitivity, hazard, validity bounds, uncertainty, and consequence severity as distinct physical scheduling evidence. Lower precision may conservatively defer or request escalation; it must not ignore a hard constraint or silently decide a consequential outcome. If required precision is unavailable or models disagree, keep the outcome unresolved.
- Use discrete typed rules for explicit state transitions and bounded continuous approximations only inside declared validity ranges. Contact, constraint, or threshold cases that can affect a consequential Event require deterministic refinement or fail-closed uncertainty. World/scenario configuration supplies geometry, receiver structure/material response, and environmental parameters; do not hardcode a setting or promote free text/model suggestions into physical facts.
- Keep perception owner-authorized and separate from global physical state. LOD may reduce detail delivered to an Agent but cannot grant hidden-state access, fabricate Observations, or turn a local coordinate projection into objective position evidence.
- Physical evaluation returns an immutable assessment/proposal bound to Attempt, tick, canonical state-slot reads, units/model version, uncertainty, and upgrade result. It cannot write WorldState. Any accepted change still requires Resolution confirmation, EventFactory, and EventProcessor revalidation before `WorldState.apply_event()`; LOD cannot bypass permission, hard constraints, source checks, or handler validation.
- Add deterministic tests for transform round trips, multiple observer frames, spatial/collision boundaries, escalation decisions, model disagreement, budget exhaustion, and no pre-Event mutation. Do not introduce continuous integration, multi-body propagation, or a generic materials engine until one bounded domain needs it and has typed state, rule, event, and restore contracts.

## Entity composition and declarative mechanisms (rules for proposed evolution)

The ECS/component direction in ARCHITECTURE.md and the proposed Entity contracts in DATA_CONTRACTS.md are not implemented APIs. Apply these constraints to later `POST-MVP-07` work; do not rewrite the current engine or make ECS a prerequisite for the MVP.

- Separate stable identity, display, component state, typed relations, calculation and commit authority. Preserve existing canonical WorldState and owner cognition/Memory Stores; no duplicate ECS state or universal Entity cognition bag.
- Prefer composing registered components and mechanisms for a new entity. Add a new contract only for genuinely new semantics; never dispatch on a particular world, object/person name, input phrase or demonstration outcome. JSON is bounded declarative data, not code, an import path, a permission or a runtime patch.
- Validate component schema/version, exact fields, values/units, identity uniqueness, references and mechanism dependencies before admitting data. An explicit persistence codec registration does not establish component semantics or effect authority. Unregistered/unsupported components cannot execute, even if a model supplied valid JSON.
- Distinguish structural hierarchy from attachment, transmission, physical constraint, spatial containment, ownership and organizational/business relations. Define each relation's endpoint roles, cardinality, lifecycle and topology. Detaching a part preserves its identity and unrelated links unless separately validated effects require changes; no implicit ownership transfer or cascade.
- Ground and reauthorize every child target from the acting observer's current permitted context; parent access never grants all descendants. Recheck endpoints, applicability, affected state and original Runtime session/generation/permit before formal effects. Keep CPU physical reads separate from what an NPC or model may know.
- Prefer pure calculations over immutable explicit inputs. Keep LLM/network calls, clock/random sampling, I/O, scheduling and persistence at explicit side-effect boundaries. Mechanism versions and sampled inputs must support deterministic reproduction. Pure outputs remain candidates, cannot mutate world/cognition, issue permits or submit Events, and cannot claim formal confirmation.
- Declare composed-mechanism dependencies, ordering and conflicting deltas. Revalidate expected prior state at the existing Resolution/commit boundary; recompute or stop unresolved if stale. Do not grant old work a new permit, silently use last-writer-wins, or claim generic multi-record atomicity before an actual handler/transaction contract is tested.
- Unknown mechanism coverage may justify bounded evidence/completion/alternative exploration under `POST-MVP-02`, not arbitrary dynamic execution. Missing a model is not proof of impossibility; missing authority, P0 denial and verified hard constraints still forbid the corresponding effect. No unknown candidate enters canonical state before the relevant reviewed validation and Event path.
- Extend persistence only through explicit symmetric record/version allowlists and reviewed signed compatibility. Keep Bundle, verified EventHistory ancestry, trusted cold/active publication and RuntimeWriteFence unchanged; no fabricated parent history or re-signing unknown data. New component/graph restore tests must precede an implementation claim.
- Acceptance must exercise independently identified parts, unrelated-link preservation, authorization, deterministic replay, stale/conflicting candidates, malformed/unknown schemas, formal commit and save/restore/branch isolation. Reuse one implementation across at least two different content configurations and a separately reviewed nonphysical composition. UI receives only authorized thin projections, never a raw component/relationship dump. Design diagrams and existing narrow tests do not count as ECS acceptance.

## Future Entity State, Open-Ended Causality, and Anti-Enumeration (Design Only)

- Follow the future-design contract in `docs/ARCHITECTURE.md` and the Entity/Attempt contracts in `docs/DATA_CONTRACTS.md`; these do not describe implemented APIs.
- Keep Entity identity/type separate from runtime state. Temporary conditions such as unconsciousness, injury, restraint, or death do not change an Agent into an Object or create a new Entity type.
- The narrow `PlayerInputUnderstandingProvider` may classify bounded player text and propose an action candidate, but cannot ground ambiguous targets from hidden WorldState, authorize targets, assert outcomes, create Events, or write state. Recheck every target against that session's authorized Observations before the ordinary action path. Resolve targets using explicit `object:{id}` / `agent:{id}` namespaces where available; never infer a namespace from a name or string shape. The namespace does not grant access. `UNPARSEABLE`, `CLARIFICATION_REQUIRED`, and provider/reasoning failure remain distinct; clarification and literary fallback use isolated display-only types and never become action results.
- Keep future Physical and Cognitive/physiological causal domains as bounded state readers and transition proposers with disjoint write scopes, not action taxonomies or independent engines/world writers. All accepted effects remain subject to the shared Resolution/EventProcessor authority and existing cognition-update governance.
- Unknown target grounding, unsupported predicates, missing evidence, or effects outside an implemented policy remain unresolved (or an explicit clarification/unsupported result). Do not force success or failure to advance a narrative. Combat is a future stress test of these general contracts, not a reason to add a fixed combat-action family.
- Avoid one-off fields for each new transient state. Prefer typed, authorized effect/source/interaction representations; this does not permit arbitrary state bags.
- Keep World Facts, Resolution results, and Observations structured. Presentation prose is not factual input; do not create a fixed text template for every circumstance or flow generated prose back into Resolution/Event authority.

## Phase 12.5C P0 Safety, Conflict, and WorldNorms Rules

- `UniversalSafetyGovernance` is an application-level invariant shared across every world, player, NPC, mode, provider, and director action. No WorldDocument, ScenarioPackage, PlayerPrompt, NPC Goal, director command, model response, or ordinary configuration may disable it or add exemptions. Do not rely on a Prompt or a keyword/regex list as the sole semantic safety layer.
- Safety assessment is not a world-result authority. It may allow, restrict presentation, refuse, or request clarification/safe degradation. Refusal itself must not append EventHistory, alter WorldState, create a crime finding/punishment, or be written as a character's Memory/Belief.
- Preserve conflict. Arguments, threats, insults, betrayal, fictional crimes, war, combat, death, competing goals/resources, NPC refusal, hostility, and attempts to escalate/de-escalate are not rejected solely because they are violent, illegal, or emotionally negative. Do not force cooperation, reconciliation, forgiveness, friendly goals, or automatic failure. Allowed attempts continue through AgentDecision and Resolution; unknown causality may remain unresolved.
- Keep Content Safety, WorldNorms, AgentDecision, Resolution, EventProcessor, Observation, and Presentation separate. Lawbreaking is not itself a safety violation or causal failure. NPC reactions remain autonomous. Safety does not create peaceful endings or substitute for combat/social Resolution.
- Before issuing a trusted Event, recheck the bound Attempt under the safety policy. Check raw proposals before interpretation, every current step before execution, untrusted causal-model advice before it can affect policy, and player-visible text before Gateway delivery. Any assessment used for a decision must bind exact content, actor, source, context, and policy version; do not reuse it for changed content. The assessment is never a permission credential for EventFactory/EventProcessor.
- Model safety output is untrusted and must have a strict bounded schema, finite uncertainty, bounded strings/lists, configured timeout, and a bounded call/output budget. Identity, permissions, facts, exemptions, Events, and results are host-bound values, never copied from model output. Provider errors cannot downgrade known high-risk inputs to allow. A classifier is fallible; document remaining coverage and avoid universal efficacy claims.
- Do not infer age, consent, legal identity, or protected status from generic Entity attributes or caller text. Add such facts only through an explicitly trusted typed data contract; unknown is not adult/consenting by default.
- WorldNorms is typed, immutable, versioned world configuration attached to the existing WorldState. It distinguishes legal rules, social norms, jurisdiction, normative force, current status, governance, due process, enforcement bodies, and law/morality. A no-formal-law world is valid and must not receive an invented formal judiciary. Norms generation requires schema, consistency, cross-world safety, and disclosure validation.
- A WorldNorms query or violation assessment cannot itself change reality, mark a character guilty, or summon enforcement. Norm consequences require known rules/observations, character cognition where relevant, autonomous agents, and normal Resolution/EventProcessor commits. Hidden rules and other Agent knowledge must not be copied into player or NPC views without the ordinary authorization path.
- The CWUI contract is a read-only public projection, not WorldState serialization. Public law entries are structured and versioned; hidden rules are omitted. CWUI owns accordion/return navigation state. Do not flatten full law text into a single long string or store expanded state in WorldState.
- Sensitive presentation may fade out or summarize but may not erase a confirmed consequence or imply an unconfirmed fact. Ordinary fictional conflict is preserved in content policy; graphical detail limits affect only presentation.

## Phase 12.5D Safety Context and Acceptance Rules

- Read safety-relevant age only from `Entity.safety_profile` in the bound WorldState. Never infer age, identity, relationship, or consent from prose, names, avatars, generic attributes, player claims, or model output. Unknown age/consent clarifies only actions whose safety depends on it; ordinary conflict and daily behavior continue through normal Decision/Resolution.
- Built-in RuntimeContext composition supplies one shared `UniversalSafetyGovernance` to AgentActionLoop, ActionPipeline, ActionResolutionFlow, its EventFactory/MethodBasedResolutionEngine, StepwisePlanExecutor, and `PresentationPipeline.for_runtime`. No subclass or injected Pipeline may bypass the outer AgentActionLoop proposal/Attempt checks. Missing or invalid governance must raise/deny; never silently skip a check.
- Inspect `SafetyReadiness` at host startup/health reporting. `deterministic_only_unvalidated` and `provider_configured_unvalidated` are not P0 acceptance. Provider configuration is not live health validation. Keep deterministic policy tests, simulated-provider contract tests, live integration tests, and adversarial-effectiveness evaluations as separate evidence.
- Keep consent unknown until a typed trusted, action-scoped source exists. Safety refusal has no world/cognition consequence. For the cross-project and narrative design requirements, use the canonical definitions in `docs/ARCHITECTURE.md`; do not duplicate them as implementation claims.
- Treat safety route labels as descriptive only: they cannot grant cross-route exemptions. Keep `SafetyInput` collections immutable, bind assessments to the exact current input/context, and do not replace the fixed `UniversalSafetyGovernance` invariant layer with a subclass or provider result.
- CW and the migrated `anchor_desktop` client form one product and occupy separate packages in this repository. `docs/ARCHITECTURE.md` remains their shared architecture authority. CW owns final truth and saves/restores/branches; the desktop package must not mutate those internals. PySide6 is an optional desktop dependency, never a Core import.
- This phase retains the Third-Party Implementation Independence rule: public research may inform general architecture/algorithm principles, but no third-party code, Prompt templates, or distinctive implementation may be copied, translated, ported, rewritten, or closely imitated.

## Phase 12.6 Autonomous Runtime Rules

- The autonomous Runner may schedule and bound turns, but must not choose a concrete action by Agent ID, round number, registration/list position, or a prewritten Event/action sequence. Candidate content must come from the current owner's immutable cognition, authorized Percepts, active Goals, and evidence-backed installed-domain affordances.
- Keep candidate, Proposal, Attempt, and confirmed world result distinct. Rankings and report traces are subjective engineering diagnostics. No diagnostic score or trace may enter player Presentation. The Runner delegates outcomes to the existing Resolution/EventFactory/EventProcessor chain.
- Schedule each due Agent at most once per logical round, use a deterministic documented order, and cap Agent turns and committed Events. Isolate ordinary Agent errors; stop safely when EventProcessor signals a recovery-required state. Never replay a partially applied Event to recover perception.
- Dispatch each committed Agent Event through EventProcessor before another Agent acts. Each subsequent Agent may use the consequence only after its own authorized Observation and normal L1 processing; no shared DecisionContext, direct WorldState read, or private cognition transfer is allowed.
- Keep autonomy claims within tested domain limits. Current observed affordances and production causal outcomes cover typed door and passage domains only. Unsupported methods remain unresolved. Do not claim general combat/social causality or use a scripted demo as evidence of autonomy.
- The current Runner submits one Proposal/Attempt per Agent turn. Do not execute all planned steps as completed. Any multi-step integration must reuse `StepwisePlanExecutor` and its Observation/L1 gates, integrity-bound progress, and budgets.
## Phase 13 content authority

- Generated text and `EventSeed` are proposals, never trusted world facts. Validate structured references and safety before registration; runtime changes still pass the canonical Resolution/EventProcessor boundaries.
- Reusable templates must not retain or acquire instance Memory, Emotion, Relationship, injury, world state, or Event history. Do not create a parallel world, cognition, or Event store for content.
- Scenario and character IDs, registration order and round number must never script Agent actions. Preserve owner-scoped cognition, observed Affordance and autonomous Decision.
- Keep side branches linked to verifiable characters, mechanisms or event hooks. Do not treat a structural value link as guaranteed narrative quality or guaranteed reward.

## Phase 14 model-generated content rules

- Reuse the Phase 13 GenerationProposal, Validator, Registry and Instantiator. A model response is untrusted data, not a world Event, runtime instance, NPC decision, safety permission or legal rule.
- Enforce exact structured schema and bounded provider calls in code. Prompt wording cannot replace field, size, reference, safety and instance-boundary checks. Provider failure must remain visible and leave canonical state and registry untouched; never substitute a scripted story.
- The generated content schema must not carry WorldState/Resolution/Observation/Cognition/Memory/safety-profile/WorldNorms authority fields. Keep world laws in the separate structured WorldNorms pipeline.
- Generated Goal and environment definitions still enter only the existing pre-runtime initialization path. During runtime, AgentDecision and Resolution remain autonomous and causal; IDs, generation order and scenario hooks may not dictate actions or Events.

## Phase 15 Scenario runtime rules

- Keep `ScenarioTemplate` immutable and reusable, `ScenarioInstance` an identity receipt, and lifecycle state in canonical WorldState. Never duplicate WorldState, EventHistory or cognition for a scenario.
- Admit or exit an already installed instance only through validated actor/location/revision requests and `EventProcessor` transition Events. Scenario code must not write WorldState or teleport characters. Physical entry/exit and all other consequences require existing Resolution where applicable.
- A Seed may wake an eligible Agent after a trusted, owner-authorized Observation. It may not select an action, issue an Event, invent a Percept or bypass L1. Bound scheduling and preserve per-Agent isolation.
- Keep emphasized side branches linked to currently available continuation resources; do not force a reward, NPC response or plot resolution. IDs, registration order and round number never script behavior. Normal fictional conflict remains governed by Safety, AgentDecision and Resolution separately.
- Treat multi-event lifecycle transitions and observation delivery as non-atomic under current in-memory recovery semantics. Do not reapply a world update to repair delivery or claim crash-durable exactly-once execution. Unsupported causal domains remain unresolved.

## Phase 16 runtime content rules

- Reuse `GenerationProposal`, `ContentValidator`, `ContentRegistry`, `ContentInstantiator` and Phase 15 Scenario lifecycle. A model/provider can propose definitions only; it cannot call the trusted installation boundary, create Events, confirm outcomes, write cognition or dictate NPC behavior.
- Run schema/reference/P0 safety and identity preflight before committing world content. Reject duplicate template/instance identities; never silently replace existing definitions or entities. Provider/validation failure must leave registry, world, cognition and EventHistory unchanged.
- Submit runtime world creation only as a typed processor-gated installation Event and batch. Keep cognition in its existing owner Stores, and register Agents only when provisioning is ready. A failure after the first Event is explicit pending recovery, not a completed atomic transaction; do not replay the world batch or claim crash recovery.
- Keep templates immutable and reusable across instances. Source labels and content digests are audit data, not authority. EventSeeds do not self-execute. Generated NPCs use the ordinary Perception → Decision → Attempt → Resolution → Event chain; IDs, registration order and template provenance never prescribe actions.
- WorldNorms, UniversalSafetyGovernance, ContentValidator, AgentDecision, Resolution and Presentation retain distinct duties. Do not turn ordinary fictional conflict into a safety violation or a forced peaceful result. CWUI only consumes future approved projections through a Gateway/API and must not copy installation or world authority.

## ANCHOR-M2-01 bounded player-interaction checks

- Derive target descriptions and candidate handles only from the active observer's currently authorized, provenance-checked Observation facts and approved visible metadata. Model-selected handles are request-local hints, never canonical references or permissions; recheck target, actor and Runtime generation before formal execution.
- Keep pending clarification in the player service with original request identity, explicit answer mode, session/generation binding and a finite lifetime. Do not infer a choice or yes/no answer without a matching typed question. Discard pending state on world replacement or restore; do not persist it implicitly.
- Read-only inspection must revalidate facts through Presentation and use a separate delivery type. It may not issue a false Event, read hidden state, or present model prose as an observed fact. Any world change still requires the existing fenced Resolution/EventProcessor chain.
- Candidate-based physical interpretation may receive only the accepted Attempt-method phrases offered by the installed typed Resolution adapter for that authorized target kind. Require exact membership at both provider-schema and service boundaries; unsupported or missing methods fail closed. Do not add a second action vocabulary, infer effects from prose, or let a model-supplied method bypass the existing causal policy.

## Committed desktop and future-planning boundary

- Treat the four responsibility groups in ARCHITECTURE.md as ownership boundaries, not separately writable copies of world truth. The host may coordinate CPU retrieval, validation, background tasks and signed restore; only the existing authorized commit chain may change WorldState. Neither Qt, LLM output, embeddings, an Event Tree candidate nor an authorized Observation may independently declare an effect.
- Build model context from the current recipient's authorized Observation and Character-linked retrieval scope. Recheck any selected handle, offered method, Memory record and Runtime session/generation at the existing service boundary. A future LLM request for information types is advisory until an independent CPU policy validates scope, relevance and budget; it is not permission to read hidden data.
- Preserve the distinction between in-process restore/fork and verified cold resume of the signed original Timeline. Use the explicit content codec, complete lineage/ancestor verification and staged first publication; never synthesize a parent Runtime, reuse an old write permit, or treat a save directory listing as proof of a valid Runtime. UI task and delivery state are not persistent world facts.
- Keep product planning separate from installed capabilities. Optional dual-model isolation, world difficulty options, honor-mode certification, creator SDK and commercial platform policy require their own reviewed contracts and evidence. Their presence in the roadmap does not authorize UI claims, a new world writer or a shortcut around Safety, Resolution or Presentation.

## Open exploration and CPU information governance

**Non-negotiable trust boundaries**

- Strictly exclude results contradicted by verified applicable hard constraints; keep unknown feasible paths open to bounded investigation. “No installed matching rule”, “not explored in this budget”, “no authorized evidence found” and “confirmed impossible under these conditions” are different conclusions. Do not issue a confirmed failed Event solely because rule lookup returned no match. This does not permit committing an unverified candidate or weakening a Safety/authorization refusal.
- CPU/application governance must validate task principal, purpose, source scope, Timeline/session/generation, evidence freshness and budget before preparing model context. A relevant datum or a database record is not a read grant. NPC context and world/system analysis have different capabilities; system findings cannot leak another owner's cognition or become an NPC Observation without the established delivery boundary.
- Model-proposed intent, entity, relation, mechanism, missing condition, information need or future branch is untrusted candidate data. It may request evaluation under the existing interfaces; it cannot define its own permission, sign its own evidence, install a causal rule or create an effect. Structural JSON validation and a second LLM do not confer authority. Any installed content or enacted effect uses its existing content/Resolution/EventProcessor governance.
- Preserve objective evidence, subjective cognition, mechanism assumptions and speculative futures as separate meanings with source/time/uncertainty. Retrieve through canonical Stores and authorized Observation/query paths; no prompt, UI-generated explanation or narrative is a replacement state source. Do not create a parallel context Store or speculative EventHistory as an implementation shortcut.
- Context sufficiency is a separate claim from relevance. A future planner must track missing required conditions and distinguish additional retrieval, clarification, capability gaps, stale/conflicting evidence, budget deferral and unresolved termination. Preserve useful safe alternatives/next information needs when available, without inventing missing facts or promising that an alternative succeeds.
- Exploration and model work must retain the originating Runtime context and bounded lifecycle. Restore, cancellation, expiry or changed evidence invalidates late results; it cannot be repaired by minting a new permit. Bundle validation, ancestral history, cold publication, Memory governance and final world commit remain unchanged by the exploration policy. Never add transient tasks or tree findings to saves without an explicit schema review.

**Adjustable policies and acceptance scope**

- Endogenous dynamics explains why work may matter; information governance determines what it needs; allocation chooses what to compute first; independent LOD axes choose detail/cadence; Resolution decides actual causal results. Do not combine them into a global plot/success score, force cooperation/conflict, or give all NPCs a shared narrative objective. Goal tension and an observed opportunity are attention inputs, not obligations or success guarantees.
- Importance, pressure, information value, cost, diversity, expiry, decay and scheduling weights are tunable candidate policies, not universal world laws or demonstrated current algorithms. Count/provider/Token/latency limits need explicit scope; local limits do not prove a total budget. Budget pruning must retain its reason rather than masquerading as causal rejection. Reusing explored work requires current authorization/source/version validation.
- Each future slice must test the new independent invariant through its real path: unknown versus verified-infeasible handling, hidden/other-owner exclusion before Provider disclosure, gap/sufficiency behavior, deterministic bounded stop/defer, stale-result refusal and no speculative world commit. Cross-world content must vary without Core branches. Source inspection or a conceptual diagram is not test execution, and a diagnostic candidate tree is not a future-world simulator.
