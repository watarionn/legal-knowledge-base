from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SNAPSHOT = _load(
    "legal_kb_phase7_runtime_snapshot_test_target",
    "007_official_bulk_snapshot.py",
)
PIPELINE = _load(
    "legal_kb_phase7_runtime_pipeline_test_target",
    "009_runtime_corpus_builder.py",
)


class OfficialBulkSnapshotTest(unittest.TestCase):
    def test_single_archive_manifest_is_phase4_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "all_xml.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "129AC0000000089_20260401_000000000000000.xml",
                    "<Law><LawNum>民法</LawNum></Law>",
                )
                archive.writestr(
                    "324AC0000000100_20250401_000000000000000.xml",
                    "<Law><LawNum>建設業法</LawNum></Law>",
                )
            manifest = SNAPSHOT.inspect_archive(
                archive_path,
                date(2026, 9, 10),
            )
            self.assertEqual(manifest["captured_on"], "2026-09-10")
            self.assertEqual(manifest["totals"]["zip_part_count"], 1)
            self.assertEqual(manifest["totals"]["xml_count"], 2)
            self.assertEqual(manifest["totals"]["unique_law_id_count"], 2)
            self.assertEqual(manifest["parts"][0]["name"], "all_xml.zip")
            self.assertEqual(len(manifest["parts"][0]["sha256"]), 64)

    def test_unknown_xml_filename_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "all_xml.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("not-a-revision.xml", "<Law/>")
            with self.assertRaisesRegex(AssertionError, "unrecognized"):
                SNAPSHOT.inspect_archive(archive_path, date(2026, 9, 10))


class RuntimePipelineContractTest(unittest.TestCase):
    def test_text_index_is_built_after_chunk_population(self):
        pre_names = [path.name for path in PIPELINE.PRE_CHUNK_DDL]
        post_names = [path.name for path in PIPELINE.POST_CHUNK_DDL]
        self.assertIn("022_retrieval_chunk_schema.sql", pre_names)
        self.assertNotIn("033_hybrid_retrieval_schema.sql", pre_names)
        self.assertEqual(post_names, ["033_hybrid_retrieval_schema.sql"])

    def test_runtime_does_not_require_embedding_schema(self):
        all_names = [
            path.name
            for path in (*PIPELINE.PRE_CHUNK_DDL, *PIPELINE.POST_CHUNK_DDL)
        ]
        self.assertNotIn("027_embedding_schema.sql", all_names)


if __name__ == "__main__":
    unittest.main()
