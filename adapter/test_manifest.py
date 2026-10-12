"""Check that published configuration and onboarding match the runnable sources."""

import json
import re
import unittest
from pathlib import Path

from adapter.config import EpisodeConfig


class ManifestContract(unittest.TestCase):
    def test_schema_and_embedded_docs_are_current(self):
        manifest = json.loads(Path("coworld_manifest_template.json").read_text())
        game = manifest["game"]
        self.assertEqual(game["config_schema"], EpisodeConfig.model_json_schema())
        self.assertEqual(json.loads(Path("config-schema.json").read_text()), game["config_schema"])
        for document, source in (
            (game["docs"]["readme"], "README.md"),
            (game["protocols"]["player"], "docs/protocol.md"),
            (game["protocols"]["global"], "docs/replay.md"),
        ):
            self.assertEqual(document, {"type": "text", "value": Path(source).read_text()}, source)
        for variant in manifest["variants"]:
            EpisodeConfig(tokens=list("abcdefg"), **variant["game_config"])
        guide = next(page for page in game["docs"]["pages"] if page["id"] == "write-a-policy")
        self.assertEqual(guide["content"], {"type": "text", "value": Path("docs/write-a-policy.md").read_text()})
        EpisodeConfig(tokens=list("abcdefg"), **manifest["certification"]["game_config"])

    def test_changelog_names_the_coworld_version_being_built(self):
        # Optimizers read the changelog to learn about a new version; a bump needs an entry.
        built = re.search(r"coworld build --version (\S+)", Path("README.md").read_text()).group(1)
        newest = re.search(r"^## \d{4}-\d{2}-\d{2} · Coworld (\S+) · ", Path("CHANGELOG.md").read_text(), re.M)
        self.assertEqual(newest.group(1), built)

    def test_certification_exercises_all_bundled_players_within_short_fixture(self):
        manifest = json.loads(Path("coworld_manifest_template.json").read_text())
        fixture = manifest["certification"]
        roster = [seat["player_id"] for seat in fixture["players"]]
        self.assertEqual(roster, ["random"] + ["hold"] * 6)
        self.assertEqual(set(roster), {player["id"] for player in manifest["player"]})
        config = EpisodeConfig(tokens=list("abcdefg"), **fixture["game_config"])
        self.assertEqual((config.seed, config.press, config.end_year), (0, "NoPress", 1901))
        self.assertEqual((config.phase_minutes, config.retreat_build_minutes), (1, 1))
        self.assertFalse(config.render_maps)
        self.assertLess(config.episode_budget_seconds, 60)
