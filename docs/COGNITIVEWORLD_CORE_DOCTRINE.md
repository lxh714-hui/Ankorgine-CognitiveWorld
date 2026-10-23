# CognitiveWorld Core Doctrine

*Authoritative Worlds, Persistent Cognition, Evidence-Governed Learning, and Deterministic Execution*

## Authority and scope

CognitiveWorld is a persistent, multi-agent cognitive world simulation system. Its continuity comes from governed world state, stable identities, causal history and separately owned cognition, not from a language model continuing a story. Language is an interface to this system and a means of proposing interpretations; it is not the system's source of truth.

This doctrine is authoritative for foundational architectural principles. It states why the boundaries exist and what future designs must preserve. It does not replace detailed data contracts, register a new API or approve an observation rule, signing purpose, persistence schema or migration. Concrete permissions, supported transitions and recovery behavior remain governed by the responsible documents below. Apparent conflicts must be recorded and resolved explicitly, not silently reconciled by bypassing a stricter contract.

Three categories must remain distinct throughout:

- **Foundational invariants** constrain present and future implementations. A requirement is not evidence that every necessary mechanism already exists.
- **Existing capabilities** are bounded paths supported by current source and tests, with their stated domain, evidence and recovery limits.
- **Architectural objectives** require further contracts, implementation or validation. In particular, the general recoverable execution-feedback lifecycle is incomplete.

## Principle I — World Authority Is Independent of Model Expression

The world is not whatever an LLM says happened. Canonical `WorldState`, installed and validated causal mechanisms, formally resolved actions and committed Events determine authoritative occurrences and state. `EventHistory` preserves the applicable processed history; an uncommitted candidate Event is not an occurrence.

A generated statement, prediction or narrative description gains no factual authority through repetition, retrieval or inclusion in later prompts. Mentioning an entity does not install it. An agent's confidence does not change the world, and player-authored Worldbook meaning does not independently become a fact, NPC knowledge or an executable rule. Presentation may organize authorized information but cannot create the evidence it presents.

**Architectural consequence:** Runtime world changes must use the existing authorized EventProcessor commit path. Physical action effects require the applicable Resolution before Event creation; legitimate system Events and the separately contracted dialogue path retain their own boundaries. Trusted initialization and verified restoration are restricted entry paths, not general runtime writers. Models, UI and narrative text cannot use any of these paths as a shortcut around authorization, causal validation or state ownership.

