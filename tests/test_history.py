"""추가 금융 지표(EPS·BPS·PBR), 일별 주가·거래량 이력(OHLCV), 관련 종목 요약 검증."""

from datetime import datetime
import unittest
from unittest.mock import patch

import pandas as pd

from src.data.history import (
    build_related_stock_summary,
    fetch_price_history,
    fetch_related_stock_summaries,
    normalize_price_history,
    resolve_range_key,
)
from src.data.stock import (
    fetch_financial,
    financial_from_info,
    reconcile_financial_metrics,
    supplement_trailing_eps,
    supplement_trailing_per,
)
from src.models import AppError, KST, StockCandidate


class AdditionalMetricsTests(unittest.TestCase):
    def setUp(self):
        self.stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
        self.base_info = {
            "symbol": "005930.KS",
            "currency": "KRW",
            "financialCurrency": "KRW",
            "regularMarketPrice": 70000,
            "currentPrice": 70000,
            "trailingPE": 15.2,
            "trailingEps": 4605.0,
            "bookValue": 51850.0,
            "priceToBook": 1.35,
            "regularMarketTime": 1700000000,
        }

    def test_eps_bps_pbr_are_collected_independently_when_per_is_present(self):
        data = financial_from_info(self.stock, self.base_info)
        self.assertEqual(data.price, 70000)
        self.assertEqual(data.per, 15.2)
        self.assertEqual(data.eps, 4605.0)
        self.assertEqual(data.bps, 51850.0)
        self.assertEqual(data.pbr, 1.35)
        self.assertEqual(data.eps_metric.unit, "주당 원")
        self.assertEqual(data.bps_metric.unit, "주당 원")
        self.assertEqual(data.pbr_metric.unit, "배")
        self.assertEqual(data.pbr_metric.basis, "provided")

    def test_negative_and_zero_eps_are_preserved_with_explanation(self):
        neg_data = financial_from_info(self.stock, {**self.base_info, "trailingEps": -1250.0})
        self.assertEqual(neg_data.eps, -1250.0)
        self.assertEqual(neg_data.eps_metric.status, "ok")
        self.assertIn("0 이하", neg_data.eps_metric.reason)

        zero_data = financial_from_info(self.stock, {**self.base_info, "trailingEps": 0.0})
        self.assertEqual(zero_data.eps, 0.0)
        self.assertEqual(zero_data.eps_metric.status, "ok")

    def test_missing_or_zero_pbr_is_calculated_from_verified_price_and_bps_with_formula(self):
        calc_data = financial_from_info(
            self.stock,
            {**self.base_info, "priceToBook": None, "regularMarketPrice": 50000, "bookValue": 25000},
        )
        self.assertEqual(calc_data.pbr, 2.0)
        self.assertEqual(calc_data.pbr_metric.basis, "calculated")
        self.assertEqual(calc_data.pbr_metric.formula, "주가 / BPS")

        zero_pbr_no_bps = financial_from_info(
            self.stock,
            {**self.base_info, "priceToBook": 0.0, "bookValue": None},
        )
        self.assertIsNone(zero_pbr_no_bps.pbr)
        self.assertEqual(zero_pbr_no_bps.pbr_metric.status, "missing")

    def test_non_krw_financial_currency_hides_eps_bps_pbr(self):
        usd_data = financial_from_info(self.stock, {**self.base_info, "financialCurrency": "USD"})
        self.assertEqual(usd_data.price, 70000)
        self.assertIsNone(usd_data.eps)
        self.assertIsNone(usd_data.bps)
        self.assertIsNone(usd_data.pbr)
        self.assertEqual(usd_data.eps_metric.status, "missing")

    def test_missing_trailing_eps_is_supplemented_from_diluted_eps_even_when_per_exists(self):
        info_without_eps = {**self.base_info, "trailingEps": None}
        income = pd.DataFrame({pd.Timestamp("2023-09-30"): {"DilutedEPS": 4500.0}})
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.get_info.return_value = info_without_eps
            mock_ticker.return_value.get_income_stmt.return_value = income
            data = fetch_financial(self.stock)
        self.assertEqual(data.per, 15.2)
        self.assertIsNone(data.per_eps)
        self.assertEqual(data.eps, 4500.0)
        self.assertEqual(data.eps_metric.raw_field, "DilutedEPS")
        self.assertIn("2023-09-30", data.eps_metric.period)

    def test_reconcile_financial_metrics_preserves_raw_precision_and_formats_display(self):
        raw_info = {**self.base_info, "trailingPE": 15.234567, "priceToBook": 1.35678}
        data = financial_from_info(self.stock, raw_info)
        table = reconcile_financial_metrics(data, raw_info)
        self.assertEqual(data.per, 15.234567)
        self.assertEqual(table["per"]["normalized_value"], 15.234567)
        self.assertEqual(table["per"]["display_value"], "15.23배")
        self.assertEqual(table["pbr"]["normalized_value"], 1.35678)
        self.assertEqual(table["pbr"]["display_value"], "1.36배")
        self.assertEqual(table["eps"]["display_value"], "4,605원")
        self.assertEqual(table["bps"]["display_value"], "51,850원")


class PriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
        self.retrieved_at = datetime(2026, 10, 20, 12, 0, 0, tzinfo=KST)

    def sample_frame(self):
        return pd.DataFrame(
            {
                "Open": [71000.0, 69000.0, 70000.0],
                "High": [72000.0, 70500.0, 71500.0],
                "Low": [70000.0, 68500.0, 69500.0],
                "Close": [71500.0, 70000.0, 71000.0],
                "Volume": [12000000, 10000000, 11000000],
            },
            index=[
                pd.Timestamp("2026-10-16"),
                pd.Timestamp("2026-10-13"),
                pd.Timestamp("2026-10-14"),
            ],
        )

    def test_normalize_sorts_ascending_and_does_not_fill_holiday_gaps(self):
        history = normalize_price_history(
            self.stock,
            self.sample_frame(),
            "1M",
            retrieved_at=self.retrieved_at,
        )
        self.assertEqual(history.status, "ok")
        self.assertFalse(history.adjusted)
        self.assertEqual(history.currency, "KRW")
        self.assertEqual(
            [bar.trade_date for bar in history.bars],
            ["2026-10-13", "2026-10-14", "2026-10-16"],
        )
        self.assertEqual(len(history.bars), 3)

    def test_invalid_or_future_or_duplicate_bars_are_filtered(self):
        frame = pd.DataFrame(
            {
                "Open": [70000.0, 70500.0, -100.0, 71000.0],
                "High": [71000.0, 71500.0, 71000.0, 72000.0],
                "Low": [69500.0, 70000.0, 69000.0, 70500.0],
                "Close": [70200.0, 71200.0, 70000.0, 71500.0],
                "Volume": [1000, 2000, 1500, 3000],
            },
            index=[
                pd.Timestamp("2026-10-15"),
                pd.Timestamp("2026-10-15"),  # 중복 거래일 -> 최신 행 유지
                pd.Timestamp("2026-10-16"),  # 음수 시가 -> 제외
                pd.Timestamp("2026-12-31"),  # 미래 날짜 -> 제외
            ],
        )
        history = normalize_price_history(
            self.stock,
            frame,
            "3M",
            retrieved_at=self.retrieved_at,
        )
        self.assertEqual(len(history.bars), 1)
        self.assertEqual(history.bars[0].trade_date, "2026-10-15")
        self.assertEqual(history.bars[0].close, 71200.0)
        self.assertEqual(history.bars[0].volume, 2000)

    def test_wrong_currency_or_wrong_multiindex_ticker_is_rejected(self):
        bad_currency = normalize_price_history(
            self.stock,
            self.sample_frame(),
            "3M",
            currency="USD",
            retrieved_at=self.retrieved_at,
        )
        self.assertEqual(bad_currency.status, "failed")
        self.assertEqual(bad_currency.bars, ())

        multi_cols = pd.MultiIndex.from_product(
            [["Open", "High", "Low", "Close", "Volume"], ["000660.KS"]]
        )
        wrong_df = pd.DataFrame(
            [[1, 2, 1, 2, 100]],
            index=[pd.Timestamp("2026-10-15")],
            columns=multi_cols,
        )
        wrong_ticker = normalize_price_history(
            self.stock,
            wrong_df,
            "3M",
            retrieved_at=self.retrieved_at,
        )
        self.assertEqual(wrong_ticker.status, "failed")
        self.assertEqual(wrong_ticker.bars, ())

    def test_related_stock_summary_uses_same_adjustment_daily_close_and_reuses_selected_history(self):
        history = normalize_price_history(
            self.stock,
            self.sample_frame(),
            "1M",
            retrieved_at=self.retrieved_at,
        )
        summary = build_related_stock_summary(self.stock, history)
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.price, 71500.0)
        self.assertEqual(summary.change, 500.0)
        self.assertAlmostEqual(summary.change_pct, (500.0 / 71000.0) * 100.0)
        self.assertIn("무수정 종가 기준", summary.comparison_basis)
        self.assertEqual(len(summary.sparkline_closes), 3)

        candidates = (
            self.stock,
            StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
            StockCandidate("미확인회사", reason="상장 종목명과 일치하지 않음"),
        )
        with patch("src.data.history.fetch_price_history") as mock_fetch:
            summaries = fetch_related_stock_summaries(
                candidates,
                selected_code="005930",
                selected_history=history,
                fetch_unselected=False,
            )
        mock_fetch.assert_not_called()
        self.assertEqual(len(summaries), 3)
        self.assertEqual(summaries[0].status, "ok")
        self.assertEqual(summaries[1].status, "ready")
        self.assertEqual(summaries[2].status, "unverified")


if __name__ == "__main__":
    unittest.main()
