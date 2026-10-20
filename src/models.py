"""데이터 수집, AI, 화면이 함께 사용하는 자료 형식."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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

    @property
    def selectable(self) -> bool:
        return bool(self.code is not None and not self.reason and self.ticker)


@dataclass(frozen=True)
class CandidateDiscoveryResult:
    theme: str
    candidates: tuple[StockCandidate, ...]
    retrieved_at: datetime
    failure_reason: str = ""

    @property
    def selectable_candidates(self) -> tuple[StockCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.selectable)


@dataclass(frozen=True)
class QueryOptions:
    price_period: str = "3M"
    bsns_year: str | None = None
    reprt_code: str = "11011"
    fs_div: str = "CFS"
    refresh_generation: int = 0
    price_range: str = ""

    def __post_init__(self):
        if self.price_range and self.price_period == "3M":
            object.__setattr__(self, "price_period", self.price_range)
        object.__setattr__(self, "price_range", self.price_period)


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float | None
    unit: str
    currency: str | None = "KRW"
    source: str = "Yahoo Finance (yfinance)"
    raw_field: str = ""
    period: str = ""
    period_end: str | None = None
    as_of: datetime | None = None
    retrieved_at: datetime = field(default_factory=now_kst)
    status: str = "ok"
    basis: str = "provided"
    is_calculated: bool = False
    formula: str = ""
    reason: str = ""
    note: str = ""
    message: str = ""

    def __post_init__(self):
        if not self.period and self.period_end:
            object.__setattr__(self, "period", self.period_end)
        elif self.period and not self.period_end:
            object.__setattr__(self, "period_end", self.period)
        if self.is_calculated and self.basis == "provided":
            object.__setattr__(self, "basis", "calculated")
        elif self.basis == "calculated" and not self.is_calculated:
            object.__setattr__(self, "is_calculated", True)
        msg = self.reason or self.note or self.message
        if msg:
            object.__setattr__(self, "reason", msg)
            object.__setattr__(self, "note", msg)
            object.__setattr__(self, "message", msg)


@dataclass(frozen=True)
class PriceBar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class PriceHistory:
    code: str
    ticker: str
    bars: tuple[PriceBar, ...]
    currency: str = "KRW"
    timezone: str = "Asia/Seoul"
    timezone_name: str = "Asia/Seoul"
    adjusted: bool = False
    range_key: str = "3M"
    period: str = "3M"
    source: str = "Yahoo Finance (yfinance)"
    retrieved_at: datetime = field(default_factory=now_kst)
    status: str = "ok"
    message: str = ""

    def __post_init__(self):
        if self.timezone_name != "Asia/Seoul" and self.timezone == "Asia/Seoul":
            object.__setattr__(self, "timezone", self.timezone_name)
        else:
            object.__setattr__(self, "timezone_name", self.timezone)
        if self.period != "3M" and self.range_key == "3M":
            object.__setattr__(self, "range_key", self.period)
        else:
            object.__setattr__(self, "period", self.range_key)


@dataclass(frozen=True)
class FinancialAccountRow:
    sj_div: str
    account_id: str
    account_nm: str
    standard_key: str
    amount: int | Decimal | None
    cumulative_amount: int | Decimal | None = None
    currency: str = "KRW"
    bsns_year: str = ""
    reprt_code: str = "11011"
    fs_div: str = "CFS"
    period_type: str = "annual"
    period_label: str = ""
    rcept_no: str = ""
    source: str = "OpenDART"


@dataclass(frozen=True)
class FinancialStatementData:
    code: str
    corp_code: str | None
    bsns_year: str
    reprt_code: str
    fs_div: str
    rows: tuple[FinancialAccountRow, ...] = ()
    annual_history: tuple["AnnualFinancialSummary", ...] = ()
    quarterly_history: tuple["QuarterlyFinancialSummary", ...] = ()
    rcept_no: str = ""
    source: str = "OpenDART"
    retrieved_at: datetime = field(default_factory=now_kst)
    status: str = "empty"
    message: str = ""
    is_separate_fallback: bool = False


@dataclass(frozen=True)
class AnnualFinancialSummary:
    bsns_year: str
    reprt_code: str = "11011"
    fs_div: str = "CFS"
    revenue: int | Decimal | None = None
    operating_income: int | Decimal | None = None
    net_income: int | Decimal | None = None
    parent_net_income: int | Decimal | None = None
    total_assets: int | Decimal | None = None
    total_liabilities: int | Decimal | None = None
    total_equity: int | Decimal | None = None
    parent_equity: int | Decimal | None = None
    operating_cash_flow: int | Decimal | None = None
    investing_cash_flow: int | Decimal | None = None
    financing_cash_flow: int | Decimal | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    debt_ratio: float | None = None
    roe: float | None = None
    rcept_no: str = ""
    currency: str = "KRW"
    is_separate_fallback: bool = False
    assets: int | Decimal | None = None
    liabilities: int | Decimal | None = None
    equity: int | Decimal | None = None
    operating_cf: int | Decimal | None = None
    investing_cf: int | Decimal | None = None
    financing_cf: int | Decimal | None = None

    def __post_init__(self):
        if self.total_assets is None and self.assets is not None:
            object.__setattr__(self, "total_assets", self.assets)
        elif self.assets is None and self.total_assets is not None:
            object.__setattr__(self, "assets", self.total_assets)
        if self.total_liabilities is None and self.liabilities is not None:
            object.__setattr__(self, "total_liabilities", self.liabilities)
        elif self.liabilities is None and self.total_liabilities is not None:
            object.__setattr__(self, "liabilities", self.total_liabilities)
        if self.total_equity is None and self.equity is not None:
            object.__setattr__(self, "total_equity", self.equity)
        elif self.equity is None and self.total_equity is not None:
            object.__setattr__(self, "equity", self.total_equity)
        if self.operating_cash_flow is None and self.operating_cf is not None:
            object.__setattr__(self, "operating_cash_flow", self.operating_cf)
        elif self.operating_cf is None and self.operating_cash_flow is not None:
            object.__setattr__(self, "operating_cf", self.operating_cash_flow)
        if self.investing_cash_flow is None and self.investing_cf is not None:
            object.__setattr__(self, "investing_cash_flow", self.investing_cf)
        elif self.investing_cf is None and self.investing_cash_flow is not None:
            object.__setattr__(self, "investing_cf", self.investing_cash_flow)
        if self.financing_cash_flow is None and self.financing_cf is not None:
            object.__setattr__(self, "financing_cash_flow", self.financing_cf)
        elif self.financing_cf is None and self.financing_cash_flow is not None:
            object.__setattr__(self, "financing_cf", self.financing_cash_flow)


@dataclass(frozen=True)
class QuarterlyFinancialSummary:
    bsns_year: str
    reprt_code: str = "11013"
    fs_div: str = "CFS"
    period_label: str = ""
    quarter_label: str = ""
    period_type: str = "quarter_3m"
    revenue: int | Decimal | None = None
    operating_income: int | Decimal | None = None
    net_income: int | Decimal | None = None
    is_standalone_quarter: bool = True
    derivation_note: str = ""
    rcept_no: str = ""
    currency: str = "KRW"

    def __post_init__(self):
        if not self.period_label and self.quarter_label:
            object.__setattr__(self, "period_label", self.quarter_label)
        elif self.period_label and not self.quarter_label:
            object.__setattr__(self, "quarter_label", self.period_label)


@dataclass(frozen=True)
class FinancialRatios:
    roe: MetricValue | None = None
    operating_margin: MetricValue | None = None
    net_margin: MetricValue | None = None
    debt_ratio: MetricValue | None = None
    bsns_year: str = ""
    reprt_code: str = "11011"
    fs_div: str = "CFS"
    interpretation_notes: tuple[str, ...] = ()
    status: str = "empty"
    message: str = ""


@dataclass(frozen=True)
class FinancialFact:
    fact_id: str
    stock_code: str
    stock_name: str
    item: str
    value: float | int | Decimal
    display_value: str
    unit: str
    period: str
    fs_div: str
    source: str
    polarity: str = "neutral"


@dataclass(frozen=True)
class RelatedStockSummary:
    stock: StockCandidate | None = None
    candidate: StockCandidate | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    comparison_basis: str = ""
    price_basis: str = ""
    sparkline_dates: tuple[str, ...] = ()
    sparkline_closes: tuple[float, ...] = ()
    period_label: str = "최근 1개월"
    currency: str = "KRW"
    source: str = "Yahoo Finance (yfinance)"
    retrieved_at: datetime = field(default_factory=now_kst)
    status: str = "empty"
    message: str = ""

    def __post_init__(self):
        if self.stock is None and self.candidate is not None:
            object.__setattr__(self, "stock", self.candidate)
        elif self.candidate is None and self.stock is not None:
            object.__setattr__(self, "candidate", self.stock)
        if not self.comparison_basis and self.price_basis:
            object.__setattr__(self, "comparison_basis", self.price_basis)
        elif self.comparison_basis and not self.price_basis:
            object.__setattr__(self, "price_basis", self.comparison_basis)


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
    pbr_metric: MetricValue | None = None
    eps_metric: MetricValue | None = None
    bps_metric: MetricValue | None = None
    roe_metric: MetricValue | None = None
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    @property
    def eps(self) -> float | None:
        return self.eps_metric.value if self.eps_metric is not None else None

    @property
    def bps(self) -> float | None:
        return self.bps_metric.value if self.bps_metric is not None else None

    @property
    def pbr(self) -> float | None:
        return self.pbr_metric.value if self.pbr_metric is not None else None


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
    fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Commentary:
    theme_trend: tuple[Statement, ...]
    stock_comment: str
    opportunity: Statement | None
    risk: Statement | None
    summary: Statement | None
    financial_commentary: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class AnalysisResult:
    theme: str
    candidates: tuple[StockCandidate, ...]
    financial: FinancialData
    news: NewsData
    commentary: Commentary | None
    ai_error: str | None = None
    selected_code: str | None = None
    query_options: QueryOptions = field(default_factory=QueryOptions)
    price_history: PriceHistory | None = None
    financial_statements: tuple[FinancialStatementData, ...] = ()
    statements: FinancialStatementData | None = None
    annual_summaries: tuple[AnnualFinancialSummary, ...] = ()
    quarterly_summaries: tuple[QuarterlyFinancialSummary, ...] = ()
    financial_ratios: FinancialRatios | None = None
    ratios: FinancialRatios | None = None
    financial_facts: tuple[FinancialFact, ...] = ()
    related_stocks: tuple[RelatedStockSummary, ...] = ()
    related_summaries: tuple[RelatedStockSummary, ...] = ()
    section_status: dict[str, str] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    result_id: str = ""

    def __post_init__(self):
        if self.financial_ratios is None and self.ratios is not None:
            object.__setattr__(self, "financial_ratios", self.ratios)
        elif self.ratios is None and self.financial_ratios is not None:
            object.__setattr__(self, "ratios", self.financial_ratios)
        if not self.related_stocks and self.related_summaries:
            object.__setattr__(self, "related_stocks", self.related_summaries)
        elif self.related_stocks and not self.related_summaries:
            object.__setattr__(self, "related_summaries", self.related_stocks)
        if not self.financial_statements and self.statements is not None:
            object.__setattr__(self, "financial_statements", (self.statements,))
        elif self.financial_statements and self.statements is None:
            object.__setattr__(self, "statements", self.financial_statements[0])

    @property
    def commentary_error(self) -> str | None:
        return self.ai_error

    @property
    def target_code(self) -> str | None:
        return self.selected_code or self.financial.stock.code

    @property
    def complete(self) -> bool:
        return (
            self.commentary is not None
            and not self.financial.warnings
            and self.news.status == "ok"
            and self.financial.stock.selectable
            and all(candidate.verified and not candidate.reason for candidate in self.candidates)
        )


DashboardResult = AnalysisResult
