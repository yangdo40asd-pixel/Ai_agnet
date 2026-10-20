"""OpenDART 재무제표 계정 정규화, 비율 계산(이익률·부채비율·ROE), 연간/분기 비교 및 DART 부분 실패 검증."""

from decimal import Decimal
import unittest
from unittest.mock import patch

from src.config import Settings
from src.data.financials import (
    build_annual_comparison,
    build_financial_facts,
    build_quarter_comparison,
    calculate_ratios,
    candidate_annual_years,
    collect_company_financials,
    get_standard_amount,
    normalize_statement,
    parse_dart_amount,
)
from src.models import StockCandidate


def sample_raw_statement(
    bsns_year="2025",
    reprt_code="11011",
    fs_div="CFS",
    *,
    revenue="300,000,000,000",
    op_income="45,000,000,000",
    net_income="36,000,000,000",
    assets="500,000,000,000",
    liabilities="200,000,000,000",
    equity="300,000,000,000",
    op_cf="50,000,000,000",
    inv_cf="-20,000,000,000",
    fin_cf="-5,000,000,000",
    rev_add=None,
    op_add=None,
    net_add=None,
    include_cis_duplicate=False,
):
    rows = [
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "IS",
            "account_id": "ifrs-full_Revenue",
            "account_nm": "매출액",
            "thstrm_amount": revenue,
            "thstrm_add_amount": rev_add,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "IS",
            "account_id": "dart_OperatingIncomeLoss",
            "account_nm": "영업이익",
            "thstrm_amount": op_income,
            "thstrm_add_amount": op_add,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "IS",
            "account_id": "ifrs-full_ProfitLoss",
            "account_nm": "당기순이익",
            "thstrm_amount": net_income,
            "thstrm_add_amount": net_add,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "BS",
            "account_id": "ifrs-full_Assets",
            "account_nm": "자산총계",
            "thstrm_amount": assets,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "BS",
            "account_id": "ifrs-full_Liabilities",
            "account_nm": "부채총계",
            "thstrm_amount": liabilities,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "BS",
            "account_id": "ifrs-full_Equity",
            "account_nm": "자본총계",
            "thstrm_amount": equity,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "CF",
            "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "account_nm": "영업활동현금흐름",
            "thstrm_amount": op_cf,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "CF",
            "account_id": "ifrs-full_CashFlowsFromUsedInInvestingActivities",
            "account_nm": "투자활동현금흐름",
            "thstrm_amount": inv_cf,
            "currency": "KRW",
        },
        {
            "rcept_no": f"{bsns_year}0331000001",
            "sj_div": "CF",
            "account_id": "ifrs-full_CashFlowsFromUsedInFinancingActivities",
            "account_nm": "재무활동현금흐름",
            "thstrm_amount": fin_cf,
            "currency": "KRW",
        },
    ]
    if include_cis_duplicate:
        rows.append(
            {
                "rcept_no": f"{bsns_year}0331000001",
                "sj_div": "CIS",
                "account_id": "ifrs-full_ProfitLoss",
                "account_nm": "당기순이익(손실)",
                "thstrm_amount": "999,999,999,999",
                "currency": "KRW",
            }
        )
    return {
        "status": "ok",
        "corp_code": "00126380",
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
        "list": rows,
    }


