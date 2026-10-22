"""Action proposal data model for the decision layer."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


@dataclass(init=False)
class ActionProposal:
    """Represent a candidate action without executing or resolving it."""

    proposal_id: str
    agent_id: str
    action_type: str
    _target_refs: list[str] = field(repr=False)
    _parameters: dict[str, Any] = field(repr=False)
    _reasoning_refs: list[str] = field(repr=False)
    _metadata: dict[str, Any] = field(repr=False)
    _runtime_write_permit: RuntimeWritePermit | None = field(
        default=None, repr=False, compare=False, init=False
    )

    def __init__(
        self,
        proposal_id: str,
        agent_id: str,
        action_type: str,
        target_refs: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        reasoning_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.proposal_id = proposal_id
        self.agent_id = agent_id
        self.action_type = action_type
        self._target_refs = deepcopy(target_refs if target_refs is not None else [])
        self._parameters = deepcopy(parameters if parameters is not None else {})
        self._reasoning_refs = deepcopy(
            reasoning_refs if reasoning_refs is not None else []
        )
        self._metadata = deepcopy(metadata if metadata is not None else {})
        self._runtime_write_permit = RuntimeWriteFence.bind_current_permit()

    @property
    def runtime_write_permit(self) -> RuntimeWritePermit | None:
        """Originating operation capability; excluded from user-facing data."""
        return self._runtime_write_permit

    @property
    def target_refs(self) -> list[str]:
        return deepcopy(self._target_refs)

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(self._parameters)

    @property
    def reasoning_refs(self) -> list[str]:
        return deepcopy(self._reasoning_refs)

    @property
    def metadata(self) -> dict[str, Any]:
        return deepcopy(self._metadata)
