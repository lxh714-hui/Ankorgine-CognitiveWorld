from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Route:
    page: str
    params: dict[str, Any] = field(default_factory=dict)
    source_page: str | None = None
    source_params: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)


class NavigationStack:
    """Routes retain page parameters, origin, and optional restorable UI state."""

    def __init__(self, initial: Route | None = None) -> None:
        self.routes = [initial or Route("home")]

    @property
    def current(self) -> Route:
        return self.routes[-1]

    def push(self, page: str, **params: Any) -> Route:
        route = Route(page, params, self.current.page, dict(self.current.params))
        self.routes.append(route)
        return route

    def pop(self) -> Route:
        if len(self.routes) > 1:
            self.routes.pop()
        return self.current

    def path(self) -> tuple[str, ...]:
        return tuple(route.page for route in self.routes)
