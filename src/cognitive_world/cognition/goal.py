"""Goal data model and owner-isolated storage for the cognition layer."""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal
from cognitive_world.cognition.proposal_origin import original_proposal_permit
from cognitive_world.runtime.write_fence import RuntimeWriteFence


GoalStatus = Literal["active", "completed", "failed", "abandoned"]


@dataclass(frozen=True)
class GoalResourceDemand:
    """A structured resource requirement explicitly attached to a canonical Goal.

    Free-text Goal descriptions are intentionally not interpreted as resource
    claims. ``scope_ref`` is a caller-defined shared-use window; an exclusive
    conflict is supported only when two active Goals name the same grounded
    object, the same non-empty scope, and both explicitly require exclusive use.
    """

    resource_ref: str
    scope_ref: str | None = None
    exclusive_use: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.resource_ref, str) or not self.resource_ref.startswith("object:"):
            raise ValueError("resource_ref must use the object:{id} namespace")
        identifier = self.resource_ref.removeprefix("object:")
        if not identifier or len(identifier) > 1024:
            raise ValueError("resource_ref must contain a bounded object ID")
        if self.scope_ref is not None and (
            not isinstance(self.scope_ref, str) or not self.scope_ref or len(self.scope_ref) > 256
        ):
            raise ValueError("scope_ref must be a bounded non-empty value or None")
        if type(self.exclusive_use) is not bool:
            raise TypeError("exclusive_use must be a bool")


@dataclass(init=False)
class Goal:
    """Represent an objective currently held by an Agent."""

    goal_id: str
    owner_id: str
    description: str
    priority: float
    status: GoalStatus
    source_refs: list[str]
    metadata: dict[str, Any]
    resource_demands: tuple[GoalResourceDemand, ...]

    def __init__(
        self,
        goal_id: str | None = None,
        owner_id: str = "",
        description: str = "",
        priority: float = 0.0,
        status: GoalStatus = "active",
        source_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        resource_demands: tuple[GoalResourceDemand, ...] = (),
    ) -> None:
        """Initialize a Goal, accepting the former ``id`` field as an alias."""
        self.goal_id = goal_id if goal_id is not None else (id or "")
        self.owner_id = owner_id
        self.description = description
        self.priority = priority
        self.status = status
        self.source_refs = deepcopy(source_refs if source_refs is not None else [])
        self.metadata = deepcopy(metadata if metadata is not None else {})
        if not isinstance(resource_demands, tuple) or any(
            not isinstance(item, GoalResourceDemand) for item in resource_demands
        ):
            raise TypeError("resource_demands must be a tuple of GoalResourceDemand")
        if len(set(resource_demands)) != len(resource_demands):
            raise ValueError("duplicate Goal resource demands are not allowed")
        self.resource_demands = tuple(resource_demands)

    @property
    def id(self) -> str:
        """Compatibility alias used by existing cognition references."""
        return self.goal_id


