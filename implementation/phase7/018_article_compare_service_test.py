import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "017_article_compare_service.py"
spec = importlib.util.spec_from_file_location("phase7_article_compare_tested", MODULE_PATH)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


def article_rows(article_num: str | None, title: str, sentence: str, start: int = 1, *, amend_law_num: str | None = None):
    scope_tag = "SupplProvision" if amend_law_num else "MainProvision"
    scope_attrs = {"AmendLawNum": amend_law_num} if amend_law_num else {}
    return [
        {"document_order": start, "parent_document_order": None, "node_kind": "element",
         "tag_name": scope_tag, "structural_num": None, "display_label": None,
         "attributes_jsonb": scope_attrs, "text_original": None,
         "mixed_content_jsonb": [{"kind": "child", "document_order": start + 1}]},
        {"document_order": start + 1, "parent_document_order": start, "node_kind": "element",
         "tag_name": "Article", "structural_num": article_num, "display_label": title,
         "attributes_jsonb": {}, "text_original": None,
         "mixed_content_jsonb": [{"kind": "child", "document_order": start + 2},
                                  {"kind": "child", "document_order": start + 3}]},
        {"document_order": start + 2, "parent_document_order": start + 1, "node_kind": "element",
         "tag_name": "ArticleTitle", "structural_num": None, "display_label": None,
         "attributes_jsonb": {}, "text_original": title,
         "mixed_content_jsonb": [{"kind": "text", "value": title}]},
        {"document_order": start + 3, "parent_document_order": start + 1, "node_kind": "element",
         "tag_name": "Paragraph", "structural_num": "1", "display_label": None,
         "attributes_jsonb": {}, "text_original": None,
         "mixed_content_jsonb": [{"kind": "child", "document_order": start + 4}]},
        {"document_order": start + 4, "parent_document_order": start + 3, "node_kind": "element",
         "tag_name": "Sentence", "structural_num": None, "display_label": None,
         "attributes_jsonb": {}, "text_original": sentence,
         "mixed_content_jsonb": [{"kind": "text", "value": sentence}]},
    ]


class ArticleIndexTest(unittest.TestCase):
    def test_reconstructs_main_article_text(self):
        index = MODULE.build_article_index(article_rows("90", "第九十条", "公序良俗に反する法律行為は、無効とする。"))
        article = index["articles"]["main\x1f90"]
        self.assertEqual(article["scope_key"], "main")
        self.assertEqual(article["text"], "第九十条公序良俗に反する法律行為は、無効とする。")
        self.assertEqual(index["article_count"], 1)
        self.assertEqual(index["duplicate_article_keys"], {})
    def test_duplicate_key_is_not_auto_selected(self):
        rows = article_rows("90", "第九十条", "A") + article_rows("90", "第九十条", "B", start=10)
        index = MODULE.build_article_index(rows)
        self.assertNotIn("main\x1f90", index["articles"])
        self.assertEqual(index["duplicate_article_keys"], {"main\x1f90": 2})

    def test_same_num_in_main_and_supplementary_stays_distinct(self):
        rows = article_rows("1", "第一条", "本則") + article_rows(
            "1", "第一条", "附則", start=10, amend_law_num="令和元年法律第一号"
        )
        index = MODULE.build_article_index(rows)
        self.assertIn("main\x1f1", index["articles"])
        self.assertIn("supplementary:令和元年法律第一号\x1f1", index["articles"])
        self.assertEqual(index["duplicate_article_keys"], {})

    def test_missing_article_num_is_excluded(self):
        index = MODULE.build_article_index(article_rows(None, "第九十条", "A"))
        self.assertEqual(index["articles"], {})
        self.assertEqual(index["missing_article_num_count"], 1)


class CompareIndexTest(unittest.TestCase):
    def test_added_removed_changed_and_unchanged(self):
        left_rows = article_rows("1", "第一条", "同じ。", start=1) + article_rows("2", "第二条", "旧文。", start=10)
        left_rows += article_rows("3", "第三条", "削除。", start=20)
        right_rows = article_rows("1", "第一条", "同じ。", start=1) + article_rows("2", "第二条", "新文。", start=10)
        right_rows += article_rows("4", "第四条", "追加。", start=20)
        result = MODULE.compare_article_indexes(
            MODULE.build_article_index(left_rows), MODULE.build_article_index(right_rows)
        )
        self.assertEqual(result["counts"], {"added": 1, "removed": 1, "changed": 1, "unchanged": 1})
        self.assertEqual(
            [(item["scope_key"], item["article_num"], item["status"]) for item in result["changes"]],
            [("main", "2", "changed"), ("main", "3", "removed"), ("main", "4", "added")],
        )

    def test_specific_article_diff_keeps_both_source_texts(self):
        left = MODULE.build_article_index(article_rows("2", "第二条", "旧文。"))
        right = MODULE.build_article_index(article_rows("2", "第二条", "新文。"))
        detail = MODULE._specific_article("2", left, right, "main")
        self.assertEqual(detail["status"], "changed")
        self.assertEqual(detail["scope_key"], "main")
        self.assertTrue(detail["diff_segments"])
        self.assertIn("旧", "".join(seg["left"] for seg in detail["diff_segments"]))
        self.assertIn("新", "".join(seg["right"] for seg in detail["diff_segments"]))

    def test_scope_omission_returns_candidates_instead_of_guessing(self):
        left_rows = article_rows("1", "第一条", "本則") + article_rows(
            "1", "第一条", "附則", start=10, amend_law_num="令和元年法律第一号")
        right_rows = article_rows("1", "第一条", "本則改正") + article_rows(
            "1", "第一条", "附則改正", start=10, amend_law_num="令和元年法律第一号")
        left = MODULE.build_article_index(left_rows)
        right = MODULE.build_article_index(right_rows)
        detail = MODULE._specific_article("1", left, right, None)
        self.assertEqual(detail["status"], "ambiguous")
        self.assertEqual(len(detail["candidates"]), 2)
        self.assertEqual({item["scope_key"] for item in detail["candidates"]}, {
            "main", "supplementary:令和元年法律第一号",
        })


    def test_duplicate_scope_key_is_ambiguous_without_guessing(self):
        left_rows = article_rows("5", "第五条", "A", start=1) + article_rows("5", "第五条", "B", start=10)
        left = MODULE.build_article_index(left_rows)
        right = MODULE.build_article_index(article_rows("5", "第五条", "C", start=1))
        detail = MODULE._specific_article("5", left, right, None)
        self.assertEqual(detail["status"], "ambiguous")



class ValidationTest(unittest.TestCase):
    def test_article_num_accepts_egov_num(self):
        self.assertEqual(MODULE.parse_article_num("398_2"), "398_2")
        self.assertEqual(MODULE.parse_article_num("155:157"), "155:157")
        self.assertIsNone(MODULE.parse_article_num(None))

    def test_article_num_accepts_range_form(self):
        self.assertEqual(MODULE.parse_article_num("155:157"), "155:157")
    def test_article_num_rejects_free_text(self):
        with self.assertRaises(ValueError):
            MODULE.parse_article_num("第九十条")

    def test_scope_key_accepts_known_forms(self):
        self.assertEqual(MODULE.parse_scope_key("main"), "main")
        self.assertEqual(MODULE.parse_scope_key("supplementary:令和元年法律第一号"), "supplementary:令和元年法律第一号")
        self.assertIsNone(MODULE.parse_scope_key(None))

    def test_scope_key_rejects_unknown_form(self):
        with self.assertRaises(ValueError):
            MODULE.parse_scope_key("chapter:1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
