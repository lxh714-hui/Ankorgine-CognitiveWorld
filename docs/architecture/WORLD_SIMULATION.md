# CognitiveWorld — Simulation Work and Expansion Direction

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Simulation work and expansion direction.

## Authority and scope

**Frozen authority level:** Domain architecture; general scheduler/acceptance marked unimplemented.

**Assigned responsibility:** EventTree, schedules, regional/global plans, independent simulation LOD and lazy-world dependencies.

Only marked architectural excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A25 — Simulation precision and compute allocation**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- Canonical state mutation, formal Event confirmation and submission.
- Perceptual disclosure authorization and cognitive-state governance.
- A new generic scheduler, unified LOD coordinator or materialization contract.

## Migrated excerpts and pending section outline

Only marked approved excerpts have migrated. Other entries remain pending. Source titles retain their original stage/status; no title is new acceptance evidence.

### ID 20 — World dynamics, task information and bounded exploration

<a id="arch-source-20"></a>

<!-- phase3c-begin:C-20-230-232 -->

<a id="arch-source-20-part-1"></a>

**Phase 3C source excerpt:** ID 20, lines 230–232 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-20-230-232:230-232 -->

**Approved architectural direction; foundations are partial.** The four responsibility groups above retain their authority. “势能 A / Why” means endogenous reasons for actors or the world to change; “势能 B / Where” means allocating finite computation among relevant tasks. These are explanatory concepts, not physical energy values, new canonical Stores, or a single plot score. Information governance determines what a task may know, LOD determines calculation detail/cadence, and Resolution determines what can actually happen. None can substitute for another.


<!-- phase3c-end:C-20-230-232 -->


### ID 23 — Compute allocation: the current Where path and future scheduler

<a id="arch-source-23"></a>

<!-- phase3c-begin:C-23-254-262 -->

<a id="arch-source-23-part-1"></a>

**Phase 3C source excerpt:** ID 23, lines 254–262 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-23-254-262:254-262 -->

The present budgets are local: AgentScheduler/EventScheduler choose due work by simulation time; owner findings rank by bounded importance/relevance; AgentTurn limits query/round/result counts; semantic retrieval limits authorized scan IDs; EventTreeExplorer limits materialized branches and optional provider calls; causal advice has its own call bound. These limits are not an aggregate Token, latency or cross-agent resource scheduler. EventTreeExplorer consumes an already selected proposal's checked decision trace; its lazy children and optional unassessed provider children are diagnostic alternatives, not simulated futures or a replacement decision. No live branch Provider, branch WorldState rollout or reusable cross-turn exploration cache is configured.

A future host/CPU allocation policy may consider endogenous pressure, task/player relevance, affected scope and consequence, uncertainty/information value, cost, diversity/duplicate effort and expiry/decay. These are experimental policy dimensions, not implemented global weights, success probabilities or hard world constraints. It must record why a task/branch was expanded, reused, deferred, degraded or stopped and distinguish budget pruning from causal rejection. Reuse requires unchanged evidence, scope, Timeline/session/generation and relevant state versions; no existing cached trust is implied. It must not always pick the easiest-to-succeed path or force all agents toward one global story goal.

Cognitive, perceptual and physical-computation LOD keep independent inputs, budgets and escalation requests. A shared future envelope may arbitrate work; it may not trade away permissions, confirmed consequences, collision/hard constraints or Event validity. Lower perceptual detail grants no extra knowledge, lower cognitive effort changes no belief without governance, and lower physical precision must conservatively escalate or remain unresolved when important effects cannot be validated. None of the three-axis coordinator, general physics precision ladder or global model/Token scheduler is implemented.

**Future cross-domain coordination, beyond the approved three axes:** one bounded allocation policy may compare cognitive reasoning, authorized perception/spatial queries, physical assessment, social-causal review, Memory retrieval/update and Event Tree exploration by uncertainty, importance, causal coupling, downstream consequences and cost. This extends resource accounting; it does not merge those domains' validators, owners or results into one authority. Social conflict or inconsistent evidence may request local review along known source/participant/mechanism links, but may remain legitimate disagreement or deception. No unified conflict vocabulary, cross-domain propagation algorithm, global budget ledger or production coordinator is specified or implemented. Spatial distance alone neither determines detail nor excuses neglecting a consequential remote event.


