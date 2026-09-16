from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase76d_content_test", HERE / "053_law_watch_content_refresh.py"
)
assert SPEC and SPEC.loader
CONTENT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONTENT
SPEC.loader.exec_module(CONTENT)

REVISION_ID = "129AC0000000089_20260624_508AC0000000045"

def response_xml(revision_id: str = REVISION_ID) -> bytes:
    return (
        b"<law_data_response><revision_info><law_revision_id>"
        + revision_id.encode("ascii")
        + b"</law_revision_id></revision_info><law_full_text>\n"
        + b'<Law Era="Meiji"><LawBody>  exact bytes  </LawBody></Law>'
        + b"\n</law_full_text></law_data_response>"
    )


class ContentRefreshTest(unittest.TestCase):
    def test_extract_law_xml_preserves_exact_response_bytes(self):
        raw = response_xml()
        extracted = CONTENT.extract_law_xml(raw, REVISION_ID)
        self.assertEqual(
            extracted,
            b'<Law Era="Meiji"><LawBody>  exact bytes  </LawBody></Law>',
        )

    def test_extract_law_xml_rejects_revision_mismatch(self):
        with self.assertRaises(ValueError):
            CONTENT.extract_law_xml(response_xml(), "129AC0000000089_20200101_000000000000000")

    def test_existing_ready_document_skips_api_fetch(self):
        fetcher = unittest.mock.Mock(side_effect=AssertionError("fetch should not run"))
        with patch.object(CONTENT, "_succeeded_document_pk", return_value=42), \
             patch.object(CONTENT, "_document_has_chunks", return_value=True):
            result = CONTENT.refresh_revision_content(
                object(), revision_id=REVISION_ID, run_id="run-1",
                raw_dir=Path("unused"), fetcher=fetcher,
            )
        self.assertTrue(result["already_ready"])
        self.assertFalse(result["api_fetched"])
        fetcher.assert_not_called()

    def test_existing_document_rebuilds_chunks_without_fetch(self):
        fetcher = unittest.mock.Mock(side_effect=AssertionError("fetch should not run"))
        chunk_builder = types.SimpleNamespace(
            rebuild_document=lambda conn, document_pk: ["c1", "c2"]
        )
        with patch.object(CONTENT, "_succeeded_document_pk", return_value=42), \
             patch.object(CONTENT, "_document_has_chunks", return_value=False):
            result = CONTENT.refresh_revision_content(
                object(), revision_id=REVISION_ID, run_id="run-1",
                raw_dir=Path("unused"), fetcher=fetcher,
                chunk_builder=chunk_builder,
            )
        self.assertEqual(result["chunk_count"], 2)
        self.assertFalse(result["api_fetched"])

    def test_new_document_fetches_raw_parses_and_chunks(self):
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, sql, params=None): pass
            def fetchone(self): return (77,)
        class Conn:
            def cursor(self): return Cursor()
            def commit(self): pass
        parsed = types.SimpleNamespace(
            law_document={"parse_status": "succeeded", "document_id": "d" * 64}
        )
        parser = types.SimpleNamespace(parse_xml_bytes=lambda *a, **k: parsed)
        member_calls = []
        pg_import = types.SimpleNamespace(
            insert_source_file_member=lambda conn, row: member_calls.append(row) or True,
            insert_parsed_document=lambda *a, **k: True,
        )
        chunk_builder = types.SimpleNamespace(rebuild_document=lambda conn, pk: ["chunk"])
        with tempfile.TemporaryDirectory() as td, \
             patch.object(CONTENT, "_succeeded_document_pk", return_value=None), \
             patch.object(CONTENT, "_store_source_file") as store_source:
            result = CONTENT.refresh_revision_content(
                Conn(), revision_id=REVISION_ID, run_id="run-1",
                raw_dir=Path(td),
                fetcher=lambda *a, **k: (datetime.now(timezone.utc), response_xml()),
                parser=parser, pg_import=pg_import, chunk_builder=chunk_builder,
            )
            raw_files = list(Path(td).rglob("*.xml"))
        self.assertTrue(result["document_imported"])
        self.assertTrue(result["api_fetched"])
        self.assertEqual(result["chunk_count"], 1)
        self.assertEqual(len(raw_files), 2)
        self.assertEqual(store_source.call_count, 2)
        self.assertEqual(member_calls[0]["member_path"], "law_full_text/Law")


if __name__ == "__main__":
    unittest.main(verbosity=2)
