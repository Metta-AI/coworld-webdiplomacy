import json
import unittest
from pathlib import Path

from tools.ci_scope import TEMPLATE, scope


class CiScope(unittest.TestCase):
    def setUp(self):
        self.template = Path(TEMPLATE).read_text()

    def edited(self, edit):
        manifest = json.loads(self.template)
        edit(manifest)
        return json.dumps(manifest)

    def test_docs_and_optimizer_changes_skip_the_image_checks(self):
        resynced = self.edited(lambda manifest: manifest["game"]["docs"]["readme"].update(value="new text"))
        changed = ["README.md", "docs/replay.md", TEMPLATE, "tools/build_intro_slides.py", "optimizer/install.sh"]
        self.assertEqual(scope(changed, self.template, resynced), dict(images=False, optimizer=True))
        self.assertEqual(scope(["AGENTS.md"], self.template, self.template), dict(images=False, optimizer=False))

    def test_image_sources_and_checks_run_the_image_checks(self):
        for path in ("adapter/boot.py", "players/api.py", "php/wdc_start.php", "config/nginx.conf", "webdiplomacy"):
            self.assertTrue(scope([path], self.template, self.template)["images"], path)
        self.assertTrue(scope(["tools/check_press.py"], self.template, self.template)["images"])

    def test_dependencies_and_workflow_run_everything(self):
        for path in ("uv.lock", "pyproject.toml", ".github/workflows/adapter-tests.yml"):
            self.assertEqual(scope([path], self.template, self.template), dict(images=True, optimizer=True), path)

    def test_manifest_runtime_change_runs_the_image_checks(self):
        shorter = self.edited(lambda manifest: manifest["variants"][0]["game_config"].update(end_year=1902))
        self.assertTrue(scope([TEMPLATE], self.template, shorter)["images"])
        self.assertTrue(scope([TEMPLATE], None, self.template)["images"])


if __name__ == "__main__":
    unittest.main()
