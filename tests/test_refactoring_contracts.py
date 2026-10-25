"""조회 실패 경계, 공급자 요청 계약, 재무 계산 경계의 추가 검수."""
from contextlib import ExitStack
from dataclasses import asdict, replace
from decimal import Decimal
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.agents.transport import _invoke, response_format
from src.config import Settings
from src.data.financials import calculate_ratios, normalize_statement, get_standard_amount
from src.models import AppError
from src.pipeline import analyze_selected_stock
from test_excel_export import _make_sample_result
from test_financials import sample_raw_statement


class CollectionFailureContracts(unittest.TestCase):
    def test_scoped_failures_preserve_unrequested_data_and_original_snapshot(self):
        base = _make_sample_result()
        settings = Settings("fake", "model", "fake", "fake", dart_api_key="fake")
        original = asdict(base)
        # all은 각 공급자 실패를 개별 주입한다. 다른 범위는 해당 공급자만 호출한다.
        for scope in ("all", "finance", "news", "history", "financials"):
            sources = ("finance", "news", "history", "financials") if scope == "all" else (scope,)
            for source in sources:
                for failure in ("auth_error", "timeout", "partial"):
                    with self.subTest(scope=scope, source=source, failure=failure), ExitStack() as stack:
                        finance = stack.enter_context(patch("src.pipeline.fetch_financial", return_value=base.financial))
                        news = stack.enter_context(patch("src.pipeline.fetch_news", return_value=base.news))
                        history = stack.enter_context(patch("src.pipeline.fetch_price_history", return_value=base.price_history))
                        related = stack.enter_context(patch("src.pipeline.fetch_related_stock_summaries", return_value=base.related_stocks))
                        dart = stack.enter_context(patch("src.pipeline.collect_company_financials", return_value={
                            "status": "ok", "statements": base.financial_statements,
                            "annual_summaries": base.annual_summaries, "ratios": base.financial_ratios,
                        }))
                        report = stack.enter_context(patch("src.pipeline.generate_commentary", return_value=None))
                        if source == "finance":
                            if failure == "partial":
                                finance.return_value = replace(base.financial, per=None, warnings=("PER 미확인",))
                            else:
                                # 금융 수집기는 인증/시간 초과를 finance_failed로 변환한다.
                                finance.side_effect = AppError("finance_failed", failure)
                        elif source == "news":
                            news.return_value = replace(base.news, articles=base.news.articles if failure == "partial" else (),
                                                        status="partial" if failure == "partial" else "failed", message=failure)
                        elif source == "history":
                            history.return_value = replace(base.price_history, status="partial" if failure == "partial" else "failed",
                                                           message=failure)
                        else:
                            dart.return_value = {"status": failure, "statements": base.financial_statements if failure == "partial" else ()}
                        fatal = source == "finance" and failure != "partial"
                        if fatal:
                            with self.assertRaises(AppError) as caught:
                                analyze_selected_stock(base.theme, base.candidates, base.target_code, settings=settings, scope=scope, previous=base)
                            self.assertEqual(caught.exception.code, "finance_failed")
                            for call in (news, history, related, dart, report):
                                call.assert_not_called()
                        else:
                            updated = analyze_selected_stock(base.theme, base.candidates, base.target_code, settings=settings, scope=scope, previous=base)
                            self.assertNotEqual(updated.result_id, base.result_id)
                            self.assertEqual(updated.target_code, base.target_code)
                            status_key = {"finance": "financial", "news": "news", "history": "history", "financials": "dart"}[source]
                            expected = failure if source == "financials" else "partial" if failure == "partial" else "failed"
                            self.assertEqual(updated.section_status[status_key], expected)
                            for name, call in (("finance", finance), ("news", news), ("history", history), ("financials", dart)):
                                self.assertEqual(call.call_count, int(scope in {"all", name}))
                            self.assertEqual(report.call_count, int(scope == "all"))
                            if scope not in {"all", "finance", "financials"}:
                                self.assertEqual(updated.financial, base.financial)
                            if scope not in {"all", "news"}:
                                self.assertEqual(updated.news, base.news)
                            if scope not in {"all", "history"}:
                                self.assertEqual(updated.price_history, base.price_history)
                            if scope not in {"all", "financials"}:
                                self.assertEqual(updated.financial_statements, base.financial_statements)
                        self.assertEqual(asdict(base), original)


