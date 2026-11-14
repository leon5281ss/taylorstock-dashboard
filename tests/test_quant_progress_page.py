"""Quant research progress must remain safely public and non-trading."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuantProgressPageTests(unittest.TestCase):
    def test_progress_page_loads_three_explicit_public_research_directories(self):
        page = (ROOT / "docs/quant-progress.html").read_text(encoding="utf-8")
        self.assertIn('dates("market_daily")', page)
        self.assertIn('dates("market_backfill_pilot")', page)
        self.assertIn('dates("institutional_research")', page)
        self.assertIn('id="institutional"', page)
        self.assertIn('id="institutionalCoverage"', page)
        self.assertIn("121", page)
        self.assertIn("top 10", page.lower())
        self.assertIn("未還原", page)
        self.assertIn("不提供自動下單", page)
        self.assertIn('cache: "no-store"', page)

    def test_no_bot_tokens_chat_identifiers_or_hardcoded_share_values(self):
        page = (ROOT / "docs/quant-progress.html").read_text(encoding="utf-8")
        for forbidden in ("github_pat_", "TELEGRAM_BOT_TOKEN",
                          "TELEGRAM_LEDGER_TOKEN", "TELEGRAM_CHAT_ID",
                          "POSITIONS_PRIVATE_JSON_B64", "0920033035"):
            self.assertNotIn(forbidden, page)
        self.assertFalse(re.search(r"\d+:[A-Za-z0-9_-]{30,}", page))

    def test_progress_link_exists_in_original_dashboard(self):
        index = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn('href="quant-progress.html"', index)
        self.assertIn('assets/app.js', index)

    def test_progress_calculation_deduplicates_dates_and_handles_api_failure(self):
        page = (ROOT / "docs/quant-progress.html").read_text(encoding="utf-8")
        self.assertIn("new Set([...live, ...historical])", page)
        self.assertIn("institutional.filter(day => observedSet.has(day))", page)
        self.assertIn("僅代表日期重疊", page)
        self.assertIn("if (!response.ok)", page)
        self.assertIn("catch (err)", page)
        self.assertIn("不是正式交易日數驗證", page)


if __name__ == "__main__":
    unittest.main()
