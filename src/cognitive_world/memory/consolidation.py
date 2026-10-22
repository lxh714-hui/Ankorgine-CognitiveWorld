"""Compatibility producer for the canonical cognition MemoryProposal model."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.core.event import Event


# Compatibility name only: there is one candidate model in the runtime.
MemoryCandidate = MemoryProposal


@dataclass
class EventMemoryProposalFactory:
    """Create a MemoryProposal from an Event and explicit owner context."""

    def propose(self, event: Event, context: Mapping[str, Any]) -> MemoryProposal:
        """Create the canonical proposal from an Event and explicit context."""
        if not isinstance(event, Event):
            raise TypeError("event must be a confirmed Event")
        if not isinstance(context, Mapping):
            raise TypeError("context must be a mapping")

        owner_id = context.get("owner_id")
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("context must contain a non-empty owner_id")

        return MemoryProposal(
            id=f"memory-proposal:{owner_id}:{event.id}",
            source_event_id=event.id,
            owner_id=owner_id,
            memory_type=context.get("memory_type", "experience"),
            content=deepcopy(context.get("content", event.changes)),
            importance=context.get("importance", 0.0),
            metadata=deepcopy(context.get("metadata", {})),
            confidence=context.get("confidence", 0.0),
        )


# Deprecated compatibility alias; Event-to-Proposal is the canonical role.
MemoryConsolidator = EventMemoryProposalFactory
