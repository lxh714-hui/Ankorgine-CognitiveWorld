"""Bounded autonomous orchestration over the existing SimulationRuntime."""

from __future__ import annotations

from dataclasses import dataclass, field
from cognitive_world.agent.action_loop import AgentActionLoop, AgentTurnExecution
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.event.processor import EventProcessor
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.runtime import AgentRuntimeTurnRecord, SimulationRuntime


@dataclass(frozen=True)
class CandidateRunSummary:
    candidate_id: str
    goal_id: str | None
    intent: str
    target: str | None
    method: str
    score: float
    factors: tuple[tuple[str, float], ...]
    uncertainty: tuple[str, ...]


@dataclass(frozen=True)
class ProposalRunSummary:
    proposal_id: str
    action_type: str
    target_refs: tuple[str, ...]
    goal_id: str | None
    method: str
    steps: tuple[str, ...]
    candidates: tuple[CandidateRunSummary, ...]
    selected_candidate_id: str | None


@dataclass(frozen=True)
class AttemptRunSummary:
    attempt_id: str
    action_type: str
    target_refs: tuple[str, ...]
    method: str
    tools: tuple[str, ...]
    steps: tuple[str, ...]


@dataclass(frozen=True)
class AgentActionReport:
    agent_id: str
    status: str
    proposal: ProposalRunSummary | None
    attempt: AttemptRunSummary | None
    resolution_outcome: str | None
    resolution_explanation: str | None
    event_id: str | None
    event_committed: bool
    received_observation_ids: tuple[str, ...]
    newly_consumed_percept_ids: tuple[str, ...]
    cognitive_update_summary: str
    failure_type: str | None = None


@dataclass(frozen=True)
class WorldRoundReport:
    round_number: int
    simulation_tick: int
    agent_actions: tuple[AgentActionReport, ...]
    committed_event_ids: tuple[str, ...]
    scheduled_event_ids: tuple[str, ...]
    budget_actions_used: int
    budget_events_used: int
    permission_or_safety_rejections: int


@dataclass(frozen=True)
class AutonomousWorldReport:
    rounds: tuple[WorldRoundReport, ...]
    termination_reason: str

    @property
    def total_rounds(self) -> int:
        return len(self.rounds)

    @property
    def total_committed_events(self) -> int:
        return sum(len(item.committed_event_ids) for item in self.rounds)


