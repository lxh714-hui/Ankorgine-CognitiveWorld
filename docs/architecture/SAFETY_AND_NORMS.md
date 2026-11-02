# CognitiveWorld — Safety and Disclosure Boundaries

> **Status: approved Phase 3B/3C excerpts migrated; excluded scope remains pending.**
> This is staged documentation migration, not new implementation or test evidence. Only explicitly marked source ranges have been copied.

The original [ARCHITECTURE.md](../ARCHITECTURE.md) remains byte-identical. Existing data, meta-contract and specialized definitions retain their frozen owners. Historical, held, reference-only and old-entry material is not implicitly migrated; source-stage descriptions remain qualified.

## Purpose

Safety and disclosure boundaries.

## Authority and scope

**Frozen authority level:** Focused cross-domain architecture; no new policy or general arbitration.

**Assigned responsibility:** Safety versus WorldNorms, trusted subjects and optional provider transport/disclosure.

Only marked architectural excerpts have migrated. Detailed data contracts, meta-contracts and specialized normative definitions retain their approved owners.

## Concepts assigned by the frozen charter

- **A37 — Safety architecture versus WorldNorms**: Approved source excerpts are migrated only where marked; remaining scope and exact canonical contracts stay with their frozen owners.

## Out of scope

- World-record schemas and WorldNorms data definitions.
- NPC decision selection and physical adjudication results.
- New admission policies, general arbitration or transport/proof schemas.

## Migrated excerpts and pending section outline

Only marked approved excerpts have migrated. Other entries remain pending. Source titles retain their original stage/status; no title is new acceptance evidence.

### ID 129 — Phase 12.5C — Universal Safety and World Norms (implemented slice; validation pending)

Pending content migration. Frozen primary source identity: **129**.

### ID 131 — Safety, conflict, and world-law responsibility

<a id="arch-source-131"></a>

<!-- phase3c-begin:C-131-1914-1918 -->

<a id="arch-source-131-part-1"></a>

**Phase 3C source excerpt:** ID 131, lines 1914–1918 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-131-1914-1918:1914-1918 -->

`UniversalSafetyGovernance` is a fixed P0 content-safety boundary shared by all worlds, players, NPCs, modes, and providers. World configuration, scenario packages, player/NPC text, director commands, and model output cannot disable it or add exemptions. It runs on the application path and is not merely a Prompt instruction. Deterministic checks protect known structured/patterned high-risk cases; a bounded semantic provider may add contextual assessment through the existing OpenAI-compatible transport. Provider output is strictly schema-checked and never issues world facts, permissions, Events, or Resolution credentials. Provider failure preserves explicit refusal and sends ambiguous high-risk inputs to clarification/safe degradation. A single classifier is not claimed to catch every evasion.

Content Safety governs prohibited assistance and restricted presentation. WorldNorms describes in-world law, morality, custom, and governance. Resolution judges causality. AgentDecision chooses NPC behavior. Presentation controls what is shown. These responsibilities do not merge: fictional crime or conflict is not inherently a safety violation; illegality does not itself make an attempt fail; Safety does not turn hostile goals friendly, compel NPC cooperation/forgiveness, create reconciliation, or write a punishment Event. Safety refusal is an input disposition only and does not enter EventHistory, WorldState, or character Memory. Allowed conflict goes through normal AgentDecision and Resolution and may be unresolved until a causal policy exists.


<!-- phase3c-end:C-131-1914-1918 -->

<!-- phase3c-begin:C-131-1920-1922 -->

**Phase 3C source excerpt:** ID 131, lines 1920–1922 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-131-1920-1922:1920-1922 -->

The existing default Resolution domains remain door operation and known passage traversal. Fictional battle or social-conflict attempts are not safety-blocked merely for being violent or illegal, but the current causal engine does not implement a general battle/social simulation. Such attempts can remain unresolved. This phase does not fabricate a combat result or NPC reaction to make conflict appear implemented.


<!-- phase3c-end:C-131-1920-1922 -->


### ID 139 — P0 safety boundary: current implementation and acceptance status

<a id="arch-source-139"></a>

<!-- phase3c-begin:C-139-2036-2093 -->

<a id="arch-source-139-part-1"></a>

**Phase 3C source excerpt:** ID 139, lines 2036–2093 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** MIXED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-139-2036-2093:2036-2093 -->

`RuntimeContext` owns one `UniversalSafetyGovernance` instance and binds it to
that runtime's WorldState and SimulationClock. `SimulationRuntime` passes this
instance into the built-in `AgentActionLoop`; that loop checks the Proposal
outside the injectable ActionPipeline, checks the resulting Attempt, then
uses the same policy through ActionResolutionFlow, MethodBasedResolutionEngine
advice checks, and EventFactory. StepwisePlanExecutor shares its
ActionResolutionFlow policy. `PresentationPipeline.for_runtime` requires the
same RuntimeContext policy. WorldNorms generation requires an explicit
governance instance. These are application composition checks, not isolation
from malicious Python code in the same process. Direct standalone objects use
their own deterministic-only governance and are not evidence of production
semantic-provider readiness.

`Entity.safety_profile` is the typed source for exact age and profile revision.
The current resolver reads only this field from the active WorldState Entity;
it ignores generic `Entity.attributes`, names, avatar/appearance data, and
player/model claims. Profiles can enter through trusted world initialization
and may be replaced only through a trusted world update. An absent profile or
age is unknown. Ordinary dialogue, bargaining, conflict, crime, and combat
attempts do not require age data. Sensitive sexual action with a minor is
blocked; missing age or consent context is clarified. Profiles currently
enter through trusted WorldState initialization; there is no dedicated
runtime profile-update handler. There is not yet a
trusted, pair- and activity-scoped consent record or relationship-safety
contract, so text claiming consent cannot authorize such an action and adult
consensual action may remain unavailable pending that contract.

