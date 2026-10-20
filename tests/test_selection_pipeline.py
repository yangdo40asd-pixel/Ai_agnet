"""후보 탐색/선택 분석 분리, 선택 종목 검증, 세션 상태 전환 검사."""

import unittest
from dataclasses import replace
from unittest.mock import patch

import pandas as pd

from src.config import Settings
from src.data.stock import resolve_candidates, resolve_selected_target
from src.models import AppError, QueryOptions, StockCandidate
from src.pipeline import analyze_selected_stock, discover_theme_candidates
from src.ui.state import (
    build_request_key,
    reset_all_state,
    reset_selection_result,
    select_candidate,
    store_analysis_error,
    store_analysis_result,
    store_candidate_discovery,
    trigger_refresh,
    update_query_options,
)
from test_report_pipeline import example_financial, example_news


class SelectionTargetRulesTests(unittest.TestCase):
    def setUp(self):
        self.listing = pd.DataFrame([
            {"Name": "예시회사", "Code": "005930", "Market": "KOSPI"},
            {"Name": "회사나", "Code": "247540", "Market": "KOSDAQ"},
            {"Name": "코넥스사", "Code": "123456", "Market": "KONEX"},
        ])
        self.candidates = resolve_candidates(("예시회사", "회사나", "없는회사"), self.listing)

    def test_selects_first_or_second_verified_candidate_by_code(self):
        first = resolve_selected_target(self.candidates, "005930")
        second = resolve_selected_target(self.candidates, "247540")
        self.assertEqual(first.name, "예시회사")
        self.assertEqual(first.ticker, "005930.KS")
        self.assertEqual(second.name, "회사나")
        self.assertEqual(second.ticker, "247540.KQ")

    def test_empty_or_missing_selection_requires_choice(self):
        for blank in (None, "", "   ", 123):
            with self.subTest(blank=blank), self.assertRaises(AppError) as error:
                resolve_selected_target(self.candidates, blank)
            self.assertEqual(error.exception.code, "selection_required")

    def test_out_of_candidate_code_is_rejected_without_substitution(self):
        for invalid in ("999999", "000660", "전혀다른회사"):
            with self.subTest(invalid=invalid), self.assertRaises(AppError) as error:
                resolve_selected_target(self.candidates, invalid)
            self.assertEqual(error.exception.code, "selection_invalid")

    def test_unconfirmed_candidate_cannot_be_selected(self):
        with self.assertRaises(AppError) as error:
            resolve_selected_target(self.candidates, "없는회사")
        self.assertEqual(error.exception.code, "stock_unconfirmed")

    def test_unsupported_market_candidate_cannot_be_selected(self):
        candidates = resolve_candidates(("예시회사", "코넥스사", "회사나"), self.listing)
        self.assertTrue(candidates[1].verified)
        self.assertFalse(candidates[1].selectable)
        with self.assertRaises(AppError) as error:
            resolve_selected_target(candidates, "123456")
        self.assertEqual(error.exception.code, "market_unsupported")


class SeparatedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("test-key", "test-model", "test-id", "test-secret")
        self.listing = pd.DataFrame([
            {"Name": "예시회사", "Code": "005930", "Market": "KOSPI"},
            {"Name": "회사나", "Code": "247540", "Market": "KOSDAQ"},
            {"Name": "회사다", "Code": "000660", "Market": "KOSPI"},
        ])

    def test_discover_candidates_does_not_call_financial_news_or_report(self):
        with (
            patch("src.pipeline.propose_candidates", return_value=("예시회사", "회사나", "회사다")) as propose,
            patch("src.pipeline.load_listing", return_value=self.listing) as load,
            patch("src.pipeline.fetch_financial") as finance,
            patch("src.pipeline.fetch_news") as news,
            patch("src.pipeline.generate_commentary") as report,
        ):
            discovery = discover_theme_candidates("  반도체  ", settings=self.settings)

        self.assertEqual(discovery.theme, "반도체")
        self.assertEqual(len(discovery.candidates), 3)
        self.assertEqual(len(discovery.selectable_candidates), 3)
        self.assertEqual(discovery.failure_reason, "")
        propose.assert_called_once()
        load.assert_called_once()
        finance.assert_not_called()
        news.assert_not_called()
        report.assert_not_called()

    def test_analyze_selected_stock_uses_chosen_candidate_without_reproposing(self):
        candidates = resolve_candidates(("예시회사", "회사나", "회사다"), self.listing)
        second_financial = replace(example_financial(), stock=candidates[1])
        with (
            patch("src.pipeline.propose_candidates") as propose,
            patch("src.pipeline.load_listing") as load,
            patch("src.pipeline.fetch_financial", return_value=second_financial) as finance,
            patch("src.pipeline.fetch_news", return_value=example_news()) as news,
            patch("src.pipeline.generate_commentary", return_value=None) as report,
        ):
            result = analyze_selected_stock("반도체", candidates, "247540", settings=self.settings)

        propose.assert_not_called()
        load.assert_not_called()
        finance.assert_called_once_with(candidates[1])
        news.assert_called_once_with("반도체", "회사나", self.settings)
        report.assert_called_once()
        self.assertEqual(result.selected_code, "247540")
        self.assertEqual(result.financial.stock.name, "회사나")

    def test_analyze_selected_stock_rejects_mismatched_financial_stock_code(self):
        candidates = resolve_candidates(("예시회사", "회사나", "회사다"), self.listing)
        wrong_financial = example_financial()  # 005930 instead of 247540
        with (
            patch("src.pipeline.fetch_financial", return_value=wrong_financial),
            patch("src.pipeline.fetch_news") as news,
        ):
            with self.assertRaises(AppError) as error:
                analyze_selected_stock("반도체", candidates, "247540", settings=self.settings)
        self.assertEqual(error.exception.code, "finance_identity")
        news.assert_not_called()


class StateManagementTests(unittest.TestCase):
    def test_selection_switch_and_refresh_invalidate_previous_result_and_export(self):
        state = {"export_bytes": b"old-xlsx", "export_result_id": "old-id"}
        candidates = (
            StockCandidate("예시회사", "005930", "KOSPI", "005930.KS"),
            StockCandidate("회사나", "247540", "KOSDAQ", "247540.KQ"),
        )
        with (
            patch("src.pipeline.propose_candidates", return_value=("예시회사", "회사나", "회사다")),
            patch("src.pipeline.load_listing", return_value=pd.DataFrame([
                {"Name": "예시회사", "Code": "005930", "Market": "KOSPI"},
                {"Name": "회사나", "Code": "247540", "Market": "KOSDAQ"},
                {"Name": "회사다", "Code": "000660", "Market": "KOSPI"},
            ])),
        ):
            discovery = discover_theme_candidates(
                "반도체",
                settings=Settings("k", "m", "i", "s"),
            )

        store_candidate_discovery(state, discovery)
        self.assertIsNone(state["selected_code"])
        self.assertNotIn("export_bytes", state)

        select_candidate(state, "005930")
        key_a = build_request_key("반도체", "005930", state["query_options"])
        fake_result = replace(
            analyze_selected_stock(
                "반도체",
                candidates,
                "005930",
                settings=Settings("k", "m", "i", "s"),
            )
            if False
            else None
        ) if False else None
        state["dashboard_result"] = "result_a"
        state["latest_result"] = "result_a"
        state["export_bytes"] = b"xlsx-a"
        state["export_result_id"] = "id-a"
        state["active_request_key"] = key_a

        # Switching to 247540 invalidates result_a and xlsx-a immediately
        select_candidate(state, "247540")
        self.assertEqual(state["selected_code"], "247540")
        self.assertNotIn("dashboard_result", state)
        self.assertNotIn("latest_result", state)
        self.assertNotIn("export_bytes", state)
        self.assertNotIn("active_request_key", state)

        # Storing an error on B ensures no stale result remains
        store_analysis_error(state, "조회 실패", request_key="key_b")
        self.assertEqual(state["latest_error"], "조회 실패")
        self.assertNotIn("dashboard_result", state)

        # Refresh increments generation and clears active_request_key
        updated_opts = trigger_refresh(state)
        self.assertEqual(updated_opts.refresh_generation, 1)
        self.assertNotIn("active_request_key", state)

        # Updating query options invalidates result
        state["dashboard_result"] = "result_b"
        update_query_options(state, price_period="1Y")
        self.assertEqual(state["query_options"].price_period, "1Y")
        self.assertNotIn("dashboard_result", state)

        reset_all_state(state)
        self.assertNotIn("candidate_result", state)
        self.assertNotIn("selected_code", state)


if __name__ == "__main__":
    unittest.main()
