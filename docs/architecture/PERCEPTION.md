# CognitiveWorld — Authorized Observations and Perceptual Precision

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Authorized observations and perceptual precision.

## Authority and scope

**Frozen authority level:** Domain architecture; does not define UI or world mutation.

**Assigned responsibility:** Generation, event-time evidence, bounded object/result projection, candidate future sensory models.

Only marked architectural excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A12 — Observation formation and event-time authorization**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.
- **A26 — Perceptual precision and detection/projection**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- Physical-world simulation and authoritative state mutation.
- Memory formation, Belief interpretation and decision selection.
- Player-facing composition and detailed record/signing definitions.

## Migrated excerpts and pending section outline

Only marked approved excerpts have migrated. Other entries remain pending. Source titles retain their original stage/status; no title is new acceptance evidence.

### ID 37 — Observation Layer

<a id="arch-source-37"></a>

<!-- phase3c-begin:C-37-434-456 -->

<a id="arch-source-37-part-1"></a>

**Phase 3C source excerpt:** ID 37, lines 434–456 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-37-434-456:434-456 -->

The Observation Layer converts objective world changes into information available to a subject:

```text
World Fact
  ↓
Observation
  ↓
Character Cognition
```

Observation does not modify WorldState or create facts. It is the only entry point through which Cognition receives external information. Different characters may receive different Observations of the same world fact.

The Phase 12.0c-2 ingestion boundary is fail-closed: a manually constructed Observation or a record merely retrieved from ObservationStore is not trusted input. `CognitiveEvolutionEngine` validates source provenance and unchanged payload before forming event-driven proposals; `CognitiveRuntime` and the lower-level `PerceptionProcessor` validate provenance and observer ownership before forming Percepts. ObservationStore remains copy-isolated storage, not an authorization authority. Phase 12.0c-3 adds immutable `ObservableFact` and `EventTimeObservationContext` contracts. EventHandler defaults to producing no facts; EventProcessor issues event-bound facts only from explicit typed drafts after the trusted Event has been successfully applied, and EventHistory stores the associated evidence without authenticating it. Phase 12.0c-4 adds a narrow production path for a controlled room-light state transition. SimulationRuntime supplies the simulation clock and registered Agent identities; EventProcessor applies the update and captures registered observers' WorldState positions and typed sensory capabilities at the same synchronous post-update event boundary, with relevant environment conditions from that state. The Event timestamp is retained as descriptive source data and is not used as the simulation clock. A default-deny VisibilityPolicy issues a signed Observation only for a registered observer with known sight capability at the event location, when the resulting room state confirms the light is on. The Observation contains only the typed ObservableFact, never Event metadata. The legacy `process()` return remains `None`; `process_with_evidence()` remains available. EventTimeObservationContext labels its captured state as post-update. The in-process receipts guard ordinary misuse only; they are not a security boundary against malicious same-process code.

