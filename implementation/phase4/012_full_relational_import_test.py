from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

PHASE4_DIR = Path(__file__).resolve().parent
SCRIPT = PHASE4_DIR / "011_full_relational_import.py"
spec = importlib.util.spec_from_file_location("phase4_full_import", SCRIPT)
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)

PG_SPEC = importlib.util.spec_from_file_location(
    "phase4_pg_import", PHASE4_DIR / "009_postgres_import.py"
)
PG_IMPORT = importlib.util.module_from_spec(PG_SPEC)
sys.modules[PG_SPEC.name] = PG_IMPORT
PG_SPEC.loader.exec_module(PG_IMPORT)

RID1 = "503AC0000000004_20210203_000000000000000"
RID2 = "428AC1000000067_20160603_000000000000000"


def make_zip(path: Path, entries: list[tuple[str, bytes]]) -> tuple[int, str]:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    raw = path.read_bytes()
    return len(raw), sha256(raw).hexdigest()


class FullRelationalImportTest(unittest.TestCase):
    def test_copy_sql_and_method_guard(self):
        self.assertEqual(
            PG_IMPORT._copy_sql("provision_node", ("node_id", "document_id")),
            "COPY legal_kb.provision_node (node_id, document_id) FROM STDIN",
        )
        with self.assertRaises(ValueError):
            PG_IMPORT.insert_parsed_document(None, None, method="invalid")

    def test_member_source_id_is_deterministic_and_path_sensitive(self):
        a = MODULE.member_source_file_id("a" * 64, "x/a.xml")
        b = MODULE.member_source_file_id("a" * 64, "x/a.xml")
        c = MODULE.member_source_file_id("a" * 64, "y/a.xml")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("zip-member:"))

    def test_archive_source_id_uses_normalized_sha(self):
        self.assertEqual(
            MODULE.archive_source_file_id("A" * 64),
            "archive-sha256:" + "a" * 64,
        )

    def test_archive_preflight_and_member_collection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            zip_path = root / "one.zip"
            size, digest = make_zip(
                zip_path,
                [
                    (f"{RID1}/{RID1}.xml", b"<Law/>"),
                    (f"{RID2}/{RID2}.xml", b"<Law/>"),
                ],
            )
            manifest = {
                "captured_on": "2026-09-04",
                "parts": [
                    {
                        "name": "one.zip",
                        "size_bytes": size,
                        "sha256": digest,
                        "xml_count": 2,
                    }
                ],
                "totals": {"xml_count": 2},
            }
            specs = MODULE.archive_specs(manifest, root)
            MODULE.validate_archives(specs)
            members = MODULE.collect_members(specs, 2)
            self.assertEqual([m.revision_id for m in members], [RID1, RID2])
            self.assertEqual([m.member_ordinal for m in members], [1, 2])

    def test_invalid_xml_basename_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            zip_path = root / "one.zip"
            size, digest = make_zip(zip_path, [("bad.xml", b"<Law/>")])
            specs = [MODULE.ArchiveSpec("one.zip", zip_path, size, digest, 1)]
            MODULE.validate_archives(specs)
            with self.assertRaises(ValueError):
                list(MODULE.iter_xml_members(specs))

    def test_duplicate_revision_id_fails_before_database_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            zip_path = root / "one.zip"
            size, digest = make_zip(
                zip_path,
                [
                    (f"a/{RID1}.xml", b"<Law/>"),
                    (f"b/{RID1}.xml", b"<Law/>"),
                ],
            )
            specs = [MODULE.ArchiveSpec("one.zip", zip_path, size, digest, 2)]
            MODULE.validate_archives(specs)
            with self.assertRaises(AssertionError):
                MODULE.collect_members(specs, 2)

    def test_preflight_only_needs_no_postgres_driver(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            zip_path = root / "one.zip"
            size, digest = make_zip(
                zip_path, [(f"{RID1}/{RID1}.xml", b"<Law/>")]
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "captured_on": "2026-09-04",
                        "parts": [
                            {
                                "name": "one.zip",
                                "size_bytes": size,
                                "sha256": digest,
                                "xml_count": 1,
                            }
                        ],
                        "totals": {"xml_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            result = MODULE.run(
                archive_dir=root,
                manifest_path=manifest_path,
                database_url=None,
                result_path=None,
                run_id="test",
                batch_size=10,
                progress_every=0,
                preflight_only=True,
                max_documents=None,
                fail_fast=True,
            )
            self.assertEqual(result["status"], "preflight-passed")
            self.assertEqual(result["document_count"], 1)
            self.assertFalse(result["database_revision_reconciliation_checked"])


if __name__ == "__main__":
    unittest.main()