class AITransportContracts(unittest.TestCase):
    cases = (
        ({"theme": "반도체", "available_names": ["가", "나", "다"]}, {"stocks"}, 250, .1),
        ({"task": "chat_route", "candidates": []}, {"action", "theme", "code", "company", "scope", "period"}, 600, .1),
        ({"task": "chat_answer", "evidence": {"PER": {}, "NEWS_1": {}}}, {"text", "evidence_ids", "follow_up", "blocks"}, 2200, .2),
        ({"task": "chat_grounding_review"}, {"supported", "answers_question", "reason", "checks", "unit_reviews"}, 3000, 0),
        ({"stock_name": "가", "price": 100, "per": None, "headlines": [{"id": 7}]},
         {"stock_name", "price", "per", "theme_trend", "stock_comment", "opportunity", "risk", "summary"}, 1800, .1),
        ({"stock_name": "가", "stock_code": "123456", "financial_facts": [{"fact_id": "F1"}]},
         {"stock_name", "stock_code", "financial_commentary"}, 1200, .1),
    )

    def test_all_task_schemas_and_provider_options(self):
        for model in ("qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b", "legacy-model"):
            for payload, fields, limit, temperature in self.cases:
                with self.subTest(model=model, task=payload.get("task", sorted(fields))), patch("langchain_groq.ChatGroq") as factory:
                    factory.return_value.invoke.return_value = SimpleNamespace(content='{"ok": true}', response_metadata={"finish_reason": "stop"})
                    result = _invoke(Settings("fake", model, "fake", "fake"), "규칙", payload, limit, temperature)
                    self.assertEqual(result, {"ok": True})
                    options = factory.call_args.kwargs
                    self.assertEqual(options["temperature"], temperature)
                    self.assertEqual(options["max_tokens"], max(limit, 1024) if model.startswith("openai/") else limit)
                    self.assertEqual(options["max_retries"], 0)
                    self.assertEqual(options["timeout"], Settings("fake", model, "fake", "fake").request_timeout)
                    expected_effort = ("medium" if payload.get("task") == "chat_grounding_review" else "low") if model.startswith("openai/") else None
                    self.assertEqual(options.get("reasoning_effort"), expected_effort)
                    messages = factory.return_value.invoke.call_args.args[0]
                    self.assertEqual(messages[0], ("system", "규칙"))
                    self.assertEqual(json.loads(messages[1][1]), payload)
                    fmt = options["model_kwargs"]["response_format"]
                    if model == "legacy-model":
                        self.assertEqual(fmt, {"type": "json_object"})
                    else:
                        self.assertTrue(fmt["json_schema"]["strict"])
                        schema = fmt["json_schema"]["schema"]
                        self.assertEqual(set(schema["properties"]), fields)
                        self.assertEqual(set(schema["required"]), fields)
                        self.assertFalse(schema["additionalProperties"])

    def test_schema_evidence_and_empty_data_constraints(self):
        def props(payload):
            return response_format(payload, "qwen/qwen3.8-27b")["json_schema"]["schema"]["properties"]
        self.assertEqual(props(self.cases[0][0])["stocks"]["items"]["enum"], ["가", "나", "다"])
        self.assertEqual(props(self.cases[2][0])["evidence_ids"]["items"]["enum"], ["PER", "NEWS_1"])
        self.assertEqual(props({"task": "chat_answer", "evidence": {}})["evidence_ids"]["maxItems"], 0)
        report = props(self.cases[4][0])
        self.assertEqual(report["price"]["enum"], [100])
        self.assertEqual(report["per"]["type"], "null")
        self.assertEqual(report["summary"]["properties"]["news_ids"]["items"]["enum"], [7])
        empty = props(dict(self.cases[4][0], headlines=[]))
        self.assertEqual(empty["summary"], {"type": "null"})
        self.assertEqual(empty["theme_trend"]["maxItems"], 0)
        financial = props(self.cases[5][0])["financial_commentary"]
        self.assertEqual(financial["items"]["properties"]["fact_ids"]["items"]["enum"], ["F1"])
        self.assertEqual(props(dict(self.cases[5][0], financial_facts=[]))["financial_commentary"]["maxItems"], 0)

    def test_retry_budget_and_response_errors_for_every_task(self):
        for payload, _, limit, temperature in self.cases:
            for status, expected in ((401, "ai_auth"), (403, "ai_auth"), (429, "ai_rate_limit"), (504, "ai_failed")):
                error = RuntimeError("private upstream body")
                error.status_code = status
                with self.subTest(task=payload.get("task"), status=status), patch("langchain_groq.ChatGroq") as factory:
                    factory.return_value.invoke.side_effect = error
                    with self.assertRaises(AppError) as caught:
                        _invoke(Settings("fake", "qwen/qwen3.8-27b", "fake", "fake"), "규칙", payload, limit, temperature)
                    self.assertEqual(caught.exception.code, expected)
                    self.assertNotIn("private", caught.exception.message)
                    factory.return_value.invoke.assert_called_once()
        for content, finish, code in (('{"a":1,"a":2}', "stop", "ai_format"), ('[]', "stop", "ai_format"), ('{}', "length", "ai_truncated")):
            with self.subTest(code=code), patch("langchain_groq.ChatGroq") as factory:
                factory.return_value.invoke.return_value = SimpleNamespace(content=content, response_metadata={"finish_reason": finish})
                with self.assertRaises(AppError) as caught:
                    _invoke(Settings("fake", "model", "fake", "fake"), "규칙", {}, 100)
                self.assertEqual(caught.exception.code, code)


