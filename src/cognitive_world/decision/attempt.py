"""Attempt data model for the decision layer."""

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any


@dataclass(init=False)
class Attempt:
    """Represent an action request submitted for world-rule validation."""

    attempt_id: str
    agent_id: str
    action_proposal_id: str
    action_type: str
    _target_refs: list[str] = field(repr=False)
    _parameters: dict[str, Any] = field(repr=False)
    _metadata: dict[str, Any] = field(repr=False)
    _legacy_intent_id: str | None = field(default=None, repr=False, compare=False)
    _initiator_id: str | None = field(default=None, repr=False, compare=False)
    _frozen: bool = field(default=False, init=False, repr=False, compare=False)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Attempt snapshots are immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        attempt_id: str | None = None,
        agent_id: str | None = None,
        action_proposal_id: str | None = None,
        action_type: str | None = None,
        target_refs: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        actor: str | None = None,
        intent_id: str | None = None,
        action: str | None = None,
        target: str | None = None,
        initiator_id: str | None = None,
    ) -> None:
        """Initialize an Attempt, accepting the former field names for compatibility."""
        self.attempt_id = attempt_id if attempt_id is not None else (id or "")
        self.agent_id = agent_id if agent_id is not None else (actor or "")
        self.action_proposal_id = action_proposal_id or ""
        self.action_type = action_type if action_type is not None else (action or "")
        if target_refs is None:
            target_refs = [] if target is None else [target]
        self._target_refs = deepcopy(target_refs)
        self._parameters = deepcopy(parameters if parameters is not None else {})
        self._metadata = deepcopy(metadata if metadata is not None else {})
        self._legacy_intent_id = intent_id
        if initiator_id is not None and (not isinstance(initiator_id, str) or not initiator_id):
            raise ValueError("initiator_id must be non-empty when provided")
        self._initiator_id = initiator_id
        self._frozen = True

    def __deepcopy__(self, memo: dict[int, object]) -> "Attempt":
        copied = Attempt(
            attempt_id=deepcopy(self.attempt_id, memo),
            agent_id=deepcopy(self.agent_id, memo),
            action_proposal_id=deepcopy(self.action_proposal_id, memo),
            action_type=deepcopy(self.action_type, memo),
            target_refs=deepcopy(self._target_refs, memo),
            parameters=deepcopy(self._parameters, memo),
            metadata=deepcopy(self._metadata, memo),
            intent_id=deepcopy(self._legacy_intent_id, memo),
            initiator_id=deepcopy(self._initiator_id, memo),
        )
        memo[id(self)] = copied
        return copied

    @property
    def target_refs(self) -> list[str]:
        return deepcopy(self._target_refs)

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(self._parameters)

    @property
    def metadata(self) -> dict[str, Any]:
        return deepcopy(self._metadata)

    @property
    def id(self) -> str:
        """Compatibility alias for the Attempt identifier."""
        return self.attempt_id

    @property
    def actor(self) -> str:
        """Compatibility alias for the Agent identifier."""
        return self.agent_id

    @property
    def intent_id(self) -> str | None:
        """Former optional Intent reference retained for existing callers."""
        return self._legacy_intent_id

    @property
    def initiator_id(self) -> str | None:
        """Identify the original requester separately from the acting Agent."""
        return self._initiator_id

    @property
    def action(self) -> str:
        """Compatibility alias for the action type."""
        return self.action_type

    @property
    def target(self) -> str | None:
        """Compatibility view of the first target reference, if any."""
        return self._target_refs[0] if self._target_refs else None

    def _resolution_snapshot(self) -> tuple[object, ...]:
        """Return an isolated content snapshot for Resolution provenance binding."""
        return (
            self.attempt_id,
            self.agent_id,
            self.action_proposal_id,
            self.action_type,
            deepcopy(self._target_refs),
            deepcopy(self._parameters),
            deepcopy(self._metadata),
            self._legacy_intent_id,
            self._initiator_id,
        )

    @staticmethod
    def fingerprint_snapshot(snapshot: tuple[object, ...]) -> str:
        """Return a stable digest for the JSON-like ActionInterpreter contract."""
        try:
            encoded = json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Attempt snapshot is not canonically serializable") from exc
        return sha256(encoded).hexdigest()

    def content_fingerprint(self) -> str:
        return self.fingerprint_snapshot(self._resolution_snapshot())
