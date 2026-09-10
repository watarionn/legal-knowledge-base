from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import check_github_actions_cost_guard as guard


class ActiveWorkflowFilesTest(unittest.TestCase):
    def test_empty_workflow_directory_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github" / "workflows").mkdir(parents=True)
            self.assertEqual(guard.active_workflow_files(root), [])

    def test_yaml_workflow_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / ".github" / "workflows"
            directory.mkdir(parents=True)
            (directory / "tests.yml").write_text("name: Tests\n", encoding="utf-8")
            self.assertEqual(guard.active_workflow_files(root), [".github/workflows/tests.yml"])

    def test_non_yaml_readme_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / ".github" / "workflows"
            directory.mkdir(parents=True)
            (directory / "README.md").write_text("guard\n", encoding="utf-8")
            self.assertEqual(guard.active_workflow_files(root), [])


if __name__ == "__main__":
    unittest.main()