class FinancialCalculationContracts(unittest.TestCase):
    def test_official_roe_and_average_or_ending_equity(self):
        statement = normalize_statement("005930", sample_raw_statement())
        prior = normalize_statement("005930", sample_raw_statement(bsns_year="2024", equity="200000000000"))
        self.assertEqual(calculate_ratios(statement, prior_statement=prior).roe.value, 14.4)
        self.assertIn("평균", calculate_ratios(statement, prior_statement=prior).roe.formula)
        self.assertEqual(calculate_ratios(statement).roe.value, 12.0)
        self.assertIn("기말", calculate_ratios(statement).roe.formula)
        for value in ("0", "-2.375", "11.23456789"):
            roe = calculate_ratios(statement, {"status": "ok", "list": [{"idx_nm": "ROE", "idx_val": value}]}, prior_statement=prior).roe
            self.assertEqual(roe.value, float(value))
            self.assertEqual(roe.basis, "provided")
        mismatched = replace(prior, fs_div="OFS")
        self.assertEqual(calculate_ratios(statement, prior_statement=mismatched).roe.value, 12.0)
        quarterly = normalize_statement("005930", sample_raw_statement(reprt_code="11013"))
        self.assertIsNone(calculate_ratios(quarterly, prior_statement=prior).roe.value)

    def test_decimal_precision_loss_and_nonpositive_equity(self):
        statement = normalize_statement("005930", sample_raw_statement(
            revenue="999999999999999.123456789", op_income="123456789012345.123456789",
            net_income="-123456789012345.123456789", equity="333333333333333.123456789"))
        self.assertEqual(get_standard_amount(statement, "revenue"), Decimal("999999999999999.123456789"))
        ratios = calculate_ratios(statement)
        self.assertEqual(ratios.operating_margin.value, 12.35)
        self.assertEqual(ratios.net_margin.value, -12.35)
        self.assertEqual(ratios.roe.value, -37.04)
        for equity in ("0", "-1"):
            prior = normalize_statement("005930", sample_raw_statement(bsns_year="2024", equity=equity))
            self.assertIsNone(calculate_ratios(statement, prior_statement=prior).roe.value)


if __name__ == "__main__":
    unittest.main()