The immutable safety assessment binds exact action text, actor, targets,
policy version, and a digest of resolved subject identity/age/profile revision,
world instance, and current simulation tick. It is recalculated at each
authority boundary; content or relevant context changes cannot reuse an old
assessment. `SafetyReadiness` explicitly reports either
`deterministic_only_unvalidated` or `provider_configured_unvalidated`. A
configured provider has not thereby passed live model validation. Missing
provider configuration is visible and does not remove deterministic gates.
High-risk cues and unknown sensitive age/consent contexts fail closed, while
unrecognized adversarial paraphrase remains a known gap of deterministic-only
operation.

The existing OpenAI-compatible transport is reused. Runtime hosts may inject
one `UniversalSafetyGovernance(provider=...)` when constructing RuntimeContext;
the built-in runtime composition shares it across action, causal, stepwise,
result/Event, and Presentation boundaries. There is no separate network
framework. Player Action does not yet have a separately authenticated
production ingress, Director Intervention has no CW execution path, and
custom host orchestration outside the built-in composition must explicitly
bind the shared policy. EventProcessor continues to authenticate Event
provenance; action-originated Events are rechecked by EventFactory. A Safety
refusal creates no Event, WorldState update, Observation, punishment, or
character memory.

Runtime governance cannot be rebound to a different WorldState or clock after
composition. Safety input collections are immutable tuples, and route labels
cannot use presentation or normative-text handling to authorize an action.
The fixed governance class is not an extension point for weaker policy
subclasses; providers contribute untrusted semantic labels only.


<!-- phase3c-end:C-139-2036-2093 -->


### ID 179 — OpenAI-compatible Provider transport security

<a id="arch-source-179"></a>

<!-- phase3c-begin:C-179-2579-2583 -->

<a id="arch-source-179-part-1"></a>

**Phase 3C source excerpt:** ID 179, lines 2579–2583 from [ARCHITECTURE.md](../ARCHITECTURE.md). Direct body only; child sections and excluded lines are not included.

**Source classification:** IMPLEMENTED. Original stage/plan/uncertainty limits are retained; this copy is not new runtime functionality or a new test result.

<!-- phase3c-source:C-179-2579-2583:2579-2583 -->

Optional OpenAI-compatible Decision and Causal adapters use the shared bounded transport and remain host-injected; this boundary does not select a remote provider or create a default external call. Plain HTTP is accepted only for an IP loopback literal or `localhost` whose resolved addresses are all loopback. The chosen numeric loopback address is pinned for HTTP connections. Other HTTP endpoints are rejected before request transmission. Remote endpoints require HTTPS using standard TLS certificate checks. Redirects are rejected for both transports; there is no HTTP downgrade or alternate remote endpoint fallback. Bearer authorization headers are rejected over HTTP, including loopback HTTP. Provider code does not log API keys or complete request bodies.

A remote Decision request may contain the bounded current-owner view: trusted observed facts, WorkingMemory, retrieved Memory, subjective Beliefs, Goals, SelfModel-derived capabilities and limitations, Personality preferences/values/traits, Emotion levels, motivation/modulation and uncertainty. Direct Causal requests contain bounded Attempt/proposal data and the verified context supplied to that operation. Existing wrappers on the same adapter send their bounded task payloads: Safety sends the submitted SafetyInput and trusted subject context, WorldNorms generation sends its world seed, and content generation sends its creative brief and schema constraints. These are disclosures to the host-configured endpoint. The host must explicitly authorize the destination and decide whether each payload may leave the process. Encryption does not establish provider trust, retention limits, data minimization, or semantic correctness.


<!-- phase3c-end:C-179-2579-2583 -->


## Canonical contract references

References identify approved owners; they are not evidence of migrated content or implementation. No new source-identity or legacy anchors are installed in this phase.

- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) — canonical owner for A38.

## Cross-domain dependencies

The following document dependencies come from the frozen charter; they do not assert new APIs or implementation relationships.

- [AI_BOUNDARY.md](../AI_BOUNDARY.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [COGNITIVEWORLD_CORE_DOCTRINE.md](../COGNITIVEWORLD_CORE_DOCTRINE.md)
- [DATA_CONTRACTS.md](../DATA_CONTRACTS.md)
- [ENGINEERING_RULES.md](../ENGINEERING_RULES.md)
- [META_CONTRACTS.md](../META_CONTRACTS.md)
- [REPOSITORY_STATUS.md](../REPOSITORY_STATUS.md)
- [COGNITION.md](COGNITION.md)
- [EXECUTION.md](EXECUTION.md)
- [INTERACTION_AND_PRESENTATION.md](INTERACTION_AND_PRESENTATION.md)
- [PERCEPTION.md](PERCEPTION.md)
- [WORLD_MODEL.md](WORLD_MODEL.md)

## Historical and implementation-status handling

Pending migration. Retain original phase boundaries, historical decisions and distinctions between approved principles, implemented paths and planned capabilities. Dated verification evidence remains owned by the existing [REPOSITORY_STATUS.md](../REPOSITORY_STATUS.md); this skeleton reports no test result.

Contact: ankorgine@outlook.com
