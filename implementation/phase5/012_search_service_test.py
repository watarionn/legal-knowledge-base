from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent


class SearchServiceOfflineTest(unittest.TestCase):
    def test_builder_normalization_contract(self):
        spec = importlib.util.spec_from_file_location("builder_for_service_test", HERE / "008_search_unit_builder.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        self.assertEqual(mod.normalize_search_text("熊本 地震\n災害"), "熊本地震災害")
        self.assertEqual(mod.normalize_search_text("ＡＢＣ"), "abc")


if __name__ == "__main__":
    unittest.main()
