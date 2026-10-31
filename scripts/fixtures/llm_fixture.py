"""가상 LLM 검수 자료. 2026-10-26 기존 Groq 비교 표본과 같은 수치를 사용한다."""
from datetime import datetime
from src.models import (AnalysisResult, StockCandidate, FinancialData, NewsData, NewsArticle,
                        AnnualFinancialSummary, KST, now_kst)


def synthetic_result():
    stock = StockCandidate("가상검수회사", "123456", "KOSPI", "123456.KS")
    now = now_kst()
    finance = FinancialData(stock, 10000, 12.5, now,
                            price_at=datetime(2026, 10, 20, 15, 30, tzinfo=KST))
    news = NewsData((
        NewsArticle(1, "가상검수회사 반도체 메모리 생산라인 가동 계획 발표", "https://example.com/memory", "2026-10-19T09:00:00+09:00", "example.com"),
        NewsArticle(2, "가상그룹 지주회사 이사회 경영 강화", "https://example.org/governance", "2026-10-20T09:00:00+09:00", "example.org"),
    ), now)
    return AnalysisResult("반도체", (stock,), finance, news, None, result_id="synthetic-local-evaluation",
                          annual_summaries=(AnnualFinancialSummary("2024", revenue=10_000_000_000, operating_income=1_000_000_000),
                                            AnnualFinancialSummary("2025", revenue=12_000_000_000, operating_income=1_800_000_000)))
