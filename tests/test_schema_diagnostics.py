import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agents.transport import response_format, _invoke
from src.agents.schema_diagnostics import schema_failure_summary
from src.agents.rate_control import paced_verification
from src.config import Settings
from src.models import AppError


class SchemaDiagnosticsTests(unittest.TestCase):
    def test_financial_plain_20b_starts_with_previous_successful_fallback_contract(self):
        payload = {"task": "chat_answer", "answer_style": "plain", "selection": {"mode": "financials"},
                   "evidence": {"CMP": {}}}
        with patch("langchain_groq.ChatGroq") as factory:
            factory.return_value.invoke.return_value = SimpleNamespace(content='{"ok":true}', response_metadata={})
            _invoke(Settings("fake", "openai/gpt-oss-20b", "fake", "fake"), "rules", payload, 100)
        self.assertEqual(factory.call_args.kwargs["model_kwargs"]["response_format"], {"type": "json_object"})
        factory.return_value.invoke.assert_called_once()
        sent = json.loads(factory.return_value.invoke.call_args.args[0][1][1])
        schema = response_format(payload, "openai/gpt-oss-20b")["json_schema"]["schema"]
        self.assertEqual(sent["required_output_schema"], schema)
        self.assertNotIn("required_output_schema", payload)

    def test_financial_direct_json_error_does_not_repeat_same_json_request(self):
        error = RuntimeError("PRIVATE")
        error.status_code = 400
        error.body = {"code": "json_validate_failed"}
        payload = {"task": "chat_answer", "answer_style": "plain", "selection": {"mode": "financials"}}
        with patch("langchain_groq.ChatGroq") as factory:
            factory.return_value.invoke.side_effect = error
            with self.assertRaises(AppError) as caught:
                _invoke(Settings("fake", "openai/gpt-oss-20b", "fake", "fake"), "rules", payload, 100)
        self.assertEqual(caught.exception.code, "ai_failed")
        factory.return_value.invoke.assert_called_once()

    def test_news_review_and_other_models_keep_original_schema_mode(self):
        for model, task, style, mode in (("openai/gpt-oss-20b", "chat_answer", "issues", "financials"),
                                       ("openai/gpt-oss-20b", "chat_answer", "plain", "news"),
                                       ("openai/gpt-oss-120b", "chat_answer", "plain", "financials"),
                                       ("openai/gpt-oss-20b", "chat_grounding_review", "plain", "financials")):
            with self.subTest(model=model, task=task, mode=mode), patch("langchain_groq.ChatGroq") as factory:
                factory.return_value.invoke.return_value = SimpleNamespace(content='{"ok":true}', response_metadata={})
                _invoke(Settings("fake", model, "fake", "fake"), "rules",
                        {"task": task, "answer_style": style, "selection": {"mode": mode}}, 100)
                self.assertEqual(factory.call_args.kwargs["model_kwargs"]["response_format"]["type"], "json_schema")

    def test_diagnostics_keep_paths_rules_but_not_values_or_unknown_keys(self):
        payload = {"task": "chat_answer", "answer_style": "plain", "evidence": {"PER": {}}}
        fmt = response_format(payload, "openai/gpt-oss-20b")
        raw = dict(text="PRIVATE GENERATED TEXT", evidence_ids=["SECRET"], follow_up="", blocks=[], PRIVATE_KEY="key")
        event = schema_failure_summary({"failed_generation": json.dumps(raw), "message": "SECRET"}, fmt, "chat_answer")
        self.assertIn({"path": ["evidence_ids", 0], "rule": "enum"}, event["violations"])
        self.assertNotIn("SECRET", str(event))
        self.assertNotIn("PRIVATE", str(event))

    def test_missing_or_invalid_generation_is_not_copied(self):
        for raw in (None, "not JSON PRIVATE", "x" * 20001):
            event = schema_failure_summary({"failed_generation": raw}, {}, "PRIVATE_TASK")
            self.assertEqual(event["task"], "other")
            self.assertNotIn("PRIVATE", str(event))

    def test_sdk_schema_failure_records_diagnostic_without_extra_diagnostic_calls(self):
        payload = {"task": "chat_answer", "answer_style": "plain", "evidence": {"PER": {}}}
        error = RuntimeError("PRIVATE")
        error.status_code = 400
        error.body = {"code": "json_validate_failed", "failed_generation": '{"text":"PRIVATE"}'}
        with paced_verification() as pacer, patch("langchain_groq.ChatGroq") as factory:
            factory.return_value.invoke.side_effect = [error, SimpleNamespace(content='{"ok":true}', response_metadata={})]
            self.assertEqual(_invoke(Settings("fake", "openai/gpt-oss-20b", "fake", "fake"), "test", payload, 100), {"ok": True})
            self.assertEqual(factory.return_value.invoke.call_count, 2)
            self.assertEqual(pacer.events[0]["event"], "schema_failure")
            self.assertNotIn("PRIVATE", str(pacer.events))
