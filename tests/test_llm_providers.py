"""공급자 전환·오류·외부 폴백 금지를 네트워크 없이 확인한다."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest
import httpx

from src.config import Settings, load_settings, validate_local_settings
from src.models import AppError
from src.agents.transport import _invoke
from src.agents.local_verification import local_verification


def settings(**changes):
    return replace(Settings("", "", "", "", ai_provider="local", local_model="fixture"), **changes)


def response(content='{"ok":true}', *, finish="stop", status=200):
    data = {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17, "private": "secret"}}
    return httpx.Response(status, json=data, request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))


class LocalProviders(unittest.TestCase):
    def test_local_uses_same_json_contract_without_groq_key_or_client(self):
        with patch("src.agents.providers.local.httpx.Client") as client, patch("langchain_groq.ChatGroq") as groq, local_verification() as run:
            client.return_value.__enter__.return_value.post.return_value = response()
            self.assertEqual(_invoke(settings(), "rules", {"task": "chat_answer", "evidence": {}}, 100), {"ok": True})
            groq.assert_not_called()
            sent = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
            self.assertEqual(sent["model"], "fixture")
            self.assertEqual(sent["response_format"]["type"], "json_schema")
            self.assertEqual(sent["messages"][0]["role"], "system")
            self.assertNotIn("reasoning_effort", sent)
            self.assertFalse(client.call_args.kwargs["follow_redirects"])
            self.assertFalse(client.call_args.kwargs["trust_env"])
            self.assertEqual(run.requests, 1)
            self.assertEqual(run.events[0]["usage"]["total_tokens"], 17)
            self.assertNotIn("secret", str(run.events))

    def test_groq_default_does_not_contact_local(self):
        with patch("langchain_groq.ChatGroq") as groq, patch("src.agents.providers.local.invoke") as local:
            groq.return_value.invoke.return_value = SimpleNamespace(content='{"ok":true}', response_metadata={})
            self.assertEqual(_invoke(Settings("fake", "model", "", ""), "rules", {}, 100), {"ok": True})
            local.assert_not_called()

    def test_schema_constraint_is_not_duplicated_and_json_mode_keeps_contract(self):
        payload = {"task": "chat_answer", "evidence": {"PRICE": {"value": 100}}}
        for mode in ("schema", "json"):
            with self.subTest(mode=mode), patch("src.agents.providers.local.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response()
                _invoke(settings(local_output_mode=mode), "rules", payload, 100)
                sent = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
                user = json.loads(sent["messages"][1]["content"])
                if mode == "schema":
                    self.assertEqual(user, payload)
                    schema = sent["response_format"]["json_schema"]["schema"]
                else:
                    self.assertEqual(sent["response_format"], {"type": "json_object"})
                    schema = user["required_output_schema"]
                self.assertEqual(schema["properties"]["evidence_ids"]["items"]["enum"], ["PRICE"])
                self.assertEqual(payload, {"task": "chat_answer", "evidence": {"PRICE": {"value": 100}}})

    def test_local_errors_never_retry_or_fall_back_to_cloud(self):
        for status, code in ((401, "ai_local_auth"), (404, "ai_local_model"), (400, "ai_local_request"),
                             (503, "ai_local_busy"), (500, "ai_local_failed"), (302, "ai_local_failed")):
            with self.subTest(status=status), patch("src.agents.providers.local.httpx.Client") as client, patch("langchain_groq.ChatGroq") as groq:
                post = client.return_value.__enter__.return_value.post
                post.return_value = response(status=status)
                with self.assertRaises(AppError) as caught:
                    _invoke(settings(), "secret input", {}, 100)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("secret", caught.exception.message)
                post.assert_called_once()
                groq.assert_not_called()

    def test_connect_and_generation_timeouts_are_distinct(self):
        for error, code in ((httpx.ConnectError("secret"), "ai_local_unavailable"),
                            (httpx.ReadTimeout("secret"), "ai_local_timeout")):
            with self.subTest(code=code), patch("src.agents.providers.local.httpx.Client") as client, local_verification() as run:
                client.return_value.__enter__.return_value.post.side_effect = error
                with self.assertRaises(AppError) as caught:
                    _invoke(settings(), "rules", {}, 100)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(run.events[0]["error_code"], code)

    def test_common_parser_rejects_duplicate_keys_and_truncation(self):
        for raw, finish, code in (('{"a":1,"a":2}', "stop", "ai_format"), ('{"a":', "length", "ai_truncated"),
                                  ('[]', "stop", "ai_format"), ('{}', "tool_calls", "ai_local_format")):
            with self.subTest(code=code), patch("src.agents.providers.local.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response(raw, finish=finish)
                with self.assertRaises(AppError) as caught:
                    _invoke(settings(), "rules", {}, 100)
                self.assertEqual(caught.exception.code, code)

    def test_complete_json_with_length_finish_is_not_truncated(self):
        # 문법 제약 생성이 JSON을 끝낸 뒤 공백만 내보내다 한도에서 멈춘 경우다. 내용은 완결돼 있다.
        with patch("src.agents.providers.local.httpx.Client") as client, local_verification() as run:
            client.return_value.__enter__.return_value.post.return_value = response('{"ok":true}\n', finish="length")
            self.assertEqual(_invoke(settings(), "rules", {}, 100), {"ok": True})
            self.assertEqual(run.events[0]["finish_reason_original"], "length")

    def test_malformed_envelope_is_not_a_success(self):
        for data in ([], {}, {"choices": [None]}, {"choices": [{"message": {}, "finish_reason": "stop"}]}):
            with self.subTest(data=data), patch("src.agents.providers.local.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = httpx.Response(200, json=data)
                with self.assertRaises(AppError) as caught:
                    _invoke(settings(), "rules", {}, 100)
                self.assertEqual(caught.exception.code, "ai_local_format")

    def test_verification_budget_stops_before_network_and_lock_is_released(self):
        with local_verification(max_requests=1) as run, patch("src.agents.providers.local.httpx.Client") as client:
            post = client.return_value.__enter__.return_value.post
            post.return_value = response()
            _invoke(settings(), "rules", {}, 100)
            with self.assertRaises(AppError) as caught:
                _invoke(settings(), "rules", {}, 100)
            self.assertEqual(caught.exception.code, "ai_verification_budget")
            self.assertEqual(run.requests, 1)
            post.assert_called_once()
        with patch("src.agents.providers.local.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response()
            self.assertEqual(_invoke(settings(), "rules", {}, 100), {"ok": True})

    def test_settings_reject_remote_redirect_credentials_and_invalid_timeouts(self):
        for url in ("https://api.example.com/v1", "http://192.168.0.3/v1", "http://localhost.evil/v1",
                    "http://user:secret@localhost/v1", "http://localhost/v1?key=secret", "http://localhost:bad/v1"):
            with self.subTest(url=url), self.assertRaises(AppError):
                validate_local_settings(settings(local_base_url=url))
        for value in (float("nan"), float("inf"), 0, True, 601):
            with self.subTest(timeout=value), self.assertRaises(AppError):
                validate_local_settings(settings(local_read_timeout=value))

    def test_load_settings_checks_selected_provider_only(self):
        env = {"AI_PROVIDER": "local", "LOCAL_LLM_MODEL": "fixture", "GROQ_MODEL": "", "GROQ_API_KEY": ""}
        with patch.dict("os.environ", env, clear=True), patch("src.config.load_dotenv"):
            result = load_settings()
            self.assertEqual(result.ai_provider, "local")
            self.assertEqual(result.groq_api_key, "")
            self.assertTrue(result.strict_news)
        with patch.dict("os.environ", {}, clear=True), patch("src.config.load_dotenv"):
            result = load_settings()
            self.assertEqual(result.ai_provider, "groq")
            self.assertFalse(result.strict_news)

    def test_busy_queue_does_not_send_another_request(self):
        with patch("src.agents.providers.local._request_lock") as lock, patch("src.agents.providers.local.httpx.Client") as client:
            lock.acquire.return_value = False
            with self.assertRaises(AppError) as caught:
                _invoke(settings(), "rules", {}, 100)
            self.assertEqual(caught.exception.code, "ai_local_busy")
            client.assert_not_called()
