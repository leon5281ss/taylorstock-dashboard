"""Daily FinMind quota must never be consumed by research-data git pushes."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FinMindQuotaWorkflowTests(unittest.TestCase):
    def test_public_data_and_code_pushes_do_not_trigger_finmind_collection(self):
        workflow = (ROOT/".github/workflows/daily-report.yml").read_text(encoding="utf-8")
        triggers = workflow.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        self.assertIn("schedule:", triggers)
        self.assertNotIn("  push:", triggers)
        self.assertIn("FINMIND_TOKEN", workflow)
        self.assertIn("scripts/check_finmind_connection.py", workflow)
        self.assertIn("vars.TELEGRAM_NOTIFICATIONS_ENABLED == 'true'", workflow)

    def test_market_research_pushes_are_different_from_22_symbol_daily_alerts(self):
        for path in (".github/workflows/research-history-backfill.yml",
                     ".github/workflows/margin-research-backfill.yml"):
            data = (ROOT/path).read_text(encoding="utf-8")
            self.assertNotIn("FINMIND_TOKEN", data)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", data)


if __name__ == "__main__":
    unittest.main()
