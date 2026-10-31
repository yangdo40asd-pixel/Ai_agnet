"""실행 08 선택적 캔버스 및 결과 일치 통합 테스트 (U03, U04)."""
import unittest
from unittest.mock import patch
from dataclasses import replace
import pandas as pd

from src.models import (
    StockCandidate, AnalysisResult, CandidateDiscoveryResult, now_kst
)
from src.ui.state import (
    add_canvas, canvas_result_id, ensure_export_bundle, get_result
)
from src.ui.app import _handle_explicit_canvas_or_export_request
from src.agents.discovery_context import collective_comparison
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals


class Stage08CanvasConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.stock_a = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
        self.stock_b = StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS")
        base = sample_result()
        self.res_a = replace(
            base,
            result_id="res-samsung-001",
            selected_code="005930",
            candidates=(self.stock_a, self.stock_b),
            financial=replace(base.financial, stock=self.stock_a, price=70000, per=15.2),
            annual_summaries=annuals(),
        )
        self.res_b = replace(
            base,
            result_id="res-hynix-002",
            selected_code="000660",
            candidates=(self.stock_a, self.stock_b),
            financial=replace(base.financial, stock=self.stock_b, price=180000, per=12.0),
            annual_summaries=annuals(),
        )

    def test_u03_i1_general_question_does_not_open_canvas(self):
        state = {"canvases": []}
        _handle_explicit_canvas_or_export_request(state, "삼성전자 실적 어때?", self.res_a)
        self.assertEqual(len(state["canvases"]), 0)
        _handle_explicit_canvas_or_export_request(state, "캔버스 없어?", self.res_a)
        self.assertEqual(len(state["canvases"]), 0)

    def test_u03_i2_explicit_chart_request_opens_canvas_for_target_stock(self):
        state = {"canvases": []}
        _handle_explicit_canvas_or_export_request(state, "차트 보여줘", self.res_a)
        self.assertEqual(len(state["canvases"]), 1)
        self.assertEqual(state["canvases"][0]["stock_name"], "삼성전자")
        self.assertEqual(state["active_canvas_id"], "c1")

    def test_u03_i2_explicit_close_request_closes_active_canvas(self):
        state = {"canvases": []}
        _handle_explicit_canvas_or_export_request(state, "차트 열어줘", self.res_a)
        self.assertEqual(len(state["canvases"]), 1)
        _handle_explicit_canvas_or_export_request(state, "캔버스 닫아줘", self.res_a)
        self.assertEqual(len(state["canvases"]), 0)

    def test_u03_i2_collective_comparison_phrasings(self):
        discovery = CandidateDiscoveryResult("반도체", (self.stock_a, self.stock_b), now_kst())
        stocks_table = collective_comparison("표로 비교해줘", discovery, [])
        self.assertIsNotNone(stocks_table)
        self.assertEqual(len(stocks_table), 2)
        stocks_comp = collective_comparison("비교표 보여줘", discovery, [])
        self.assertIsNotNone(stocks_comp)
        self.assertEqual(len(stocks_comp), 2)

    def test_u03_i2_u04_i4_excel_export_prepares_bundle(self):
        state = {"canvases": []}
        _handle_explicit_canvas_or_export_request(state, "Excel로 내보내줘", self.res_a)
        self.assertEqual(len(state["canvases"]), 1)
        card = state["canvases"][0]
        self.assertTrue(isinstance(card.get("export_bytes"), bytes))
        self.assertTrue(card["export_bytes"].startswith(b"PK"))
        self.assertIn("005930", card["export_filename"])

    def test_u04_i2_switching_stock_preserves_previous_canvas(self):
        state = {"canvases": []}
        add_canvas(state, self.res_a)
        self.assertEqual(len(state["canvases"]), 1)
        self.assertEqual(state["canvases"][0]["stock_name"], "삼성전자")

        add_canvas(state, self.res_b)
        self.assertEqual(len(state["canvases"]), 2)
        self.assertEqual(state["canvases"][0]["stock_name"], "SK하이닉스")
        self.assertEqual(state["canvases"][1]["stock_name"], "삼성전자")

    def test_u04_i3_result_id_is_strictly_aligned(self):
        state = {"canvases": []}
        add_canvas(state, self.res_a)
        card = state["canvases"][0]
        self.assertEqual(card["result_id"], self.res_a.result_id)
        self.assertEqual(canvas_result_id(self.res_a), self.res_a.result_id)


if __name__ == "__main__":
    unittest.main()
