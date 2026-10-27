"""대시보드 화면(4+2 지표 카드·주가/거래량 차트·관련 종목·부분 실패·포맷) 검증."""

from datetime import datetime
from decimal import Decimal
import unittest

import pandas as pd

from src.data.history import build_related_stock_summary, normalize_price_history
from src.data.stock import financial_from_info
from src.models import (
    AnnualFinancialSummary,
    FinancialRatios,
    KST,
    MetricValue,
    QuarterlyFinancialSummary,
    StockCandidate,
)
from src.ui.charts import (
    build_annual_performance_figure,
    build_balance_sheet_figure,
    build_mini_sparkline_figure,
    build_price_volume_figure,
    build_quarter_performance_figure,
)
from src.ui.formatting import (
    format_change_summary,
    format_eok,
    format_multiple,
    format_per_share_krw,
    format_percent,
    format_price,
    format_volume,
)


class FormattingAndChartsTests(unittest.TestCase):
    def setUp(self):
        self.stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
        self.retrieved_at = datetime(2026, 10, 20, 12, 0, 0, tzinfo=KST)

    def test_unit_formatting_separates_won_per_share_multiple_percent_eok_and_signs(self):
        self.assertEqual(format_price(70000), "70,000원")
        self.assertEqual(format_price(None), "정보 없음")
        self.assertEqual(format_per_share_krw(4605), "4,605원")
        self.assertEqual(format_per_share_krw(-1200.5), "-1,200.50원")
        self.assertEqual(format_multiple(15.2), "15.20배")
        self.assertEqual(format_percent(12.345), "12.35%")
        self.assertEqual(format_percent(2.5, signed=True), "+2.50%")
        self.assertEqual(format_percent(-1.2, signed=True), "-1.20%")
        self.assertEqual(format_change_summary(1500, 2.19), "+1,500원 (+2.19%)")
        self.assertEqual(format_change_summary(-500, -0.71), "-500원 (-0.71%)")
        self.assertEqual(format_change_summary(0, 0.0), "0원 (0.00%)")
        self.assertEqual(format_change_summary(None, None), "등락 정보 없음")
        self.assertEqual(format_eok(Decimal("258935500000000")), "2,589,355.0억원")
        self.assertEqual(format_eok(0), "0.0억원")
        self.assertEqual(format_eok(None), "정보 없음")
        self.assertEqual(format_volume(12345678), "12,345,678주")

    def test_price_volume_figure_uses_shared_date_axis_and_distinct_units(self):
        frame = pd.DataFrame(
            {
                "Open": [69000.0, 70000.0, 71000.0],
                "High": [70500.0, 71500.0, 72000.0],
                "Low": [68500.0, 69500.0, 70000.0],
                "Close": [70000.0, 71000.0, 71500.0],
                "Volume": [10000000, 11000000, 12000000],
            },
            index=[
                pd.Timestamp("2026-10-13"),
                pd.Timestamp("2026-10-14"),
                pd.Timestamp("2026-10-16"),
            ],
        )
        history = normalize_price_history(
            self.stock,
            frame,
            "3M",
            retrieved_at=self.retrieved_at,
        )
        fig = build_price_volume_figure(self.stock, history)
        self.assertIsNotNone(fig)
        self.assertEqual(len(fig.data), 2)
        self.assertEqual(list(fig.data[0].x), ["2026-10-13", "2026-10-14", "2026-10-16"])
        self.assertEqual(list(fig.data[0].y), [70000.0, 71000.0, 71500.0])
        self.assertEqual(list(fig.data[1].y), [10000000, 11000000, 12000000])
        self.assertIn("주가 (원)", fig.layout.yaxis.title.text)
        self.assertIn("거래량 (주)", fig.layout.yaxis2.title.text)
        self.assertIn("005930", fig.layout.title.text)

        summary = build_related_stock_summary(self.stock, history)
        spark = build_mini_sparkline_figure(summary)
        self.assertIsNotNone(spark)
        self.assertEqual(list(spark.data[0].y), [70000.0, 71000.0, 71500.0])

    def test_empty_or_mismatched_history_returns_none_figure(self):
        empty_history = normalize_price_history(
            self.stock,
            pd.DataFrame(),
            "3M",
            retrieved_at=self.retrieved_at,
        )
        self.assertIsNone(build_price_volume_figure(self.stock, empty_history))
        empty_summary = build_related_stock_summary(self.stock, empty_history)
        self.assertIsNone(build_mini_sparkline_figure(empty_summary))

    def test_financial_performance_and_balance_sheet_figures_convert_won_to_eok_once(self):
        summaries = (
            AnnualFinancialSummary(
                bsns_year="2024",
                fs_div="CFS",
                revenue=300000000000,
                operating_income=30000000000,
                net_income=25000000000,
                total_assets=500000000000,
                total_liabilities=200000000000,
                total_equity=300000000000,
            ),
            AnnualFinancialSummary(
                bsns_year="2025",
                fs_div="CFS",
                revenue=350000000000,
                operating_income=42000000000,
                net_income=33000000000,
                total_assets=560000000000,
                total_liabilities=210000000000,
                total_equity=350000000000,
            ),
        )
        annual_fig = build_annual_performance_figure(self.stock, summaries)
        self.assertIsNotNone(annual_fig)
        self.assertEqual(list(annual_fig.data[0].x), ["2024", "2025"])
        self.assertEqual(list(annual_fig.data[0].y), [3000.0, 3500.0])
        self.assertIn("억원", annual_fig.layout.yaxis.title.text)

        bs_fig = build_balance_sheet_figure(self.stock, summaries)
        self.assertIsNotNone(bs_fig)
        self.assertEqual(list(bs_fig.data[0].y), [5000.0, 5600.0])

        quarters = (
            QuarterlyFinancialSummary(
                bsns_year="2025",
                reprt_code="11013",
                fs_div="CFS",
                period_label="2025 1Q",
                period_type="quarter_3m",
                revenue=80000000000,
                operating_income=9000000000,
                net_income=7000000000,
            ),
            QuarterlyFinancialSummary(
                bsns_year="2025",
                reprt_code="11012",
                fs_div="CFS",
                period_label="2025 반기누적",
                period_type="cumulative",
                revenue=170000000000,
                operating_income=19000000000,
                net_income=15000000000,
            ),
        )
        q_fig = build_quarter_performance_figure(self.stock, quarters)
        self.assertIsNotNone(q_fig)
        # 누적(cumulative) 데이터는 당분기(quarter_3m) 차트에 섞지 않는다.
        self.assertEqual(list(q_fig.data[0].x), ["2025 1Q"])

    def test_dashboard_renders_financial_tables_roe_card_and_dart_links(self):
        from pathlib import Path
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        from src.models import (
            AnalysisResult,
            CandidateDiscoveryResult,
            Commentary,
            NewsArticle,
            NewsData,
            Statement,
        )

        app_path = Path(__file__).resolve().parents[1] / "src" / "ui" / "app.py"
        stock = self.stock
        roe_metric = MetricValue(
            name="ROE",
            value=11.25,
            unit="%",
            source="OpenDART 주요 재무지표 (fnlttSinglIndx)",
            raw_field="idx_val (ROE)",
            period="2025년 사업보고서",
            status="ok",
            basis="provided",
        )
        fin = financial_from_info(
            stock,
            {
                "symbol": "005930.KS",
                "currency": "KRW",
                "financialCurrency": "KRW",
                "regularMarketPrice": 70000,
                "trailingPE": 15.2,
                "trailingEps": 4605.0,
                "bookValue": 51850.0,
                "priceToBook": 1.35,
                "regularMarketTime": 1700000000,
            },
        )
        from dataclasses import replace
        fin = replace(fin, roe_metric=roe_metric)
        annual = (
            AnnualFinancialSummary(
                bsns_year="2025",
                fs_div="CFS",
                revenue=300000000000,
                operating_income=45000000000,
                net_income=36000000000,
                total_assets=500000000000,
                total_liabilities=200000000000,
                total_equity=300000000000,
                operating_cash_flow=50000000000,
                investing_cash_flow=-20000000000,
                financing_cash_flow=-5000000000,
                operating_margin=15.0,
                net_margin=12.0,
                debt_ratio=66.67,
                roe=11.25,
                rcept_no="20260331000001",
            ),
        )
        ratios = FinancialRatios(
            roe=roe_metric,
            operating_margin=MetricValue(
                name="영업이익률", value=15.0, unit="%", period="2025년 사업보고서 (CFS)",
                status="ok", basis="calculated", formula="영업이익 / 매출액 × 100",
            ),
            net_margin=MetricValue(
                name="순이익률", value=12.0, unit="%", period="2025년 사업보고서 (CFS)",
                status="ok", basis="calculated", formula="당기순이익 / 매출액 × 100",
            ),
            debt_ratio=MetricValue(
                name="부채비율", value=66.67, unit="%", period="2025년 사업보고서 (CFS)",
                status="ok", basis="calculated", formula="부채총계 / 자본총계 × 100",
            ),
            bsns_year="2025",
            reprt_code="11011",
            fs_div="CFS",
            status="ok",
        )
        news = NewsData(
            articles=(
                NewsArticle(1, "반도체 수출 호조", "https://example.com/1", "2026-10-13 KST", "example.com"),
            ),
            retrieved_at=self.retrieved_at,
        )
        stmt = Statement("수출 호조 소식입니다.", (1,))
        comm = Commentary((stmt,), "핵심 지표 설명입니다.", stmt, stmt, stmt)
        result = AnalysisResult(
            theme="반도체",
            candidates=(stock,),
            financial=fin,
            news=news,
            commentary=comm,
            selected_code="005930",
            annual_summaries=annual,
            financial_ratios=ratios,
            section_status={"financial": "ok", "dart": "ok", "news": "ok", "commentary": "ok"},
            result_id="반도체:005930:3M:latest:11011:CFS:0",
        )

        with patch("src.pipeline.analyze_selected_stock", return_value=result):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["candidate_result"] = CandidateDiscoveryResult(
                theme="반도체", candidates=(stock,), retrieved_at=self.retrieved_at
            )
            app.session_state["selected_code"] = "005930"
            app.run()
            app.button(key="add_canvas").click().run()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(
            [m.value for m in app.metric],
            ["70,000원", "15.20배", "1.35배", "11.25%", "4,605원", "51,850원"],
        )
        links = [el.proto.url for el in app.get("link_button")]
        self.assertIn("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260331000001", links)


if __name__ == "__main__":
    unittest.main()
