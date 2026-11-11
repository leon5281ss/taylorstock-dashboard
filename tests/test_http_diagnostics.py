import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_finmind_connection import smoke
from market_pipeline.pipeline import ROOT, TAIPEI, collect, load_watchlist, main
from market_pipeline.sources import FINMIND, HttpClient, SourceError, classify_response
from test_pipeline import FixtureClient


class DiagnosticsTests(unittest.TestCase):
    def test_safe_categories(self):
        cases = [(400, "TokenIllegal SECRET", "invalid_token"),
                 (400, "TokenLevelTooLow SECRET", "permission_denied"),
                 (400, "invalid start_date SECRET", "invalid_parameters"),
                 (400, "unknown SECRET", "bad_request"),
                 (402, "SECRET", "rate_limited"),
                 (429, "SECRET", "rate_limited"),
                 (403, "ip banned SECRET", "ip_blocked"),
                 (403, "SECRET", "access_denied"),
                 (401, "SECRET", "invalid_token"),
                 (503, "SECRET", "server_error")]
        for status, message, category in cases:
            with self.subTest(category=category):
                error = classify_response(status, {"msg": message, "status": status})
                self.assertEqual(error.code, category)
                self.assertNotIn("SECRET", json.dumps(error.diagnostic()))

    def test_invalid_token_circuit_and_no_retry(self):
        error = HTTPError(FINMIND, 400, "SECRET", {}, io.BytesIO(b'{"msg":"TokenIllegal SECRET","status":400}'))
        with patch("market_pipeline.sources.urlopen", side_effect=error) as opening:
            client = HttpClient("SECRET")
            for unused in range(3):
                with self.assertRaisesRegex(SourceError, "^invalid_token$"):
                    client.dataset("TaiwanStockPrice", "2026-11-01", "2026-11-10", "2303")
            self.assertEqual(opening.call_count, 1)

    def test_api_error_inside_http_success(self):
        response = io.BytesIO(b'{"status":400,"msg":"TokenIllegal SECRET"}')
        with patch("market_pipeline.sources.urlopen", return_value=response):
            with self.assertRaises(SourceError) as caught:
                HttpClient("SECRET").get(FINMIND, authenticated=True)
        self.assertEqual(caught.exception.diagnostic(), {"category": "invalid_token", "httpStatus": 200, "apiStatus": 400})

    def test_quota_does_not_retry(self):
        error = HTTPError(FINMIND, 402, "SECRET", {}, io.BytesIO(b"quota"))
        with patch("market_pipeline.sources.urlopen", side_effect=error) as opening:
            with self.assertRaisesRegex(SourceError, "^rate_limited$"):
                HttpClient("SECRET").get(FINMIND, authenticated=True)
            self.assertEqual(opening.call_count, 1)

    def test_bad_secret_format_never_sent(self):
        with patch("market_pipeline.sources.urlopen") as opening:
            with self.assertRaisesRegex(SourceError, "^token_format_error$"):
                HttpClient("Bearer SECRET").get(FINMIND, authenticated=True)
            opening.assert_not_called()

    def test_smoke_stops_after_first_failure_and_anonymous_control(self):
        calls = []
        class Client:
            def __init__(self, token, attempts):
                self.token = token

            def dataset(self, dataset, start, end, code=None):
                calls.append((self.token, dataset, code))
                if self.token:
                    raise SourceError("invalid_token", 400, 400)
                return [{"date": end}]
        result = smoke("SECRET", Client)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["anonymousControl"]["category"], "ok")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[2] == "2303" for call in calls))
        self.assertNotIn("SECRET", json.dumps(result))

    def test_smoke_success_and_missing_secret(self):
        result = smoke("SECRET", lambda *args, **kwargs: FixtureClient(), datetime(2026, 11, 11, tzinfo=TAIPEI))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["checks"]), 4)
        self.assertEqual(smoke("")["checks"][0]["category"], "missing_token")

    def test_all_core_failures_fail_report_and_cli(self):
        class FailedClient(FixtureClient):
            def dataset(self, *args):
                raise SourceError("invalid_token", 400, 400)
        payload = collect(FailedClient(), load_watchlist(ROOT / "config/watchlist_public.json"), datetime(2026, 11, 11, tzinfo=TAIPEI))
        self.assertEqual(payload["reportStatus"], "failed")
        self.assertEqual(set(payload["failedDatasets"]), {"price", "institutional", "margin"})
        self.assertEqual(payload["calendar"]["diagnostic"]["category"], "invalid_token")
        with patch.dict("os.environ", {"FINMIND_TOKEN": "SECRET"}), patch("sys.argv", ["collector"]), patch("market_pipeline.pipeline.collect", return_value=payload), patch("market_pipeline.pipeline.write_outputs"):
            self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
