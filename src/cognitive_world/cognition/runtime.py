"""Orchestration for assembling an Agent's current cognition state."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Sequence

from cognitive_world.cognition.belief import Belief, BeliefStore
from cognitive_world.cognition.goal import Goal, GoalStore
from cognitive_world.cognition.perception import Percept, PerceptionProcessor
from cognitive_world.cognition.self_model import SelfModel, SelfModelStore
from cognitive_world.cognition.working_memory import WorkingMemory, WorkingMemoryStore
from cognitive_world.observation.observation import Observation


@dataclass
class CognitionState:
    """A snapshot of cognition references prepared for decision input."""

    agent_id: str
    percept_ids: list[str] = field(default_factory=list)
    belief_ids: list[str] = field(default_factory=list)
    goal_ids: list[str] = field(default_factory=list)
    focus: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    percepts: list[Percept] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.percept_ids = deepcopy(self.percept_ids)
        self.belief_ids = deepcopy(self.belief_ids)
        self.goal_ids = deepcopy(self.goal_ids)
        self.focus = deepcopy(self.focus)
        self.metadata = deepcopy(self.metadata)
        self.percepts = deepcopy(self.percepts)


@dataclass(frozen=True)
class _L1ConsumptionReceipt:
    """Runtime-local proof that one intact Observation passed L1."""

    owner_id: str
    observation_id: str
    source_event_id: str
    percept_id: str
    observation_snapshot: tuple[Any, ...]
    runtime_identity: int
    working_memory_identity: int
    instance: object | None = None
    original_permit: object | None = None


@dataclass
class CognitiveRuntime:
    """Build transient cognition state from authoritative input snapshots.

    AgentTurn supplies Belief and Goal snapshots read from CognitionContext.
    Optional stores are injected references for legacy direct callers only;
    this runtime never constructs or owns long-lived cognition stores.
    """

    perception_processor: PerceptionProcessor = field(
        default_factory=PerceptionProcessor
    )
    working_memory_store: WorkingMemoryStore = field(
        default_factory=WorkingMemoryStore
    )
    belief_store: BeliefStore | None = None
    goal_store: GoalStore | None = None
    self_model_store: SelfModelStore | None = None
    _l1_consumption_receipts: dict[tuple[str, str], _L1ConsumptionReceipt] = field(
        default_factory=dict, init=False, repr=False
    )

    def process(
        self,
        agent_id: str,
        observations: Sequence[Observation],
        *,
        beliefs: Sequence[Belief] | None = None,
        goals: Sequence[Goal] | None = None,
    ) -> CognitionState:
        """Build a state snapshot from observations and supplied cognition.

        Explicit Belief and Goal snapshots take precedence. Legacy stores are
        only read when the corresponding argument is omitted.
        """
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("agent_id must be a non-empty string")
        # This public compatibility entry point may receive caller-supplied
        # records directly. Storage or identity matching is not authorization.
        authorized_observations = tuple(
            observation
            for observation in observations
            if isinstance(observation, Observation)
            and observation.observer_id == agent_id
            and observation.has_trusted_provenance()
        )
        for observation in authorized_observations:
            prior = self._l1_consumption_receipts.get((agent_id, observation.observation_id))
            if prior is not None and prior.instance is not None and prior.observation_snapshot != observation._snapshot():
                raise PermissionError("conflicting consumed Observation identity")
        percepts = tuple(
            self.perception_processor.process(observation, observer_id=agent_id)
            for observation in authorized_observations
        )

        previous = self.working_memory_store.get(agent_id)
        percept_ids = list(previous.percept_ids) if previous is not None else []
        known_percept_ids = set(percept_ids)
        newly_ingested_percept_ids: list[str] = []
        for percept in percepts:
            # Percept identity is derived from the trusted Observation ID.
            # Distinct Events (even with identical text) and distinct Agents
            # retain distinct IDs; replaying the same Observation is a no-op.
            if percept.percept_id not in known_percept_ids:
                percept_ids.append(percept.percept_id)
                known_percept_ids.add(percept.percept_id)
                newly_ingested_percept_ids.append(percept.percept_id)
        working_memory = WorkingMemory(
            owner_id=agent_id,
            percept_ids=percept_ids,
            focus=None if previous is None else previous.focus,
            context={} if previous is None else previous.context,
            metadata={} if previous is None else previous.metadata,
        )
        self.working_memory_store.update(working_memory)

        if beliefs is None:
            belief_snapshot = (
                ()
                if self.belief_store is None
                else tuple(
                    belief
                    for belief in (self.belief_store.get(agent_id),)
                    if belief is not None
                )
            )
        else:
            belief_snapshot = tuple(beliefs)
        if goals is None:
            goal_snapshot = (
                () if self.goal_store is None else self.goal_store.get(agent_id)
            )
        else:
            goal_snapshot = tuple(goals)

        state = CognitionState(
            agent_id=agent_id,
            percept_ids=newly_ingested_percept_ids,
            belief_ids=[
                belief.belief_id
                for belief in belief_snapshot
                if belief.owner_id == agent_id
            ],
            goal_ids=[
                goal.goal_id for goal in goal_snapshot if goal.owner_id == agent_id
            ],
            focus=working_memory.focus,
            percepts=list(percepts),
        )
        for observation, percept in zip(authorized_observations, percepts):
            prior = self._l1_consumption_receipts.get((agent_id, observation.observation_id))
            if prior is not None and prior.instance is not None:
                continue  # B2's first receipt and tick are immutable.
            self._l1_consumption_receipts[(agent_id, observation.observation_id)] = (
                _L1ConsumptionReceipt(
                    owner_id=agent_id,
                    observation_id=observation.observation_id,
                    source_event_id=observation.source_event_id,
                    percept_id=percept.percept_id,
                    observation_snapshot=observation._snapshot(),
                    runtime_identity=id(self),
                    working_memory_identity=id(self.working_memory_store),
                )
            )
        return state

    def _accept_result_instance(self, owner, observation, instance, permit, *, authority):
        from cognitive_world.cognition.l1_instance import (
            _INSTANCE_ACCEPTANCE_AUTHORITY, AmbiguousL1ConsumptionError,
        )
        if authority is not _INSTANCE_ACCEPTANCE_AUTHORITY:
            raise PermissionError("instance acceptance has no Runtime authority")
        state = self.process(owner, (observation,))
        expected_id = "percept:" + observation.observation_id
        percept = (state.percepts[0] if type(state) is CognitionState
                   and len(state.percepts) == 1 else None)
        workspace = self.working_memory_store.get(owner)
        if (type(state) is not CognitionState or state.agent_id != owner
                or state.percept_ids != [expected_id] or type(percept) is not Percept
                or percept.percept_id != expected_id or percept.observer_id != owner
                or percept.source_observation_id != observation.observation_id
                or percept.content != observation.content or percept.metadata != observation.metadata
                or workspace is None or workspace.owner_id != owner
                or workspace.percept_ids.count(expected_id) != 1):
            # process() can return an existing Percept without newly ingesting
            # it. No instance may be attached to that ambiguous result. The
            # caller's protected post-L1 failure boundary freezes this Runtime.
            raise AmbiguousL1ConsumptionError("ambiguous L1 acceptance: expected a newly consumed Percept")
        self._publish_result_receipt(owner, observation, instance, permit)

    def _publish_result_receipt(self, owner, observation, instance, permit):
        from dataclasses import replace
        if not self.has_consumed_observation(owner, observation, source_event_id=observation.source_event_id):
            raise PermissionError("instance input did not cross L1")
        key = (owner, observation.observation_id)
        self._l1_consumption_receipts[key] = replace(
            self._l1_consumption_receipts[key], instance=instance, original_permit=permit)

    def has_consumed_observation(
        self, agent_id: str, observation: Observation, *, source_event_id: str
    ) -> bool:
        """Verify this runtime previously ingested this intact Observation for its owner.

        The receipt is tied to this CognitiveRuntime, its existing
        WorkingMemoryStore, owner, Observation payload, and source Event.
        It is process-local and is not a durable or malicious-code security
        boundary.
        """
        if (
            not isinstance(agent_id, str)
            or not agent_id
            or not isinstance(observation, Observation)
            or observation.observer_id != agent_id
            or observation.source_event_id != source_event_id
            or not observation.has_trusted_provenance()
        ):
            return False
        receipt = self._l1_consumption_receipts.get(
            (agent_id, observation.observation_id)
        )
        if (
            receipt is None
            or receipt.owner_id != agent_id
            or receipt.observation_id != observation.observation_id
            or receipt.source_event_id != source_event_id
            or receipt.percept_id != f"percept:{observation.observation_id}"
            or receipt.runtime_identity != id(self)
            or receipt.working_memory_identity != id(self.working_memory_store)
            or receipt.observation_snapshot != observation._snapshot()
        ):
            return False
        working_memory = self.working_memory_store.get(agent_id)
        return (
            working_memory is not None
            and working_memory.owner_id == agent_id
            and receipt.percept_id in working_memory.percept_ids
        )

    def get_self_model(self, agent_id: str) -> SelfModel | None:
        """Return an injected SelfModel snapshot for legacy callers, if any."""
        if self.self_model_store is None:
            return None
        return self.self_model_store.get(agent_id)
