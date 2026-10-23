"""Framework-neutral, in-process asynchronous admission for player input."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import Context, copy_context
from dataclasses import dataclass, field, replace
from enum import Enum
from threading import Event, RLock, Timer
from time import monotonic
from uuid import uuid4

from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit
from .input_understanding import PlayerInputRequest
from .service import PlayerActionOutcome, PlayerActionService
from .task_context import (
    PlayerTaskAborted, PlayerTaskBinding, activate_player_task, reset_player_task,
)


class PlayerTaskExecutionState(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    STALE = "stale"
    FAILED = "failed"


class PlayerTaskDeliveryState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    DELIVERED = "delivered"
    RETRYABLE = "retryable"
    STALE = "stale"


@dataclass(frozen=True)
class PlayerInputTaskSnapshot:
    """Allowlisted application status; contains no domain or authority objects."""

    request_id: str
    execution: PlayerTaskExecutionState
    delivery: PlayerTaskDeliveryState
    outcome_status: str | None = None
    recovery_code: str | None = None


@dataclass(frozen=True)
class PlayerInputTaskHandle:
    """Opaque process-local handle returned after request admission."""

    value: str


@dataclass
class _TaskRecord:
    handle: PlayerInputTaskHandle
    request: PlayerInputRequest
    digest: str
    permit: RuntimeWritePermit
    binding: PlayerTaskBinding
    context: Context
    runtime_session_id: str
    restore_generation: int
    completion: Future[PlayerInputTaskSnapshot] = field(default_factory=Future)
    work: Future[object] | None = None
    timer: Timer | None = None
    execution: PlayerTaskExecutionState = PlayerTaskExecutionState.ACCEPTED
    delivery: PlayerTaskDeliveryState = PlayerTaskDeliveryState.PENDING
    outcome_status: str | None = None
    recovery_code: str | None = None


class PlayerInputTaskCoordinator:
    """Run one Runtime's player inputs on a serialized background worker.

    Admission captures the original RuntimeWritePermit before handoff. The
    worker carries that exact ContextVar context; cancellation can revoke it
    only before EventProcessor enters its final fence-protected commit scope.
    """

    def __init__(self, service: PlayerActionService, *, timeout_seconds: float = 30.0) -> None:
        if not isinstance(service, PlayerActionService):
            raise TypeError("PlayerActionService required")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0.05 <= float(timeout_seconds) <= 300.0):
            raise ValueError("timeout_seconds must be between 0.05 and 300")
        fence = service.processor.write_fence
        if not isinstance(fence, RuntimeWriteFence):
            raise ValueError("asynchronous player input requires a Runtime-bound EventProcessor")
        self._service = service
        self._fence = fence
        self._timeout_seconds = float(timeout_seconds)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cw-player-input")
        self._lock = RLock()
        self._closed = False
        self._by_handle: dict[str, _TaskRecord] = {}
        self._by_request: dict[str, _TaskRecord] = {}

    def submit_input(self, request: PlayerInputRequest) -> PlayerInputTaskHandle:
        """Accept promptly; identical request reuses its in-process task handle."""
        if not isinstance(request, PlayerInputRequest):
            raise TypeError("PlayerInputRequest required")
        session = self._service.context.player_session
        if (session is None or request.session_id != session.session_id
                or request.world_id != self._service.world_id):
            raise PermissionError("player request does not match the bound session and world")
        digest = self._service._input_digest(request)
        with self._lock:
            if self._closed:
                raise RuntimeError("player input coordinator is closed")
            prior = self._by_request.get(request.request_id)
            if prior is not None:
                if prior.digest != digest:
                    raise PermissionError("request identity reused with changed content")
                return prior.handle
            with self._fence.operation() as permit:
                with self._fence.snapshot_scope():
                    actor_id = self._service._actor()
                context = copy_context()
            binding = PlayerTaskBinding(
                self._fence, permit, Event(), monotonic() + self._timeout_seconds,
                session.session_id, actor_id, (),
            )
            handle = PlayerInputTaskHandle(uuid4().hex)
            record = _TaskRecord(
                handle, request, digest, permit, binding, context,
                permit.session_id, permit.restore_generation,
            )
            self._by_handle[handle.value] = record
            self._by_request[request.request_id] = record
            timer = Timer(self._timeout_seconds, self._expire, args=(handle.value,))
            timer.daemon = True
            record.timer = timer
            timer.start()
            try:
                record.work = self._executor.submit(context.run, self._run, record)
            except Exception:
                self._fence.revoke_uncommitted(permit)
                record.execution = PlayerTaskExecutionState.FAILED
                record.delivery = PlayerTaskDeliveryState.NOT_REQUIRED
                record.recovery_code = "task_admission_failed"
                timer.cancel()
                record.completion.set_result(self._snapshot(record))
                raise
            return handle

    def _run(self, record: _TaskRecord) -> None:
        with self._lock:
            if record.execution is not PlayerTaskExecutionState.ACCEPTED:
                return
            record.execution = PlayerTaskExecutionState.RUNNING
        token = None
        try:
            record.binding.check()
            # Authorization projection can scan the owner's Observation set;
            # keep it off the caller/UI thread while reading one consistent
            # view from the originally bound Runtime generation.
            with self._fence.snapshot_scope():
                authorized_targets = self._service.available_targets()
            record.binding = replace(
                record.binding, authorized_targets=authorized_targets,
            )
            token = activate_player_task(record.binding)
            record.binding.check()
            outcome = self._service.submit_input(record.request)
        except PlayerTaskAborted as exc:
            self._finish_aborted(record, exc.status)
        except Exception:
            if self._service.has_completed_event_for_request(record.request.request_id, record.digest):
                self._finish(record, PlayerTaskExecutionState.COMPLETED,
                             PlayerTaskDeliveryState.RETRYABLE, recovery_code="presentation_retryable")
            else:
                try:
                    self._fence.require_current_permit(record.permit)
                except PermissionError:
                    state = (PlayerTaskExecutionState.CANCELLED
                             if record.binding.cancellation.is_set()
                             else PlayerTaskExecutionState.STALE)
                else:
                    state = PlayerTaskExecutionState.FAILED
                self._finish(record, state, PlayerTaskDeliveryState.NOT_REQUIRED,
                             recovery_code=state.value if state is not PlayerTaskExecutionState.FAILED
                             else "request_failed")
        else:
            if outcome.recovery_action is None:
                delivery = PlayerTaskDeliveryState.DELIVERED
            elif self._service.has_completed_event_for_request(record.request.request_id, record.digest):
                delivery = PlayerTaskDeliveryState.RETRYABLE
            else:
                delivery = PlayerTaskDeliveryState.PENDING
            recovery_code = None
            if outcome.status == "reasoning_unavailable":
                recovery_code = self._safe_input_failure_code(
                    self._service.fallback_diagnostic(record.request.request_id)
                )
            self._finish(record, PlayerTaskExecutionState.COMPLETED, delivery,
                         outcome_status=self._safe_outcome_status(outcome),
                         recovery_code=recovery_code)
        finally:
            if token is not None:
                reset_player_task(token)

    @staticmethod
    def _safe_outcome_status(outcome: PlayerActionOutcome) -> str:
        allowed = {
            "resolved", "failed", "unresolved", "unparseable", "clarification_required",
            "reasoning_unavailable", "rejected", "observed", "target_unavailable",
            "observation_empty",
            "clarification_expired", "clarification_cancelled",
            "goal_already_satisfied", "executed_no_observable_change",
        }
        return outcome.status if outcome.status in allowed else "completed"

    @staticmethod
    def _safe_input_failure_code(internal: str | None) -> str:
        """Export a bounded category, never a provider exception or payload."""
        if internal == "input_provider_unavailable":
            return "input_provider_unavailable"
        if internal and internal.startswith("input_provider_configuration_failed:"):
            return "input_provider_configuration_invalid"
        if internal == "input_understanding_failed:TimeoutError":
            return "input_provider_timeout"
        if internal in {
            "input_understanding_failed:ValueError",
            "input_understanding_failed:TypeError",
            "input_understanding_failed:KeyError",
            "input_understanding_failed:IndexError",
        }:
            return "input_provider_invalid_response"
        if internal in {
            "input_understanding_failed:ConnectionError",
            "input_understanding_failed:ConnectionRefusedError",
            "input_understanding_failed:OSError",
        }:
            return "input_provider_unreachable"
        return "input_reasoning_unavailable"

    def _finish_aborted(self, record: _TaskRecord, status: str) -> None:
        mapping = {
            "cancelled": PlayerTaskExecutionState.CANCELLED,
            "expired": PlayerTaskExecutionState.EXPIRED,
            "stale": PlayerTaskExecutionState.STALE,
        }
        self._finish(record, mapping.get(status, PlayerTaskExecutionState.STALE),
                     PlayerTaskDeliveryState.NOT_REQUIRED, recovery_code=status)

    def _finish(
        self, record: _TaskRecord, execution: PlayerTaskExecutionState,
        delivery: PlayerTaskDeliveryState, *, outcome_status: str | None = None,
        recovery_code: str | None = None,
    ) -> None:
        with self._lock:
            if record.execution in {
                PlayerTaskExecutionState.CANCELLED, PlayerTaskExecutionState.EXPIRED,
                PlayerTaskExecutionState.STALE, PlayerTaskExecutionState.FAILED,
                PlayerTaskExecutionState.COMPLETED,
            }:
                return
            record.execution = execution
            record.delivery = delivery
            record.outcome_status = outcome_status
            record.recovery_code = recovery_code
            self._fence._clear_commit_marker(record.permit)
            if record.timer is not None:
                record.timer.cancel()
            if not record.completion.done():
                record.completion.set_result(self._snapshot(record))

    def _expire(self, handle_id: str) -> None:
        self._cancel(handle_id, expired=True)

    def cancel(self, handle: PlayerInputTaskHandle) -> bool:
        return self._cancel(self._record(handle).handle.value, expired=False)

    def _cancel(self, handle_id: str, *, expired: bool) -> bool:
        with self._lock:
            record = self._by_handle.get(handle_id)
            if record is None or record.execution in {
                PlayerTaskExecutionState.CANCELLED, PlayerTaskExecutionState.EXPIRED,
                PlayerTaskExecutionState.STALE, PlayerTaskExecutionState.FAILED,
                PlayerTaskExecutionState.COMPLETED,
            }:
                return False
            revoked = self._fence.revoke_uncommitted(record.permit)
            if not revoked:
                return False
            record.binding.cancellation.set()
            state = PlayerTaskExecutionState.EXPIRED if expired else PlayerTaskExecutionState.CANCELLED
            record.execution = state
            record.delivery = PlayerTaskDeliveryState.NOT_REQUIRED
            record.recovery_code = state.value
            if record.work is not None:
                record.work.cancel()
            if record.timer is not None:
                record.timer.cancel()
            if not record.completion.done():
                record.completion.set_result(self._snapshot(record))
            return True

    def get_status(self, handle: PlayerInputTaskHandle) -> PlayerInputTaskSnapshot:
        with self._lock:
            return self._snapshot(self._record(handle))

    def completion(self, handle: PlayerInputTaskHandle) -> Future[PlayerInputTaskSnapshot]:
        """Return a cancellable view; only the coordinator can cancel the underlying task."""
        return self._future_view(self._record(handle).completion)

    def retry_presentation(self, handle: PlayerInputTaskHandle) -> Future[PlayerInputTaskSnapshot]:
        """Retry delivery of a completed action without rerunning that action."""
        record = self._record(handle)
        with self._lock:
            if self._closed:
                raise RuntimeError("player input coordinator is closed")
            if (record.execution is not PlayerTaskExecutionState.COMPLETED
                    or record.delivery is not PlayerTaskDeliveryState.RETRYABLE):
                raise PermissionError("task has no retryable completed presentation")
            if not self._runtime_binding_is_current(record):
                record.delivery = PlayerTaskDeliveryState.STALE
                record.recovery_code = "runtime_generation_changed"
                return self._future_view(self._completed_future(self._snapshot(record)))
            record.delivery = PlayerTaskDeliveryState.PENDING
            delivery_future: Future[PlayerInputTaskSnapshot] = Future()
            work = self._executor.submit(self._retry_delivery, record, delivery_future)
            work.add_done_callback(
                lambda done: self._finish_cancelled_delivery_job(
                    record, delivery_future, done,
                )
            )
            return self._future_view(delivery_future)

    def _finish_cancelled_delivery_job(
        self,
        record: _TaskRecord,
        delivery_future: Future[PlayerInputTaskSnapshot],
        work: Future[object],
    ) -> None:
        """Resolve queued retry handles when executor shutdown cancels the job."""
        if not work.cancelled():
            return
        with self._lock:
            if record.delivery is PlayerTaskDeliveryState.PENDING:
                record.recovery_code = "coordinator_closed"
            snapshot = self._snapshot(record)
        if not delivery_future.done():
            delivery_future.set_result(snapshot)

    def _retry_delivery(
        self, record: _TaskRecord, future: Future[PlayerInputTaskSnapshot],
    ) -> None:
        if not self._runtime_binding_is_current(record):
            with self._lock:
                record.delivery = PlayerTaskDeliveryState.STALE
                record.recovery_code = "runtime_generation_changed"
                snapshot = self._snapshot(record)
            if not future.done():
                future.set_result(snapshot)
            return
        try:
            outcome = record.context.run(
                self._retry_presentation_under_original_permit, record,
            )
        except Exception:
            with self._lock:
                if not self._runtime_binding_is_current(record):
                    record.delivery = PlayerTaskDeliveryState.STALE
                    record.recovery_code = "runtime_generation_changed"
                elif record.delivery is PlayerTaskDeliveryState.PENDING:
                    record.delivery = PlayerTaskDeliveryState.RETRYABLE
                    record.recovery_code = "presentation_retryable"
                snapshot = self._snapshot(record)
        else:
            with self._lock:
                record.delivery = PlayerTaskDeliveryState.DELIVERED
                record.outcome_status = self._safe_outcome_status(outcome)
                record.recovery_code = None
                snapshot = self._snapshot(record)
        if not future.done():
            future.set_result(snapshot)

    def _retry_presentation_under_original_permit(
        self, record: _TaskRecord,
    ) -> PlayerActionOutcome:
        """Serialize projection/delivery with Runtime generation changes.

        The captured ContextVar contains the admission-time permit. The fence
        read scope rejects a stale generation and prevents restore from
        advancing until this already-started projection has finished.
        """
        return self._service._retry_input_presentation_in_runtime_snapshot(record.request)

    @staticmethod
    def _completed_future(snapshot: PlayerInputTaskSnapshot) -> Future[PlayerInputTaskSnapshot]:
        future: Future[PlayerInputTaskSnapshot] = Future()
        future.set_result(snapshot)
        return future

    @staticmethod
    def _future_view(
        source: Future[PlayerInputTaskSnapshot],
    ) -> Future[PlayerInputTaskSnapshot]:
        """Expose completion without granting callers cancellation of owned work."""
        view: Future[PlayerInputTaskSnapshot] = Future()

        def relay(done: Future[PlayerInputTaskSnapshot]) -> None:
            if view.cancelled():
                return
            try:
                result = done.result()
            except BaseException as exc:
                if not view.done():
                    view.set_exception(exc)
            else:
                if not view.done():
                    view.set_result(result)

        source.add_done_callback(relay)
        return view

    def close(self) -> None:
        """Stop admission and revoke queued/running operations that have not entered commit."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = tuple(self._by_handle)
        for handle_id in handles:
            self._cancel(handle_id, expired=False)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _record(self, handle: PlayerInputTaskHandle) -> _TaskRecord:
        if not isinstance(handle, PlayerInputTaskHandle):
            raise TypeError("PlayerInputTaskHandle required")
        with self._lock:
            record = self._by_handle.get(handle.value)
        if record is None:
            raise KeyError("unknown player input task handle")
        return record

    def _runtime_binding_is_current(self, record: _TaskRecord) -> bool:
        return (
            self._fence.session_id == record.runtime_session_id
            and self._fence.restore_generation == record.restore_generation
            and not self._fence.frozen
            and not self._fence.retired
        )

    @staticmethod
    def _snapshot(record: _TaskRecord) -> PlayerInputTaskSnapshot:
        return PlayerInputTaskSnapshot(
            record.request.request_id, record.execution, record.delivery,
            record.outcome_status, record.recovery_code,
        )
