from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = Path(__file__).with_name("008_search_unit_builder.py")
spec = importlib.util.spec_from_file_location("phase5_search_builder", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader is not None
spec.loader.exec_module(mod)


def node(order, tag, parent=None, *, text=None, mixed=None, num=None, label=None):
    return {
        "document_order": order,
        "node_id": bytes([order % 251 + 1]) * 32,
        "parent_document_order": parent,
        "node_kind": "element",
        "ordinal": 1,
        "path_index": 1,
        "depth": 0,
        "tag_name": tag,
        "structural_num": num,
        "display_label": label,
        "text_original": text,
        "mixed_content_jsonb": mixed or ([] if text is None else [{"kind": "text", "value": text}]),
    }


class SearchUnitBuilderTest(unittest.TestCase):
    META = dict(
        law_id="900AC0000000001",
        law_revision_id="900AC0000000001_20200101_000000000000001",
        document_pk=1,
        document_id="a" * 64,
        source_xml_sha256="b" * 64,
        law_title="テスト法",
    )

    def build(self, nodes):
        return mod.build_search_units(nodes, **self.META)

    def test_normalization_nfkc_casefold_whitespace(self):
        self.assertEqual(mod.normalize_search_text(" Ａ B\nＣ　ｱ "), "abcア")

    def test_sentence_anchors_to_paragraph(self):
        rows = [node(1,"Law"), node(2,"Article",1,num="1",label="第一条"), node(3,"Paragraph",2,num="1"), node(4,"Sentence",3,text="目的を定める。")]
        result = self.build(rows)
        self.assertEqual(result.uncovered_sentence_count, 0)
        unit = [u for u in result.units if u.unit_kind == "sentence"][0]
        self.assertEqual(unit.anchor_document_order, 3)
        self.assertEqual(unit.anchor_tag_name, "Paragraph")
        self.assertIn("第一条", unit.context_text_cache)

    def test_item_sentence_anchors_to_item(self):
        rows = [node(1,"Law"), node(2,"Paragraph",1,num="1"), node(3,"Item",2,num="1",label="一"), node(4,"Sentence",3,text="項目本文")]
        unit = self.build(rows).units[0]
        self.assertEqual(unit.anchor_tag_name, "Item")
        self.assertEqual(unit.anchor_structural_num, "1")

    def test_table_row_suppresses_descendant_sentence_duplicate(self):
        rows = [
            node(1,"Law"),
            node(2,"TableRow",1, mixed=[{"kind":"child","document_order":3}]),
            node(3,"Sentence",2,text="表の本文"),
        ]
        result = self.build(rows)
        self.assertEqual(result.searchable_sentence_count, 1)
        self.assertEqual(result.covered_sentence_count, 1)
        self.assertEqual([(u.unit_kind,u.source_document_order) for u in result.units], [("table-row",2)])

    def test_empty_sentence_is_not_coverage_denominator(self):
        result = self.build([node(1,"Law"), node(2,"Sentence",1,text="  \n　")])
        self.assertEqual(result.searchable_sentence_count, 0)
        self.assertEqual(result.uncovered_sentence_count, 0)

    def test_direct_text_without_sentence_is_indexed(self):
        result = self.build([node(1,"Law"), node(2,"EnactStatement",1,text="公布文")])
        units = [u for u in result.units if u.unit_kind == "direct-text"]
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].search_text_cache, "公布文")

    def test_mixed_content_string_reconstruction_preserves_order(self):
        rows = [
            node(1,"Sentence",None,mixed=[
                {"kind":"text","value":"前"},
                {"kind":"child","document_order":2},
                {"kind":"tail","after_document_order":2,"value":"後"},
            ]),
            node(2,"Ruby",1,text="中"),
        ]
        values = mod.reconstruct_string_values(rows)
        self.assertEqual(values[1], "前中後")
        self.assertEqual(self.build(rows).units[0].search_text_cache, "前中後")

    def test_search_unit_id_is_deterministic(self):
        rows = [node(1,"Sentence",None,text="本文")]
        a = self.build(rows).units[0].search_unit_id
        b = self.build(rows).units[0].search_unit_id
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)


if __name__ == "__main__":
    unittest.main()
