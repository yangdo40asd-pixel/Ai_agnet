"""재무제표 사실(FinancialFact) 기반 AI 설명 생성·검증·부호/범위 정합성 테스트."""

import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.agents.report import (
    build_financial_ai_payload,
    generate_financial_commentary,
    response_format,
    validate_financial_commentary,
)
from src.config import Settings
from src.models import AppError, FinancialData, FinancialFact, StockCandidate

KST = ZoneInfo("Asia/Seoul")


class FinancialCommentaryTests(unittest.TestCase):
    def setUp(self):
        self.retrieved_at = datetime(2026, 10, 20, 10, 0, tzinfo=KST)
        self.stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
        self.financial = FinancialData(
            stock=self.stock,
            price=70000.0,
            per=15.2,
            retrieved_at=self.retrieved_at,
        )
        self.facts = (
            FinancialFact(
                fact_id="FIN_2024_REVENUE",
                stock_code="005930",
                stock_name="삼성전자",
                item="매출액",
                value=Decimal("300870903000000"),
                display_value="3,008,709.0억원",
                unit="억원",
                period="2024년 연간",
                fs_div="CFS",
                source="OpenDART",
                polarity="positive",
            ),
            FinancialFact(
                fact_id="FIN_2025_REVENUE",
                stock_code="005930",
                stock_name="삼성전자",
                item="매출액",
                value=Decimal("333605938000000"),
                display_value="3,336,059.4억원",
                unit="억원",
                period="2025년 연간",
                fs_div="CFS",
                source="OpenDART",
                polarity="positive",
            ),
            FinancialFact(
                fact_id="FIN_2025_OPERATING_INCOME",
                stock_code="005930",
                stock_name="삼성전자",
                item="영업이익",
                value=Decimal("43601051000000"),
                display_value="436,010.5억원",
                unit="억원",
                period="2025년 연간",
                fs_div="CFS",
                source="OpenDART",
                polarity="positive",
            ),
            FinancialFact(
                fact_id="RATIO_2025_ROE",
                stock_code="005930",
                stock_name="삼성전자",
                item="ROE",
                value=10.783,
                display_value="10.78%",
                unit="%",
                period="2025년 사업보고서",
                fs_div="CFS",
                source="OpenDART 주요재무지표",
                polarity="positive",
            ),
        )

    def test_build_financial_ai_payload_includes_fact_metadata_and_rejects_other_stock(self):
        payload = build_financial_ai_payload("반도체", self.financial, self.facts)
        self.assertEqual(payload["stock_name"], "삼성전자")
        self.assertEqual(payload["stock_code"], "005930")
        self.assertEqual(payload["financial_status"], "ok")
        self.assertEqual(len(payload["financial_facts"]), 4)
        self.assertEqual(payload["financial_facts"][0]["fact_id"], "FIN_2024_REVENUE")

        schema_fmt = response_format(payload, "openai/gpt-oss-20b")
        self.assertEqual(schema_fmt["type"], "json_schema")

        wrong_fact = FinancialFact(
            fact_id="FIN_2025_REVENUE",
            stock_code="000660",
            stock_name="SK하이닉스",
            item="매출액",
            value=Decimal("97146675000000"),
            display_value="971,466.8억원",
            unit="억원",
            period="2025년 연간",
            fs_div="CFS",
            source="OpenDART",
            polarity="positive",
        )
        with self.assertRaises(AppError) as ctx:
            build_financial_ai_payload("반도체", self.financial, (wrong_fact,))
        self.assertEqual(ctx.exception.code, "report_identity")

    def test_validate_financial_commentary_accepts_valid_fact_citations(self):
        payload = {
            "stock_name": "삼성전자",
            "stock_code": "005930",
            "financial_commentary": [
                {
                    "text": "연결재무제표 기준 최근 사업연도 매출액이 직전 사업연도 대비 증가했으며 영업이익도 흑자를 기록했습니다.",
                    "fact_ids": [
                        "FIN_2024_REVENUE",
                        "FIN_2025_REVENUE",
                        "FIN_2025_OPERATING_INCOME",
                    ],
                },
                {
                    "text": "수익성 지표인 자기자본이익률도 양수 수준을 유지하고 있습니다.",
                    "fact_ids": ["RATIO_2025_ROE"],
                },
            ],
        }
        stmts = validate_financial_commentary(payload, self.financial, self.facts, "반도체")
        self.assertEqual(len(stmts), 2)
        self.assertEqual(
            stmts[0].fact_ids,
            ("FIN_2024_REVENUE", "FIN_2025_REVENUE", "FIN_2025_OPERATING_INCOME"),
        )
        self.assertEqual(stmts[0].news_ids, ())

    def test_validate_financial_commentary_rejects_unknown_fact_id_or_empty_facts(self):
        bad_id_payload = {
            "stock_name": "삼성전자",
            "stock_code": "005930",
            "financial_commentary": [
                {
                    "text": "연결재무제표 기준 매출액이 증가했습니다.",
                    "fact_ids": ["FIN_2026_REVENUE"],
                }
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_financial_commentary(bad_id_payload, self.financial, self.facts, "반도체")
        self.assertEqual(ctx.exception.code, "report_evidence")

        with self.assertRaises(AppError) as empty_ctx:
            validate_financial_commentary(bad_id_payload, self.financial, (), "반도체")
        self.assertEqual(empty_ctx.exception.code, "report_evidence")

    def test_validate_financial_commentary_rejects_polarity_and_scope_mismatches(self):
        loss_fact = FinancialFact(
            fact_id="FIN_2023_OPERATING_INCOME",
            stock_code="005930",
            stock_name="삼성전자",
            item="영업이익",
            value=Decimal("-7730313000000"),
            display_value="-77,303.1억원",
            unit="억원",
            period="2023년 연간",
            fs_div="CFS",
            source="OpenDART",
            polarity="negative",
        )
        # 적자 지표를 흑자로 설명하면 거부
        with self.assertRaises(AppError) as loss_ctx:
            validate_financial_commentary(
                {
                    "stock_name": "삼성전자",
                    "stock_code": "005930",
                    "financial_commentary": [
                        {
                            "text": "해당 사업연도 영업이익은 흑자를 기록하며 수익성이 양호했습니다.",
                            "fact_ids": ["FIN_2023_OPERATING_INCOME"],
                        }
                    ],
                },
                self.financial,
                (loss_fact,),
                "반도체",
            )
        self.assertEqual(loss_ctx.exception.code, "report_polarity")

        # 연결(CFS) 자료를 별도재무제표로 설명하면 거부
        with self.assertRaises(AppError) as scope_ctx:
            validate_financial_commentary(
                {
                    "stock_name": "삼성전자",
                    "stock_code": "005930",
                    "financial_commentary": [
                        {
                            "text": "별도재무제표 기준 최근 사업연도 영업이익이 양수를 기록했습니다.",
                            "fact_ids": ["FIN_2025_OPERATING_INCOME"],
                        }
                    ],
                },
                self.financial,
                self.facts,
                "반도체",
            )
        self.assertEqual(scope_ctx.exception.code, "report_scope")

        # 증가한 동일 계정(매출액)을 감소로 설명하면 거부
        with self.assertRaises(AppError) as trend_ctx:
            validate_financial_commentary(
                {
                    "stock_name": "삼성전자",
                    "stock_code": "005930",
                    "financial_commentary": [
                        {
                            "text": "최근 사업연도 매출액은 직전 사업연도 대비 감소했습니다.",
                            "fact_ids": ["FIN_2024_REVENUE", "FIN_2025_REVENUE"],
                        }
                    ],
                },
                self.financial,
                self.facts,
                "반도체",
            )
        self.assertEqual(trend_ctx.exception.code, "report_polarity")

        # 자본잠식(음수 자본)을 안정적인 자본으로 설명하면 거부
        impaired_equity = FinancialFact(
            fact_id="FIN_2025_TOTAL_EQUITY",
            stock_code="005930",
            stock_name="삼성전자",
            item="자본총계",
            value=Decimal("-5000000000"),
            display_value="-50.0억원",
            unit="억원",
            period="2025년 연간",
            fs_div="CFS",
            source="OpenDART",
            polarity="negative",
        )
        with self.assertRaises(AppError) as eq_ctx:
            validate_financial_commentary(
                {
                    "stock_name": "삼성전자",
                    "stock_code": "005930",
                    "financial_commentary": [
                        {
                            "text": "최근 사업연도 기준 안정적인 자본으로 재무건전성이 양호합니다.",
                            "fact_ids": ["FIN_2025_TOTAL_EQUITY"],
                        }
                    ],
                },
                self.financial,
                (impaired_equity,),
                "반도체",
            )
        self.assertEqual(eq_ctx.exception.code, "report_polarity")

    def test_generate_financial_commentary_skips_when_empty_and_retries_once_on_number(self):
        settings = Settings("test-key", "openai/gpt-oss-20b", "id", "secret")
        self.assertEqual(
            generate_financial_commentary("반도체", self.financial, (), settings),
            (),
        )

        bad_first = {
            "stock_name": "삼성전자",
            "stock_code": "005930",
            "financial_commentary": [
                {
                    "text": "2025년 매출액이 증가했습니다.",
                    "fact_ids": ["FIN_2025_REVENUE"],
                }
            ],
        }
        good_second = {
            "stock_name": "삼성전자",
            "stock_code": "005930",
            "financial_commentary": [
                {
                    "text": "연결재무제표 기준 최근 사업연도 매출액과 영업이익이 양호한 흑자 흐름을 보였습니다.",
                    "fact_ids": ["FIN_2025_REVENUE", "FIN_2025_OPERATING_INCOME"],
                }
            ],
        }
        with patch("src.agents.report._invoke", side_effect=[bad_first, good_second]) as mock_invoke:
            stmts = generate_financial_commentary("반도체", self.financial, self.facts, settings)
        self.assertEqual(mock_invoke.call_count, 2)
        self.assertEqual(len(stmts), 1)
        self.assertEqual(stmts[0].fact_ids, ("FIN_2025_REVENUE", "FIN_2025_OPERATING_INCOME"))


if __name__ == "__main__":
    unittest.main()
