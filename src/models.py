"""데이터 수집, AI, 화면이 함께 사용하는 자료 형식."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


class AppError(Exception):
    """외부 응답이나 비밀값을 포함하지 않는 사용자 안내 오류."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StockCandidate:
    name: str
    code: str | None = None
    market: str | None = None
    ticker: str | None = None
    reason: str = ""

    @property
    def verified(self) -> bool:
        return self.code is not None


@dataclass(frozen=True)
class FinancialData:
    stock: StockCandidate
    price: float | None
    per: float | None
    retrieved_at: datetime
    price_at: datetime | None = None
    source: str = "Yahoo Finance (yfinance)"
    warnings: tuple[str, ...] = ()
    per_eps: float | None = None
    per_period_end: str | None = None


@dataclass(frozen=True)
class NewsArticle:
    id: int
    title: str
    url: str | None
    published_at: str | None
    publisher_domain: str | None


@dataclass(frozen=True)
class NewsData:
    articles: tuple[NewsArticle, ...]
    retrieved_at: datetime
    status: str = "ok"
    message: str = ""
    source: str = "NAVER 뉴스 검색 API"
    sort: str = "date"


@dataclass(frozen=True)
class Statement:
    text: str
    news_ids: tuple[int, ...]


@dataclass(frozen=True)
class Commentary:
    theme_trend: tuple[Statement, ...]
    stock_comment: str
    opportunity: Statement | None
    risk: Statement | None
    summary: Statement | None


@dataclass(frozen=True)
class AnalysisResult:
    theme: str
    candidates: tuple[StockCandidate, ...]
    financial: FinancialData
    news: NewsData
    commentary: Commentary | None
    ai_error: str | None = None

    @property
    def complete(self) -> bool:
        return (
            self.commentary is not None
            and not self.financial.warnings
            and self.news.status == "ok"
            and all(candidate.verified and not candidate.reason for candidate in self.candidates)
        )
