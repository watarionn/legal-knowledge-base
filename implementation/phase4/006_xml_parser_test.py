from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

PARSER_PATH = Path(__file__).with_name("005_xml_parser.py")
SPEC = importlib.util.spec_from_file_location("phase4_xml_parser", PARSER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load parser: {PARSER_PATH}")
PARSER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PARSER
SPEC.loader.exec_module(PARSER)

REVISION_ID = "321CONSTITUTION_19470503_000000000000000"
COMMON = {
    "law_revision_id": REVISION_ID,
    "source_file_id": "source-file-test",
    "ingestion_run_id": "ingestion-run-test",
}


class XmlParserSyntheticTests(unittest.TestCase):
    def parse(self, xml: str, **kwargs):
        return PARSER.parse_xml_bytes(
            xml.encode("utf-8"),
            **COMMON,
            **kwargs,
        )

    @staticmethod
    def node_by_tag(result, tag_name: str):
        return next(
            node
            for node in result.nodes
            if node["tag_name"] == tag_name
        )

    def test_articleless_main_provision(self):
        result = self.parse(
            "<Law><LawBody><MainProvision>"
            "<Paragraph Num='1'><Sentence>本文</Sentence></Paragraph>"
            "</MainProvision></LawBody></Law>"
        )

        self.assertFalse(
            any(node["tag_name"] == "Article" for node in result.nodes)
        )
        main = self.node_by_tag(result, "MainProvision")
        paragraph = self.node_by_tag(result, "Paragraph")
        self.assertEqual(paragraph["parent_node_id"], main["node_id"])
        self.assertTrue(paragraph["xml_path"].endswith("/Paragraph[1]"))

    def test_mixed_content_and_tail(self):
        result = self.parse(
            "<Law><Sentence>前<Ruby>中</Ruby>後</Sentence></Law>"
        )
        sentence = self.node_by_tag(result, "Sentence")
        ruby = self.node_by_tag(result, "Ruby")

        self.assertEqual(sentence["text_original"], "前中後")
        self.assertEqual(
            sentence["mixed_content_jsonb"],
            [
                {"kind": "text", "value": "前"},
                {"kind": "child", "node_id": ruby["node_id"]},
                {
                    "kind": "tail",
                    "after_node_id": ruby["node_id"],
                    "value": "後",
                },
            ],
        )

    def test_whitespace_tail_is_not_trimmed(self):
        result = self.parse(
            "<Law><Sentence>A<Ruby>B</Ruby>   </Sentence></Law>"
        )
        sentence = self.node_by_tag(result, "Sentence")
        self.assertEqual(
            sentence["mixed_content_jsonb"][-1]["value"],
            "   ",
        )

    def test_unknown_element_and_attribute_survive(self):
        result = self.parse(
            "<Law Mystery='yes'>"
            "<FutureThing Odd='42'>x</FutureThing>"
            "</Law>",
            schema_validation_status="invalid",
        )
        root = self.node_by_tag(result, "Law")
        future = self.node_by_tag(result, "FutureThing")

        self.assertEqual(root["attributes_jsonb"]["Mystery"], "yes")
        self.assertEqual(future["attributes_jsonb"]["Odd"], "42")
        self.assertEqual(
            result.law_document["parse_status"],
            "succeeded-with-warnings",
        )

    def test_oldnum_oldstyle_and_display_label(self):
        result = self.parse(
            "<Law><Article Num='1' OldNum='壱' OldStyle='true'>"
            "<ArticleTitle>第一条</ArticleTitle>"
            "</Article></Law>"
        )
        article = self.node_by_tag(result, "Article")

        self.assertEqual(article["structural_num"], "1")
        self.assertEqual(article["old_num"], "壱")
        self.assertEqual(article["old_style"], "true")
        self.assertEqual(article["attributes_jsonb"]["OldNum"], "壱")
        self.assertEqual(article["attributes_jsonb"]["OldStyle"], "true")
        self.assertEqual(article["display_label"], "第一条")

    def test_column_and_tablecolumn_remain_distinct(self):
        result = self.parse(
            "<Law><Table>"
            "<Column>A</Column><TableColumn>B</TableColumn>"
            "</Table></Law>"
        )
        tags = [node["tag_name"] for node in result.nodes]
        self.assertIn("Column", tags)
        self.assertIn("TableColumn", tags)

        column = self.node_by_tag(result, "Column")
        table_column = self.node_by_tag(result, "TableColumn")
        self.assertLess(
            column["document_order"],
            table_column["document_order"],
        )

    def test_namespace_tolerant_paths(self):
        result = self.parse(
            "<Law xmlns:a='urn:a' xmlns:b='urn:b'>"
            "<a:X/><b:X/>"
            "</Law>"
        )
        nodes = [
            node
            for node in result.nodes
            if node["tag_name"] == "X"
        ]

        self.assertEqual(
            {node["namespace_uri"] for node in nodes},
            {"urn:a", "urn:b"},
        )
        self.assertEqual(len({node["xml_path"] for node in nodes}), 2)
        self.assertTrue(
            any("{urn:a}X[1]" in node["xml_path"] for node in nodes)
        )

    def test_comments_and_processing_instructions_are_retained(self):
        result = self.parse(
            "<Law><!--memo--><?target data?><Article/></Law>"
        )
        kinds = [node["node_kind"] for node in result.nodes]
        self.assertIn("comment", kinds)
        self.assertIn("processing-instruction", kinds)

        pi = next(
            node
            for node in result.nodes
            if node["node_kind"] == "processing-instruction"
        )
        self.assertEqual(pi["qname_original"], "target")

    def test_unresolved_attachment_reference_survives(self):
        result = self.parse(
            "<Law><Fig src='fig/foo.png'/></Law>"
        )
        self.assertEqual(len(result.attachments), 1)

        attachment = result.attachments[0]
        self.assertEqual(attachment["source_src"], "fig/foo.png")
        self.assertEqual(attachment["source_attribute_name"], "src")
        self.assertEqual(attachment["availability_status"], "unresolved")
        self.assertIsNone(attachment["source_file_id"])

    def test_namespaced_src_keeps_expanded_attribute_identity(self):
        result = self.parse(
            "<Law xmlns:a='urn:a'><Fig a:src='x.png'/></Law>"
        )
        self.assertEqual(
            result.attachments[0]["source_attribute_name"],
            "{urn:a}src",
        )

    def test_deterministic_identifiers(self):
        xml = "<Law><Fig src='x.png'/></Law>"
        first = self.parse(xml)
        second = self.parse(xml)

        self.assertEqual(
            first.law_document["document_id"],
            second.law_document["document_id"],
        )
        self.assertEqual(
            [node["node_id"] for node in first.nodes],
            [node["node_id"] for node in second.nodes],
        )
        self.assertEqual(
            first.attachments[0]["attachment_id"],
            second.attachments[0]["attachment_id"],
        )

    def test_malformed_xml_returns_failed_document(self):
        result = self.parse("<Law><Article></Law>")

        self.assertEqual(result.law_document["parse_status"], "failed")
        self.assertIsNone(result.law_document["root_tag_name"])
        self.assertEqual(result.law_document["node_count"], 0)
        self.assertEqual(
            result.issues[0]["issue_code"],
            "XML_NOT_WELL_FORMED",
        )

    def test_xml_declaration_encoding_is_observed(self):
        xml = b'<?xml version="1.0" encoding="UTF-8"?><Law/>'
        result = PARSER.parse_xml_bytes(xml, **COMMON)
        self.assertEqual(
            result.law_document["xml_decl_encoding"],
            "UTF-8",
        )

    def test_tree_relational_invariants(self):
        result = self.parse(
            "<Law><A/><A><B/></A><!--x--><?p y?></Law>"
        )

        roots = [
            node
            for node in result.nodes
            if node["parent_node_id"] is None
        ]
        self.assertEqual(len(roots), 1)
        self.assertEqual(
            [node["document_order"] for node in result.nodes],
            list(range(1, len(result.nodes) + 1)),
        )
        self.assertEqual(
            len({node["xml_path"] for node in result.nodes}),
            len(result.nodes),
        )

        ordinals_by_parent = {}
        for node in result.nodes:
            ordinals_by_parent.setdefault(
                node["parent_node_id"],
                [],
            ).append(node["ordinal"])
        for ordinals in ordinals_by_parent.values():
            self.assertEqual(
                sorted(ordinals),
                list(range(1, len(ordinals) + 1)),
            )

    def test_source_file_member_helper_preserves_crc32(self):
        row = PARSER.build_source_file_member_row(
            member_source_file_id="member-source",
            container_source_file_id="zip-source",
            member_path="path/example.xml",
            member_ordinal=3,
            compressed_size=100,
            uncompressed_size=250,
            crc32=0x12AB,
        )

        self.assertEqual(row["member_path"], "path/example.xml")
        self.assertEqual(row["member_ordinal"], 3)
        self.assertEqual(row["crc32"], "000012ab")


if __name__ == "__main__":
    unittest.main()
