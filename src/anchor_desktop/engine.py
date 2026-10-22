"""Desktop-only projection boundary for a future trusted product host.

M0.5 deliberately has no default Runtime or world package. A host must supply
an authorized gateway in a later phase; the installed desktop never fabricates
worlds, saves, Events, or successful commands.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import ActionEffectProjection, SaveSlot, Timeline, WorldProjection


class FeatureUnavailable(RuntimeError):
    """The current desktop host has not connected this capability."""


@runtime_checkable
class EngineGateway(Protocol):
    def list_worlds(self) -> tuple[WorldProjection, ...]: ...
    def read_world_projection(self, world_id: str, save_id: str | None = None) -> WorldProjection: ...
    def list_saves(self, world_id: str) -> tuple[SaveSlot, ...]: ...
    def list_timelines(self, save_id: str) -> tuple[Timeline, ...]: ...
    def available_targets(self, world_id: str) -> tuple[str, ...]: ...
    def subscribe_performance(self, callback: Callable[[ActionEffectProjection], None]) -> Callable[[], None]: ...


class UnavailableEngineGateway:
    """Honest default: no product host or world package is configured."""

    status_message = "尚未配置世界包与可信运行宿主。请完成 M1 后再进入世界。"

    def list_worlds(self) -> tuple[WorldProjection, ...]:
        return ()

    def read_world_projection(self, world_id: str, save_id: str | None = None) -> WorldProjection:
        raise FeatureUnavailable(self.status_message)

    def list_saves(self, world_id: str) -> tuple[SaveSlot, ...]:
        return ()

    def list_timelines(self, save_id: str) -> tuple[Timeline, ...]:
        return ()

    def available_targets(self, world_id: str) -> tuple[str, ...]:
        return ()

    def subscribe_performance(self, callback: Callable[[ActionEffectProjection], None]) -> Callable[[], None]:
        return lambda: None


class BundledWorldCatalogGateway(UnavailableEngineGateway):
    """Read-only product catalog while trusted Runtime composition is pending."""

    status_message = "世界包已通过结构检查；运行宿主与读档入口尚未接入。"

    def __init__(self, directory: Path | None = None) -> None:
        from .world_packages import WorldPackageCatalog

        self.catalog = WorldPackageCatalog(directory or Path(__file__).parent / "worlds")

    def list_worlds(self) -> tuple[WorldProjection, ...]:
        return self.catalog.list_worlds()

    def read_world_projection(self, world_id: str, save_id: str | None = None) -> WorldProjection:
        if save_id is not None:
            raise FeatureUnavailable("尚无可恢复的正式存档。")
        return self.catalog.package(world_id).projection()