<!-- phase3c-end:C-23-254-262 -->


### ID 42 — Narrative Layer

<a id="arch-source-42"></a>

<!-- phase3c-begin:C-42-522-524 -->

<a id="arch-source-42-part-1"></a>

**Phase 3C source excerpt:** ID 42, lines 522–524 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-42-522-524:522-524 -->

The Narrative Layer provides conflict possibilities, opportunities, Event Tree expansion, and narrative pressure. It presents possibilities; it does not decide character behavior or control the world.


<!-- phase3c-end:C-42-522-524 -->


### ID 93 — 7. Event Tree System

<a id="arch-source-93"></a>

<!-- phase3c-begin:C-93-1395-1415 -->

<a id="arch-source-93-part-1"></a>

**Phase 3C source excerpt:** ID 93, lines 1395–1415 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-93-1395-1415:1395-1415 -->

Event Tree manages future possibilities. It is NOT a fixed story tree.

Not:

```text
A → B → C
```

Instead:

```text
Current State
  ↓
Potential Events
  ↓
Conditions
  ↓
Expansion
```


<!-- phase3c-end:C-93-1395-1415 -->


### ID 94 — Lazy Expansion

<a id="arch-source-94"></a>

<!-- phase3c-begin:C-94-1417-1429 -->

<a id="arch-source-94-part-1"></a>

**Phase 3C source excerpt:** ID 94, lines 1417–1429 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-94-1417-1429:1417-1429 -->

