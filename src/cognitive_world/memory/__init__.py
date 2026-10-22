"""Memory lifecycle compatibility exports.

The single candidate model is ``MemoryProposal``. The supported write path is
``MemoryProposal -> MemoryDecision -> MemoryWriteRequest -> MemoryPersistence
-> MemoryStore``. ``MemoryCandidate`` is a compatibility alias, not a second
candidate representation.
"""

__all__ = [
    "MemoryCandidate",
    "MemoryConsolidator",
    "EventMemoryProposalFactory",
    "MemoryDecision",
    "MemoryDecisionAuthority",
    "MemoryWriteAuthorizationSnapshot",
    "MemoryWriteRequest",
    "MemoryWriteFactory",
    "MemoryWriteRequestFactory",
    "MemoryPersistence",
    "MemoryDecisionInput",
    "MemoryDecisionResult",
    "MemoryPolicyOutput",
    "MemoryDecisionPolicy",
]


def __getattr__(name: str):
    """Load exports lazily to keep cognition/memory compatibility imports acyclic."""
    if name in {
        "MemoryCandidate",
        "MemoryConsolidator",
        "EventMemoryProposalFactory",
    }:
        from cognitive_world.memory.consolidation import (
            MemoryCandidate,
            MemoryConsolidator,
            EventMemoryProposalFactory,
        )

        return {
            "MemoryCandidate": MemoryCandidate,
            "MemoryConsolidator": MemoryConsolidator,
            "EventMemoryProposalFactory": EventMemoryProposalFactory,
        }[name]
    if name in {"MemoryDecision", "MemoryDecisionAuthority"}:
        from cognitive_world.memory.memory_decision import (
            MemoryDecision,
            MemoryDecisionAuthority,
        )

        return {
            "MemoryDecision": MemoryDecision,
            "MemoryDecisionAuthority": MemoryDecisionAuthority,
        }[name]
    if name in {"MemoryWriteAuthorizationSnapshot", "MemoryWriteRequest"}:
        from cognitive_world.memory.memory_write import (
            MemoryWriteAuthorizationSnapshot,
            MemoryWriteRequest,
        )

        return {
            "MemoryWriteAuthorizationSnapshot": MemoryWriteAuthorizationSnapshot,
            "MemoryWriteRequest": MemoryWriteRequest,
        }[name]
    if name in {"MemoryWriteFactory", "MemoryWriteRequestFactory"}:
        from cognitive_world.memory.memory_write_factory import (
            MemoryWriteFactory,
            MemoryWriteRequestFactory,
        )

        return {
            "MemoryWriteFactory": MemoryWriteFactory,
            "MemoryWriteRequestFactory": MemoryWriteRequestFactory,
        }[name]
    if name == "MemoryPersistence":
        from cognitive_world.memory.memory_persistence import MemoryPersistence

        return MemoryPersistence
    if name in {"MemoryDecisionInput", "MemoryDecisionResult", "MemoryPolicyOutput", "MemoryDecisionPolicy"}:
        from cognitive_world.memory.decision_policy import (
            MemoryDecisionInput, MemoryDecisionPolicy, MemoryDecisionResult,
            MemoryPolicyOutput,
        )
        return {
            "MemoryDecisionInput": MemoryDecisionInput,
            "MemoryDecisionResult": MemoryDecisionResult,
            "MemoryPolicyOutput": MemoryPolicyOutput,
            "MemoryDecisionPolicy": MemoryDecisionPolicy,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
