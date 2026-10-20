"""엑셀(XLSX) 시트·네이티브 차트·수식 주입 방지·원자료 대조 및 종목 전환 다운로드 상태 검증 테스트."""

import io
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import openpyxl
from streamlit.testing.v1 import AppTest

from src.export.excel import (
    SHEET_NAMES,
    build_export_filename,
    build_workbook_bytes,
    reconcile_workbook_values,
    sanitize_excel_text,
)
from src.models import (
    AnalysisResult,
    AnnualFinancialSummary,
    AppError,
    CandidateDiscoveryResult,
    Commentary,
    FinancialData,
    FinancialFact,
    FinancialRatios,
    MetricValue,
    NewsArticle,
    NewsData,
    PriceBar,
    PriceHistory,
    QueryOptions,
    Statement,
    StockCandidate,
)
from src.ui.state import (
    ensure_export_bundle,
    select_candidate,
    store_analysis_error,
    store_analysis_result,
)

KST = ZoneInfo("Asia/Seoul")


def _make_sample_result(
    code: str = "005930",
    name: str = "삼성전자",
    price: float | None = 70000.0,
    per: float | None = 15.2,
    theme: str = "반도체",
) -> AnalysisResult:
    dt = datetime(2026, 10, 20, 10, 30, tzinfo=KST)
    stock = StockCandidate(name, code, "KOSPI", f"{code}.KS")
    candidates = (
        StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
        StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
    )
    fin = FinancialData(
        stock=stock,
        price=price,
        per=per,
        retrieved_at=dt,
        price_at=dt,
        pbr_metric=MetricValue("PBR", 1.35, "배", period="2025년 기말", status="ok", basis="provided"),
        eps_metric=MetricValue("EPS", 4605.0, "원", period="TTM", status="ok", basis="provided"),
        bps_metric=MetricValue("BPS", None, "원", status="missing", basis="missing", message="BPS 원자료 없음"),
    )
    history = PriceHistory(
        code=code,
        ticker=f"{code}.KS",
        period="3M",
        bars=(
            PriceBar("2026-10-16", 69000.0, 70500.0, 68800.0, 69500.0, 11000000),
            PriceBar("2026-10-19", 69600.0, 70800.0, 69200.0, 70000.0, 12500000),
        ),
        currency="KRW",
        adjusted=False,
        retrieved_at=dt,
        status="ok",
    )
    annuals = (
        AnnualFinancialSummary(
            bsns_year="2024",
            reprt_code="11011",
            fs_div="CFS",
            revenue=Decimal("300870903000000"),
            operating_income=Decimal("32725961000000"),
            net_income=Decimal("34451351000000"),
            total_assets=Decimal("514531948000000"),
            total_liabilities=Decimal("112339878000000"),
            total_equity=Decimal("402192070000000"),
            operating_cash_flow=Decimal("72982621000000"),
            investing_cash_flow=Decimal("-85381702000000"),
            financing_cash_flow=Decimal("-7797243000000"),
            roe=8.997,
            rcept_no="20250311001085",
        ),
        AnnualFinancialSummary(
            bsns_year="2025",
            reprt_code="11011",
            fs_div="CFS",
            revenue=Decimal("333605938000000"),
            operating_income=Decimal("43601051000000"),
            net_income=Decimal("45206805000000"),
            total_assets=Decimal("566942110000000"),
            total_liabilities=Decimal("130621773000000"),
            total_equity=Decimal("436320337000000"),
            operating_cash_flow=Decimal("85315148000000"),
            investing_cash_flow=Decimal("-68512206000000"),
            financing_cash_flow=Decimal("-13478040000000"),
            roe=10.783,
            rcept_no="20260310002820",
        ),
    )
    ratios = FinancialRatios(
        roe=MetricValue("ROE", 10.783, "%", period="2025년 사업보고서", status="ok", basis="provided"),
        operating_margin=MetricValue(
            "영업이익률", 13.07, "%", period="2025년 사업보고서", status="ok", basis="calculated",
            formula="영업이익 / 매출액 × 100",
        ),
        net_margin=MetricValue(
            "순이익률", 13.55, "%", period="2025년 사업보고서", status="ok", basis="calculated",
            formula="당기순이익 / 매출액 × 100",
        ),
        debt_ratio=MetricValue(
            "부채비율", 29.94, "%", period="2025년 사업보고서", status="ok", basis="calculated",
            formula="부채총계 / 자본총계 × 100",
        ),
        bsns_year="2025",
        reprt_code="11011",
        fs_div="CFS",
        status="ok",
    )
    news = NewsData(
        articles=(
            NewsArticle(1, "=SUM(1,2) 반도체 수출 증가 소식", "https://example.com/news/1", "2026-10-20 KST", "example.com"),
        ),
        retrieved_at=dt,
    )
    stmt = Statement("반도체 수출 관련 긍정 소식이 보도되었습니다.", (1,))
    fstmt = Statement(
        "연결재무제표 기준 최근 사업연도 매출액과 영업이익이 직전 사업연도 대비 증가했습니다.",
        (),
        ("FIN_2024_REVENUE", "FIN_2025_REVENUE", "FIN_2025_OPERATING_INCOME"),
    )
    comm = Commentary(
        theme_trend=(stmt,),
        stock_comment="현재 주가와 PER가 확인되었습니다.",
        opportunity=stmt,
        risk=stmt,
        summary=stmt,
        financial_commentary=(fstmt,),
    )
    return AnalysisResult(
        theme=theme,
        candidates=candidates,
        financial=fin,
        news=news,
        commentary=comm,
        selected_code=code,
        query_options=QueryOptions(price_period="3M", fs_div="CFS"),
        price_history=history,
        annual_summaries=annuals,
        financial_ratios=ratios,
        financial_facts=(
            FinancialFact(
                fact_id="FIN_2025_REVENUE",
                stock_code=code,
                stock_name=name,
                item="매출액",
                value=Decimal("333605938000000"),
                display_value="3,336,059.4억원",
                unit="억원",
                period="2025년 연간",
                fs_div="CFS",
                source="OpenDART",
                polarity="positive",
            ),
        ),
        section_status={
            "financial": "ok",
            "history": "ok",
            "dart": "ok",
            "news": "ok",
            "commentary": "ok",
            "financial_commentary": "ok",
        },
        result_id=f"{theme}:{code}:3M:latest:11011:CFS:0",
    )


