"""Read bundled world definitions without giving their metadata runtime authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cognitive_world.content.llm import parse_generation_proposal
from cognitive_world.content.pipeline import ContentRegistry, ContentValidator, GenerationProposal
from cognitive_world.safety.governance import SafetyDisposition, SafetyInput, UniversalSafetyGovernance

from .models import WorldProjection


@dataclass(frozen=True)
class WorldPackage:
    world_id: str
    title: str
    summary: str
    notice: str
    scenario_template_id: str
    player_character_key: str
    proposal: GenerationProposal
    opening: str = ""
    english_title: str = ""
    listed: bool = True

    def projection(self) -> WorldProjection:
        # Catalog metadata is public. Scenario participants, location graph and
        # mechanisms are not player Observations and must not be projected.
        return WorldProjection(
            self.world_id, self.title, self.summary, self.notice,
            (), (), (), (), "", "", "", "",
        )


class WorldPackageCatalog:
    """Application-owned local content; registration still uses Core validation."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._packages: dict[str, WorldPackage] = {}
        if not self.directory.is_dir():
            raise FileNotFoundError(self.directory)
        safety = UniversalSafetyGovernance()
        for folder in sorted(self.directory.iterdir()):
            if not folder.is_dir():
                continue
            manifest_path = folder / "manifest.json"
            content_path = folder / "content.json"
            if not manifest_path.is_file() or not content_path.is_file():
                raise ValueError(f"incomplete world package: {folder.name}")
            raw = manifest_path.read_text(encoding="utf-8")
            if len(raw) > 4000:
                raise ValueError("world manifest exceeds its bound")
            def unique_pairs(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("duplicate world manifest field")
                    value[key] = item
                return value

            manifest = json.loads(raw, object_pairs_hook=unique_pairs)
            required = {"world_id", "title", "summary", "notice",
                        "scenario_template_id", "player_character_key"}
            optional = {"opening", "english_title", "listed"}
            if (type(manifest) is not dict or not required <= set(manifest)
                    or set(manifest) - required - optional):
                raise ValueError("world manifest has an invalid schema")
            for name, value in manifest.items():
                if name == "listed":
                    if type(value) is not bool:
                        raise ValueError("world listing flag must be boolean")
                    continue
                maximum = 2000 if name == "opening" else 1000
                if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                    raise ValueError("world manifest contains invalid text")
            if manifest["world_id"] != folder.name or manifest["world_id"] in self._packages:
                raise ValueError("world package identity is inconsistent")
            for name in ("title", "summary", "notice", "opening", "english_title"):
                if name not in manifest:
                    continue
                assessment = safety.assess(SafetyInput(
                    actor_id="world_package", source="world_content_hint",
                    intent=manifest[name], context="untrusted public world package metadata",
                ))
                if assessment.disposition in {SafetyDisposition.REFUSE, SafetyDisposition.CLARIFY}:
                    raise PermissionError("world package metadata failed safety review")
            proposal = parse_generation_proposal(content_path.read_text(encoding="utf-8"))
            registry = ContentRegistry(ContentValidator(safety))
            registry.register(proposal)
            scenario = registry.scenario(manifest["scenario_template_id"])
            if manifest["player_character_key"] not in {key for key, _, _ in scenario.characters}:
                raise ValueError("world player key is absent from its scenario")
            self._packages[manifest["world_id"]] = WorldPackage(**manifest, proposal=proposal)

    def list_worlds(self) -> tuple[WorldProjection, ...]:
        return tuple(package.projection() for package in self._packages.values() if package.listed)

    def legacy_worlds(self) -> tuple[WorldProjection, ...]:
        """Unlisted package identities remain available for signed save recovery."""
        return tuple(package.projection() for package in self._packages.values() if not package.listed)

    def package(self, world_id: str) -> WorldPackage:
        return self._packages[world_id]
