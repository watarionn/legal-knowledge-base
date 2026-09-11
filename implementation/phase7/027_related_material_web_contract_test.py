from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"


class RelatedMaterialWebContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (WEB / "index.html").read_text(encoding="utf-8")
        cls.app = (WEB / "app.js").read_text(encoding="utf-8")
        cls.related = (WEB / "related.js").read_text(encoding="utf-8")
        cls.styles = (WEB / "styles.css").read_text(encoding="utf-8")

    def test_related_panel_and_opt_in_exist(self):
        self.assertIn('id="related-panel"', self.index)
        self.assertIn('id="related-include-nonconfirmed"', self.index)
        self.assertIn('/related.js', self.index)

    def test_candidate_opt_in_defaults_off(self):
        marker = 'id="related-include-nonconfirmed"'
        fragment = self.index[self.index.index(marker):self.index.index(marker) + 180]
        self.assertNotIn("checked", fragment)

    def test_provider_content_uses_text_content(self):
        self.assertIn("title.textContent =", self.related)
        self.assertIn("evidence.textContent = JSON.stringify", self.related)
        self.assertNotIn("innerHTML", self.related)
    def test_external_url_is_protocol_limited(self):
        self.assertIn("['https:', 'http:'].includes(url.protocol)", self.related)
        self.assertIn("noopener noreferrer", self.related)

    def test_related_failure_is_isolated(self):
        self.assertIn("await loadRelatedMaterials(data)", self.app)
        self.assertIn("catch (relatedError)", self.app)
        self.assertIn("関連資料を取得できませんでした", self.app)

    def test_nonconfirmed_is_visibly_non_citation_ready(self):
        self.assertIn("引用不可", self.related)
        self.assertIn("候補資料を含みます", self.related)
        self.assertIn('[data-citation-ready="false"]', self.styles)


if __name__ == "__main__":
    unittest.main(verbosity=2)
