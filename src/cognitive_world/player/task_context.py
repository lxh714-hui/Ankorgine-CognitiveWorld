"""Internal binding for one asynchronous player request."""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Event
from time import monotonic

from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


class PlayerTaskAborted(RuntimeError):
    """A queued player task was cancelled, expired, or became stale."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


@dataclass(frozen=True)
class PlayerTaskBinding:
    fence: RuntimeWriteFence
    permit: RuntimeWritePermit
    cancellation: Event
    deadline: float
    player_session_id: str
    actor_id: str
    authorized_targets: tuple[str, ...]

    def check(self) -> None:
        if self.cancellation.is_set():
            raise PlayerTaskAborted("cancelled")
        if monotonic() >= self.deadline:
            self.cancellation.set()
            self.fence.revoke_uncommitted(self.permit)
            raise PlayerTaskAborted("expired")
        try:
            self.fence.require_current_permit(self.permit)
        except PermissionError as exc:
            raise PlayerTaskAborted("stale") from exc


_active_player_task: ContextVar[PlayerTaskBinding | None] = ContextVar(
    "cognitive_world_active_player_task", default=None,
)


def activate_player_task(binding: PlayerTaskBinding) -> Token[PlayerTaskBinding | None]:
    return _active_player_task.set(binding)


def reset_player_task(token: Token[PlayerTaskBinding | None]) -> None:
    _active_player_task.reset(token)


def check_active_player_task() -> None:
    binding = _active_player_task.get()
    if binding is not None:
        binding.check()


def active_player_task() -> PlayerTaskBinding | None:
    return _active_player_task.get()
