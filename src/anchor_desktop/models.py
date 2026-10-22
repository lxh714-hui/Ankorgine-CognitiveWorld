from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    id: str
    name: str


@dataclass(frozen=True)
class Event:
    id: str
    time: str
    title: str
    description: str


@dataclass(frozen=True)
class Timeline:
    id: str
    name: str
    parent_id: str | None = None
    events: tuple[Event, ...] = ()


@dataclass(frozen=True)
class SaveSlot:
    id: str
    world_id: str
    name: str
    updated: str
    timeline_count: int


@dataclass(frozen=True)
class WorldProjection:
    world_id: str
    title: str
    summary: str
    notice: str
    characters: tuple[Character, ...]
    locations: tuple[str, ...]
    public_rules: tuple[str, ...]
    known_events: tuple[str, ...]
    stage_background: str
    speaker_id: str
    speaker_line: str
    narration: str


@dataclass(frozen=True)
class ActionEffectProjection:
    """Allowlisted display-only effect fields; not a canonical Event."""

    subject: str = ""
    action: str = ""
    effect: str = ""
