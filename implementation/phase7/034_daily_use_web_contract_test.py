from __future__ import annotations

from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
APP = (WEB / "app.js").read_text(encoding="utf-8-sig")
DAILY = (WEB / "daily.js").read_text(encoding="utf-8-sig")


class DailyUseWebContractTest(unittest.TestCase):
    def test_daily_panel_contains_four_features(self):
        self.assertIn('id="daily-panel"', INDEX)
        self.assertIn('id="favorite-list"', INDEX)
        self.assertIn('id="recent-list"', INDEX)
        self.assertIn('id="search-history-list"', INDEX)
        self.assertIn('id="saved-theme-list"', INDEX)

    def test_daily_script_is_loaded(self):
        self.assertIn('<script src="/daily.js" defer></script>', INDEX)

    def test_replay_resubmits_current_query_form(self):
        self.assertIn("dailyQueryForm.requestSubmit()", DAILY)
        self.assertNotIn("saved_answer", DAILY)
        self.assertNotIn("answer_html", DAILY)

    def test_user_text_is_not_rendered_with_inner_html(self):
        self.assertNotIn("innerHTML", DAILY)
        self.assertIn("textContent", DAILY)

    def test_query_success_refreshes_daily_state_independently(self):
        self.assertIn("await refreshDailyUse(data)", APP)
        self.assertIn("catch (dailyError)", APP)
        self.assertIn("マイリストを更新できませんでした", APP)

    def test_theme_save_keeps_only_query_inputs(self):
        self.assertIn("question: dailyQuestionInput.value.trim()", DAILY)
        self.assertIn("law_id: dailyLawIdInput.value || null", DAILY)
        self.assertIn("as_of_date: dailyAsOfDate.value || null", DAILY)
        self.assertNotIn("evidence", DAILY.lower())

    def test_phase75_marker(self):
        self.assertIn("Legal Knowledge Base · Phase 7-5", INDEX)
        self.assertIn("Phase 7-5", INDEX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