@dataclass
class GoalStore:
    """Store isolated Goal records grouped by their owning Agent."""

    _goals: dict[str, dict[str, Goal]] = field(default_factory=dict, repr=False)
    write_fence: RuntimeWriteFence | None = field(default=None, repr=False, compare=False)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("GoalStore is already bound to another runtime fence")
        self.write_fence = fence

    def add(self, goal: Goal) -> None:
        """Register an initial Goal; existing records require validated updates."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            self._add(goal)

    def _add(self, goal: Goal) -> None:
        if not isinstance(goal, Goal):
            raise TypeError("goal must be a Goal")
        owner_goals = self._goals.setdefault(goal.owner_id, {})
        if goal.goal_id in owner_goals:
            raise ValueError("Goal already exists; use a validated update")
        owner_goals[goal.goal_id] = deepcopy(goal)

    def get(self, owner_id: str) -> tuple[Goal, ...]:
        """Return isolated copies of all Goals owned by the requested Agent."""
        return tuple(deepcopy(tuple(self._goals.get(owner_id, {}).values())))

    def get_by_id(self, goal_id: str) -> Goal | None:
        """Compatibility lookup for an ID held by exactly one owner.

        Agent-scoped callers must use get_owned; a shared ID is ambiguous.
        """
        found = None
        for owned_goals in self._goals.values():
            goal = owned_goals.get(goal_id)
            if goal is not None:
                if found is not None:
                    raise ValueError("Goal ID is shared by multiple owners; specify owner_id")
                found = goal
        return deepcopy(found) if found is not None else None

    def get_owned(self, owner_id: str, goal_id: str) -> Goal | None:
        """Return an isolated Goal copy by owner and identifier."""
        goal = self._goals.get(owner_id, {}).get(goal_id)
        return deepcopy(goal) if goal is not None else None

    def get_all(self) -> tuple[Goal, ...]:
        """Return isolated copies of every Goal in insertion order."""
        return tuple(
            deepcopy(
                tuple(
                    goal
                    for owned_goals in self._goals.values()
                    for goal in owned_goals.values()
                )
            )
        )

    def create(self, goal: Goal, *, proposal: Any, validation_result: Any) -> None:
        """Commit only the exact evidence-authorized new Goal, without replacing an old one."""
        from cognitive_world.cognition.goal_creation import GoalCreationProposal
        from cognitive_world.cognition.validation import ValidationResult
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            if self.write_fence is not None:
                self.write_fence.require_candidate_origin(original_proposal_permit(proposal))
            if (type(proposal) is not GoalCreationProposal
                    or type(validation_result) is not ValidationResult
                    or not validation_result.authorizes(proposal)):
                raise PermissionError("Goal creation requires matching governance")
            expected = Goal(proposal.goal_id, proposal.owner_id, proposal.description,
                            proposal.priority, "active", proposal.source_refs, proposal.metadata)
            if type(goal) is not Goal or goal != expected:
                raise PermissionError("new Goal differs from its authorized proposal")
            prior = self.get_owned(goal.owner_id, goal.goal_id)
            if prior is not None:
                if prior != goal:
                    raise PermissionError("conflicting Goal identity")
                return
            self._add(goal)

    def update(
        self,
        goal: Goal,
        *,
        proposal: Any = None,
        validation_result: Any = None,
    ) -> None:
        """Apply only a Goal snapshot authorized by its validated proposal."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            if self.write_fence is not None:
                self.write_fence.require_candidate_origin(
                    original_proposal_permit(proposal)
                )
            self._update(goal, proposal=proposal, validation_result=validation_result)

    def _update(self, goal: Goal, *, proposal: Any, validation_result: Any) -> None:
        from cognitive_world.cognition.goal_update import GoalUpdateProposal
        from cognitive_world.cognition.validation import ValidationResult

        if not isinstance(goal, Goal):
            raise TypeError("goal must be a Goal")
        if (
            not isinstance(proposal, GoalUpdateProposal)
            or not isinstance(validation_result, ValidationResult)
            or not validation_result.authorizes(proposal)
        ):
            raise PermissionError("Goal updates require a matching accepted validation")
        current = self._goals.get(proposal.owner_id, {}).get(proposal.goal_id)
        expected_metadata = {} if current is None else deepcopy(current.metadata)
        expected_metadata.update(deepcopy(proposal.metadata))
        if (
            proposal.owner_id != goal.owner_id
            or proposal.goal_id != goal.goal_id
            or current is None
            or current.status != proposal.change.previous_state
            or current.priority != proposal.change.previous_priority
            or proposal.change.proposed_state != goal.status
            or proposal.change.proposed_priority != goal.priority
            or proposal.source_refs != goal.source_refs
            or current is None
            or current.description != goal.description
            or current.resource_demands != goal.resource_demands
            or expected_metadata != goal.metadata
        ):
            raise ValueError("Goal does not match its validated proposal")
        from cognitive_world.cognition.goal_completion import COMPLETION_KEY
        if current.metadata.get(COMPLETION_KEY) != goal.metadata.get(COMPLETION_KEY):
            raise ValueError("status/priority updates cannot change the Goal completion condition")
        self._goals.setdefault(goal.owner_id, {})[goal.goal_id] = deepcopy(goal)