Details: [World authority and system structure](COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md), [data authority](DATA_CONTRACTS.md#15-data-authority-rules).

## Principle II — Cognitive Agents Own Distinct Cognitive States

A cognitive agent is not a transcript. Applicable Beliefs, Memory, Goals, SelfModel and other governed cognitive records belong to a particular owner. Observations and relevant experiences have their own source, time and access scope. A world fact, an owner's subjective interpretation and a task's temporary reasoning context are different kinds of information.

The world may contain facts an agent never learned. An utterance proves neither the speaker's Belief nor the truth of its content; a recorded Event does not establish that every participant observed it. False Beliefs, incomplete Memory, deception and disagreement can be legitimate states. They must not be silently replaced by omniscient knowledge in the interest of consistency.

**Architectural consequence:** Context construction, retrieval and revision must preserve owner/Character association, provenance and temporal applicability. Authoritative records stay in their existing canonical Stores; dialogue history is not a replacement Store or identity. Persistence covers only the record families included in the verified save contracts. Ordinary Observations, L1 cursors and task buffers do not become durable merely because an agent's identity persists. On-demand simulation may reduce activity while preserving the important identities, experiences and causal links required by supported continuity contracts.

Details: [Memory authority](MEMORY_DESIGN.md#17-memory-authority), [social evidence and asymmetry](SOCIAL_CAUSAL_DESIGN.md).

## Principle III — Reconstruct the Reasoning Context for Every Action

Each action task must be grounded in a deliberately constructed context derived from current governed cognition and its relevant authorized evidence. Previous generated text is not an automatically authoritative continuation of the agent's mind. Starting a new prompt does not erase Memory; it selects a bounded working representation from the state that actually belongs to the agent.

Relevant authorized Observations, applicable Beliefs and Goals, linked Memory and justified prior conversation may inform this context. Their meanings must remain explicit: conversation can be testimony or an earlier proposal without becoming verified experience. Provenance, freshness, contradictions, ownership and access restrictions must be checked to the extent supported by the governing contracts; missing checks remain a limitation, not an implicit grant. A cached projection may be reused only within its valid scope after applicable revalidation, never solely because it was present in the previous prompt.

**Architectural consequence:** Prompt and decision-context construction are derived, temporary operations. They cannot install entities, copy another owner's private state, promote a model claim into Memory or expose canonical WorldState to an NPC. Consequential selection and commit must revalidate their actual dependencies and original Runtime scope. This principle does not require an LLM call, a fresh full-state scan or a new persistent context service for every action.

Details: [task context and evidence planning](DATA_CONTRACTS.md#task-context-information-gaps-and-exploration-approved-requirements-unified-api-not-implemented), [owner-scoped DecisionContext](../src/cognitive_world/decision/context.py).

## Principle IV — LLMs Propose; Deterministic Mechanisms Enforce Authority

LLMs can contribute open-ended interpretation, hypotheses, deliberation, predictions and candidate actions. Their structured output is still untrusted proposed information. Correctly interpreting an intention does not authorize its execution; a syntactically valid response does not establish an entity, mechanism, precondition or successful outcome.

Engine-side checks must enforce supported schemas, current identity and permissions, Safety, applicable preconditions and mechanisms, valid Resolution evidence, original Runtime write permits and the final commit boundary. Safety, WorldNorms, AgentDecision, Resolution and Presentation retain distinct responsibilities. World law is not an automatic causal rejection, and physical feasibility does not override Safety or access restrictions.

Unsupported interpretation, absent evidence, a budget limit, an unavailable mechanism and verified impossibility are different dispositions. The system must preserve uncertainty, clarify, defer or reject according to its existing contracts; it must not substitute a favorable guess or fabricate a failed Event simply because rule lookup was inconclusive.

**Architectural consequence:** Semantic intelligence and authoritative execution cooperate across a strict boundary. CPU execution is not intrinsically correct: reliability depends on explicit rules, validated evidence and properly enforced transitions. Deterministic enforcement does not claim a universal physics solver, exhaustive causal knowledge or platform-independent determinism for every future model. Open language must remain possible without granting open-ended state-write authority.

Details: [AI boundary](AI_BOUNDARY.md), [engineering requirements](ENGINEERING_RULES.md).

## Principle V — Cognitive Revision Requires Evidence and Governance

Action expectation, actual outcome, actor-available evidence and cognitive revision are separate stages. A formal Event establishes only what its contract and processing evidence support. It does not prove that a particular NPC observed, consumed or understood the result. An authorized Observation is not proven consumption; a consumption proof is not proof that an interpretation is true.

New cognitive learning must obey the relevant owner, authorization, consumption-proof and governance requirements. Comparison must distinguish an expected result from an actual result, a fact from a Belief, insufficient support from contradiction, a proposed update from an accepted revision, and an accepted in-memory record from a published and verified checkpoint. A behavior-score adjustment is not a Belief or Memory revision.

A single failed attempt must not invalidate a general causal Belief. Review must identify the particular expectation, method, precondition or existing cognitive record justified by the evidence. It may defer or reject a revision; learning is not guaranteed merely because an action finished. Eligible Belief and Memory writes must use their existing independent governance and persistence paths.

**Architectural consequence:** The objective is an evidence-governed lifecycle connecting bounded action expectations, authoritative results, actor-authorized evidence, verified consumption where required, and governed feedback. Its processing must be idempotent, compatible with current Runtime fencing, recoverable under its approved signed contracts and isolated across timelines. Committed actions must not be replayed to repair feedback. A restore cannot synthesize missing historical Observations or proofs. This objective remains incomplete; it does not itself approve new record types or expand proof coverage.

Existing locked-door `BehaviorFeedback` separately preserves a bounded decision penalty using a committed failure and its cited condition evidence. Its signed snapshot is not a general expectation-result journal or proof that the actor consumed the execution result. That supported path remains independent until a reviewed replacement or integration contract says otherwise.

Details: [feedback contract](DATA_CONTRACTS.md#behavior-feedback-v03b-signed-snapshot-component), [consumption-proof scope](DATA_CONTRACTS.md#consumption-proof-separation), [Memory feedback governance](MEMORY_DESIGN.md#cognitive-feedback-and-evidence-provenance-architectural-direction).

## Principle VI — Computational Effort Must Follow Cognitive Need

CognitiveWorld is a multi-layer hybrid system. Decisions do not all require the same model, context size, reasoning depth or cost. Sufficiently specified supported operations should use deterministic mechanisms; optional LLM work should add value where open-ended interpretation, deliberation or hypothesis generation is needed. Structured cognition and authorized retrieval connect these approaches.

Allocation should reflect significance, uncertainty, risk, complexity, information gaps, narrative relevance and potential causal impact within available budgets. Physical evaluation, semantic interpretation, Memory retrieval, social reasoning and narrative generation retain their own responsibilities. A contradiction can justify local review, but more computation need not eliminate genuine ignorance, deception or differing Beliefs.

The spatial LOD direction uses distance, angular relevance and importance as allocation cues, alongside task requirements, causal coupling and uncertainty. These cues are not the independent cognitive, perceptual and physical-computation LOD axes, nor the three spatial responsibility layers: canonical world representation, derived subject-centered projection and adaptive scheduling. A projection changes the viewpoint, not the entity's canonical location. No cue grants access to hidden information.

**Architectural consequence:** More reasoning is not automatically better reasoning. Increase precision locally when warranted and permit bounded expansion along relevant dependencies; preserve unresolved status when the budget cannot support a consequential conclusion. Lower fidelity must not erase required identity, committed history or causal constraints. Allocation never changes fact truth, authorizes a new observation or replaces Resolution. A unified cross-domain allocator, calibrated spatial scheduling formula and general precision-upgrade coordinator are objectives, not existing capabilities.

Details: [hybrid cognition](ARCHITECTURE.md#hybrid-cognition-execution-levels-architectural-direction-unified-policy-not-implemented), [independent LOD and spatial design](ARCHITECTURE.md#hybrid-physical-engine-and-independent-lod-axes-approved-design-not-implemented).

## Unified cognitive lifecycle

The following sequence is a conceptual responsibility model, not a claim that one complete service executes every step today:

1. **Read valid state in separate authority scopes.** The engine may read canonical WorldState through its existing capabilities. The actor's context draws on its own governed cognition; an engine read does not grant the actor omniscience.
2. **Construct the current action context.** Gather relevant owner-authorized evidence and appropriately classified Beliefs, Goals, Memory and conversation. Preserve sources, temporal meaning, uncertainty and unmet information needs.
3. **Form a candidate expectation and action.** Use deterministic cognition and, where justified, an LLM for interpretation or deliberation. A prediction remains subjective; an unselected candidate is not an Attempt.
4. **Validate the selected proposal.** Apply existing identity, Safety, authorization, method, precondition, mechanism and Runtime checks. An `ActionProposal`, submitted `Attempt` and confirmed `ResolutionResult` retain separate meanings.
5. **Resolve and commit eligible effects.** An issued physical Resolution may produce an Event; only successful authoritative processing establishes the occurrence and applies any WorldUpdate. Unresolved or rejected work does not acquire a fictional result.
6. **Produce eligible actor-authorized observations.** Use the applicable source evidence and visibility contract. A result may be committed without providing a particular actor any result Observation.
7. **Establish actual consumption and required proof.** The actor consumes evidence through L1. Where a later update requires recoverable proof, only an approved issuer/rule and verified signed record can establish it. Proof absence remains absence.
8. **Review and persist eligible feedback.** Compare only the justified specific expectation or cognitive target. Governance may accept, defer or reject. Apply approved revisions idempotently through the existing Store, fence and persistence boundaries; preserve explicit recovery-required failure handling where applicable.
9. **Reconstruct the next action context.** Use the resulting valid world and owner-scoped cognition, with current authorization and Runtime generation, rather than treating the previous generated narrative as the next state.

Not every action invokes a model, every result changes WorldState, every Observation updates Memory, or every comparison changes a Belief. Read-only requests, dialogue, system Events and non-fact presentation keep their existing specialized paths. Initial setup and restoration are not ordinary action execution.

## Current foundations and uncompleted objectives

| Existing bounded foundation | Evidence and remaining boundary |
|---|---|
| Immutable owner-checked decision context, normal AgentTurn preparation and linked Memory retrieval | [Decision context tests](../tests/test_decision_context_pipeline.py), [AgentTurn tests](../tests/test_agent_turn.py). These do not establish a universal context-sufficiency planner or automatic long-term learning. |
| Typed door and known-passage adjudication, source-bound Events and authorization checks | [Causal Resolution tests](../tests/test_causal_resolution.py), [architecture](ARCHITECTURE.md). Unsupported mechanisms remain unresolved; general physical simulation is absent. |
| Confirmed locked-door failure penalties and separately signed feedback restoration | [Behavior feedback tests](../tests/test_behavior_feedback.py), [save/restore tests](../tests/test_save_restore_end_to_end.py). This is bounded adaptation, not general Belief revision. |
| Governed Memory decisions and narrowly registered L1 proof families | [Memory decision tests](../tests/test_memory_decision_policy.py), [proof persistence tests](../tests/test_l1_consumption_persistence.py), [proof contract](DATA_CONTRACTS.md#consumption-proof-separation). Supported proof coverage does not extend to arbitrary result facts. |
| Runtime generation fencing, verified save/restore and branch isolation for supported records | [write-fence tests](../tests/test_runtime_write_fence.py), [save/restore tests](../tests/test_save_restore_end_to_end.py). A snapshot does not restore excluded tasks, reasoning buffers or arbitrary proof capabilities. |

These references identify existing implementation/test coverage, not a new test run or complete product acceptance. The general recoverable execution-feedback lifecycle, durable expectation/result/feedback associations, general social attribution, universal physical simulation and unified cross-domain LOD coordination remain objectives. Where the detailed architecture explicitly labels a design approved, that status is retained; this doctrine neither withdraws it nor claims it is implemented. Other directions still require review.

In particular, the default historical nonverbal consumption rule covers the documented room-light case, not general door-result feedback. New observation rules, proof policies, owner-scoped system records and snapshot migrations require their explicit contracts before implementation. The doctrine does not close those gaps or turn transient expectations into persistent cognition.

## Prohibited architectural shortcuts

- Treating generated prose, predictions, Worldbook descriptions or rendered UI as authoritative world facts.
- Carrying generated text forward unconditionally as trusted Memory, identity or evidence.
- Injecting hidden world facts or another owner's cognition into an actor's context without the existing authorization path.
- Letting model output bypass applicable action authorization, Resolution or EventProcessor commitment.
- Treating Event existence, an utterance or issued Observation as proof of an actor's knowledge, consumption or Belief.
- Treating one failed action as automatic refutation of a general Belief.
- Persisting cognition without the applicable evidence, governance and verified record contract.
- Replaying a committed action to repair missing feedback, delivery or proof.
- Letting an obsolete Runtime task acquire a new permit to commit its old result.
- Leaking branch-specific evidence or cognition into a parent, sibling or unrelated timeline outside validated ancestry rules.
- Treating a future proposal, unregistered mechanism or higher LOD request as an implemented capability or expanded permission.

These prohibitions constrain design and review. They do not install new behavior or expand existing source-level guarantees.

## Relationship to the documentation set

| Document | Continuing responsibility |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System structure, module responsibilities and authoritative execution/persistence boundaries. |
| [AI_BOUNDARY.md](AI_BOUNDARY.md) | Model responsibilities, permitted inputs/outputs and model authority restrictions. |
| [DATA_CONTRACTS.md](DATA_CONTRACTS.md) | Normative record schemas, validation, supported lifecycle and signing/restore contracts. |
| [MEMORY_DESIGN.md](MEMORY_DESIGN.md) | Memory and related Belief/evidence boundaries, provenance, governance and durable cognition. |
| [SOCIAL_CAUSAL_DESIGN.md](SOCIAL_CAUSAL_DESIGN.md) | Social information, attribution, asymmetric knowledge and causal design scope. |
| [COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md](COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md) | Integrated map of cognition, spatial representation, physical mechanisms, LOD, world packages and product boundaries. |
| [ENGINEERING_RULES.md](ENGINEERING_RULES.md) | Implementation, compatibility, testing and repository engineering constraints. |
| [REPOSITORY_STATUS.md](REPOSITORY_STATUS.md) | Recorded implementation and verification status with its evidence limits. |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Planned work and dependencies; the historical compact roadmap is not a competing authority. |

Future contracts must state which principle they enforce, what evidence authorizes each transition, what remains unknown, and how supported records survive or deliberately do not survive restore. Doctrine establishes the constraints; detailed contracts establish the executable permission and evidence scope.