The system does not generate all possibilities. Expansion happens only when relevant, nearby, important, or required by player interaction. This Event Tree exploration direction is distinct from [hybrid world-structure expansion](../ARCHITECTURE.md#hybrid-lazy-world-expansion-selected-direction-acceptance-boundary-unresolved); node pruning/deletion does not erase committed Events or accepted world structure.

Event nodes support:

- importance;
- relevance;
- decay;
- deletion;
- expansion.

---


<!-- phase3c-end:C-94-1417-1429 -->


### ID 95 — 8. Narrative Pressure Layer

<a id="arch-source-95"></a>

<!-- phase3c-begin:C-95-1431-1463 -->

<a id="arch-source-95-part-1"></a>

**Phase 3C source excerpt:** ID 95, lines 1431–1463 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-95-1431-1463:1431-1463 -->

**Design umbrella with narrow implemented foundations.** This section describes proposed discovery responsibilities; it is not a claim that separate general Conflict, Opportunity or NarrativePressure engines are installed. The concrete current module is `ConflictOpportunityScheduler`, connected to owner-local AgentDecision and a narrow Runtime-issued Goal-resource comparison. Its actual source checks, lifecycle and limits are specified in the production-slice section below. Optional content expansion uses a separate injected host need policy and the existing validated installer.

The Narrative Layer direction covers:

- conflict possibilities;
- opportunities;
- Event Tree expansion;
- narrative pressure.

The Narrative Layer offers possibilities but does not determine character behavior. In the Why/Where architecture above, discovery suggests why an issue may matter; independent information governance checks what may be known, and CPU allocation decides whether/when to investigate. LOD and Resolution remain separate. There is no default global story goal or implemented narrative-pressure scalar. The conceptual relationship is:

- **Narrative Layer** provides possibilities.
- **Cognition Layer** chooses based on its own state.
- **Decision Layer** forms Intent and Attempt.
- **World Core** validates and records facts.

```text
Narrative Possibility
  ↓
Cognition Choice
  ↓
Attempt
  ↓
Resolution
  ↓
Event
  ↓
WorldState
```

The Narrative Layer must not force character behavior, directly create Events, or modify WorldState.


<!-- phase3c-end:C-95-1431-1463 -->


### ID 96 — Conflict System

<a id="arch-source-96"></a>

<!-- phase3c-begin:C-96-1465-1467 -->

<a id="arch-source-96-part-1"></a>

**Phase 3C source excerpt:** ID 96, lines 1465–1467 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-96-1465-1467:1465-1467 -->

The future responsibility is to discover potential relationship/goal/information conflicts with explicit sources and uncertainty. Current production coverage is limited to configured owner Goal tension and structured exclusive-resource-demand comparison; no general relationship, scarcity or information-conflict detector exists. A potential finding is not an enacted conflict or proof that an NPC knows another actor's intentions.


<!-- phase3c-end:C-96-1465-1467 -->


### ID 97 — Opportunity System

<a id="arch-source-97"></a>

<!-- phase3c-begin:C-97-1469-1475 -->

<a id="arch-source-97-part-1"></a>

**Phase 3C source excerpt:** ID 97, lines 1469–1475 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-97-1469-1475:1469-1475 -->

The future responsibility is to discover possible cooperation, relationship development and goal advancement. Current production coverage is an existing candidate/Goal whose target and evidence match an observed affordance. General cooperation/relationship-opportunity discovery is not installed. An opportunity is neither guaranteed success nor a requirement to cooperate.

These responsibilities yield non-authoritative candidate findings. Each NPC still selects independently through its existing decision path; only the ordinary applicable content/Resolution/EventProcessor boundaries can enact consequences. A missing rule/evidence path stays unmodeled or unresolved and may warrant bounded inquiry, not an invented failure fact or forced plot branch.

---


<!-- phase3c-end:C-97-1469-1475 -->


### ID 105 — 10. Simulation Strategy

<a id="arch-source-105"></a>

<!-- phase3c-begin:C-105-1578-1580 -->

<a id="arch-source-105-part-1"></a>

**Phase 3C source excerpt:** ID 105, lines 1578–1580 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-105-1578-1580:1578-1580 -->

The world uses layered simulation.


<!-- phase3c-end:C-105-1578-1580 -->


### ID 106 — Local Simulation

<a id="arch-source-106"></a>

Source ID 106 is consolidated in [ID 110](#arch-source-110). Its approved excerpt is retained there with its own source-line ledger; no separate simulation definition is maintained here.

### ID 107 — Regional Simulation

<a id="arch-source-107"></a>

Source ID 107 is consolidated in [ID 111](#arch-source-111). Its approved excerpt is retained there with its own source-line ledger; no separate simulation definition is maintained here.

### ID 108 — Global Simulation

<a id="arch-source-108"></a>

Source ID 108 is consolidated in [ID 112](#arch-source-112). Its approved excerpt is retained there with its own source-line ledger; no separate simulation definition is maintained here.

### ID 109 — Simulation LOD

<a id="arch-source-109"></a>

<!-- phase3c-begin:C-109-1596-1598 -->

<a id="arch-source-109-part-1"></a>

**Phase 3C source excerpt:** ID 109, lines 1596–1598 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-109-1596-1598:1596-1598 -->

CognitiveWorld uses layered simulation to control the scale of large worlds. Spatial simulation scale is a scheduling concern; it is not itself a physical, perceptual, or cognitive precision setting. LOD changes computation, not the truth of the world.


<!-- phase3c-end:C-109-1596-1598 -->


### ID 110 — Local Simulation

<a id="arch-source-110"></a>

<!-- phase3c-begin:C-106-1582-1584 -->

<a id="arch-source-106-part-1"></a>

**Phase 3C source excerpt:** ID 106, lines 1582–1584 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-106-1582-1584:1582-1584 -->

High detail. Player-related area.


<!-- phase3c-end:C-106-1582-1584 -->

<!-- phase3c-begin:C-110-1600-1608 -->

<a id="arch-source-110-part-1"></a>

**Phase 3C source excerpt:** ID 110, lines 1600–1608 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-110-1600-1608:1600-1608 -->

High-precision simulation for:

- areas near the player;
- important characters;
- current events.

Local simulation preserves complete state, relationships, and behavior.


<!-- phase3c-end:C-110-1600-1608 -->


### ID 111 — Regional Simulation

<a id="arch-source-111"></a>

<!-- phase3c-begin:C-107-1586-1588 -->

<a id="arch-source-107-part-1"></a>

**Phase 3C source excerpt:** ID 107, lines 1586–1588 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-107-1586-1588:1586-1588 -->

Medium detail. Nearby areas and important entities.


<!-- phase3c-end:C-107-1586-1588 -->

<!-- phase3c-begin:C-111-1610-1618 -->

<a id="arch-source-111-part-1"></a>

**Phase 3C source excerpt:** ID 111, lines 1610–1618 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-111-1610-1618:1610-1618 -->

Medium-precision simulation for:

- nearby regions;
- secondary characters;
- potential events.

Regional simulation preserves summarized state and key trends.


<!-- phase3c-end:C-111-1610-1618 -->


### ID 112 — Global Simulation

<a id="arch-source-112"></a>

<!-- phase3c-begin:C-108-1590-1594 -->

<a id="arch-source-108-part-1"></a>

**Phase 3C source excerpt:** ID 108, lines 1590–1594 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-108-1590-1594:1590-1594 -->

Low detail. Only maintains large trends.

The world is expanded according to relevance.


<!-- phase3c-end:C-108-1590-1594 -->

<!-- phase3c-begin:C-112-1620-1624 -->

<a id="arch-source-112-part-1"></a>

**Phase 3C source excerpt:** ID 112, lines 1620–1624 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** APPROVED_PRINCIPLE. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-112-1620-1624:1620-1624 -->

Low-precision simulation for distant parts of the world and large-scale trends. It preserves macro-level state.

Regional/global simulation may summarize or defer work only when no confirmed event, hard constraint, or required causal consequence is lost. It may not replace an unresolved physical result with a guessed outcome.


<!-- phase3c-end:C-112-1620-1624 -->


### ID 113 — Hybrid Physical Engine and Independent LOD Axes (Approved Design, Not Implemented)

<a id="arch-source-113"></a>

<!-- phase3c-begin:C-113-1626-1652 -->

<a id="arch-source-113-part-1"></a>

**Phase 3C source excerpt:** ID 113, lines 1626–1652 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-113-1626-1652:1626-1652 -->

The planned physical layer is a hybrid, world-configured causal evaluator, not a general-purpose simulator of all real-world physics. It combines (1) discrete typed rules for domain transitions and event-driven changes, (2) bounded simplified continuous approximations where motion or interaction requires them, and (3) higher-precision deterministic checks for contact, constraints, safety-critical thresholds, or outcomes whose uncertainty could change a consequential Event. Structure, material, shape, mass-like resistance, friction, elasticity, strength, and environmental conditions are typed inputs to a receiver-side response contract; world/scenario configuration supplies their values and supported models. These are parameters to a domain rule, not permission for an LLM to invent a state transition.

The longer-term composable-mechanism direction evaluates combinations of installed, typed state, properties, capabilities, preconditions, spatial relationships and permitted transitions rather than enumerating every natural-language command. Opening a door and traversing its passage remain different mechanisms and Events: a description of an open door cannot establish an installed destination. The current door/passage rules are narrow concrete mechanisms; general composition, arbitrary force or rigid-body simulation, and automatic discovery of new executable rules are not implemented. Candidate effects still need evidence, Resolution and formal Event processing.

The three LOD axes are independently scheduled:

- **Cognitive LOD** budgets an Agent's reasoning depth, candidate count, review work, and model/CPU calls. It reads only that Agent's authorized DecisionContext and cannot change a physical result.
- **Perceptual LOD** budgets which owner-authorized observations are produced and their spatial/detail resolution (for example range, coarse shape, material cues, movement trend, and local relations). It may reduce information delivered to an Agent but cannot change the canonical world or grant global-state access.
- **Physical-computation LOD** selects solver/model, step size, collision broad/narrow phase, frequency, and numeric tolerance. It operates on canonical world inputs and returns a bounded assessment, uncertainty, and any upgrade request; it cannot write WorldState.

A shared budget coordinator may account for total tick/time/compute limits and pass explicit per-axis budgets, but each axis retains its own policy, result, and upgrade reasons. Distance can inform perception and physical scheduling but is never the sole precision selector: proximity to collision, velocity, energy, constraint sensitivity, hazard, confidence interval, and consequence severity also matter. A high-impact or hard-constraint case requests an upgrade before adjudication. If the budget cannot satisfy it, the outcome is unresolved/deferred; lower precision cannot silently choose the favorable or less costly outcome. Confirmed Events and their required consequences are never dropped by an LOD downgrade.

Within an applicable geometric domain, canonical entity positions and orientations live in its authoritative coordinate frame (initially a configured Cartesian 3D frame); this does not require all potential world topology to share one global Euclidean embedding. A subject-centered local frame is a derived query projection: relative displacement is computed from canonical positions, and a polar/spherical form `(r, azimuth, elevation)` may be used for radial scheduling and presentation-facing spatial relations. A deterministic frame transform records origin, axes, handedness, units, and version. Changing the observing subject changes the projection origin and orientation; it never moves an entity. Multiple Agents may hold different local projections of the same world snapshot and tick. Simulation and collision use canonical coordinates or explicitly transformed values, never a cached projection whose origin can drift. Unknown/stale position stays unknown rather than being inferred from prose.

For a horizontal slice of one canonical snapshot, subject and target positions `p_a=(x_a,y_a)` and `p_e=(x_e,y_e)`, and subject heading `phi_a`, the derived planar projection is `r=||p_e-p_a||` and `theta=wrap(atan2(y_e-y_a,x_e-x_a)-phi_a)`, with a declared normalization such as `[-pi,pi)`. Recompute it when the action subject changes; neither `r` nor `theta` is a second authoritative position. Height/elevation and full 3D constraints need their own applicable representation; planar distance alone cannot decide reachability or contact. Visual field of view is one perception condition, not a substitute for hearing, Memory or observation authorization. These equations specify an architectural projection, not a current transform API.

A future adaptive scheduler can use this projection in a conceptual request `L(a,e)=F(r,theta,importance,causal_coupling,...)`, together with uncertainty, available evidence, task requirements and budget. This is not a calibrated formula, fixed threshold or fourth authority: it requests independent cognitive, perceptual and physical precision and, if separately designed, bounded social/Memory/Event Tree work. A distant or unseen entity may deserve high precision because of its causal impact; a nearby entity receives no automatic information grant. The scheduler cannot mutate WorldState, confirm a Resolution or erase established identity and history.

Discrete event rules remain the authority for doors, passage movement, and other explicitly supported transitions. Simplified continuous models may estimate trajectories or contact candidates only inside declared validity bounds. Broad-phase collision may conservatively identify possible pairs; narrow-phase deterministic checks decide contact when contact changes a consequential result. Occlusion belongs to perception unless a typed physical rule makes it causally relevant. Force-like inputs require typed magnitude, direction/frame, application point or region, duration/impulse, and units; the receiver's supported structure/material/constraint contract determines response. Unsupported propagation, fracture, injury, multi-body chains, fluid/thermal effects, or ambiguous constraints remain unresolved until their rules and typed state slots are installed.

When low- and high-precision evaluations disagree, the low-precision result is advisory and cannot commit. The coordinator upgrades and reruns against the same immutable input snapshot/tick. If results still disagree, violate an invariant, or exceed the available budget, Resolution returns an explicit unresolved/insufficient-evidence outcome. Hard constraints and authorization checks are independent of LOD and are revalidated at the EventProcessor boundary. A physical assessment becomes a typed Resolution proposal bound to its Attempt, tick, canonical state-slot reads, model/version, and uncertainty; only an issued Resolution result may create an Event, and only EventProcessor may apply its WorldUpdate.

The current implementation does **not** provide canonical 3D position/orientation primitives, a general coordinate transform service, material/structure response models, generic collision/occlusion, continuous integration, three-axis LOD scheduling, an upgrade coordinator, or multi-body physical resolution. Current production adjudication remains the narrow door and known-passage slice described above. The approved implementation route is: (1) typed canonical 3D position/units plus pure coordinate transforms and round-trip/multi-observer tests; (2) deterministic spatial query and conservative collision candidate detection without writes; (3) one configured, bounded receiver-response model and collision Resolution proposal through EventProcessor; (4) independent per-axis budget contracts and deterministic upgrade/degrade rules; (5) optional simplified motion, only after replay determinism, state provenance, and save/restore contracts are established. Each phase must retain unresolved fallback outside supported model bounds.

---


<!-- phase3c-end:C-113-1626-1652 -->


### ID 141 — Meaningful Side-Branch Policy (planned)

<a id="arch-source-141"></a>

<!-- phase3c-begin:C-141-2123-2134 -->

<a id="arch-source-141-part-1"></a>

**Phase 3C source excerpt:** ID 141, lines 2123–2134 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-141-2123-2134:2123-2134 -->

Ordinary daily events may be quiet and end naturally. A separately generated
and emphasized side branch should have at least one plausible continuation
value: an important NPC, potential opponent/competitor, meaningful item or
resource, information/knowledge change, persistent relationship change, or a
causal seed that may generate a later Event. Avoid mass production of
fetch-work, repeated errands, investigations with no follow-up, disputes with
no possible impact, and tasks added only to fill space. A branch need not
promise a reward or major Event; an NPC may refuse or redirect it. Planning
allocates attention and generation budget only and cannot write WorldState.
This policy is architectural direction, not an implemented quest planner.


<!-- phase3c-end:C-141-2123-2134 -->


### ID 170 — Event Tree minimum vertical slice (implemented, candidate exploration only)

<a id="arch-source-170"></a>

<!-- phase3c-begin:C-170-2417-2423 -->

<a id="arch-source-170-part-1"></a>

**Phase 3C source excerpt:** ID 170, lines 2417–2423 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-170-2417-2423:2417-2423 -->

The tree root is bound to the current proposal, owner and trusted Runtime tick; each materialized child references one existing evaluated candidate and its previously validated source references. Candidate score/factors are retained solely as the decision's subjective assessment, not as event probability or causal effect. Expansion is lazy, stable by score then candidate ID, and bounded to four branches per Agent turn. Pruned alternatives retain parent, source and reason. Each node records whether it remains unexplored, was expanded, was pruned by a budget, or was blocked by provider failure; newly proposed children remain unassessed. The optional proposal-provider seam accepts only existing `ActionCandidate` records, checks the full batch before materializing it, deduplicates equivalent alternatives, and has fixed per-node and per-tree call/output limits. It checks the current owner's candidate-derived goals, targets, and evidence references; such branches cannot replace the selected proposal. Runtime additionally checks linked Conflict & Opportunity finding IDs against findings issued for this owner and tick, without treating those findings as objective facts.

This implementation provides traceable alternative-action exploration and bounded pruning. It does **not** contain isolated branch WorldState snapshots, hypothetical EventHistory, continuous causal simulation, effects propagation, value backup, or Event Tree persistence. Resolution output/effects cannot safely support serial speculative application today; no EventProcessor-and-rollback simulation is allowed. Actual action execution remains exclusively on the established Safety → Attempt → Resolution → EventFactory → EventProcessor → WorldState path.

The same bounded snapshot can inform the separately authorized “灵光一闪” backend projection: only current, same-owner branches backed by player-visible Event evidence and targets contribute reduced attention metadata. Private branch language is never directly projected. The UI trigger and display remain unimplemented; a tree branch cannot itself create an Attempt or Event.


<!-- phase3c-end:C-170-2417-2423 -->


### ID 171 — Conflict & Opportunity Scheduler minimum production slice

<a id="arch-source-171"></a>

<!-- phase3c-begin:C-171-2425-2433 -->

<a id="arch-source-171-part-1"></a>

**Phase 3C source excerpt:** ID 171, lines 2425–2433 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-171-2425-2433:2425-2433 -->

`ConflictOpportunityScheduler` runs inside the canonical `SimulationRuntime` AgentDecision assembly after the current owner's immutable `SituationAssessment` and bounded `ActionCandidate` batch exist. Its owner-local rules consume no shared/global WorldState and no other Agent's cognition. They recognize subjective goal tensions already supplied by the current Motivation assessment and opportunities where an existing candidate, its Goal, its target, and the candidate-cited owner Percept source align with a currently observed affordance. These are attention/evaluation hypotheses, not objective world conflicts or guaranteed outcomes; each carries typed source references and uncertainty. An absent observation or source cannot create an opportunity.

The Runtime also has a bounded system-level Cross-Agent Goal projection. It reads only active Goals linked to each registered owner's `CognitionContext`, extracts explicit typed `GoalResourceDemand` claims, grounds exact `object:{id}` references to current WorldState Entity identity, and verifies the resource identity slot read and its origin. The projection omits Goal prose, priority, and all private cognition. The Scheduler distinguishes matching exclusive-use/scope requirements (`supported_conflict`), incomplete exclusivity/scope (`potential_conflict`), and a shared target without an exclusive constraint (`shared_target_only`). This verifies only declared Goal requirements over a grounded resource; no generic capacity/possession model is present. Owner-facing findings contain only the recipient's own Goal identity and opaque source/revision digests and explicitly remain system-level attention, not an observation or proof that the recipient knows another Goal. They can influence only existing linked-candidate bounded relevance and diagnostics. They cannot decide, create an action, or alter world/cognition. Their de-duplication/lifecycle is process-local and is not save/restore safe.

Findings are bounded and process-local, keyed by owner and stable issue identity, updated across repeated ticks, and marked dormant after bounded missed evaluations. The existing `DeterministicActionEvaluationPolicy` can add a small bounded relevance factor to candidates explicitly linked to a finding. `ActionProposal.decision_trace` and candidate-only Event Tree branches retain finding IDs for diagnostics. The scheduler cannot create candidates, force an action, change an already-issued proposal, write cognition/world state, or create Events. Runtime exposes findings only in developer turn diagnostics, not player Presentation.

An optional `ConflictOpportunityAnalysisProvider` is a host-injected contract, disabled by default. It receives a narrow projection of owner-authorized observed facts, owner Goals, affordances and current candidates; it does not receive WorldState, memory content, beliefs, emotions, or another Agent's context. Program validation restricts output to current owner Goals, targets, candidates and cited observation sources; provider findings are always marked as unverified interpretations. No external provider is selected or called automatically. The current slice does not discover global cross-Agent resource/relationship conflicts, preserve lifecycle across process restarts, or proactively create/install content. Reusable character/scene expansion remains a separate future capability described in `DEVELOPMENT_ROADMAP.md`.


<!-- phase3c-end:C-171-2425-2433 -->


### Content received from coordinated splits

- Original ID **168**, source lines **2408–2411**: approved excerpt copied in Phase 3C below; other parts and final coordination remain pending. The original heading keeps its separate primary assignment.

### Split source ID 168 — Candidate evidence review integration (local, optional) / Candidate-only Event Tree and provider boundary

<!-- phase3c-begin:C-168-2408-2411 -->

<a id="arch-source-168-part-2"></a>

**Phase 3C source excerpt:** ID 168, lines 2408–2411 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

Compatibility reference: this source-stage evidence-review description does not supersede the existing Reference Policy v0.1 contract in [DATA_CONTRACTS.md](../DATA_CONTRACTS.md).

<!-- phase3c-source:C-168-2408-2411:2408-2411 -->
The current Event Tree slice is a bounded **candidate-exploration tree**, not a simulated future world. `EventTreeExplorer` consumes the canonical AgentDecision trace, retains candidate/parent/source/evaluation links, expands only up to a fixed per-turn budget, and records the remaining candidate IDs as pruned. A branch is an alternative proposed action with subjective evaluation and uncertainty; it has no predicted or confirmed effect. `SimulationRuntime` stores the immutable snapshot only in its developer-facing `AgentRuntimeTurnRecord`. The tree does not select an action, call Resolution, update cognition, create an Event, or mutate WorldState/EventHistory. This is the first production-connected Event Tree capability, but it is not continuous branch-state simulation, outcome propagation, or a general planning system. `EventSeed` remains an observation-gated attention opportunity, not a tree branch or Event.

`EventTreeBranchProposalProvider` is an optional, explicit dependency-injection boundary. It receives a bounded owner-scoped proposal context and returns existing `ActionCandidate` values; programmatic checks bind owner, target, goal, evidence references, uniqueness, and remaining branch budget. Provider-created branches remain unassessed hypotheses and cannot affect the already selected ActionProposal. No provider is configured by `SimulationRuntime`, no external endpoint is selected, and no real LLM branch proposal or evaluation is claimed. A future model path must reuse the current candidate validation/evaluation policies and the approved local/host data boundary before it can influence a decision.


<!-- phase3c-end:C-168-2408-2411 -->


## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [COGNITION.md](COGNITION.md) — canonical owner for A27, A29.
- [PERCEPTION.md](PERCEPTION.md) — canonical owner for A26.
- [WORLD_MODEL.md](WORLD_MODEL.md) — canonical owner for A24.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [SOCIAL_CAUSAL_DESIGN.md](../SOCIAL_CAUSAL_DESIGN.md)
- [COGNITION.md](COGNITION.md)
- [EXECUTION.md](EXECUTION.md)
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md)
- [PERCEPTION.md](PERCEPTION.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)

## Historical and implementation-status handling

Pending migration. Preserve the frozen charter historical-retention and status-reporting responsibilities; no capability or test result is established by this skeleton.

Contact: ankorgine@outlook.com
