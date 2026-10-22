"""In-process final-write fencing across runtime generations."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import RLock
from threading import get_ident
from typing import Iterator
from uuid import uuid4
from weakref import WeakValueDictionary
from weakref import ReferenceType, ref


_RESTORE_COORDINATOR_AUTHORITY = object()


_active_permit: ContextVar["RuntimeWritePermit | None"] = ContextVar(
    "cognitive_world_runtime_write_permit", default=None
)


@dataclass(frozen=True)
class RuntimeWritePermit:
    """Opaque capability captured by one operation at its start."""

    session_id: str
    restore_generation: int
    _authority: object = field(repr=False, compare=False)
    _nonce: object = field(repr=False, compare=False)

    def __deepcopy__(self, memo: dict[int, object]) -> "RuntimeWritePermit":
        return self


class RuntimeWriteFence:
    """Serialize generation changes with final authoritative commits.

    The lock is held for the entire guarded commit. Thus a freeze either waits
    for an already-started commit to finish or invalidates the permit before
    the commit starts; there is no check-then-write window.
    """

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid4())
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be non-empty")
        self._generation = 0
        self._frozen = False
        self._staged_only = False
        self._retired = False
        self._coordinator_frozen = False
        self._recovery_required = False
        self._authority = object()
        self._issued: WeakValueDictionary[int, RuntimeWritePermit] = WeakValueDictionary()
        self._commit_started: dict[int, ReferenceType[RuntimeWritePermit]] = {}
        self._event_history_verification_context: (
            tuple[object, str, object, object] | None
        ) = None
        self._lock = RLock()
        self._commit_thread: int | None = None
        self._commit_depth = 0

    def _bind_event_history_verifier(
        self, *, history: object, codec: object, trust: object,
    ) -> None:
        """Bind the Runtime's EventHistory verifier without changing permit authority."""
        from cognitive_world.core.persistence import PersistedValueCodec
        from cognitive_world.event.history import EventHistory

        if type(history) is not EventHistory:
            raise TypeError("Runtime EventHistory verifier requires the canonical history")
        if not isinstance(codec, PersistedValueCodec):
            raise TypeError("Runtime EventHistory verifier requires PersistedValueCodec")
        if not callable(getattr(trust, "verify", None)):
            raise TypeError("Runtime EventHistory verifier requires persistence trust")
        timeline_id = history.timeline_id
        if not isinstance(timeline_id, str) or not timeline_id:
            raise PermissionError("Runtime EventHistory verifier requires a bound Timeline")

        context = (history, timeline_id, codec, trust)
        with self._lock:
            prior = self._event_history_verification_context
            if prior is not None:
                different_binding = (
                    any(prior[index] is not context[index] for index in (0, 2, 3))
                    or prior[1] != context[1]
                )
                if different_binding:
                    raise PermissionError(
                        "Runtime fence EventHistory verifier is immutable once bound"
                    )
            self._event_history_verification_context = context

    def _verify_complete_event_history(self, history: object):
        """Verify a candidate history with this Runtime's trusted persistence root."""
        from cognitive_world.event.history import EventHistory

        if type(history) is not EventHistory:
            raise TypeError("formal Memory/v2 requires a canonical EventHistory")
        with self._lock:
            context = self._event_history_verification_context
        if context is None:
            raise PermissionError("Runtime has no trusted EventHistory verifier for Memory/v2")
        canonical_history, expected_timeline_id, codec, trust = context
        if (canonical_history.timeline_id != expected_timeline_id
                or history.timeline_id != expected_timeline_id):
            raise PermissionError("EventHistory Timeline differs from the Runtime verifier")
        if history is not canonical_history:
            raise PermissionError("EventHistory is not bound to this Runtime")
        return history.verify_persisted_lineage(codec=codec, trust=trust)

    @property
    def restore_generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def frozen(self) -> bool:
        with self._lock:
            return self._frozen

    @property
    def retired(self) -> bool:
        with self._lock:
            return self._retired

    @property
    def recovery_required(self) -> bool:
        with self._lock:
            return self._recovery_required

    def mark_recovery_required(self) -> None:
        """Latch a non-replayable world commit failure at the final-write lock."""
        with self._lock:
            if not self._recovery_required:
                self._recovery_required = True
                self._frozen = True
                self._generation += 1

    @property
    def staged_only(self) -> bool:
        """Whether activation requires the one-shot RestoreCoordinator path."""
        with self._lock:
            return self._staged_only

    def capture(self) -> RuntimeWritePermit:
        with self._lock:
            if self._frozen or self._retired:
                raise PermissionError("runtime is frozen or retired; no new operation may start")
            nonce = object()
            permit = RuntimeWritePermit(
                self.session_id, self._generation, self._authority, nonce
            )
            self._issued[id(nonce)] = permit
            return permit

    @contextmanager
    def operation(self) -> Iterator[RuntimeWritePermit]:
        permit = self.capture()
        token = _active_permit.set(permit)
        try:
            yield permit
        finally:
            _active_permit.reset(token)

    @contextmanager
    def commit_scope(self) -> Iterator[RuntimeWritePermit]:
        """Validate and hold the generation lock across a canonical mutation."""
        permit = _active_permit.get()
        if permit is None:
            raise PermissionError("authoritative write has no captured runtime context")
        with self._lock:
            if (
                not isinstance(permit, RuntimeWritePermit)
                or permit._authority is not self._authority
                or self._issued.get(id(permit._nonce)) is not permit
                or permit.session_id != self.session_id
                or permit.restore_generation != self._generation
                or self._frozen
            ):
                raise PermissionError("runtime write context is stale, foreign, or frozen")
            self._mark_commit_started_locked(permit)
            thread_id = get_ident()
            if self._commit_depth and self._commit_thread != thread_id:
                raise RuntimeError("runtime commit lock ownership is inconsistent")
            self._commit_thread = thread_id
            self._commit_depth += 1
            try:
                yield permit
            finally:
                self._commit_depth -= 1
                if self._commit_depth == 0:
                    self._commit_thread = None

    def require_current_permit(self, permit: RuntimeWritePermit) -> None:
        """Check an operation capability without acquiring write authority."""
        with self._lock:
            if (
                not isinstance(permit, RuntimeWritePermit)
                or permit._authority is not self._authority
                or self._issued.get(id(permit._nonce)) is not permit
                or permit.session_id != self.session_id
                or permit.restore_generation != self._generation
                or self._frozen
                or self._retired
            ):
                raise PermissionError("runtime operation capability is stale or unavailable")

    def revoke_uncommitted(self, permit: RuntimeWritePermit) -> bool:
        """Invalidate one operation unless it already entered its final commit section.

        The Runtime lock serializes this decision with ``commit_scope``. A
        ``False`` result means the operation crossed the non-cancellable
        commit boundary and its effects must be observed, never rolled back.
        """
        if not isinstance(permit, RuntimeWritePermit):
            return False
        with self._lock:
            if permit._authority is not self._authority or permit.session_id != self.session_id:
                return False
            marker = self._commit_started.get(id(permit._nonce))
            if marker is not None and marker() is permit:
                return False
            issued = self._issued.get(id(permit._nonce))
            if issued is permit:
                self._issued.pop(id(permit._nonce), None)
            return True

    def _clear_commit_marker(self, permit: RuntimeWritePermit) -> None:
        """Release per-operation lifecycle metadata after its host task is terminal."""
        with self._lock:
            key = id(permit._nonce)
            marker = self._commit_started.get(key)
            if marker is not None and marker() is permit:
                self._commit_started.pop(key, None)

    def _mark_commit_started_locked(self, permit: RuntimeWritePermit) -> None:
        key = id(permit._nonce)
        fence_ref = ref(self)

        def discard(dead_ref: ReferenceType[RuntimeWritePermit]) -> None:
            fence = fence_ref()
            if fence is None:
                return
            with fence._lock:
                if fence._commit_started.get(key) is dead_ref:
                    fence._commit_started.pop(key, None)

        self._commit_started[key] = ref(permit, discard)

    @contextmanager
    def snapshot_scope(self) -> Iterator[RuntimeWritePermit]:
        """Hold the same fence across a consistent multi-store read.

        Snapshot capture must run inside an operation. This lock coordinates
        only canonical writers that are bound to this fence; it is not a
        process-wide lock for private-field mutation or unrelated callbacks.
        """
        permit = _active_permit.get()
        if permit is None:
            raise PermissionError("snapshot capture has no captured runtime context")
        with self._lock:
            if (
                not isinstance(permit, RuntimeWritePermit)
                or permit._authority is not self._authority
                or self._issued.get(id(permit._nonce)) is not permit
                or permit.session_id != self.session_id
                or permit.restore_generation != self._generation
                or self._frozen
            ):
                raise PermissionError("snapshot runtime context is stale, foreign, or frozen")
            thread_id = get_ident()
            if self._commit_depth and self._commit_thread != thread_id:
                raise RuntimeError("runtime critical-section ownership is inconsistent")
            self._commit_thread = thread_id
            self._commit_depth += 1
            try:
                yield permit
            finally:
                self._commit_depth -= 1
                if self._commit_depth == 0:
                    self._commit_thread = None

    def freeze_and_advance(self) -> int:
        """Invalidate all outstanding permits and refuse new operations."""
        with self._lock:
            if self._commit_depth and self._commit_thread == get_ident():
                raise RuntimeError("cannot advance runtime generation from inside a commit")
            self._frozen = True
            self._generation += 1
            return self._generation

    def unfreeze(self) -> None:
        """Allow new operations; permits from previous generations stay stale."""
        with self._lock:
            if self._recovery_required:
                raise PermissionError("Runtime requires explicit recovery")
            if self._staged_only:
                raise PermissionError("a staged-only Runtime fence cannot be activated")
            if self._retired or self._coordinator_frozen:
                raise PermissionError("Runtime activation is controlled by RestoreCoordinator")
            if not self._frozen:
                raise RuntimeError("runtime is not frozen")
            self._frozen = False

    def seal_staged_only(self) -> int:
        """Seal this fence until a RestoreCoordinator-issued one-shot activation."""
        with self._lock:
            if self._commit_depth:
                raise RuntimeError("cannot seal a Runtime fence during a commit")
            self._frozen = True
            self._generation += 1
            self._staged_only = True
            return self._generation


    def _freeze_for_recovery(self, authority: object) -> int:
        """Coordinator-only freeze that also blocks public unfreeze calls."""
        if authority is not _RESTORE_COORDINATOR_AUTHORITY:
            raise PermissionError("only RestoreCoordinator may freeze for recovery")
        with self._lock:
            if self._commit_depth and self._commit_thread == get_ident():
                raise RuntimeError("cannot freeze Runtime from inside its own commit")
            if self._retired:
                raise PermissionError("Runtime has already been retired")
            self._frozen = True
            self._coordinator_frozen = True
            self._generation += 1
            return self._generation

    def _resume_after_failed_recovery(self, authority: object) -> None:
        """Resume an old Runtime with its old permits invalidated."""
        if authority is not _RESTORE_COORDINATOR_AUTHORITY:
            raise PermissionError("only RestoreCoordinator may resume a frozen Runtime")
        with self._lock:
            if self._recovery_required:
                raise PermissionError("failed restore cannot resume an inconsistent Runtime")
            if self._retired or not self._coordinator_frozen or not self._frozen:
                raise RuntimeError("Runtime is not recoverably frozen")
            self._coordinator_frozen = False
            self._frozen = False

    def _retire_after_recovery(self, authority: object) -> None:
        """Permanently invalidate this Runtime after a new one is published."""
        if authority is not _RESTORE_COORDINATOR_AUTHORITY:
            raise PermissionError("only RestoreCoordinator may retire a Runtime")
        with self._lock:
            if not self._coordinator_frozen or not self._frozen:
                raise RuntimeError("old Runtime must remain coordinator-frozen before retirement")
            if self._commit_depth:
                raise RuntimeError("cannot retire Runtime while a commit is active")
            self._generation += 1
            self._retired = True
            self._coordinator_frozen = False
            self._frozen = True

    def _activate_staged_and_publish(self, authority: object, publish, *, validate=None) -> None:
        """Activate only while holding the fence lock across publication.

        Runtime operations block in ``capture`` until the publisher has swapped
        the active pointer. If any pre-publication step fails, the fence is
        returned to staged-only, frozen state with its generation advanced.
        """
        if authority is not _RESTORE_COORDINATOR_AUTHORITY:
            raise PermissionError("only RestoreCoordinator may activate a staged Runtime")
        if not callable(publish):
            raise TypeError("publication callback must be callable")
        if validate is not None and not callable(validate):
            raise TypeError("publication validator must be callable")
        with self._lock:
            if (not self._staged_only or not self._frozen or self._retired
                    or self._commit_depth):
                raise PermissionError("Runtime is not an activatable staged instance")
            # The final staged check and publication share this lock. No
            # fence-governed writer can enter between verification and swap.
            if validate is not None:
                validate()
            self._generation += 1
            self.session_id = str(uuid4())
            self._staged_only = False
            self._frozen = False
            try:
                publish()
            except BaseException:
                self._frozen = True
                self._staged_only = True
                self._generation += 1
                raise

    @staticmethod
    def current_permit() -> RuntimeWritePermit | None:
        """Return the ambient captured context for propagation/diagnostics."""
        return _active_permit.get()

    @staticmethod
    def bind_current_permit() -> RuntimeWritePermit | None:
        """Capture the originating operation when a proposal is constructed."""
        return _active_permit.get()

    def require_candidate_origin(self, permit: RuntimeWritePermit | None) -> None:
        """Reject a proposal created outside or in another runtime generation."""
        current = _active_permit.get()
        if permit is None or current is not permit:
            raise PermissionError("candidate is not bound to this runtime operation")
        # commit_scope performs the authoritative current-generation check.
        if permit._authority is not self._authority:
            raise PermissionError("candidate belongs to another runtime session")