@dataclass
class AutonomousWorldRunner:
    """Run bounded NPC turns using the canonical cognition and Event paths.

    This wrapper owns no world or cognition Store. It schedules one turn per
    registered Agent each round, in stable Agent ID order, and delegates each
    decision to the existing AgentTurn, AgentDecision, ActionPipeline,
    Resolution and EventProcessor. Agent IDs control identity and stable
    ordering only; candidate content is derived from each Agent's own frozen
    cognition and authorized Percepts.
    """

    runtime: SimulationRuntime
    maximum_rounds: int = 20
    maximum_agents_per_round: int = 32
    maximum_events_per_run: int = 128
    _rounds_completed: int = field(default=0, init=False, repr=False)
    _events_committed: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.runtime) is not SimulationRuntime:
            raise TypeError("AutonomousWorldRunner requires the canonical SimulationRuntime")
        context = self.runtime.context
        if context.agent_registry is None or context.agent_scheduler is None:
            raise ValueError("RuntimeContext requires AgentRegistry and AgentScheduler")
        if context.observation_store is None:
            raise ValueError("autonomous perception requires the Runtime ObservationStore")
        if type(self.runtime.event_processor) is not EventProcessor:
            raise TypeError("autonomous turns require the canonical EventProcessor")
        loop = self.runtime.agent_action_loop
        if type(loop) is not AgentActionLoop or type(loop.agent_turn) is not AgentTurn:
            raise TypeError("autonomous turns require the canonical AgentActionLoop and AgentTurn")
        if type(self.runtime.agent_decision) is not AgentDecision:
            raise TypeError("autonomous turns require the production AgentDecision")
        flow = loop.action_resolution_flow
        if type(flow) is not ActionResolutionFlow or type(flow.resolution_engine) is not MethodBasedResolutionEngine:
            raise TypeError("autonomous world execution requires MethodBasedResolutionEngine")
        if loop.safety_governance is not context.safety_governance:
            raise PermissionError("AgentActionLoop is not bound to RuntimeContext safety governance")
        for name, value, upper in (
            ("maximum_rounds", self.maximum_rounds, 100),
            ("maximum_agents_per_round", self.maximum_agents_per_round, 64),
            ("maximum_events_per_run", self.maximum_events_per_run, 1000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
                raise ValueError(f"{name} must be in [1, {upper}]")

        self.runtime.maximum_agent_actions_this_step = self.maximum_agents_per_round

    def run(self, rounds: int) -> AutonomousWorldReport:
        """Run no more than the constructor's trusted round/event budgets."""
        if isinstance(rounds, bool) or not isinstance(rounds, int) or not 0 <= rounds <= self.maximum_rounds:
            raise ValueError("requested rounds exceed the trusted Runtime budget")
        reports: list[WorldRoundReport] = []
        reason = "requested_round_budget_complete"
        for _ in range(rounds):
            if self._events_committed >= self.maximum_events_per_run:
                reason = "event_budget_exhausted"
                break
            report = self.run_round()
            reports.append(report)
            if any(item.failure_type in {"RuntimeError", "RECOVERY_REQUIRED"} for item in report.agent_actions):
                reason = "recovery_required"
                break
        else:
            if rounds == 0:
                reason = "zero_round_request"
        return AutonomousWorldReport(tuple(reports), reason)

    def run_round(self) -> WorldRoundReport:
        """Schedule every registered Agent once, then advance one clock tick."""
        if self._rounds_completed >= self.maximum_rounds:
            raise RuntimeError("AutonomousWorldRunner round budget is exhausted")
        context = self.runtime.context
        registry = context.agent_registry
        scheduler = context.agent_scheduler
        assert registry is not None and scheduler is not None
        agents = tuple(sorted(registry.all_agents(), key=lambda item: item.agent_id))
        if len(agents) > self.maximum_agents_per_round:
            raise RuntimeError("registered Agent count exceeds the per-round action budget")

        due_tick = context.clock.current_time + 1
        for agent in agents:
            scheduler.schedule_agent(agent.agent_id, due_tick)
        remaining_events = max(0, self.maximum_events_per_run - self._events_committed)
        self.runtime.maximum_events_this_step = remaining_events
        self.runtime.step()
        self._rounds_completed += 1

        actions = tuple(self._summarize_turn(item) for item in self.runtime.last_agent_turn_results)
        committed = tuple(
            item.event_id for item in self.runtime.last_agent_turn_results
            if item.event_id is not None and item.event_committed
        )
        scheduled = tuple(
            item.event_id for item in self.runtime.last_scheduled_event_results
            if item.committed
        )
        self._events_committed += len(committed) + len(scheduled)
        return WorldRoundReport(
            round_number=self._rounds_completed,
            simulation_tick=context.clock.current_time,
            agent_actions=actions,
            committed_event_ids=(*scheduled, *committed),
            scheduled_event_ids=scheduled,
            budget_actions_used=sum(
                item.execution is not None or item.failure_type is not None
                for item in self.runtime.last_agent_turn_results
            ),
            budget_events_used=len(committed) + len(scheduled),
            permission_or_safety_rejections=sum(
                item.failure_type == "PermissionError" for item in self.runtime.last_agent_turn_results
            ),
        )

    @staticmethod
    def _summarize_turn(record: AgentRuntimeTurnRecord) -> AgentActionReport:
        execution = record.execution
        if execution is None:
            status = "rejected" if record.failure_type == "PermissionError" else (
                "error" if record.failure_type else "not_executed"
            )
            return AgentActionReport(
                record.agent_id, status, None, None, None, None, record.event_id,
                record.event_committed, record.observation_ids,
                record.newly_consumed_percept_ids,
                f"{len(record.newly_consumed_percept_ids)} new L1 percept(s)",
                record.failure_type,
            )
        proposal = AutonomousWorldRunner._proposal_summary(execution)
        if execution.communication_result is not None:
            return AgentActionReport(
                record.agent_id, "communicated", proposal, None, "delivered",
                "trusted speech Observation issued to the addressed Agent",
                record.event_id, record.event_committed, record.observation_ids,
                record.newly_consumed_percept_ids,
                f"{len(record.newly_consumed_percept_ids)} new L1 percept(s)",
                record.failure_type,
            )
        if execution.attempt is None or execution.resolution is None:
            raise RuntimeError("non-communication turn has an incomplete action result")
        attempt = AutonomousWorldRunner._attempt_summary(execution)
        result = execution.resolution
        if not result.confirmed and result.outcome == "unresolved":
            status = "unresolved"
        elif result.success:
            status = "success" if record.event_committed else "confirmed_not_committed"
        else:
            status = "failure" if record.event_committed else "failure_not_committed"
        if record.failure_type is not None:
            status = "event_delivery_failed"
        return AgentActionReport(
            record.agent_id, status, proposal, attempt, result.outcome,
            result.outcome, record.event_id, record.event_committed,
            record.observation_ids, record.newly_consumed_percept_ids,
            f"{len(record.newly_consumed_percept_ids)} new L1 percept(s)",
            record.failure_type,
        )

    @staticmethod
    def _proposal_summary(execution: AgentTurnExecution) -> ProposalRunSummary:
        proposal = execution.proposal
        metadata = proposal.metadata
        parameters = proposal.parameters
        trace = metadata.get("decision_trace", ())
        candidates = tuple(
            CandidateRunSummary(
                candidate_id=item["candidate_id"],
                goal_id=item.get("goal_id"),
                intent=item["intent"],
                target=item.get("target"),
                method=item["method"],
                score=float(item["score"]),
                factors=tuple((str(k), float(v)) for k, v in item.get("factors", ())),
                uncertainty=tuple(item.get("uncertainty", ())),
            )
            for item in trace if isinstance(item, dict)
        )
        return ProposalRunSummary(
            proposal.proposal_id, proposal.action_type, tuple(proposal.target_refs),
            parameters.get("goal_id"), str(parameters.get("method", "")),
            tuple(parameters.get("steps", ())), candidates,
            metadata.get("selected_candidate_id"),
        )

    @staticmethod
    def _attempt_summary(execution: AgentTurnExecution) -> AttemptRunSummary:
        attempt = execution.attempt
        parameters = attempt.parameters
        return AttemptRunSummary(
            attempt.attempt_id, attempt.action_type, tuple(attempt.target_refs),
            str(parameters.get("method", "")), tuple(parameters.get("tools", ())),
            tuple(parameters.get("steps", ())),
        )
