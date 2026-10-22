"""Non-mutating proposals for caller-supplied Goal updates."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.cognition.goal import Goal, GoalStatus
from cognitive_world.cognition.proposal_origin import ProposalOriginMarker, bind_proposal_origin
from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


@dataclass
class GoalChange:
    """Describe a traceable proposed state and priority change for a Goal."""

    operation: str
    previous_state: GoalStatus
    proposed_state: GoalStatus
    previous_priority: float
    proposed_priority: float
    reason: str
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.evidence_refs = deepcopy(self.evidence_refs)


@dataclass
class GoalUpdateProposal:
    """Describe a proposed Goal update without applying it."""

    owner_id: str
    goal_id: str
    change: GoalChange
    source_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    runtime_write_permit: RuntimeWritePermit | None = field(
        default=None, repr=False, compare=False
    )
    _origin_marker: ProposalOriginMarker = field(
        default_factory=ProposalOriginMarker, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.runtime_write_permit is None:
            self.runtime_write_permit = RuntimeWriteFence.bind_current_permit()
        self.change = deepcopy(self.change)
        self.source_refs = deepcopy(self.source_refs)
        self.metadata = deepcopy(self.metadata)
        bind_proposal_origin(self)


@dataclass
class GoalUpdater:
    """Build a proposal from a Goal and explicit caller-supplied values."""

    def propose_update(
        self, goal: Goal, cognition_context: Any
    ) -> GoalUpdateProposal:
        """Return a detached proposal without changing the Goal or its Store.

        A mapping may explicitly provide ``new_state``, ``new_priority``,
        ``operation``, ``reason``, ``evidence_refs``, ``source_refs``, and
        ``metadata``. Missing values retain the current Goal snapshot; this
        boundary performs no inference.
        """
        if not isinstance(goal, Goal):
            raise TypeError("goal must be a Goal")

        supplied = cognition_context if isinstance(cognition_context, Mapping) else {}
        source_refs = deepcopy(supplied.get("source_refs", goal.source_refs))
        change = GoalChange(
            operation=supplied.get("operation", "update"),
            previous_state=goal.status,
            proposed_state=supplied.get("new_state", goal.status),
            previous_priority=goal.priority,
            proposed_priority=supplied.get("new_priority", goal.priority),
            reason=supplied.get("reason", "proposed from cognition context"),
            evidence_refs=deepcopy(supplied.get("evidence_refs", source_refs)),
        )
        return GoalUpdateProposal(
            owner_id=goal.owner_id,
            goal_id=goal.goal_id,
            change=change,
            source_refs=source_refs,
            metadata=deepcopy(supplied.get("metadata", {})),
        )
