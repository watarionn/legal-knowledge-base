from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
TARGET = HERE / "031_application_state_bootstrap.py"
spec = importlib.util.spec_from_file_location("phase75_app_state_bootstrap", TARGET)
assert spec and spec.loader
BOOT = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = BOOT
spec.loader.exec_module(BOOT)


class ClassificationTest(unittest.TestCase):
    def test_empty(self):
        state, missing = BOOT.classify_state(set())
        self.assertEqual(state, "empty")
        self.assertEqual(missing, BOOT.REQUIRED_RELATIONS)

    def test_ready(self):
        state, missing = BOOT.classify_state(set(BOOT.REQUIRED_RELATIONS))
        self.assertEqual((state, missing), ("ready", ()))

    def test_partial(self):
        state, missing = BOOT.classify_state({BOOT.REQUIRED_RELATIONS[0]})
        self.assertEqual(state, "partial")
        self.assertEqual(set(missing), set(BOOT.REQUIRED_RELATIONS[1:]))


class PlanTest(unittest.TestCase):
    def test_schema_file_exists(self):
        self.assertTrue(BOOT.SCHEMA_PATH.is_file())

    def test_schema_declares_all_relations(self):
        sql = BOOT.SCHEMA_PATH.read_text(encoding="utf-8")
        for relation in BOOT.REQUIRED_RELATIONS:
            self.assertIn(f"CREATE TABLE {relation}", sql)

    def test_no_credentials_are_embedded(self):
        text = TARGET.read_text(encoding="utf-8").lower()
        self.assertNotIn("postgresql://", text)
        self.assertIn('"database_url_recorded": false', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
