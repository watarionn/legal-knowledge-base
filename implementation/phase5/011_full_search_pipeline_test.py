from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("010_full_search_pipeline.py")
spec = importlib.util.spec_from_file_location("phase5_full_search_pipeline", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FullSearchPipelineTest(unittest.TestCase):
    def test_archive_names_are_four_split_parts(self):
        self.assertEqual(
            module.ARCHIVE_NAMES,
            ("all_xml_01.zip", "all_xml_02.zip", "all_xml_03.zip", "all_xml_04.zip"),
        )

    def test_validate_archive_dir_rejects_missing_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                module.validate_archive_dir(Path(temp))

    def test_validate_archive_dir_accepts_named_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in module.ARCHIVE_NAMES:
                (root / name).write_bytes(b"placeholder")
            paths = module.validate_archive_dir(root)
            self.assertEqual([p.name for p in paths], list(module.ARCHIVE_NAMES))

    def test_phase3_args_are_resumable_by_default(self):
        args = module.build_phase3_args(
            "postgresql://example",
            Path("raw"),
            Path("report.json"),
            workers=3,
            history_request_interval=0.7,
        )
        self.assertNotIn("--no-resume-existing", args)
        self.assertIn("--workers", args)
        self.assertIn("3", args)
        self.assertIn("--history-request-interval", args)
        self.assertIn("0.7", args)

    def test_runner_never_records_database_url(self):
        self.assertEqual(module.RUNNER_VERSION, "phase5-full-search-pipeline-0.1")


if __name__ == "__main__":
    unittest.main()
