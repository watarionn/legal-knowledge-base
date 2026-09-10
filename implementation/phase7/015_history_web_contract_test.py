from __future__ import annotations

from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"


class HistoryWebContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")
        cls.js = (WEB / "app.js").read_text(encoding="utf-8")
        cls.css = (WEB / "styles.css").read_text(encoding="utf-8")

    def test_phase72_controls_exist(self):
        for marker in (
            'id="today-button"',
            'id="history-panel"',
            'id="history-count"',
            'id="history-summary"',
            'id="history-list"',
        ):
            self.assertIn(marker, self.html)

    def test_history_endpoint_is_loaded_with_effective_date(self):
        self.assertIn('/api/v1/laws/${encodeURIComponent(selectedId)}/history', self.js)
        self.assertIn("as_of_date: queryData.effective_as_of_date", self.js)

    def test_history_research_uses_date_not_revision_override(self):
        self.assertIn("asOfDate.value = item.valid_from", self.js)
        self.assertNotIn("payload.law_revision_id", self.js)

    def test_history_failure_does_not_clear_query_evidence(self):
        self.assertIn("改正履歴を取得できませんでした", self.js)
        self.assertIn("historyPanel.hidden = false", self.js)

    def test_selected_and_candidate_styles_exist(self):
        self.assertIn('history-item[data-selected="true"]', self.css)
        self.assertIn('history-item[data-candidate="true"]', self.css)


if __name__ == "__main__":
    unittest.main()
