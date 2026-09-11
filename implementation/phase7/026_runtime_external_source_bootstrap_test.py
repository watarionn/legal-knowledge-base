from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
PATH = HERE / "025_runtime_external_source_bootstrap.py"
spec = importlib.util.spec_from_file_location("phase74_runtime_external_bootstrap", PATH)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


class ClassificationTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(MODULE.classify_step(set(), ("a", "b")), "empty")

    def test_ready(self):
        self.assertEqual(MODULE.classify_step({"a", "b"}, ("a", "b")), "ready")

    def test_partial(self):
        self.assertEqual(MODULE.classify_step({"a"}, ("a", "b")), "partial")


class PlanTest(unittest.TestCase):
    def test_schema_files_exist_in_dependency_order(self):
        self.assertEqual(
            [name for name, _path, _objects in MODULE.DDL_STEPS],
            ["foundation", "parliamentary", "official_gazette", "ndl_metadata", "linkage"],
        )
        for _name, path, objects in MODULE.DDL_STEPS:
            self.assertTrue(path.is_file(), path)
            self.assertTrue(objects)

    def test_base_prerequisites_are_explicit(self):
        self.assertEqual(
            MODULE.BASE_REQUIRED,
            ("ingestion_run", "source_file", "law", "law_revision", "provision_node"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
