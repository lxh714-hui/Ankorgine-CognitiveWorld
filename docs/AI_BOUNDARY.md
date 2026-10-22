# CognitiveWorld AI Boundary

Version: 1.0

---

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
