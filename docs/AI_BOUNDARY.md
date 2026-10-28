# CognitiveWorld AI Boundary

## B3 predictions remain subjective

The [B3 records](DATA_CONTRACTS.md#b3-immutable-expectation-and-authoritative-result-association)
certify pre-execution capture and a verified formal-result association, not the
truth of the original prediction. Free text is not compiled into physics;
players without explicit predictions remain `expectation_absent`. No extra
model inference, knowledge grant or automatic cognitive revision is introduced.
The [source binding](DATA_CONTRACTS.md#trusted-action-expectation-source-binding-v1)
is issued by the trusted NPC selection/player entry, with distinct closed
payloads. Its ID and digest are bound into the final Attempt. Issuance and
restore validate claims against it; signatures alone or mutable origin flags
cannot turn a captured prediction into absence.
Only the actual source selection can supply a decision tick; later Event times
cannot substitute. The engine, not model prose, owns association verification.


Version: 1.0

The [CognitiveWorld Core Doctrine](COGNITIVEWORLD_CORE_DOCTRINE.md) supplies the foundational model/world distinction and the requirements for task-scoped context, deterministic enforcement, governed learning and computational allocation. This document specifies the AI-facing boundary; a temporary prompt or model-generated expectation cannot replace canonical cognition, authorize an outcome or expand the existing proof/persistence contracts.

---

## B2 consumption evidence is engine authority

The [B2 instance proof](DATA_CONTRACTS.md#b2-durable-l1-identity-and-instance-bound-proof)
is issued only after Runtime-controlled L1 acceptance of the original owner's
B1 result. Models, prompts, retrieval, UI delivery and caller-supplied identities
cannot assert consumption or its time. The engine fixes the original tick and
Timeline; retries do not refresh either. Ambiguous restored history rejects,
and post-L1 proof failure freezes the Runtime. A valid proof is technical
consumption evidence, not evidence of understanding, belief or learning.

# 1. Purpose

This document defines the responsibility boundaries of AI components in CognitiveWorld.

The purpose is to ensure:

- AI assists understanding;
- AI assists reasoning;
- AI does not become the authority of the world.

The World Core remains the only authority that changes reality.

---

# 2. Core Principle

## AI Understands, World Decides

AI modules may:

- understand player language;
- infer intentions;
- generate proposals;
- organize memories.

AI modules may NOT:

- directly modify World State;
- create confirmed facts;
- bypass Event validation;
- directly write permanent memory.

The required flow:

```text
AI
  ↓
Proposal
  ↓
Validation
  ↓
Event
  ↓
World State Update
  ↓
Memory
```

---

# 3. AI Component Overview

CognitiveWorld contains several AI-assisted components:

```text
Cognitive AI
Memory AI
Narrative AI (Future Extension)
```

Each component has independent responsibilities.

---

# 4. Cognitive AI

## 4.0 Hybrid cognition allocation (architectural direction)

The [system architecture](ARCHITECTURE.md#hybrid-cognition-execution-levels-architectural-direction-unified-policy-not-implemented) distinguishes deterministic fast paths, structured owner-scoped cognition, and optional LLM-assisted high-level reasoning. These are compute choices across the existing five cognitive functions, not new Stores or a requirement to call an LLM for every Agent turn. Known facts and installed rules should use deterministic processing where sufficient; uncertainty, complexity, importance or causal impact may justify bounded higher-cost proposals. There is no implemented unified policy that selects among these levels.

An LLM may suggest an interpretation, hypothesis, plan, expected outcome or social reading only from the recipient's authorized context. Its structured output must be validated against current identity, evidence, capability and Runtime bindings before use. It cannot turn a mentioned entity into an installed one, authorize a target, decide a social recipient's Belief, assert an actual outcome, or grant itself more observation detail. The exact feedback and Memory write boundaries remain in [MEMORY_DESIGN.md](MEMORY_DESIGN.md#cognitive-feedback-and-evidence-provenance-architectural-direction).

## 4.1 Responsibility

Cognitive AI interprets player input.

Its purpose:

> Understand what the player wants to do.

It does not decide what happens.

## 4.2 Input

Cognitive AI receives:

```text
Player Message
  + Current Context
  + Relevant Short-term Memory
  + Visible World Information
```

Example:

```text
"I slowly approach the guard and try to convince him."
```

## 4.3 Output

Cognitive AI produces:

```text
Intent Proposal
Attempt Proposal
```

Example:

```json
{
  "intent": {
    "goal": "enter_area"
  },
  "attempt": {
    "method": "persuasion",
    "target": "guard"
  }
}
```

## 4.4 Restrictions

Cognitive AI cannot:

- execute actions;
- decide success;
- modify relationships;
- create events;
- write memories.

---

# 5. Intent Understanding

Intent represents the player's desired objective.

Example:

```text
Goal: Enter castle
```

Intent does not contain:

- guaranteed result;
- success probability;
- world reaction.

Intent only describes purpose.

---

# 6. Attempt Understanding

Attempt represents the player's chosen approach.

Example intent:

```text
Enter castle
```

Different attempts:

```text
Persuade guard
Climb wall
Steal key
```

Each attempt must be evaluated independently.

---

# 7. Resolution Boundary

AI may assist with interpretation. However, AI does NOT decide reality.

The final process:

```text
Intent
  ↓
Attempt
  ↓
World Rules
  ↓
Resolution Engine
  ↓
Event
  ↓
World Update
```

The Resolution Engine determines:

- possibility;
- consequences;
- state changes.

---

# 8. Memory AI

## 8.1 Responsibility

Memory AI manages memory consolidation.

Its purpose is to decide how confirmed experiences should be stored.

## 8.2 Input

Memory AI receives:

```text
Confirmed Events
  + Existing Memory
```

## 8.3 Output

Memory AI produces a Memory Proposal.

Example:

```json
{
  "type": "relationship_memory",
  "subject": "npc",
  "change": {
    "trust": "+10"
  }
}
```

## 8.4 Restrictions

Memory AI cannot:

- invent events;
- assume facts;
- modify historical records;
- override World Core.

Only confirmed events can become long-term memory.

---

# 9. Narrative AI (Future Extension)

Narrative AI is an optional future component.

Its responsibility is to analyze:

- conflicts;
- opportunities;
- potential developments.

It does not:

- force story progression;
- create unavoidable events;
- override player actions.

---

# 10. AI Communication Rules

AI components communicate through defined protocols.

Forbidden:

```text
AI A
  ↓
Directly modifies
  ↓
AI B State
```

Required:

```text
AI
  ↓
Proposal
  ↓
Validator
  ↓
System Processing
```

---

# 11. Hallucination Prevention

AI output is considered a suggestion, not a fact.

Example:

```text
AI says: "The NPC probably dislikes the player."
```

This is NOT stored.

The system must verify actual Relationship State and Confirmed Events before creating any change.

---

# 12. Human-like Behavior Principle

AI helps simulate:

- understanding;
- interpretation;
- communication.

The system maintains:

- consistency;
- causality;
- persistence.

AI provides intelligence. The World Core provides reality.

---

# Final Rule

> AI may interpret the world, but it does not own the world.

> AI may propose possibilities, but only the system can create reality.

Contact: ankorgine@outlook.com
