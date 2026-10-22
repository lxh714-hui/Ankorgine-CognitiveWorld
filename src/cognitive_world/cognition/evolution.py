"""Coordinate proposal-only cognition updates after confirmed Events."""

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.belief_update import (
    BeliefUpdateProposal,
    BeliefUpdater,
)
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.goal_update import GoalUpdateProposal, GoalUpdater
from cognitive_world.core.event import Event
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.observation.generator import ObservationGenerator
from cognitive_world.observation.observation import Observation

if TYPE_CHECKING:
    from cognitive_world.memory.consolidation import EventMemoryProposalFactory


def _create_event_memory_proposal_factory() -> "EventMemoryProposalFactory":
    """Import the proposal factory lazily to keep package initialization acyclic."""
    from cognitive_world.memory.consolidation import EventMemoryProposalFactory

    return EventMemoryProposalFactory()


class ObservationStatus(str, Enum):
    """Outcome of finding an observer-scoped input for a confirmed Event."""

    OBSERVED = "observed"
    UNOBSERVED = "unobserved"
    UNAUTHORIZED_EVENT = "unauthorized_event"
    UNAUTHORIZED_OBSERVATION = "unauthorized_observation"


@dataclass(init=False)
class CognitiveEvolutionResult:
    """Collect proposals created while processing an Agent's experience."""

    belief_update_proposals: tuple[BeliefUpdateProposal, ...] = ()
    goal_update_proposals: tuple[GoalUpdateProposal, ...] = ()
    memory_proposals: tuple[MemoryProposal, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_status: ObservationStatus = ObservationStatus.UNOBSERVED

    def __init__(
        self,
        belief_update_proposals: tuple[BeliefUpdateProposal, ...] = (),
        goal_update_proposals: tuple[GoalUpdateProposal, ...] = (),
        memory_proposals: tuple[MemoryProposal, ...] = (),
        metadata: dict[str, Any] | None = None,
        *,
        memory_candidates: tuple[MemoryProposal, ...] | None = None,
        observation_status: ObservationStatus = ObservationStatus.UNOBSERVED,
    ) -> None:
        """Initialize canonical fields, accepting the former keyword alias."""
        if memory_candidates is not None:
            if memory_proposals:
                raise ValueError("provide memory_proposals or memory_candidates, not both")
            memory_proposals = memory_candidates
        self.belief_update_proposals = belief_update_proposals
        self.goal_update_proposals = goal_update_proposals
        self.memory_proposals = memory_proposals
        self.metadata = {} if metadata is None else metadata
        self.observation_status = observation_status
        self.__post_init__()

    def __post_init__(self) -> None:
        self.belief_update_proposals = deepcopy(
            tuple(self.belief_update_proposals)
        )
        self.goal_update_proposals = deepcopy(tuple(self.goal_update_proposals))
        self.memory_proposals = deepcopy(tuple(self.memory_proposals))
        self.metadata = deepcopy(self.metadata)
        if not isinstance(self.observation_status, ObservationStatus):
            raise TypeError("observation_status must be an ObservationStatus")

    @property
    def memory_candidates(self) -> tuple[MemoryProposal, ...]:
        """Compatibility alias; candidates are canonical MemoryProposals."""
        return self.memory_proposals


@dataclass(init=False)
class CognitiveEvolutionEngine:
    """Orchestrate Observation and cognition proposal generation only.

    Store application is intentionally left to ``CognitiveUpdateApplier``
    after a separate ``CognitiveUpdateValidator`` decision.
    """

    observation_generator: ObservationGenerator
    belief_updater: BeliefUpdater
    goal_updater: GoalUpdater
    event_memory_proposal_factory: "EventMemoryProposalFactory"
    self_model_review_provider: object | None

    def __init__(
        self,
        observation_generator: ObservationGenerator | None = None,
        belief_updater: BeliefUpdater | None = None,
        goal_updater: GoalUpdater | None = None,
        event_memory_proposal_factory: "EventMemoryProposalFactory | None" = None,
        *,
        memory_consolidator: "EventMemoryProposalFactory | None" = None,
        self_model_review_provider: object | None = None,
    ) -> None:
        if (
            event_memory_proposal_factory is not None
            and memory_consolidator is not None
            and event_memory_proposal_factory is not memory_consolidator
        ):
            raise ValueError(
                "event_memory_proposal_factory and memory_consolidator "
                "must reference the same object"
            )
        self.observation_generator = (
            observation_generator
            if observation_generator is not None
            else ObservationGenerator()
        )
        self.belief_updater = (
            belief_updater if belief_updater is not None else BeliefUpdater()
        )
        self.goal_updater = goal_updater if goal_updater is not None else GoalUpdater()
        self.event_memory_proposal_factory = (
            event_memory_proposal_factory
            if event_memory_proposal_factory is not None
            else memory_consolidator
            if memory_consolidator is not None
            else _create_event_memory_proposal_factory()
        )
        self.self_model_review_provider = self_model_review_provider

    def propose_self_model_update(
        self,
        owner_id: str,
        new_percept_ids: tuple[str, ...] | list[str],
        percepts: tuple[object, ...] | list[object],
        observations: tuple[Observation, ...] | list[Observation],
        self_model: object,
        cognitive_runtime: object,
        *,
        provider: object | None = None,
    ) -> object | None:
        """Propose a tentative SelfModel addition from this turn's L1 evidence.

        A provider is opt-in. The method never applies a candidate to a Store.
        """
        active_provider = self.self_model_review_provider if provider is None else provider
        if active_provider is None:
            return None
        from cognitive_world.cognition.self_model import SelfModel
        from cognitive_world.cognition.self_model_evolution import (
            SelfModelReview,
            build_self_model_review_input,
            make_self_model_update_proposal,
        )
        from cognitive_world.cognition.runtime import CognitiveRuntime

        if not isinstance(self_model, SelfModel) or not isinstance(cognitive_runtime, CognitiveRuntime):
            return None
        request = build_self_model_review_input(
            owner_id, new_percept_ids, percepts, observations, self_model,
            cognitive_runtime,
        )
        if request is None:
            return None
        review_method = getattr(active_provider, "review", None)
        if not callable(review_method):
            raise TypeError("SelfModel review provider must expose review(request)")
        review = review_method(request)
        if not isinstance(review, SelfModelReview):
            raise TypeError("SelfModel review provider returned an invalid result")
        return make_self_model_update_proposal(review, request, self_model)

    @property
    def memory_consolidator(self) -> "EventMemoryProposalFactory":
        """Deprecated compatibility alias for the Event proposal factory."""
        return self.event_memory_proposal_factory

    @memory_consolidator.setter
    def memory_consolidator(self, value: "EventMemoryProposalFactory") -> None:
        self.event_memory_proposal_factory = value

    def process(self, event: Event, agent_context: Any) -> CognitiveEvolutionResult:
        """Prepare proposals only; never validate or apply state changes."""
        if not isinstance(event, Event):
            raise TypeError("event must be a confirmed Event")
        if not event.has_trusted_source():
            return CognitiveEvolutionResult(
                metadata={"source_event_id": event.id},
                observation_status=ObservationStatus.UNAUTHORIZED_EVENT,
            )

        owner_id = self._get_owner_id(agent_context)
        observations = self._read_items(agent_context, "get_observations", "observations")
        matching_observations = tuple(
            item
            for item in observations
            if isinstance(item, Observation)
            and item.observer_id == owner_id
            and item.source_event_id == event.id
        )
        if not matching_observations:
            return CognitiveEvolutionResult(
                metadata={
                    "agent_id": owner_id,
                    "source_event_id": event.id,
                },
                observation_status=ObservationStatus.UNOBSERVED,
            )
        observation = next(
            (
                item
                for item in matching_observations
                if item.has_trusted_provenance()
            ),
            None,
        )
        if observation is None:
            return CognitiveEvolutionResult(
                metadata={
                    "agent_id": owner_id,
                    "source_event_id": event.id,
                },
                observation_status=ObservationStatus.UNAUTHORIZED_OBSERVATION,
            )
        update_context = {
            "agent_id": owner_id,
            "source_refs": [observation.observation_id],
            "metadata": {"source_observation_id": observation.observation_id},
        }
        beliefs = self._read_items(agent_context, "get_beliefs", "beliefs")
        goals = self._read_items(agent_context, "get_goals", "goals")
        belief_updates = tuple(
            self.belief_updater.propose_update(
                belief, self._belief_update_context(belief, update_context)
            )
            for belief in beliefs
            if isinstance(belief, Belief)
        )
        goal_updates = tuple(
            self.goal_updater.propose_update(goal, update_context)
            for goal in goals
            if isinstance(goal, Goal)
        )
        memory_proposal = self.event_memory_proposal_factory.propose(
            event,
            {
                "owner_id": owner_id,
                "memory_type": "experience",
                "content": deepcopy(observation.content),
                "metadata": {
                    "source_observation_id": observation.observation_id,
                    "source": "observation",
                },
            },
        )
        return CognitiveEvolutionResult(
            belief_update_proposals=belief_updates,
            goal_update_proposals=goal_updates,
            memory_proposals=(memory_proposal,),
            metadata={
                "agent_id": owner_id,
                "observation_id": observation.observation_id,
                "source_event_id": event.id,
            },
            observation_status=ObservationStatus.OBSERVED,
        )

    @staticmethod
    def _get_owner_id(agent_context: Any) -> str:
        # CognitionContext binds all reads to its immutable owner_id. Prefer
        # that canonical identity; agent_id remains a compatibility input for
        # runtime contexts that predate CognitionContext.
        owner_id = getattr(agent_context, "owner_id", None)
        if not owner_id:
            owner_id = getattr(agent_context, "agent_id", None)
        if not owner_id:
            owner_id = getattr(agent_context, "_observer_id", None)
        if not owner_id:
            get_identity = getattr(agent_context, "get_identity", None)
            if callable(get_identity):
                identity = get_identity()
                if isinstance(identity, dict):
                    owner_id = identity.get("agent_id")
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("agent_context must identify a non-empty agent_id")
        return owner_id

    @staticmethod
    def _read_items(agent_context: Any, method_name: str, attribute_name: str) -> tuple:
        getter = getattr(agent_context, method_name, None)
        if callable(getter):
            values = getter()
        else:
            values = getattr(agent_context, attribute_name, ())
        if values is None:
            return ()
        if isinstance(values, Iterable):
            return tuple(values)
        return ()

    @staticmethod
    def _belief_update_context(
        belief: Belief, base_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Provide a stable dictionary proposal shape without changing Belief."""
        context = deepcopy(base_context)
        candidate_value = deepcopy(belief.content)
        if isinstance(candidate_value, dict):
            candidate_value.setdefault("changes", [])
        context["new_value"] = candidate_value
        return context
