"""Bundled world data goes through the existing content preflight."""

import json
import shutil
from pathlib import Path

import pytest

from anchor_desktop.engine import BundledWorldCatalogGateway, FeatureUnavailable
from anchor_desktop.world_packages import WorldPackageCatalog
from cognitive_world.content.pipeline import ContentRegistry, ContentValidator
from cognitive_world.safety.governance import UniversalSafetyGovernance


PACKAGES = Path(__file__).parents[1] / "src" / "anchor_desktop" / "worlds"


def test_two_independent_bundled_worlds_validate_without_core_scene_rules():
    catalog = WorldPackageCatalog(PACKAGES)
    worlds = catalog.list_worlds()
    assert len(worlds) >= 2
    assert len({world.world_id for world in worlds}) == len(worlds)
    for world in worlds:
        package = catalog.package(world.world_id)
        registry = ContentRegistry(ContentValidator(UniversalSafetyGovernance()))
        registry.register(package.proposal)
        scenario = registry.scenario(package.scenario_template_id)
        assert package.player_character_key in {key for key, _, _ in scenario.characters}
        assert world.speaker_line == "" and world.narration == ""
        assert world.known_events == () and world.public_rules == ()


def test_catalog_does_not_expose_unverified_saves():
    gateway = BundledWorldCatalogGateway(PACKAGES)
    for world in gateway.list_worlds():
        assert gateway.read_world_projection(world.world_id) == world
        assert gateway.list_saves(world.world_id) == ()
        with pytest.raises(FeatureUnavailable, match="尚无可恢复"):
            gateway.read_world_projection(world.world_id, "unverified-save")


def test_invalid_package_is_rejected_before_any_runtime_can_start(tmp_path):
    folder = tmp_path / "clockwork-library"
    shutil.copytree(PACKAGES / "clockwork-library", folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["player_character_key"] = "absent-player"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="player key is absent"):
        WorldPackageCatalog(tmp_path)
