from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "024_retrieval_chunk_builder.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_retrieval_chunk_builder_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHUNK = _load()


def nid(value: int) -> str:
    return f"{value:064x}"


def node(order, parent, tag, *, text=None, num=None, label=None):
    return CHUNK.NodeRow(order, nid(order), parent, tag, num, label, text)

META = CHUNK.DocumentMeta(
    document_pk=10,
    law_id="123AC0000000001",
    law_revision_id="123AC0000000001_20260101_123AC0000000002",
    source_xml_sha256="a" * 64,
)


class RetrievalChunkBuilderTest(unittest.TestCase):
    def test_structural_boundaries_do_not_mix(self):
        rows = [
            node(1, None, "Law"),
            node(2, 1, "Article", num="1", label="第一条"),
            node(3, 2, "ArticleTitle", text="第一条　目的"),
            node(4, 2, "Paragraph", num="1"),
            node(5, 4, "Sentence", text="この法律は、目的を定める。"),
            node(6, 4, "Sentence", text="必要な事項を定める。"),
            node(7, 4, "Item", num="1", label="一"),
            node(8, 7, "Sentence", text="項目本文"),
            node(9, 2, "Paragraph", num="2"),
            node(10, 9, "Sentence", text="第二項本文"),
        ]
        chunks = CHUNK.build_document_chunks(META, rows, max_chars=1200)
        self.assertEqual([c.anchor_document_order for c in chunks], [2, 4, 7, 9])
        self.assertEqual(chunks[1].source_document_orders, (5, 6))
        self.assertEqual(chunks[2].context_prefix, "第一条 > Paragraph 1 > 一")

    def test_soft_limit_splits_only_between_source_units(self):
        rows = [
            node(1, None, "Law"),
            node(2, 1, "Paragraph", num="1"),
            node(3, 2, "Sentence", text="あ" * 60),
            node(4, 2, "Sentence", text="い" * 60),
        ]
        chunks = CHUNK.build_document_chunks(META, rows, max_chars=100)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].source_document_orders, (3,))
        self.assertEqual(chunks[1].source_document_orders, (4,))
        self.assertFalse(chunks[0].is_oversize)
        self.assertFalse(chunks[1].is_oversize)

    def test_single_source_unit_can_be_oversize(self):
        rows = [
            node(1, None, "Law"),
            node(2, 1, "Paragraph", num="1"),
            node(3, 2, "Sentence", text="法" * 150),
        ]
        chunks = CHUNK.build_document_chunks(META, rows, max_chars=100)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_document_orders, (3,))
        self.assertTrue(chunks[0].is_oversize)
        self.assertEqual(chunks[0].char_count, 150)

    def test_unknown_structure_falls_back_to_direct_parent(self):
        rows = [
            node(1, None, "Law"),
            node(2, 1, "FutureUnknownContainer"),
            node(3, 2, "FutureUnknownText", text="未知要素の本文"),
        ]
        chunks = CHUNK.build_document_chunks(META, rows)
        self.assertEqual(chunks[0].anchor_document_order, 2)
        self.assertEqual(chunks[0].anchor_tag_name, "FutureUnknownContainer")

    def test_identity_is_deterministic_and_not_tied_to_document_pk(self):
        rows = [
            node(1, None, "Law"),
            node(2, 1, "Article", num="1", label="第一条"),
            node(3, 2, "Sentence", text="本文"),
        ]
        first = CHUNK.build_document_chunks(META, rows)[0]
        second = CHUNK.build_document_chunks(META, rows)[0]
        moved_meta = CHUNK.DocumentMeta(
            document_pk=999,
            law_id=META.law_id,
            law_revision_id=META.law_revision_id,
            source_xml_sha256=META.source_xml_sha256,
        )
        moved = CHUNK.build_document_chunks(moved_meta, rows)[0]
        changed = CHUNK.build_document_chunks(
            META, rows, chunking_version="phase5-structural-chunk-2.0"
        )[0]
        self.assertEqual(first.chunk_id, second.chunk_id)
        self.assertEqual(first.chunk_id, moved.chunk_id)
        self.assertNotEqual(first.chunk_id, changed.chunk_id)

    def test_retrieval_text_collapses_whitespace_only(self):
        rows = [
            node(1, None, "Law"),
            node(2, 1, "Paragraph", num="1"),
            node(3, 2, "Sentence", text="  日本\n\t国  "),
        ]
        chunk = CHUNK.build_document_chunks(META, rows)[0]
        self.assertEqual(chunk.retrieval_text, "日本 国")

    def test_rejects_tiny_limit(self):
        with self.assertRaisesRegex(ValueError, "max_chars"):
            CHUNK.build_document_chunks(META, [], max_chars=99)


if __name__ == "__main__":
    unittest.main()
