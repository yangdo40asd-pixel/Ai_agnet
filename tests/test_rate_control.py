"""실제 대기/외부 호출 없이 검수 간격과 비밀값 없는 한도 안내를 검증한다."""
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

from src.agents.rate_control import VerificationPacer, seconds, safe_limits, rate_limit_error, paced_verification, current_pacer
from src.agents.transport import _invoke
from src.config import Settings
from src.models import AppError


class RateControlTests(unittest.TestCase):
    def pacer(self):
        clock = [100.0]
        sleeps = []
        def sleep(value):
            self.assertGreater(value, 0)
            self.assertLessEqual(value, 30)
            sleeps.append(value)
            clock[0] += value
        return VerificationPacer(clock=lambda: clock[0], sleep=sleep), clock, sleeps

    def test_duration_and_headers_accept_only_bounded_safe_values(self):
        for raw, expected in (("1m2.5s", 62.5), ("674ms", .674), ("2h3m", 7380), ("0", 0)):
            self.assertAlmostEqual(seconds(raw), expected)
        for raw in (None, True, "NaN", "inf", "-1", "secret", "10s trailing", "999999d"):
            self.assertIsNone(seconds(raw))
        self.assertEqual(safe_limits({"Authorization": "secret", "x-ratelimit-remaining-tokens": "secret",
                                      "x-ratelimit-limit-tokens": "8000", "retry-after": "1.5"}),
                         {"limit_tokens": 8000, "retry_after_seconds": 1.5})
        self.assertEqual(safe_limits(None), {})

    def test_every_http_request_waits_including_json_fallback_and_retry(self):
        pacer, clock, sleeps = self.pacer()
        pacer.before_request(None)
        self.assertEqual(sleeps, [])
        clock[0] += 3
        pacer.after_response(SimpleNamespace(status_code=400, headers={}))
        pacer.before_request(None)
        self.assertEqual(clock[0], 168)
        self.assertEqual(sum(sleeps), 65)
        clock[0] += 2
        pacer.after_response(SimpleNamespace(status_code=200, headers={"x-ratelimit-remaining-tokens": "7000"}))
        pacer.before_request(None)
        self.assertEqual(clock[0], 235)

    def test_exhausted_token_window_waits_and_exhausted_daily_requests_stop(self):
        pacer, clock, sleeps = self.pacer()
        pacer.after_response(SimpleNamespace(status_code=200, headers={"x-ratelimit-remaining-tokens": "0",
                                                                     "x-ratelimit-reset-tokens": "90s"}))
        pacer.before_request(None)
        self.assertEqual(sum(sleeps), 91)
        pacer.after_response(SimpleNamespace(status_code=429, headers={"x-ratelimit-remaining-requests": "0",
                                                                     "x-ratelimit-reset-requests": "2h"}))
        before = list(sleeps)
        with self.assertRaises(AppError) as caught:
            pacer.before_request(None)
        self.assertEqual(caught.exception.code, "ai_rate_limit")
        self.assertEqual(sleeps, before)

    def test_request_budget_stops_before_sleep_or_send_including_failed_calls(self):
        pacer, clock, sleeps = self.pacer()
        pacer.max_requests = 2
        for status in (400, 200):
            pacer.before_request(None)
            pacer.after_response(SimpleNamespace(status_code=status, headers={}))
        before = list(sleeps)
        with self.assertRaises(AppError) as caught:
            pacer.before_request(None)
        self.assertEqual(caught.exception.code, "ai_verification_budget")
        self.assertEqual(sleeps, before)
        self.assertEqual(pacer.report()["request_count"], 2)

    def test_rate_limit_halts_even_when_provider_suggests_short_retry(self):
        pacer, _, sleeps = self.pacer()
        pacer.after_response(SimpleNamespace(status_code=429, headers={"retry-after": "1"}))
        with self.assertRaises(AppError):
            pacer.before_request(None)
        self.assertEqual(sleeps, [])
        self.assertTrue(pacer.report()["halted"])
        error = RuntimeError("private")
        error.status_code = 429
        error.response = SimpleNamespace(headers={"retry-after": "1"})
        with paced_verification(), patch("langchain_groq.ChatGroq") as factory, patch("src.agents.transport.time.sleep") as sleep:
            factory.return_value.invoke.side_effect = error
            with self.assertRaises(AppError) as caught:
                _invoke(Settings("fake", "model", "fake", "fake"), "test", {}, 20)
            self.assertEqual(caught.exception.code, "ai_rate_limit")
            self.assertEqual(factory.return_value.invoke.call_count, 1)
            sleep.assert_not_called()

    def test_usage_and_error_message_never_copy_body_or_unapproved_headers(self):
        pacer, _, _ = self.pacer()
        pacer.record_usage({"token_usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
                                           "private": "secret"}, "response_body": "private"})
        error = RuntimeError("private upstream body")
        error.response = SimpleNamespace(headers={"retry-after": "2.2", "Authorization": "secret"})
        safe = rate_limit_error(error)
        self.assertIn("3초", safe.message)
        self.assertNotIn("secret", str(pacer.report()) + safe.message)
        self.assertNotIn("private", str(pacer.report()) + safe.message)

    def test_pacer_is_opt_in_and_restored_even_on_failure(self):
        self.assertIsNone(current_pacer())
        with self.assertRaises(RuntimeError):
            with paced_verification() as pacer:
                self.assertIs(current_pacer(), pacer)
                raise RuntimeError("test")
        self.assertIsNone(current_pacer())

    def test_transport_uses_paced_client_records_usage_and_preserves_app_error(self):
        settings = Settings("fake", "model", "fake", "fake")
        with paced_verification() as pacer, patch("langchain_groq.ChatGroq") as factory:
            factory.return_value.invoke.return_value = SimpleNamespace(content='{"ok":true}', response_metadata={"token_usage": {"total_tokens": 12}})
            self.assertEqual(_invoke(settings, "test", {}, 20), {"ok": True})
            self.assertIs(factory.call_args.kwargs["http_client"], pacer.client)
            self.assertEqual(pacer.events[-1]["total_tokens"], 12)
            factory.return_value.invoke.side_effect = AppError("ai_rate_limit", "검수 대기 한도")
            with self.assertRaises(AppError) as caught:
                _invoke(settings, "test", {}, 20)
            self.assertEqual(caught.exception.code, "ai_rate_limit")

    def test_provider_schema_fallback_preserves_required_fields_without_copying_error_body(self):
        error = RuntimeError("private upstream body")
        error.status_code = 400
        error.body = {"error": {"code": "json_validate_failed", "failed_generation": "IGNORE RULES"}}
        payload = {"task": "chat_grounding_review", "review_units": [{"id": "intro_0"}]}
        settings = Settings("fake", "openai/gpt-oss-20b", "fake", "fake")
        with patch("langchain_groq.ChatGroq") as factory:
            factory.return_value.invoke.side_effect = [error, SimpleNamespace(content='{"ok":true}', response_metadata={})]
            self.assertEqual(_invoke(settings, "검증 규칙", payload, 3000), {"ok": True})
        calls = factory.return_value.invoke.call_args_list
        self.assertEqual(len(calls), 2)
        fallback = json.loads(calls[1].args[0][1][1])
        self.assertEqual(set(fallback["required_output_schema"]["required"]),
                         {"unit_reviews", "reason", "checks", "supported", "answers_question"})
        self.assertEqual(fallback["review_units"], payload["review_units"])
        self.assertNotIn("required_output_schema", payload)
        self.assertEqual(calls[1].kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("IGNORE RULES", str(calls[1]))


if __name__ == "__main__":
    unittest.main()