Ordinary L1 now qualifies each Observation against an assembly-bound canonical EventHistory before Percept construction. Persistent runtimes verify the signed lineage and inherited prefix; an authoritative live in-memory history may instead establish current-process Event/evidence membership without claiming durable authenticity. Exact Event, processor evidence, fact and issuance-context bindings are checked through the existing observation policy. The issuer-bound Timeline and generation describe delivery, not original Event ownership or current action permission. Unproved ancestry, unavailable history or recovery-required history defers ingestion; a proven nonmember is ineligible. Neither case adds Percepts or receipts or changes the affected WorkingMemory. Mixed batches retain independently eligible work. A direct compatibility call without bound history now reports deferred qualification rather than silently ingesting. This is ordinary transient cognition, not B2 proof issuance or a new action authorization. See [the ordinary L1 result contract](../DATA_CONTRACTS.md#ordinary-l1-per-observation-history-qualification).

Phase 12.0c-R adds narrow in-process reliability markers to the existing EventHistory. EventProcessor reserves an Event ID before handler work, marks entry into the WorldState update boundary, then records the Event and evidence before Observation delivery. A repeated Event with matching source content reuses recorded evidence and never invokes the handler or applies its WorldUpdate again. A failure before WorldState application releases the reservation and can be retried; once application begins, failures are marked `RECOVERY_REQUIRED` and automatic replay is denied because WorldState has no rollback or durable transaction support. Observation delivery is marked pending before saves; retry reuses EventHistory evidence and regenerates the same observer/fact-scoped Observation IDs, so it does not reapply the Event. ObservationStore overwrites the same ID, making a repeated save idempotent for this path. These markers are process-local and do not provide crash recovery, durable atomicity, or cross-process coordination.

`CognitiveRuntime` now keeps WorkingMemory percept references unique by stable `percept:{observation_id}` identity. Re-consuming the same Observation is a no-op for stored percept references; distinct Observation IDs remain distinct even when text/content matches, and Agent memories remain owner-scoped. CognitiveEvolutionEngine continues to produce proposals only; Belief/Goal writes still require the existing validator/applier, including stale-value checks. This does not make arbitrary external proposal application globally exactly-once.

For bounded stepwise execution, `CognitiveRuntime` also retains process-local L1 consumption receipts in the runtime instance, bound to owner, intact Observation snapshot, source Event, and its existing WorkingMemoryStore. `CognitionState.percept_ids` continues to mean newly ingested percepts for that call; an empty list on replay does not negate a previously validated receipt. Stepwise continuation checks the receipt rather than accepting an ObservationStore row or a caller-supplied percept ID. Receipts do not survive process restart and are not a security boundary against malicious same-process code.


<!-- phase3c-end:C-37-434-456 -->


### ID 83 — Shared Observation Facts (General Design; Narrow 12.0c-4 Slice Implemented)

<a id="arch-source-83"></a>

<!-- phase3c-begin:C-83-1237-1243 -->

<a id="arch-source-83-part-1"></a>

**Phase 3C source excerpt:** ID 83, lines 1237–1243 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-83-1237-1243:1237-1243 -->

Agent Observation and player Presentation share a lower-level observable-fact evaluation boundary while keeping separate identity, permissions, and output contracts. Evaluation may use trusted event facts, necessary world state for the event time, resolved observer identity, location/environment conditions, and applicable sensory/visibility rules. Missing required inputs mean deny/no observation.

An Event cannot grant itself presentation permission through metadata. Full Event metadata must not be copied into Observation or Presentation. Objective world facts, facts available to a particular observer, and facts allowed to a player are separate. NPC private cognition remains outside Presentation access.

WorldState owns locations and environment values; `Entity.sensory_capabilities` is an optional typed world-state field, where `None` means unknown. Event has generic changes and open metadata, neither of which grants visibility. Phase 12.0c-4 supports only the explicit `room_light_changed` system-event handler and the positive `room_light_on=True` perception rule. Unknown location, sensory capability, or simulation clock means no Observation. Hearing, occlusion, geometry, and arbitrary environmental visibility are not implemented. Do not substitute Event metadata, participant membership, current/default locations, or assumed senses. `ObservationGenerator.generate()` remains a fail-closed compatibility API; the controlled production path consumes EventProcessor evidence through its authorized issuance method. Phase 12.0d adds a player Presentation path only for this already-authorized narrow Observation slice; it does not expand Agent perception rules.


<!-- phase3c-end:C-83-1237-1243 -->


### ID 114 — Visual and auditory LOD mathematics (candidate models; uncalibrated)

<a id="arch-source-114"></a>

<!-- phase3c-begin:C-114-1654-1656 -->

<a id="arch-source-114-part-1"></a>

**Phase 3C source excerpt:** ID 114, lines 1654–1656 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-114-1654-1656:1654-1656 -->

**Status:** the three independent LOD axes and authorization boundaries above remain approved principles. The equations below are candidate mathematical models and validation hypotheses, not calibrated probabilities, implemented propagation services, approved production classifiers, or frozen APIs/schemas. The broader meaning of simulation fidelity remains a maintainer terminology decision. Current visibility uses narrow event/location/sensory checks, not a general FOV/occlusion engine; no general acoustic propagation engine is installed. Observer sampling and historical payload preservation retain the existing [observation contract](../DATA_CONTRACTS.md#18-phase-120c-shared-observable-facts-and-agent-perception-partial-120c-4-narrow-slice-implemented).


<!-- phase3c-end:C-114-1654-1656 -->


### ID 115 — Visual eligibility and quality

<a id="arch-source-115"></a>

<!-- phase3c-begin:C-115-1658-1684 -->

<a id="arch-source-115-part-1"></a>

**Phase 3C source excerpt:** ID 115, lines 1658–1684 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-115-1658-1684:1658-1684 -->

Use one valid snapshot and coordinate frame: observer and target positions \(p_o,p_t\) in metres, \(r=\|p_t-p_o\|>0\), unit forward vector \(f\), and half-FOV angle \(\phi\in(0,\pi]\) in radians:

\[
\theta=\arccos\left(\operatorname{clip}\left[f\cdot\frac{p_t-p_o}{r},-1,1\right]\right),
\qquad G_{\mathrm{FOV}}=\mathbf1[\theta\leq\phi].
\]

This is point-target geometric eligibility only. Extended targets require a target/frustum intersection rule. At zero distance direction is undefined: use an applicable near-field rule or return unsupported, never divide by zero. Geometry grants neither recognition nor disclosure authority.

Let \(v\in[0,1]\) be the visible projected-area fraction. Missing reliable occlusion inputs mean unknown, not \(v=1\). For a planar target of transverse width \(s\), facing the observer, with \(s\ge0\) and \(r>0\) in the same length unit, its angular width in radians is

\[
\alpha=2\arctan\frac{s}{2r}.
\]

This geometry is not universal for arbitrary shapes. A candidate task-specific quality proxy is

\[
Q_k=G_{\mathrm{FOV}}\,v\,
\frac{\alpha^{n_k}}{\alpha^{n_k}+a_k^{n_k}}\,h_k(C,L).
\]

Here \(k\) distinguishes detection, shape recognition and detail recognition; \(a_k>0\) is an angular scale in radians, \(n_k>0\) is dimensionless, \(C\) is explicitly defined dimensionless contrast, \(L\) is luminance in cd/m², and \(h_k\in[0,1]\) is a separately calibrated contrast/illumination response. With other inputs fixed inside model bounds, quality is nondecreasing in angular size and visible fraction; complete occlusion gives zero. Each task needs its own calibration. \(Q_k\) is not a probability without experimental calibration. Illumination response need not increase indefinitely: glare and adaptation may matter. Inverse-square intensity attenuation is not a general visual-recognition law.

Computational fidelity may change query density, occlusion approximation or detail cost, not target geometry, physical illumination or information rights. Low-cost results require declared validity/error bounds and escalation conditions; missing historical geometry, unknown occlusion and computation failure cannot become full visibility.


<!-- phase3c-end:C-115-1658-1684 -->


### ID 116 — Auditory propagation and detection

<a id="arch-source-116"></a>

<!-- phase3c-begin:C-116-1686-1720 -->

<a id="arch-source-116-part-1"></a>

**Phase 3C source excerpt:** ID 116, lines 1686–1720 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-116-1686-1720:1686-1720 -->

For a steady isotropic point source in a uniform lossless free field, outside the source/near-field region and within the declared model range,

\[
I(r)=\frac{W}{4\pi r^2},
\qquad
L_I=10\log_{10}(I/I_0),
\qquad
L_p=20\log_{10}(p_{\mathrm{rms}}/p_0).
\]

\(W\) is sound power in watts, \(I\) intensity in W/m², \(r>0\) distance in metres, and \(p_{\mathrm{rms}}\) RMS pressure in Pa. Common airborne references are \(I_0=10^{-12}\,\mathrm{W/m^2}\) and \(p_0=20\,\mu\mathrm{Pa}\). Pressure and intensity levels are distinct; relating them additionally requires the appropriate medium/wave assumptions, such as \(I=p_{\mathrm{rms}}^2/(\rho c)\) for a suitable progressive-wave approximation, with density \(\rho\) in kg/m³ and sound speed \(c\) in m/s. Logarithmic levels require positive intensity/pressure; zero is a limiting case, while negative or missing physical inputs are invalid or unknown. Doubling distance quarters intensity and, under these assumptions, reduces the corresponding level by about 6.02 dB. This is not a general indoor/reverberant or directional-source rule.

A candidate finite-band extension is

\[
L_{S,b}(r)=L_{S,b}(r_0)-20\log_{10}(r/r_0)
-\gamma_b(r-r_0)-A_{\mathrm{obs},b},
\qquad r\ge r_0>0.
\]

\(b\) identifies the frequency band, \(L_{S,b}(r_0)\) its reference signal level, \(\gamma_b\ge0\) absorption in dB/m and \(A_{\mathrm{obs},b}\ge0\) supported obstruction loss in dB. Reflection, reverberation, coherent paths and multipath require separate applicable models. Do not directly sum dB as a general path-combination method.

For the same bandwidth and time window, a candidate detection model is

\[
\mathrm{SNR}_b=L_{S,b}-L_{N,b},\qquad
P_{\mathrm{det},b}=\sigma\left(\frac{\mathrm{SNR}_b-\eta_b}{\beta_b}\right),
\quad \sigma(x)=\frac1{1+e^{-x}}.
\]

\(L_{N,b}\) is band noise level; \(\eta_b,\beta_b\) are in dB, with \(\beta_b>0\). Detection probability is a proposed calibrated use, not a validated prediction. Detection, direction estimation, source classification, speech intelligibility and semantic disclosure are separate outputs. SNR alone does not determine intelligibility. Physically audible content is not automatically authorized protected semantic content.

Visual and auditory models may share verified distance/frame primitives but retain separate propagation, uncertainty and recognition models. Higher fidelity never expands permissions. Candidate results still require independent authorization before trusted Observation issuance and actual L1 acceptance; neither stage implies justified cognitive revision.


<!-- phase3c-end:C-116-1686-1720 -->


### ID 117 — Mathematical review and open decisions

<a id="arch-source-117"></a>

<!-- phase3c-begin:C-117-1722-1726 -->

<a id="arch-source-117-part-1"></a>

**Phase 3C source excerpt:** ID 117, lines 1722–1726 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** PLANNED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-117-1722-1726:1722-1726 -->

Future model validation must check zero/large distance and missing inputs, dimensions/unit conversions, FOV and threshold boundaries, distance-doubling behavior under stated assumptions, occlusion/illumination and noise changes, and no permission gain with higher fidelity. Loud noise does not imply intelligible speech; quiet speech in high noise must remain a separate detection/intelligibility case. A matching happy-path output does not prove low/high-fidelity equivalence. These are acceptance requirements, not executed tests.

Calibration data, parameters, model ranges and whether an output is a proxy, probability or another measure remain undecided. Historical inputs must be verifiable; current WorldState or prose cannot fill missing past geometry. Model upgrades cannot silently reinterpret accepted historical evidence. Shared cost, priority, fairness and recovery semantics remain separate undecided coordinator work. [Reference-policy deviation models](../SOCIAL_CAUSAL_DESIGN.md#reference-policy-deviation-candidate-mathematics-not-a-production-classifier) affect cognition-side decision modeling, not a fourth LOD axis or physical authority.


<!-- phase3c-end:C-117-1722-1726 -->


### ID 167 — Bounded owner-visible state query (current local foundation)

<a id="arch-source-167"></a>

<!-- phase3c-begin:C-167-2401-2403 -->

<a id="arch-source-167-part-1"></a>

**Phase 3C source excerpt:** ID 167, lines 2401–2403 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-167-2401-2403:2401-2403 -->

`AuthorizedStateQuery` reads only unchanged typed facts in the current actor's provenance-checked Observations, cross-checking the trusted Event and EventProcessor evidence, event-time VisibilityPolicy decision, requested Attempt target, and simulation tick. A per-Attempt `AuthorizedQuerySession` limits queries and fact count. Hidden, unknown, and unsupported agent targets yield no evidence. It never reads the whole WorldState or writes any Store. Query proposals and cited-fact analyses have closed, bounded schemas. The live OpenAI-compatible query/analysis loop and any incorporation into `MethodBasedResolutionEngine` are **not implemented**; no model query grants state access or confirms effects. Existing deterministic causal adjudication remains authoritative.


<!-- phase3c-end:C-167-2401-2403 -->


### ID 187 — Position driven observation precision (bounded implementation)

<a id="arch-source-187"></a>

<!-- phase3c-begin:C-187-2662-2672 -->

<a id="arch-source-187-part-1"></a>

**Phase 3C source excerpt:** ID 187, lines 2662–2672 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-187-2662-2672:2662-2672 -->

The opt-in JSON v3 path adds a one-dimensional metric **observation domain**, not a global spatial engine. Each configured location node has an ObservationZone/v1 frame identity and meter offset. A configured object's ObservationRangePolicy/v1 supplies coarse/detail distance limits and explicit detail recipients. Content validation resolves local frame/recipient references into canonical runtime identities. These values live on existing canonical location/object Entities; no parallel position Store or LOD coordinator exists.

A character's effective observation position follows its actual WorldState.locations entry. Moving through an installed passage changes that entry only through Attempt, Resolution, EventFactory and EventProcessor. Resolving the new location's zone can change the next observation's precision without changing the target's identity, ownership, appearance or position. The developer host's `--approach` offers exactly one explicitly requested installed passage step, then a fresh observation; it is not an autonomous planner or physical teleportation shortcut.

Distance is absolute offset difference inside the same explicitly authored domain. Known sight/light, target visibility and valid domain evidence remain prerequisites. Detail also needs a detail request, the object's detail_visible permission, an explicitly listed recipient and the configured detail range. A nearer but unauthorized NPC gets only qualifying coarse evidence. Coarse requests do not silently become inspections, unsupported coordinates/domains produce no range-based disclosure, and passage connectivity alone proves no visibility or metric distance.

The existing object projection module owns this bounded selection rule, reused by the handler and event-time authorization. Signed evidence captures only the relevant positions, domain, limits and that receiver's disclosure decision. Rendering remains unchanged and receives only the permitted finite fact. Old observations retain their original captured precision after movement or restore; presentation retry never recomputes them using a newer position or repeats movement. The older no-policy carried-object contract remains separate and unchanged.

This model assumes an explicitly shared observation domain, known lighting and authored feature permissions. It implements neither FOV/occlusion nor a claim that all locations in a geometric frame are mutually visible. There is no continuous coordinate motion, 3D transform, sensory calibration or general distance-based physics/LOD scheduler. [Exact configuration and persistence](../DATA_CONTRACTS.md#position-observation-contracts-v1-and-json-v3); [current verification](../REPOSITORY_STATUS.md#position-driven-observation-acceptance).


<!-- phase3c-end:C-187-2662-2672 -->


### ID 190 — Committed Boolean result Observation

<a id="arch-source-190"></a>

<!-- phase3c-begin:C-190-2698-2703 -->

<a id="arch-source-190-part-1"></a>

**Phase 3C source excerpt:** ID 190, lines 2698–2703 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-190-2698-2703:2698-2703 -->

The first physical-to-cognition extension supersedes the earlier v1 slice's absence of a physical fact projection only for a validated Boolean transition. ResolutionEffectsHandler delegates its pre-apply fact draft hook to the existing physical adapter, after independent current-state/rule/delta validation. EventProcessor applies the update, issues signed processing evidence, appends formal history and only then delivers authorized Observations. The draft is not itself an Observation or committed fact.

The owner-private `action_result / boolean_transition_applied` fact binds the receiver to a property-name/Boolean-value tuple. Its shared projection/authorization module verifies exact canonical Event/evidence and event-time actor binding; proximity alone grants nothing. Ordinary qualified L1 in AgentTurn must actually ingest it before it is available in decision context. Existing source, history and Runtime permission responsibilities remain distinct. No automatic Belief/Goal revision, B2 rule, UI rendering permission or full physical-state disclosure is added. [Exact boundaries and restore semantics](../DATA_CONTRACTS.md#committed-boolean-result-observation).



<!-- phase3c-end:C-190-2698-2703 -->


### Content received from coordinated splits

- Original ID **186**, source lines **2654–2660**: approved excerpt copied in Phase 3C below; other parts and final coordination remain pending. The original heading keeps its separate primary assignment.

### Split source ID 186 — JSON objects and bounded visual projection (implemented narrow slice) / Closed appearance projection and independently authorized disclosure

<!-- phase3c-begin:C-186-2654-2660 -->

<a id="arch-source-186-part-2"></a>

**Phase 3C source excerpt:** ID 186, lines 2654–2660 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-186-2654-2660:2654-2660 -->
A controlled `object_observed` request reads only an exact ObjectAppearance/v1 value installed in the reserved Entity.attributes appearance entry. This is a single closed authored visual record, not arbitrary attributes disclosure, ECS, identity recognition or a general component permission system. A read-only handler projection hook defaults to each existing handler's original observable_facts behavior. The object handler requests a no-op world update and supplies explicit facts; EventProcessor captures authoritative post-update conditions and seals them through the normal evidence chain.

Coarse projection requires a registered sighted observer, the same supported location, explicitly known light and an appearance permitted to be visible. Detailed projection additionally requires a detail request, explicit detail permission and the object actually located on and owned by that observer. It therefore demonstrates **carried-object inspection**, not general geometric near-distance inspection. Missing reach/permission downgrades to valid coarse evidence; missing sight/light/visibility produces none. Increasing requested detail never grants permission. Neither object existence nor a shape fact proves its name, purpose, ownership or mechanical use to the observer.

VisibilityPolicy, ObservationGenerator/Store, PerspectiveResolver, VisibilityFilter, MinimalComposer, PresentationValidator and the existing output Gateway remain the delivery path. Only a finite shape/detail value reaches composition; raw attributes, private cognition, IDs and debug values are not prose. This adds no full visual LOD, FOV, occlusion, orientation, acoustics, 3D distance, shared LOD coordinator or natural-language object-inspection UI integration. See [the exact contracts](../DATA_CONTRACTS.md#json-object-content-v2-and-appearance-v1) and [working-tree verification](../REPOSITORY_STATUS.md#json-object-and-perceptual-projection-acceptance).



<!-- phase3c-end:C-186-2654-2660 -->


## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [ARCHITECTURE.md](../ARCHITECTURE.md) — canonical owner for A02.
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) — canonical owner for A08, A13.
- [SOCIAL_CAUSAL_DESIGN.md](../SOCIAL_CAUSAL_DESIGN.md) — canonical owner for A21.
- [COGNITION.md](COGNITION.md) — canonical owner for A27, A29, A30.
- [EXECUTION.md](EXECUTION.md) — canonical owner for A11.
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md) — canonical owner for A14.
- [WORLD_MODEL.md](WORLD_MODEL.md) — canonical owner for A03, A24, A28.
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md) — canonical owner for A25.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [COGNITION.md](COGNITION.md)
- [EXECUTION.md](EXECUTION.md)
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md)
- [PERSISTENCE.md](PERSISTENCE.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)
- [WORLD_SIMULATION.md](WORLD_SIMULATION.md)

## Historical and implementation-status handling

Pending migration. Preserve the frozen charter historical-retention and status-reporting responsibilities; no capability or test result is established by this skeleton.

Contact: ankorgine@outlook.com
