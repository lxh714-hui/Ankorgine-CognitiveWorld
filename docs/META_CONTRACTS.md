# CognitiveWorld Meta-Contracts

## Authority and status

**Approved normative design; universal runtime conformance is not implemented or verified.** This is the single authoritative location for the shared semantic boundaries of replaceable physical, causal and governance modules. It complements the [Core Doctrine](COGNITIVEWORLD_CORE_DOCTRINE.md), [architecture](ARCHITECTURE.md), [detailed data contracts](DATA_CONTRACTS.md) and [engineering rules](ENGINEERING_RULES.md); it does not replace module-specific specifications or silently supersede frozen historical contracts. A conflict requires explicit contract review before implementation.

“MUST”, “MUST NOT” and “required” below express approved requirements, not claims about current code. The [implementation-status matrix](#implementation-status-matrix) separately identifies source-inspected mechanisms, gaps and proposed acceptance. No API, schema, registry, persistence format or module lifecycle is frozen by this document. No new runtime mechanism is implemented by publishing it.

## L0 admission

L0 is a non-pluggable admission validator. A module being admitted cannot override its allowlist. L0 checks closed structure, types, supported versions and fixed permitted values; it does not interpret arbitrary module internals or prove semantic correctness.

Mandatory explicit declarations are:

- `failure_semantics = fail_closed`
- `provenance = required`
- `commit_path = governed`

Missing mandatory fields, invalid types, unsupported versions, unknown fields in a closed schema and values outside the fixed allowlist MUST be rejected. Mandatory declarations receive no substituted defaults. Changing L0 requires an explicit, independently validated kernel-contract revision; plugins cannot change admission policy. Passing L0 establishes declaration eligibility only, never runtime correctness. Concrete declaration encoding and admission implementation remain future work.

## Three distinct responsibilities

### Physical meta-contract

The physical contract governs typed world state, properties, relationships, invariants, dependencies and candidate transitions. Changes involving related records require joint validation and publication under the applicable governed boundary. A replaceable physical module has no direct world-fact commit authority. Joint publication is a semantic requirement, not a new cross-Store atomicity or crash-durability guarantee.

### Causal meta-contract

The causal contract governs conditional predictions, dependencies, evidence, candidate effects, applicability and invalidation conditions. A conditional result remains a proposal, not an established world fact. A causal module cannot independently grant write authority.

### Governance meta-contract

The governance contract governs admission, authorization, evidence qualification, independent candidate validation, conflicts, formal commit, auditability, recovery boundaries and compensation. It determines eligibility to become a formal world fact under applicable rules. Model confidence and explanatory plausibility cannot replace authorization or evidence. All three contracts remain subject to L0's non-overridable requirements.

## Candidate, adjudication and fact separation

The conceptual responsibility flow is:

`Candidate generation → Evidence and authorization validation → Governance adjudication → Independent commit-boundary validation → Formal commit → Append-only history`

Module output, successful adjudication and committed fact are distinct. Candidates MUST NOT mutate authoritative WorldState directly. The formal commit boundary MUST independently verify applicable prerequisites, provenance, authorization and permitted changes against authoritative inputs.

This flow does not claim a transactional gap-free implementation between state application and history publication. Existing EventProcessor ordering and recovery protections remain in force; append-only history does not imply cross-Store atomicity.

When two admissible causal candidates conflict and available rules or evidence cannot distinguish them, adopt neither. Confidence, execution order, randomness and module identity are not implicit tie-breakers. Prioritization or specificity-based resolution requires an explicitly admitted governance rule.

## G1 Governed candidate collection and closure

### G1.1 Round membership and required-source authority

A module may propose outcomes, but MUST NOT define its own authority, certify collection completeness or authorize its own effects. Before generation begins, a previously admitted governance policy MUST define the required candidate-source set. Generators MUST NOT add, remove, replace or redefine required sources, certify their own completion, or close the round.

Each round MUST bind its adjudication question (the particular Attempt or governed operation request), canonical Timeline/history context, applicable governance-policy identity/version, required-source set, registered candidate content identities and independently validated source-completion evidence. Shared targets or arrival times alone do not establish common membership. A generator cannot split a governed question into separate rounds to evade comparison. Authorized source-set or policy changes require an explicitly permitted new-round rule; a closed round is immutable.

### Collection and explicit completion barrier

Keep generation, registration, candidate-set closure, independent validation, conflict detection, governance decision and formal commit distinct. Only the policy-authorized governance boundary may close a round. Closure evidence MUST bind the exact membership and required-source completion evidence; generator self-declaration is not sufficient evidence. The governance boundary must independently validate completion under the admitted policy.

The first version uses an explicit completion barrier. Explicit validated completion with no candidate, no response, source failure and an unverifiable response are distinct states. An absent, failed or incomplete required source MUST NOT be treated as an empty result. An incomplete set is ineligible for formal submission. An empty queue, elapsed timeout or lack of callbacks proves neither completion nor closure authority. Timeout-based partial-set adjudication is forbidden unless an explicitly approved applicable policy permits it; this specification installs no such policy.

### Closed-set conflict and late candidates

Independent validation must establish admissibility before conflict arbitration. Compare verified effects, state dependencies and applicable invariants; missing comparison evidence does not establish compatibility. Within the same closed round, mutually incompatible admitted candidates that no explicitly admitted rule distinguishes cause the conflicting indivisible result group not to be submitted. Unauthorized candidates are rejected, not promoted into valid competitors. Confidence, module identity, arrival order and randomness cannot silently choose a winner. Unresolved conflict MUST NOT be fabricated into an ordinary failed-action Event.

Late candidates cannot mutate or reopen a closed set. Any further consideration requires an explicitly authorized new round and current prerequisites. A previously committed incompatible Event remains history; a new candidate must be checked against current state and rejected/deferred when inapplicable, never used to retroactively reject or rewrite that Event. Sequential independent actions and same-round causal alternatives are not interchangeable. This specification does not introduce a generic round mechanism, concurrent global arbitration or cross-Store atomicity.

## Failure and invalidation

| Situation | Required disposition |
| --- | --- |
| Uncommitted candidate has changed prerequisites | Invalidate and reject; do not silently re-adjudicate it. |
| Missing or invalid evidence or authorization | Reject without fabricating proof. |
| Unresolved conflict between admissible candidates | Adopt neither by default. |
| Valid no-effect failure | May record formally under its applicable contract; failure is not fabricated success. |
| Committed fact requires correction | Issue a new governed compensating event, subject to G-3. |
| Uncertain write outcome | Preserve existing recovery-required protections; no blind retry, replay or rollback claim. |

Only uncommitted candidates may be invalidated. Committed historical facts and their signature history cannot be retracted, erased or rewritten. A new authorized event may correct current state. Negative feedback from failed actions, searches or interactions may influence cognition through its own supported governance; it does not independently change authoritative world facts. Receipt, observation, interpretation, actual consumption, subjective belief and world-write authorization remain separate. No observation, a failed observation attempt, not found within a defined scope, evidence supporting absence and authoritative destruction/removal are different states. Failed search or interaction alone proves neither nonexistence nor removal; private evidence does not automatically become another actor's knowledge.

## Contract-version binding

A formal event MUST retain enough information to identify the contract identity and version under which its result was adjudicated. Contract version, adjudication evidence, formal result and currently installed implementation version are different bindings.

A newer contract MUST NOT silently reinterpret or re-adjudicate historical events. An unavailable old contract or required migration needs an explicit validated compatibility or migration procedure. This requirement does not authorize retrofitting fields, rewriting signatures, upgrading old records or changing Bundle versions. Existing events have narrower domain bindings; universal coverage is not established.

## G2 Authoritative-state dependency freeze

G2 freezes the governed operation's relevant authoritative state bindings, not NPC cognition or the whole world. Revalidate exact identity/type, life-state value and source, selected contract, Attempt, Timeline/tick and Runtime permit at submission. Relevant provenance changes invalidate a candidate even if the value returns to its previous value. Unrelated world changes and Belief/Goal changes do not by themselves invalidate it. Build the narrow update from current canonical state, never a captured whole-world snapshot. The life-transition path implements this bounded dependency check; no universal G2 coordinator is established. Contract identity and operation admission below remain independent requirements, formerly labelled G2/G2.3; their semantics are retained.

## Contract identity and operation admission

Contract admission, runtime conformance and formal submission authorization are separate checks. A selected contract MUST have stable identity, immutable version identity and a canonical content fingerprint, with explicit permitted operation kinds and scope. The same identity/version cannot silently acquire different content. Unknown, unavailable, incompatible or unadmitted versions do not authorize new submissions; never substitute a global latest version. Existing Event signatures, Runtime permits and policy fingerprints do not by themselves constitute general admission evidence. L0 remains non-pluggable and retains its fixed mandatory values; structural admission proves no semantic correctness.

### Contract-admission trust root

The selected minimum trust model is a maintainer-signed canonical admission manifest plus a pinned public key held by the trusted host. Before signing and verification, the manifest MUST be canonicalized under an explicitly defined deterministic representation. It MUST bind contract identity, immutable version identity, canonical content fingerprint, permitted operation kinds, applicable scope, approving authority and any explicitly defined validity or revocation conditions. Representation, cryptographic algorithm, API, storage location and wire format are not frozen here; implementation requires their explicit specification and acceptance.

The trusted host MUST independently verify the manifest signature against its trusted configured public key. Contract self-declarations, plugin-generated approval claims and model output cannot establish admission. A valid signature establishes approval by the corresponding trusted key holder, not candidate semantic correctness or authorization of the current operation. Independent runtime validation and formal submission authorization remain mandatory.

### Trust updates and revocation

A plugin or a new manifest MUST NOT make a new key trusted. Rotation requires an authorized trust-update procedure, such as authorization under the existing trust root or an independently reviewed trusted-host update. This is not a full PKI, certificate-chain service, remote registry or key-management service.

Revocation MUST distinguish new-submission eligibility from historical verification. Ordinary admission revocation must not silently rewrite, invalidate or re-adjudicate previously recorded Events. Suspected key compromise or invalid historical evidence requires a separately authorized recovery/review policy. Installing a new version or rotating a key cannot silently substitute present approval for the original historical bindings. Required historical validation that cannot be established must fail closed or remain unresolved under an explicit compatibility procedure, without fabricating old approval. No historical migration, signature reinterpretation or stronger recovery guarantee is authorized here.

## G-3 Compensation

A compensating event MUST explicitly identify:

- `contract_id`;
- `contract_version`;
- `operation_kind`;
- `compensates_event_ref`;
- required evidence and authorization bindings.

The selected version must have been admitted for that compensation operation kind. Compensation is adjudicated under that explicit contract, never an ambiguous global latest version. It may change current state without erasing the original event or signature history. These are semantic requirements, not a newly approved persistent envelope or an existing compensation API. Existing scheduling retry or skipped-wakeup behavior is not this compensation mechanism.

### Governed current-state compensation

Compensation is a new governed operation through the same semantic execution boundary as other operations. It requires an explicitly selected admitted contract version and operation-specific authorization. The original Event reference establishes a relationship only, not execution permission. Candidates MUST bind required evidence, current-state preconditions and dependencies, which must be independently revalidated against authoritative state before submission.

Successful compensation creates a new Event; the original remains immutable. Never restore an old snapshot, blindly invert a WorldUpdate or undo unrelated later Events. If the original effect has been replaced or current preconditions no longer hold, reject or defer according to the specific operation contract. Compensation semantics may differ by operation; there is no universal inverse.

Mutually incompatible admitted candidates in the same closed round follow G1: absent an explicitly admitted distinguishing rule, do not submit the conflicting indivisible group. Unadmitted candidates are rejected as unauthorized, not treated as valid competitors. Uncertain writes retain existing recovery-required protection; compensation grants no replay or rollback exemption.

The first version uses one explicitly authorized compensation decision source. This bounds scope; it does not certify that source's correctness or remove independent validation. Generic multi-module compensation arbitration, cascading rollback and universal reversibility are outside that first version. No compensation implementation or persistence fields are added by this specification.

## G-4 Branch and ancestor semantics

A child inherits an ancestor event's formal result and historical identity, not permission to re-adjudicate it under the child's current contract. This applies to cold recovery, ancestor-history reads, timeline creation and repeated delivery. New child actions may use the child's admitted version; authorized compensation still requires G-3. Neither operation may reinterpret the ancestor as originally governed by the new version. Children do not inherit unfinished candidate rounds or old Runtime permits. Exact ancestry and sibling isolation remain mandatory; historical evidence is not a live execution permit.

## Anti-special-case and kernel acceptance gates

Code-level and data-level exceptions that bypass these contracts are prohibited, including entity-name execution branches, scenario flags such as `is_dead_dropped`, hidden metadata or unvalidated configuration, direct authoritative mutation by a replaceable module, and treating confidence, repetition or keyword overlap as factual proof. Requirements cannot be silently relaxed to make a slice pass.

Reusable independently validated properties and relationships are allowed; a disguised one-scenario exemption is not a general data-model extension. If a capability cannot be expressed, stop and explicitly revise the contract before implementing it.

“The kernel remains unchanged” is a falsifiable acceptance gate for each new slice, not a permanent prohibition on approved kernel revisions. A slice may add its own module, rules, tests and necessary reusable model extensions. It may not weaken L0, bypass independent validation, broaden plugin privileges or add special-case escapes. If a kernel change is required, that architecture acceptance fails: return to contract review, explicitly revise and rerun acceptance. Promote requirements to code-guaranteed status only after the relevant tests actually pass.

## Implementation-status matrix

The two columns distinguish exact source-inspected guarantees from normative gaps. “Partially implemented” never means universal conformance. Source inspection in this documentation task is static evidence, not a fresh dynamic verification. **No tests were created or executed for this task.** All eight proposed test filenames below were checked against the current tests directory and are absent. Their names are traceability labels, not executable coverage claims. Where evidence is insufficient, the new capability is **NO-GO** pending its stated acceptance.

| Currently guaranteed by code | Required by the specification but not yet implemented or verified |
| --- | --- |
| No universal L0 mechanism established. **Status: not implemented** for this new admission contract. | **NO-GO:** non-overridable closed declarations, mandatory values and independently controlled kernel revision. Proposed `test_meta_contract_admission.py`: missing/unknown/wrong-type/version/value rejection, no defaults, plugin attempts to replace allowlist, and admission not treated as conformance. |
| **Status: partially implemented.** [EventFactory](../src/cognitive_world/event/factory.py) `validate_live_resolution_entry` and [EventProcessor](../src/cognitive_world/event/processor.py) `_process_with_evidence` independently guard live Resolution entry; handlers and read guards validate supported effects before apply. [RuntimeWriteFence](../src/cognitive_world/runtime/write_fence.py) guards bound protected work. These are bounded mechanisms, not universal module admission. | **NO-GO** for universal conformance. Proposed `test_governance_contract_conformance.py`: malicious module cannot mutate canonical state; unsupported/unauthorized/stale candidates fail before commit; valid no-effect failure remains distinguishable from rejection; post-apply uncertainty freezes writes/capture. Include permanent independent Processor and Event-copy regressions still missing from the audited take slice. |
| No general arbitration mechanism established. **Status: not implemented** for conflicting causal candidates. | **NO-GO:** proposed `test_conflicting_causal_candidates.py`: two admissible indistinguishable conflicting candidates produce neither effect, regardless of order/confidence/module identity; only an explicitly admitted rule may prioritize. |
| Generic round registration/closure and governance-owned required-source admission are **not implemented**. | **NO-GO:** newly specified G1 requirements need acceptance scenarios for prior policy binding, forbidden generator source-set changes/self-certification, explicit empty completion versus absent/failed/unverifiable responses, incomplete-set submission rejection, immutable closure and late candidates. No new tests are created or executed here. |
| Generic contract-version admission, signed canonical manifest verification and trusted-host key rotation/revocation are **not implemented**. | **NO-GO:** newly specified contract-admission requires deterministic canonicalization, exact operation/scope/content binding, pinned-key verification, rejection of self-approval and manifest-introduced keys, authorized rotation, new-submission revocation and unchanged historical verification semantics. A manifest signature must not replace conformance or current authorization. |
| Existing signatures and append-only formal processing do not implement G-3. **Status: not implemented** for versioned compensation. | **NO-GO:** proposed `test_versioned_compensation.py`: exact original reference, admitted operation/version and authorization required; reject global-latest substitution and missing bindings; original bytes/signatures unchanged; single authorized source still independently validated, replaced current effects/preconditions rejected or deferred, unrelated later Events preserved and no inverse replay. Universal event contract-version coverage is also **not verified**; test unavailable old contracts and explicit compatibility refusal. |
| **Status: partially implemented.** [EventHistory](../src/cognitive_world/event/history.py) `begin_processing` verifies matching ancestor Event/evidence and returns reusable evidence rather than applying again; [reconstruction](../src/cognitive_world/runtime/reconstruction.py) supplies verified recovery. Domain history compatibility remains bounded by [data contracts](DATA_CONTRACTS.md). | **NO-GO** for universal cross-version G-4. Proposed `test_branch_contract_version_isolation.py`: cold restore, delivery and fork under a newer child version retain ancestor result/identity/signatures, reject sibling leakage and re-adjudication; new child action and explicit compensation use their selected admitted versions. |
| [Take](../src/cognitive_world/items/take.py) and canonical [WorldState](../src/cognitive_world/core/world_state.py) support the audited position/held_by joint transition with unchanged ownership. **Status: partially implemented** for physical relationships; death disposition is **not implemented** by this slice. | **NO-GO:** proposed `test_death_disposition_governance.py`: death, possession, item transfer and compensation cannot bypass governance; failure/uncertain outcomes retain recovery boundaries. Containers/nested possession require their own relationship and joint-transition acceptance; do not infer them from ordinary take. |
| **Status: partially implemented.** Owner-authorized result Observations, [ordinary L1 history qualification](../src/cognitive_world/cognition/l1_history.py) and [qualified consumption](../src/cognitive_world/cognition/runtime.py) keep receipt/evidence separate from world writes. Existing cognition review is narrower than arbitrary beliefs. | **NO-GO** for the unverified combined observer-disagreement scenario. Proposed `test_observer_belief_world_fact_separation.py`: A witnesses B's death, C does not; C's reasonable living-person search decision cannot revive B, fabricate evidence or disclose A's private observation. Test negative feedback through its supported cognitive gate separately from world mutation. |
| Closed [physical types](../src/cognitive_world/core/physical.py), domain codecs and declarative take policy support finite registered semantics. **Status: partially implemented**; not a universal extension protocol. | **NO-GO:** proposed `test_generic_contract_extension.py`: a reusable new capability passes admitted contracts without kernel changes or code/data special cases; unknown types/versions fail closed. Also pressure-test containers and nested possession, conditional discovery/search failure and negative feedback under applicable contracts. A required kernel change fails this gate and returns to review. |

Existing [take regressions](../tests/test_item_take.py) are narrower evidence, not substitutes for these absent tests. Published-checkpoint durability, process-local fences and explicit permitless synchronous-host limitations remain unchanged. No global cross-Runtime/Timeline single-execution guarantee, automatic rollback, durable pending journal or stronger crash recovery follows from this specification. Prior reported test counts remain historical and are not rerun results here.

## Approved acceptance sequence

1. **Governance first:** derive its normative contract from existing Resolution, EventProcessor, Runtime write fence, signed history and governed item-take boundaries; do not mistake reuse for completed conformance.
2. **Immediate death and item-disposition pressure test:** challenge governance with death, possession, item transfer, compensation and observer disagreement without waiting for the other meta-contracts. A witnesses B's death while C does not. C reasonably believes B alive and searches for B as a living person. The belief may influence C's decision but cannot authorize changing B's authoritative state. Test cognition, evidence, causal interpretation and write authority separately.
3. **Physical contract:** pressure-test reusable relationship semantics and joint transitions with containers and nested possession.
4. **Causal contract:** pressure-test conditional candidates, evidence strength, discovery, failed search and negative feedback.

These are approved development and acceptance priorities, not implementation authorization for death, containers, search, general learning, a plugin lifecycle or a universal coordinator. Preserve independent cognitive, perceptual and physical-computation LOD axes and existing Lazy World Expansion acceptance/recovery boundaries. Missing evidence remains unknown, not a fabricated physical result. Module details remain in the linked specifications; update this status matrix only with exact repository evidence and recorded acceptance execution.

Contact: ankorgine@outlook.com