class ExcelExportTests(unittest.TestCase):
    def test_filename_generation_and_formula_sanitization(self):
        result = _make_sample_result(theme='반도체/AI: "차세대"?')
        fname = build_export_filename(result)
        self.assertTrue(fname.endswith("_삼성전자_005930_3M_20261020.xlsx"))
        self.assertFalse(any(ch in fname for ch in r'\/:*?"<>|'))

        self.assertEqual(sanitize_excel_text("=CMD|' /C calc'!A0"), "'=CMD|' /C calc'!A0")
        self.assertEqual(sanitize_excel_text("+100"), "'+100")
        self.assertEqual(sanitize_excel_text("-200"), "'-200")
        self.assertEqual(sanitize_excel_text("@SUM(A1:A2)"), "'@SUM(A1:A2)")

    def test_workbook_reconciliation_leading_zero_missing_blank_and_native_charts(self):
        result = _make_sample_result()
        xlsx_bytes = build_workbook_bytes(result)
        self.assertGreater(len(xlsx_bytes), 5000)

        check = reconcile_workbook_values(result, xlsx_bytes)
        self.assertTrue(check["all_sheets_present"])
        self.assertEqual(check["sheet_names"], SHEET_NAMES)
        self.assertTrue(check["code_matches"])
        self.assertEqual(check["summary_code"], "005930")
        self.assertTrue(check["price_matches"])
        self.assertTrue(check["per_matches"])

        # 결측치(BPS=None)는 0이 아니라 None(빈 셀)이어야 함
        self.assertIsNone(check["metric_values"]["BPS"])
        self.assertEqual(check["metric_values"]["PBR"], 1.35)
        self.assertEqual(check["metric_values"]["ROE"], 10.78)
        self.assertEqual(check["metric_values"]["영업이익률"], 13.07)
        self.assertEqual(check["metric_values"]["부채비율"], 29.94)

        # 일별시세 및 손익계산서 원값/억원 대조
        self.assertEqual(check["history_rows"], 2)
        self.assertEqual(check["first_close"], 69500)
        self.assertEqual(check["last_close"], 70000)
        self.assertEqual(check["annual_rows"], 2)
        self.assertEqual(check["latest_rev_krw"], 333605938000000)
        self.assertEqual(check["latest_rev_eok"], 3336059.38)

        # 수식 주입된 셀이 단 하나도 없어야 함
        self.assertEqual(check["formula_cells"], [])

        # 네이티브 차트(주가·거래량·손익·재무상태·요약)와 셀 범위 참조 확인
        self.assertGreaterEqual(check["chart_count"], 4)
        refs_joined = " | ".join(check["chart_references"])
        self.assertIn("일별시세!$E$5:$E$6", refs_joined)
        self.assertIn("일별시세!$F$5:$F$6", refs_joined)
        self.assertIn("손익계산서!$F$5:$F$6", refs_joined)
        self.assertIn("재무상태표!$F$5:$F$6", refs_joined)

    def test_state_invalidates_export_on_stock_switch_and_error_and_reuses_on_same_result(self):
        res_a = _make_sample_result(code="005930", name="삼성전자", price=70000.0)
        res_b = _make_sample_result(code="000660", name="SK하이닉스", price=190000.0)
        state: dict = {}

        store_analysis_result(state, res_a, "반도체|005930|3M|latest|11011|CFS|0")
        bytes_a = state["export_bytes"]
        name_a = state["export_filename"]
        self.assertIn("005930", name_a)

        # 동일 result_id로 재호출 시 build_workbook_bytes를 다시 실행하지 않고 캐시 재사용
        with patch("src.ui.state.build_workbook_bytes") as mock_build:
            cached_b, cached_n = ensure_export_bundle(state, res_a)
            mock_build.assert_not_called()
        self.assertEqual(cached_b, bytes_a)
        self.assertEqual(cached_n, name_a)

        # 종목을 000660으로 변경하면 이전 005930 엑셀 바이트가 즉시 무효화됨
        select_candidate(state, "000660")
        self.assertNotIn("export_bytes", state)
        self.assertNotIn("export_filename", state)

        # B 분석 성공 시 B의 엑셀 바이트가 저장되고 내부 종목코드가 000660임
        store_analysis_result(state, res_b, "반도체|000660|3M|latest|11011|CFS|0")
        self.assertIn("000660", state["export_filename"])
        wb_b = openpyxl.load_workbook(io.BytesIO(state["export_bytes"]))
        self.assertEqual(wb_b["요약"]["B5"].value, "000660")

        # 이후 전환/재요청 실패 시 이전 파일이 남지 않음
        store_analysis_error(state, "금융 조회 실패", request_key="반도체|000660|1Y|latest|11011|CFS|0")
        self.assertNotIn("export_bytes", state)
        self.assertNotIn("dashboard_result", state)

    def test_apptest_download_button_matches_selected_stock_and_switches_cleanly(self):
        app_path = Path(__file__).resolve().parents[1] / "src" / "ui" / "app.py"
        res_a = _make_sample_result(code="005930", name="삼성전자", price=70000.0)
        res_b = _make_sample_result(code="000660", name="SK하이닉스", price=190000.0)
        discovery = CandidateDiscoveryResult(
            theme="반도체",
            candidates=res_a.candidates,
            retrieved_at=res_a.financial.retrieved_at,
        )

        with patch("src.pipeline.analyze_selected_stock", side_effect=[res_a, res_b]) as mock_analyze:
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["candidate_result"] = discovery
            app.session_state["selected_code"] = "005930"
            app.run()

            self.assertEqual(len(app.exception), 0)
            self.assertEqual(mock_analyze.call_count, 1)
            self.assertIn("005930", app.session_state["export_filename"])
            self.assertGreater(len(app.get("download_button")), 0)

            # 단순 rerun에서는 analyze_selected_stock과 build_workbook_bytes를 다시 호출하지 않음
            with patch("src.ui.state.build_workbook_bytes") as mock_build:
                app.run()
                mock_build.assert_not_called()
            self.assertEqual(mock_analyze.call_count, 1)

            # 후보 2(000660)로 전환 시 새 종목 엑셀로 교체됨
            app.selectbox(key="candidate_selector").select("000660").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(mock_analyze.call_count, 2)
            self.assertIn("000660", app.session_state["export_filename"])
            wb = openpyxl.load_workbook(io.BytesIO(app.session_state["export_bytes"]))
            self.assertEqual(wb["요약"]["B5"].value, "000660")


if __name__ == "__main__":
    unittest.main()