class FinancialsNormalizationAndRatiosTests(unittest.TestCase):
    def setUp(self):
        self.stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")

    def test_parse_dart_amount_preserves_precision_and_distinguishes_zero_negative_missing(self):
        self.assertEqual(parse_dart_amount("300,000,000,000"), 300000000000)
        self.assertEqual(parse_dart_amount("-20,000,000,000"), -20000000000)
        self.assertEqual(parse_dart_amount("(5,000,000)"), -5000000)
        self.assertEqual(parse_dart_amount("0"), 0)
        self.assertEqual(parse_dart_amount("12.34"), Decimal("12.34"))
        for bad in (None, "", "-", "N/A", True, False):
            self.assertIsNone(parse_dart_amount(bad))

    def test_normalize_statement_does_not_sum_duplicate_is_and_cis_accounts(self):
        raw = sample_raw_statement(include_cis_duplicate=True)
        stmt = normalize_statement("005930", raw)
        self.assertEqual(stmt.status, "ok")
        self.assertEqual(get_standard_amount(stmt, "revenue"), 300000000000)
        self.assertEqual(get_standard_amount(stmt, "operating_income"), 45000000000)
        # IS가 CIS보다 우선하며 두 계정을 합산하지 않는다.
        self.assertEqual(get_standard_amount(stmt, "net_income"), 36000000000)
        # CF 유출 음수 부호를 그대로 보존한다.
        self.assertEqual(get_standard_amount(stmt, "investing_cash_flow"), -20000000000)

    def test_calculate_ratios_handles_normal_loss_zero_revenue_and_capital_impairment(self):
        stmt = normalize_statement("005930", sample_raw_statement())
        idx_resp = {"status": "ok", "list": [{"idx_nm": "ROE", "idx_val": "11.25"}]}
        ratios = calculate_ratios(stmt, idx_resp)
        self.assertEqual(ratios.operating_margin.value, 15.0)
        self.assertEqual(ratios.net_margin.value, 12.0)
        self.assertEqual(ratios.debt_ratio.value, 66.67)
        # 제공된 ROE는 이미 %이므로 100을 중복 곱하지 않는다.
        self.assertEqual(ratios.roe.value, 11.25)
        self.assertEqual(ratios.roe.basis, "provided")

        # 매출 0 또는 자본잠식(음수 자본)일 때 잘못된 비율을 만들지 않는다.
        impairment_stmt = normalize_statement(
            "005930",
            sample_raw_statement(revenue="0", op_income="-10,000", equity="-50,000,000,000"),
        )
        imp_ratios = calculate_ratios(impairment_stmt, None)
        self.assertIsNone(imp_ratios.operating_margin.value)
        self.assertEqual(imp_ratios.operating_margin.status, "invalid")
        self.assertIsNone(imp_ratios.debt_ratio.value)
        self.assertEqual(imp_ratios.debt_ratio.status, "impairment")
        self.assertIsNone(imp_ratios.roe.value)
        self.assertEqual(imp_ratios.roe.status, "impairment")

    def test_candidate_annual_years_does_not_assume_current_year_annual_is_disclosed(self):
        years = candidate_annual_years(reference_year=2026, count=3)
        self.assertEqual(years, ("2023", "2024", "2025"))
        self.assertNotIn("2026", years)

    def test_annual_comparison_does_not_mix_cfs_and_ofs_or_interpolate_missing_years(self):
        s_2023_cfs = normalize_statement("005930", sample_raw_statement(bsns_year="2023", fs_div="CFS"))
        s_2024_ofs = normalize_statement("005930", sample_raw_statement(bsns_year="2024", fs_div="OFS"))
        s_2025_cfs = normalize_statement("005930", sample_raw_statement(bsns_year="2025", fs_div="CFS"))
        summaries = build_annual_comparison([s_2025_cfs, s_2024_ofs, s_2023_cfs])
        # CFS 계열만 유지하며 2024(OFS)를 섞거나 보간하지 않는다.
        self.assertEqual([item.bsns_year for item in summaries], ["2023", "2025"])
        self.assertTrue(all(item.fs_div == "CFS" for item in summaries))

    def test_quarter_comparison_uses_3m_values_directly_and_derives_4q_from_annual_minus_q3_cumulative(self):
        q1 = normalize_statement(
            "005930",
            sample_raw_statement(bsns_year="2025", reprt_code="11013", revenue="70,000,000,000", rev_add="70,000,000,000"),
        )
        q2 = normalize_statement(
            "005930",
            sample_raw_statement(bsns_year="2025", reprt_code="11012", revenue="75,000,000,000", rev_add="145,000,000,000"),
        )
        q3 = normalize_statement(
            "005930",
            sample_raw_statement(bsns_year="2025", reprt_code="11014", revenue="80,000,000,000", rev_add="225,000,000,000"),
        )
        annual = normalize_statement(
            "005930",
            sample_raw_statement(bsns_year="2025", reprt_code="11011", revenue="310,000,000,000"),
        )
        quarters = build_quarter_comparison([q1, q2, q3, annual])
        self.assertEqual([q.period_label for q in quarters], ["2025 1Q", "2025 2Q", "2025 3Q", "2025 4Q"])
        # 2Q와 3Q는 이미 당분기 3개월 값인 thstrm_amount를 그대로 쓰며 다시 차감하지 않는다.
        self.assertEqual(quarters[1].revenue, 75000000000)
        self.assertEqual(quarters[2].revenue, 80000000000)
        # 4Q는 연간(3100억) - 3분기 누적(2250억) = 850억
        self.assertEqual(quarters[3].revenue, 85000000000)

    def test_collect_company_financials_falls_back_uniformly_to_ofs_when_cfs_is_empty(self):
        settings = Settings("g", "m", "i", "s", dart_api_key="test-dart-key")
        corp_map = {"005930": {"corp_code": "00126380", "ambiguous": False}}

        def fake_fetch_statement(corp_code, year, reprt_code, fs_div, *, settings):
            if fs_div == "CFS":
                return {"status": "empty", "message": "조회된 공시 재무 자료가 없습니다.", "list": []}
            return sample_raw_statement(bsns_year=year, reprt_code=reprt_code, fs_div="OFS")

        with (
            patch("src.data.financials.fetch_corp_codes", return_value=corp_map),
            patch("src.data.financials.fetch_statement", side_effect=fake_fetch_statement),
            patch("src.data.financials.fetch_financial_indices", return_value={"status": "empty", "list": []}),
        ):
            bundle = collect_company_financials(self.stock, settings, years=("2024", "2025"))

        self.assertEqual(bundle["status"], "ok")
        self.assertEqual(len(bundle["annual_summaries"]), 2)
        self.assertTrue(all(s.fs_div == "OFS" for s in bundle["annual_summaries"]))
        self.assertTrue(all(s.is_separate_fallback for s in bundle["statements"]))
        facts = bundle["facts"]
        self.assertTrue(any(f.fact_id == "FIN_2025_REVENUE" for f in facts))


if __name__ == "__main__":
    unittest.main()
