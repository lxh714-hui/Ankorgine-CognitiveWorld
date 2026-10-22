"""Per-action bounded provider-call accounting shared by interpretation and Resolution."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass
class _CallBudget:
    maximum: int
    used: int = 0


_CURRENT: ContextVar[_CallBudget | None] = ContextVar("causal_provider_call_budget", default=None)


@contextmanager
def provider_call_scope(maximum_calls: int = 1) -> Iterator[None]:
    current = _CURRENT.get()
    if current is not None:
        yield
        return
    if isinstance(maximum_calls, bool) or maximum_calls < 0:
        raise ValueError("maximum_calls must be non-negative")
    token = _CURRENT.set(_CallBudget(maximum_calls))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def claim_provider_call() -> bool:
    budget = _CURRENT.get()
    if budget is None:
        # Direct policy calls are individually bounded to a single request.
        with provider_call_scope(1):
            return claim_provider_call()
    if budget.used >= budget.maximum:
        return False
    budget.used += 1
    return True


def provider_calls_used() -> int:
    budget = _CURRENT.get()
    return 0 if budget is None else budget.used
