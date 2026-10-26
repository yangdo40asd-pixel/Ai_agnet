"""질문에 필요한 비교·근거·표시 동작을 확인한다. 모든 수치는 가상이다."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch
import unittest

from src.agents.answer_quality import select_evidence, QUALITY_CHECKS
from src.agents.chat import answer_question, build_evidence
from src.agents.request import company_to_lookup
from src.agents.report import generate_commentary, validate_report
from src.analysis_flow import analysis_response
from src.data.financial_comparison import annual_comparison_evidence
from src.models import AnnualFinancialSummary, AppError
from src.ui.answer import source_groups
from test_answer_blocks import sample_result
from test_report_pipeline import example_financial, example_news, example_payload
from src.config import Settings
from review_fixtures import with_review_units


def annuals():
    return (AnnualFinancialSummary("2024", revenue=10_000_000_000, operating_income=1_000_000_000),
            AnnualFinancialSummary("2025", revenue=12_000_000_000, operating_income=1_800_000_000))


def comparison(rows):
    return annual_comparison_evidence(rows, stock_code="123456", result_id="fixture")


class FinancialComparisonTests(unittest.TestCase):
    def test_growth_and_margin_are_computed_from_same_basis(self):
        facts = comparison(annuals())
        self.assertEqual(Decimal(facts["CMP_2024_2025_CFS_REVENUE"]["change_pct"]), 20)
        self.assertEqual(Decimal(facts["CMP_2024_2025_CFS_OPERATING_INCOME"]["change_pct"]), 80)
        margin = facts["CMP_2024_2025_CFS_OPERATING_MARGIN"]
        self.assertEqual(Decimal(margin["previous"]), 10)
        self.assertEqual(Decimal(margin["current"]), 15)
        self.assertEqual(Decimal(margin["delta_pp"]), 5)

    def test_no_comparison_across_basis_gap_currency_or_duplicate(self):
        old, new = annuals()
        for rows in ((old, replace(new, fs_div="OFS")), (old, replace(new, bsns_year="2026")),
                     (old, replace(new, currency="USD")), (old, old, new),
                     (old, replace(new, reprt_code="11013"))):
            with self.subTest(rows=rows):
                self.assertFalse(any(k.startswith("CMP_") for k in comparison(rows)))

    def test_loss_transitions_and_zero_base_do_not_invent_growth_rates(self):
        old, new = annuals()
        for before, after, state in ((-10, 20, "흑자 전환"), (10, -20, "적자 전환"),
                                     (-10, -5, "적자 축소"), (-10, -20, "적자 확대"),
                                     (0, 10, "전기 값이 영이므로 증감률 계산 제외")):
            item = comparison((replace(old, operating_income=before), replace(new, operating_income=after)))["CMP_2024_2025_CFS_OPERATING_INCOME"]
            self.assertIsNone(item["change_pct"])
            self.assertEqual(item["change_state"], state)

    def test_missing_profit_retains_revenue_without_implying_profit_growth(self):
        old, new = annuals()
        facts = comparison((replace(old, operating_income=None), new))
        self.assertIn("CMP_2024_2025_CFS_REVENUE", facts)
        self.assertNotIn("CMP_2024_2025_CFS_OPERATING_INCOME", facts)
        self.assertNotIn("CMP_2024_2025_CFS_OPERATING_MARGIN", facts)


class QuestionScopeTests(unittest.TestCase):
    def setUp(self):
        self.result = replace(sample_result(), annual_summaries=annuals())
        self.evidence = build_evidence(self.result)

    def test_revenue_followup_uses_profit_comparison_and_omits_unasked_news_pbr(self):
        before = deepcopy(self.evidence)
        selection = select_evidence("매출이 늘었으면 실적이 좋아진 거야?", [], self.evidence, [])
        self.assertIn("CMP_2024_2025_CFS_REVENUE", selection.evidence)
        self.assertIn("CMP_2024_2025_CFS_OPERATING_INCOME", selection.required_ids)
        self.assertIn("CMP_2024_2025_CFS_OPERATING_MARGIN", selection.required_ids)
        self.assertNotIn("PBR", selection.evidence)
        self.assertFalse(any(k.startswith("NEWS_") for k in selection.evidence))
        self.assertEqual(self.evidence, before)

    def test_explicit_year_uses_that_year_not_latest_comparison(self):
        selection = select_evidence("2024년 매출 알려줘", [], self.evidence, [])
        self.assertIn("FIN_2024_CFS_REVENUE", selection.evidence)
        self.assertFalse(any(k.startswith("CMP_") for k in selection.evidence))

    def test_mixed_news_financial_question_preserves_both_and_per_does_not_leak(self):
        mixed = select_evidence("뉴스와 실적을 함께 설명해줘", [], self.evidence, [])
        self.assertIn("NEWS_1", mixed.evidence)
        self.assertIn("CMP_2024_2025_CFS_REVENUE", mixed.evidence)
        metric = select_evidence("그럼 PER을 비교해서 어떻게 봐야 해?", [], self.evidence, ["PER"])
        self.assertEqual(set(metric.evidence), {"PER"})
        self.assertEqual(company_to_lookup("그럼 PER 9.6배는 어떻게 봐야 해?"), "")

    def test_financial_question_passes_computed_values_through_generation_and_review(self):
        ids = ["CMP_2024_2025_CFS_REVENUE", "CMP_2024_2025_CFS_OPERATING_INCOME", "CMP_2024_2025_CFS_OPERATING_MARGIN"]
        payload = dict(text="연결 기준으로 매출과 영업이익이 함께 증가했습니다. 매출은 {{" + ids[0] + "}}, 영업이익은 {{" + ids[1] + "}}입니다. 영업이익률도 {{" + ids[2] + "}}으로 높아졌습니다.", evidence_ids=ids, follow_up="", blocks=[])
        verdict = dict(checks=dict.fromkeys(QUALITY_CHECKS, True), supported=True, answers_question=True)
        with patch("src.agents.chat._invoke", side_effect=with_review_units([payload, verdict])) as invoke:
            response = answer_question("매출이 늘었으면 실적이 좋아진 거야?", self.result, [], Settings("fake", "model", "fake", "fake"))
        self.assertIn("80.00% 증가", response.text)
        self.assertNotIn("정보 없음", response.text)
        self.assertNotIn("PBR", str(invoke.call_args_list[0].args[2]["evidence"]))
        self.assertEqual(set(invoke.call_args_list[1].args[2]["evidence"]), set(ids))

    def test_default_report_and_financial_fact_units(self):
        response = analysis_response(self.result)
        self.assertIn("80.00% 증가", response.text)
        self.assertNotIn("PBR", [e["id"] for e in response.evidence])
        self.assertNotIn("억원 억원", str(self.evidence))
        self.assertNotIn("%%", str(self.evidence))

    def test_footer_groups_same_period_and_preserves_different_periods(self):
        response = analysis_response(self.result)
        from src.ui.answer import response_fields
        message = dict(text=response.text, evidence=response.evidence, **response_fields(response))
        groups, numbers = source_groups(message)
        cmp_ids = [k for k in numbers if k.startswith("CMP_")]
        self.assertEqual(len({numbers[k] for k in cmp_ids}), 1)
        self.assertTrue(all("id" in item for group in groups for item in group["items"]))


class BasicReportQualityTests(unittest.TestCase):
    settings = Settings("fake", "model", "fake", "fake")

    def test_no_relevant_news_can_omit_all_sections(self):
        payload = dict(example_payload(), theme_trend=[], stock_comment="", opportunity=None, risk=None, summary=None)
        self.assertEqual(validate_report(payload, example_financial(), example_news()).theme_trend, ())
        with patch("src.agents.report._invoke", return_value=payload) as invoke:
            result = generate_commentary("반도체", example_financial(), example_news(), self.settings)
        self.assertIsNone(result.summary)
        self.assertEqual(invoke.call_count, 1)

    def test_irrelevant_article_with_valid_id_retries_and_does_not_return(self):
        payload = dict(example_payload(), stock_comment="", opportunity=None, risk=None, summary=None)
        payload["theme_trend"] = [{"text": "경영 구조 강화가 반도체 실적을 높일 가능성이 있습니다.", "news_ids": [1]}]
        rejected = dict(checks=dict.fromkeys(QUALITY_CHECKS, False), supported=False, answers_question=False)
        with patch("src.agents.report._invoke", side_effect=with_review_units([payload, rejected, payload, rejected])) as invoke:
            with self.assertRaises(AppError) as caught:
                generate_commentary("반도체", example_financial(), example_news(), self.settings)
        self.assertEqual(caught.exception.code, "report_grounding")
        self.assertEqual(invoke.call_count, 4)

    def test_review_rate_limit_is_not_rewritten(self):
        with patch("src.agents.report._invoke", side_effect=[example_payload(), AppError("ai_rate_limit", "한도")]) as invoke:
            with self.assertRaises(AppError) as caught:
                generate_commentary("반도체", example_financial(), example_news(), self.settings)
        self.assertEqual(caught.exception.code, "ai_rate_limit")
        self.assertEqual(invoke.call_count, 2)
