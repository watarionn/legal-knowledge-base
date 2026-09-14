from __future__ import annotations

from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
APP = (WEB / "app.js").read_text(encoding="utf-8-sig")
DAILY = (WEB / "daily.js").read_text(encoding="utf-8-sig")
STYLES = (WEB / "styles.css").read_text(encoding="utf-8-sig")


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

    def test_generated_answer_is_labeled_as_ai_explanation(self):
        self.assertIn("AI生成の説明です", APP)
        self.assertIn("法的根拠は「根拠」に表示された法令原文です", APP)
        self.assertIn("skipped-no-substantive-evidence", APP)

    def test_generated_answer_is_not_duplicated_as_claim_text(self):
        self.assertIn("p.className = 'answer-text'", APP)
        self.assertNotIn("item.textContent = `${claim.text}", APP)
        self.assertIn("refs.append('参照根拠: ')", APP)
        self.assertIn("link.textContent = `E${index}`", APP)

    def test_evidence_card_hides_internal_details(self):
        self.assertIn("heading.textContent = `E${index + 1}`", APP)
        self.assertNotIn("evidence-path mono muted", APP)
        self.assertNotIn("source_xml_sha256_short", APP)
        self.assertIn("card.append(heading, quote, actions)", APP)

    def test_my_list_is_collapsed_and_after_results(self):
        self.assertIn('<details id="daily-panel" class="daily-panel">', INDEX)
        self.assertIn('class="daily-summary"', INDEX)
        self.assertLess(INDEX.index('id="result"'), INDEX.index('id="daily-panel"'))
        self.assertIn(".daily-panel-body", STYLES)

    def test_local_rag_marker(self):
        self.assertIn("Legal Knowledge Base · Phase 7 Local RAG", INDEX)
        self.assertIn("Phase 7 Local RAG", INDEX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
