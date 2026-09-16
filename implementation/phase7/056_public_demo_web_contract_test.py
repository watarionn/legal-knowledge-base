from __future__ import annotations

from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / "web_public"


class PublicDemoWebContractTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (PUBLIC / name).read_text(encoding="utf-8")

    def test_public_assets_exist(self):
        expected = {"index.html", "styles.css", "app.js", "compare.js", "related.js"}
        self.assertEqual({p.name for p in PUBLIC.iterdir() if p.is_file()}, expected)

    def test_html_has_no_private_daily_surface(self):
        html = self.read("index.html")
        self.assertIn("Public Demo", html)
        self.assertNotIn("daily.js", html)
        for text in ("お気に入り", "保存テーマ", "法令ウォッチ", "検索履歴"):
            self.assertNotIn(text, html)

    def test_javascript_only_calls_public_api_surface(self):
        allowed = ("/api/v1/query", "/api/v1/laws/")
        for path in PUBLIC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for api in re.findall(r"/api/v1/[A-Za-z0-9_{}$?&=./:-]+", text):
                self.assertTrue(api.startswith(allowed), f"{path.name}: {api}")

    def test_javascript_avoids_html_injection_sinks(self):
        banned = ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function")
        for path in PUBLIC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for token in banned:
                self.assertNotIn(token, text, f"{path.name}: {token}")

    def test_question_limit_is_visible_in_ui(self):
        html = self.read("index.html")
        self.assertIn('maxlength="800"', html)
        self.assertIn("個人機能・更新操作・AI生成回答は無効", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
