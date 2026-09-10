from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest

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


APP = _load("legal_kb_phase7_application_contract_test_target", "001_application_contract.py")


class QueryPayloadTest(unittest.TestCase):
    def test_server_date_default_is_explicit(self):
        request = APP.parse_query_payload(
            {"question": "建設業法を確認したい"},
            default_date=date(2026, 9, 10),
        )
        self.assertEqual(request.requested_as_of_date, None)
        self.assertEqual(request.effective_as_of_date, date(2026, 9, 10))
        self.assertEqual(request.as_of_date_source, "server-date-default")

    def test_unknown_field_is_rejected(self):
        with self.assertRaisesRegex(APP.RequestValidationError, "unknown request fields"):
            APP.parse_query_payload(
                {"question": "民法", "typo": True},
                default_date=date(2026, 9, 10),
            )

    def test_bad_date_is_rejected(self):
        with self.assertRaisesRegex(APP.RequestValidationError, "YYYY-MM-DD"):
            APP.parse_query_payload(
                {"question": "民法", "as_of_date": "2026/09/10"},
                default_date=date(2026, 9, 10),
            )

    def test_bad_law_id_is_rejected(self):
        with self.assertRaisesRegex(APP.RequestValidationError, "15-character"):
            APP.parse_query_payload(
                {"question": "民法", "law_id": "not-a-law-id"},
                default_date=date(2026, 9, 10),
            )


class LawPhraseResolutionTest(unittest.TestCase):
    def test_single_title_phrase_resolves(self):
        resolution = APP.resolve_law_phrases(
            "建設業法で請負契約を確認したい",
            [
                {
                    "law_id": "324AC0000000100",
                    "law_num": "昭和二十四年法律第百号",
                    "law_title": "建設業法",
                    "abbrev": None,
                }
            ],
        )
        self.assertEqual(resolution.status, "resolved")
        self.assertEqual(resolution.selected_law_id, "324AC0000000100")

    def test_nested_title_prefers_longer_exact_phrase(self):
        resolution = APP.resolve_law_phrases(
            "労働基準法施行令の内容を確認したい",
            [
                {
                    "law_id": "322AC0000000049",
                    "law_num": None,
                    "law_title": "労働基準法",
                    "abbrev": None,
                },
                {
                    "law_id": "322CO0000000323",
                    "law_num": None,
                    "law_title": "労働基準法施行令",
                    "abbrev": None,
                },
            ],
        )
        self.assertEqual(resolution.status, "resolved")
        self.assertEqual(resolution.selected_law_id, "322CO0000000323")
        self.assertIn("NESTED_LAW_PHRASES_COLLAPSED_TO_LONGEST", resolution.warnings)

    def test_multiple_independent_laws_are_not_auto_selected(self):
        resolution = APP.resolve_law_phrases(
            "民法と商法の違いを確認したい",
            [
                {
                    "law_id": "129AC0000000089",
                    "law_num": None,
                    "law_title": "民法",
                    "abbrev": None,
                },
                {
                    "law_id": "132AC0000000048",
                    "law_num": None,
                    "law_title": "商法",
                    "abbrev": None,
                },
            ],
        )
        self.assertEqual(resolution.status, "law-candidates")
        self.assertIsNone(resolution.selected_law_id)


if __name__ == "__main__":
    unittest.main()
