"""당분기 수집·근거·수치 검증의 정상/반례. 값은 가상 재무 fixture다."""
import copy
from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from src.config import Settings
from src.data.report_period import QuarterRequest, quarter_request
from src.data.quarterly import collect_quarterly_financials, quarterly_evidence
from src.data.financials import normalize_statement, build_quarter_comparison
from src.agents.quarterly import contextual_quarter, selection_data
from src.agents.answer_quality import select_evidence, model_evidence
from src.agents.financial_numbers import verified_sentence
from src.agents.chat import validate_answer
from src.models import AppError, StockCandidate
from test_financials import sample_raw_statement


def statement(year="2025", code="11014", basis="CFS", revenue="12000000000", profit="2400000000", cumulative="90000000000"):
    return normalize_statement("005930", sample_raw_statement(
        bsns_year=year, reprt_code=code, fs_div=basis, revenue=revenue, op_income=profit,
        rev_add=cumulative, net_income="1000000000"))


def evidence():
    statements = (statement("2024", revenue="10000000000", profit="1000000000"), statement())
    return quarterly_evidence(build_quarter_comparison(statements), stock_code="005930",
                              result_id="q-fixture", statements=statements)


class QuarterPeriodTests(unittest.TestCase):
    def test_request_is_explicit_and_bounded(self):
        request = quarter_request("2025년 3분기 실적 어때?", reference_year=2026)
        self.assertEqual(request.reports, (("2024", "11014"), ("2025", "11014")))
        self.assertFalse(request.reason)
        self.assertEqual(len(QuarterRequest(2025, 4).reports), 4)

    def test_first_supported_year_does_not_request_unsupported_prior_year(self):
        self.assertEqual(QuarterRequest(2015, 3).reports, (("2015", "11014"),))

    def test_relative_year_uses_reference_not_latest_available_year(self):
        self.assertEqual(quarter_request("올해 2분기 매출", reference_year=2026).year, 2026)
        self.assertEqual(quarter_request("작년 2분기 매출", reference_year=2026).year, 2025)

    def test_ambiguous_and_unsupported_periods_are_not_replaced(self):
        for text in ("3분기 실적", "2025년 3분기 누적 매출", "2025년 2분기 대비 3분기 실적",
                     "2023년과 2025년 3분기 비교", "2025년 연결과 별도 3분기 실적", "2027년 3분기 실적"):
            with self.subTest(text=text):
                self.assertTrue(quarter_request(text, reference_year=2026).reason)

    def test_news_provisional_and_concepts_are_not_official_quarter_requests(self):
        for text in ("2025년 3분기 실적 뉴스", "2025년 3분기 잠정 실적", "3분기 매출의 뜻", "2025년 어닝콜 실적"):
            self.assertIsNone(quarter_request(text))

    def test_context_is_carried_only_for_same_topic_followup(self):
        messages = [{"role": "user", "text": "2025년 3분기 실적은?"}]
        self.assertEqual(contextual_quarter("그럼 영업이익률은?", messages).year, 2025)
        for text in ("2024년 연간 실적", "PER은?", "최근 뉴스", "올해 실적은?"):
            self.assertIsNone(contextual_quarter(text, messages))


class QuarterCollectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("", "", "", "", dart_api_key="fixture-key")
        self.stock = StockCandidate("가상회사", "005930", "KOSPI", "005930.KS")
        self.corp = patch("src.data.quarterly.fetch_corp_codes", return_value={"005930": {"corp_code": "00126380", "corp_name": "가상회사"}})
        self.corp.start(); self.addCleanup(self.corp.stop)

    def raw(self, corp, year, code, basis, **kwargs):
        return sample_raw_statement(bsns_year=year, reprt_code=code, fs_div=basis)

    def test_only_requested_and_prior_quarter_are_collected(self):
        with patch("src.data.quarterly.fetch_statement", side_effect=self.raw) as fetch:
            bundle = collect_quarterly_financials(self.stock, QuarterRequest(2025, 3), self.settings)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual({q.period_label for q in bundle["summaries"]}, {"2024 3Q", "2025 3Q"})
        self.assertEqual(bundle["status"], "ok")
        self.assertTrue(all(c["elapsed_ms"] >= 0 for c in bundle["calls"]))

    def test_explicit_basis_does_not_fallback(self):
        with patch("src.data.quarterly.fetch_statement", return_value={"status": "empty"}) as fetch:
            bundle = collect_quarterly_financials(self.stock, QuarterRequest(2025, 3, "CFS"), self.settings)
        self.assertEqual(fetch.call_count, 2); self.assertEqual(bundle["status"], "empty")

    def test_auto_basis_falls_back_as_a_whole_only_on_empty(self):
        def fetch(corp, year, code, basis, **kwargs):
            return {"status": "empty"} if basis == "CFS" else self.raw(corp, year, code, basis)
        with patch("src.data.quarterly.fetch_statement", side_effect=fetch) as mocked:
            bundle = collect_quarterly_financials(self.stock, QuarterRequest(2025, 3), self.settings)
        self.assertEqual(mocked.call_count, 4)
        self.assertEqual({s.fs_div for s in bundle["summaries"]}, {"OFS"})

    def test_auth_and_rate_limit_stop_without_fallback_or_retry(self):
        for status in ("auth_error", "rate_limit"):
            with self.subTest(status=status), patch("src.data.quarterly.fetch_statement", return_value={"status": status}) as fetch:
                bundle = collect_quarterly_financials(self.stock, QuarterRequest(2025, 3), self.settings)
                self.assertEqual(fetch.call_count, 1); self.assertEqual(bundle["status"], "failed")

    def test_missing_prior_is_partial_not_invented_comparison(self):
        def fetch(corp, year, code, basis, **kwargs):
            return {"status": "empty"} if year == "2024" else self.raw(corp, year, code, basis)
        with patch("src.data.quarterly.fetch_statement", side_effect=fetch):
            bundle = collect_quarterly_financials(self.stock, QuarterRequest(2025, 3), self.settings)
        self.assertEqual(bundle["status"], "partial")
        refs = quarterly_evidence(bundle["summaries"], stock_code="005930", result_id="q")
        self.assertFalse(any(v["kind"] == "quarterly_comparison" for v in refs.values()))

    def test_invalid_request_never_calls_api(self):
        with patch("src.data.quarterly.fetch_statement") as fetch:
            collect_quarterly_financials(self.stock, QuarterRequest(2025, 3, reason="clarify"), self.settings)
        fetch.assert_not_called()


class QuarterEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.refs = evidence()

    def test_quarter_does_not_use_cumulative_amount(self):
        current = self.refs["QFIN_2025_3_CFS_REVENUE"]
        self.assertEqual(Decimal(current["value"]), Decimal("12000000000"))
        self.assertIn("3개월", current["period"])
        self.assertTrue(current["parents"])

    def test_growth_and_margin_are_from_same_quarter(self):
        growth = self.refs["Q_CMP_2024_2025_3_CFS_REVENUE"]
        margin = self.refs["Q_CMP_2024_2025_3_CFS_OPERATING_MARGIN"]
        self.assertEqual(Decimal(growth["change_pct"]), 20)
        self.assertEqual(Decimal(margin["delta_pp"]), 10)
        self.assertEqual(growth["kind"], "quarterly_comparison")

    def test_duplicate_currency_and_period_type_are_not_promoted(self):
        q = build_quarter_comparison((statement(),))[0]
        for entries in ((q, q), (replace(q, currency="USD"),), (replace(q, period_type="cumulative"),)):
            self.assertEqual(quarterly_evidence(entries, stock_code="005930", result_id="q"), {})
        self.assertEqual(build_quarter_comparison((statement(), statement())), ())

    def test_separate_and_different_quarters_do_not_form_yoy_pair(self):
        old = build_quarter_comparison((statement("2024"),))[0]
        new = build_quarter_comparison((statement(),))[0]
        for changed in (replace(old, fs_div="OFS"), replace(old, period_label="2024 2Q")):
            refs = quarterly_evidence((changed, new), stock_code="005930", result_id="q")
            self.assertFalse(any(v["kind"] == "quarterly_comparison" for v in refs.values()))

    def test_negative_and_zero_do_not_get_growth_percentage(self):
        for previous in ("-100", "0"):
            statements = (statement("2024", profit=previous), statement())
            refs = quarterly_evidence(build_quarter_comparison(statements), stock_code="005930", result_id="q")
            self.assertIsNone(refs["Q_CMP_2024_2025_3_CFS_OPERATING_INCOME"]["change_pct"])

    def test_explicit_selection_never_uses_annual_or_other_period(self):
        mixed = {**self.refs, "ANNUAL": {"kind": "annual_comparison", "years": [2024, 2025]}}
        selected = select_evidence("2025년 3분기 실적 어때?", [], mixed, [], strict=True)
        self.assertEqual(selected.reason, "quarterly")
        self.assertTrue(selected.required_ids)
        self.assertTrue(all(v.get("kind") == "quarterly_comparison" for v in selected.evidence.values()))
        wrong = select_evidence("2023년 3분기 실적은?", [], mixed, [], strict=True)
        self.assertEqual(wrong.evidence, {})

    def test_mixed_question_keeps_explicit_price_and_per(self):
        refs = {**self.refs, "PRICE": {"value": 10000, "status": "ok", "value_text": "10,000원"},
                "PER": {"value": 12, "status": "ok", "value_text": "12.00배"}}
        selected = select_evidence("2025년 3분기 실적과 현재 주가, PER을 함께 설명해줘", [], refs, ["PRICE", "PER"], strict=True)
        self.assertTrue({"PRICE", "PER"}.issubset(selected.required_ids))
        self.assertTrue(any(v.get("kind") == "quarterly_comparison" for v in selected.evidence.values()))
        missing = select_evidence("2026년 3분기 실적과 현재 주가", [], refs, ["PRICE"], strict=True)
        self.assertIn("PRICE", missing.evidence)
        self.assertIn("QUARTER_STATUS", missing.evidence)

    def test_missing_quarter_in_mixed_answer_keeps_available_quote(self):
        refs = {"PRICE": {"value": 10000, "value_text": "10,000원", "status": "ok"}}
        selected = select_evidence("2026년 3분기 실적과 주가", [], refs, ["PRICE"], strict=True)
        answer = validate_answer({"text": "{{QUARTER_STATUS}}. 확인된 주가는 {{PRICE}}입니다.",
            "evidence_ids": ["QUARTER_STATUS", "PRICE"], "follow_up": ""}, selected.evidence,
            question="2026년 3분기 실적과 주가")[0]
        self.assertIn("10,000원", answer)
        self.assertIn("2026년 3분기", answer)

    def test_model_receives_verified_sentence_without_changing_source_kind(self):
        converted = model_evidence(self.refs)
        self.assertIn("verified_sentence", converted["Q_CMP_2024_2025_3_CFS_REVENUE"])
        self.assertEqual(converted["Q_CMP_2024_2025_3_CFS_REVENUE"]["kind"], "quarterly_comparison")

    def validate(self, text, refs=None):
        refs = refs or {"Q_CMP_2024_2025_3_CFS_REVENUE": self.refs["Q_CMP_2024_2025_3_CFS_REVENUE"]}
        return validate_answer({"text": text, "evidence_ids": list(refs), "follow_up": ""}, refs,
                               question="2025년 3분기 매출 어때?")

    def test_valid_quarter_expression_passes_and_preserves_original(self):
        key = "Q_CMP_2024_2025_3_CFS_REVENUE"
        before = copy.deepcopy(self.refs)
        sentence = verified_sentence(self.refs[key])
        self.assertIn("증가", self.validate("2025년 3분기 " + sentence)[0])
        self.assertEqual(self.refs, before)

    def test_wrong_year_quarter_value_direction_and_item_stay_rejected(self):
        sentence = verified_sentence(self.refs["Q_CMP_2024_2025_3_CFS_REVENUE"])
        bad = ("2026년 3분기 " + sentence, "2025년 2분기 " + sentence,
               sentence.replace("20.00%", "21.00%"), sentence.replace("증가", "감소"),
               sentence.replace("매출", "영업이익"), "전분기 대비 " + sentence)
        for text in bad:
            with self.subTest(text=text), self.assertRaises(AppError):
                self.validate(text)

    def test_current_margin_statement_binds_value_to_current_year_and_item(self):
        key = "Q_CMP_2024_2025_3_CFS_OPERATING_MARGIN"
        refs = {key: self.refs[key]}
        text = "가상회사의 2025년 3분기 영업이익률은 20.00%입니다."
        self.validate(text, refs)
        for invalid in (text.replace("20.00%", "21.00%"), text.replace("2025년", "2024년"),
                        text.replace("3분기", "2분기"), text.replace("영업이익률", "순이익률")):
            with self.subTest(invalid=invalid), self.assertRaises(AppError):
                self.validate(invalid, refs)

    def test_recorded_comma_form_checks_current_value_delta_year_and_direction(self):
        key = "Q_CMP_2024_2025_3_CFS_OPERATING_MARGIN"
        refs = {key: self.refs[key]}
        text = "2025년 3분기 영업이익률은 20.00%로, 전년 동기 대비 10.00%p 상승했습니다."
        self.validate(text, refs)
        for invalid in (text.replace("20.00%", "21.00%"), text.replace("10.00%p", "11.00%p"),
                        text.replace("상승", "하락"), text.replace("2025년", "2024년")):
            with self.subTest(invalid=invalid), self.assertRaises(AppError):
                self.validate(invalid, refs)

    def test_current_value_cannot_be_attributed_to_valid_but_previous_year(self):
        key = "Q_CMP_2024_2025_3_CFS_REVENUE"
        current = self.refs[key]["current"]
        from src.formatting import format_eok
        with self.assertRaises(AppError):
            self.validate("2024년 3분기 매출은 " + format_eok(Decimal(current)) + "입니다.")
        answer = self.validate("2025년 3분기 매출은 " + format_eok(Decimal(current)) + "입니다.")[0]
        self.assertIn("2025년", answer)

    def test_three_month_basis_is_allowed_but_six_months_not(self):
        sentence = verified_sentence(self.refs["Q_CMP_2024_2025_3_CFS_REVENUE"])
        self.validate("3개월 실적을 비교하면 " + sentence)
        with self.assertRaises(AppError):
            self.validate("6개월 실적을 비교하면 " + sentence)

    def test_placeholder_value_retains_period_and_actual_number(self):
        key = "QFIN_2025_3_CFS_REVENUE"
        answer = self.validate("2025년 3분기 매출은 {{" + key + "}}입니다.", {key: self.refs[key]})[0]
        self.assertIn(self.refs[key]["value_text"], answer)
