"""데이터 수집, AI, 화면이 함께 사용하는 자료 형식."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

_UNSET = object()

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
    association_reason: str = ""
    association_source: str = ""
    association_status: str = "not_collected"

    @property
    def verified(self) -> bool:
        return self.code is not None

    @property
    def selectable(self) -> bool:
        return bool(self.code is not None and not self.reason and self.ticker)


@dataclass(frozen=True)
class CompanyBusinessProfile:
    """공식 목록의 회사 식별·업종·제품 원문. 수집 시각은 자료 갱신일이 아니다."""
    stock_name: str
    stock_code: str
    industry: str
    products: str
    retrieved_at: datetime
    source_url: str
    website_url: str = ""


@dataclass(frozen=True)
class CompanyBusinessSource:
    """한 회사·한 문서·한 절의 사업 근거. 조회일과 보고기간은 구별한다."""
    stock_name: str
    stock_code: str
    document_id: str
    document_title: str
    section_title: str
    text: str
    source_url: str
    retrieved_at: datetime
    content_hash: str
    parser_revision: str
    published_at: str | None = None
    reporting_period: str | None = None
    source: str = "OpenDART 정기보고서 사업 원문"
    corp_code: str = ""


@dataclass(frozen=True)
class BusinessSourceBatch:
    """부분 성공을 보존한다. 상태에 인증키/외부 응답 원문을 넣지 않는다."""
    sources: tuple[CompanyBusinessSource, ...] = ()
    statuses: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CandidateDiscoveryResult:
    theme: str
    candidates: tuple[StockCandidate, ...]
    retrieved_at: datetime
    failure_reason: str = ""
    batch_codes: tuple[str, ...] = ()
    business_profiles: tuple[CompanyBusinessProfile, ...] = ()
    business_error: str = ""
    business_sources: tuple[CompanyBusinessSource, ...] = ()
    business_source_statuses: tuple[tuple[str, str], ...] = ()

    @property
    def selectable_candidates(self) -> tuple[StockCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.selectable)

    @property
    def latest_candidates(self) -> tuple[StockCandidate, ...]:
        if not self.batch_codes:
            return self.candidates
        return tuple(stock for stock in self.candidates if stock.code in self.batch_codes)


@dataclass(frozen=True, init=False)
class QueryOptions:
    price_period: str = "3M"
    bsns_year: str | None = None
    reprt_code: str = "11011"
    fs_div: str = "CFS"
    refresh_generation: int = 0

    def __init__(
        self,
        price_period: str = _UNSET,
        bsns_year: str | None = None,
        reprt_code: str = '11011',
        fs_div: str = 'CFS',
        refresh_generation: int = 0,
        price_range: str = '',
    ):
        """별칭 인수는 생성 시 변환하고 정식 필드만 저장한다."""
        object.__setattr__(self, "price_period", (price_range or "3M") if price_period is _UNSET else price_period)
        object.__setattr__(self, "bsns_year", bsns_year)
        object.__setattr__(self, "reprt_code", reprt_code)
        object.__setattr__(self, "fs_div", fs_div)
        object.__setattr__(self, "refresh_generation", refresh_generation)

    @property
    def price_range(self):
        return self.price_period


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
    collection_status: str = "collected"

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
    description: str = ""


@dataclass(frozen=True)
class NewsAssessment:
    article_id: int
    relation: str
    subject_quote: str
    support_quote: str
    accepted: bool
    reason: str


@dataclass(frozen=True)
class NewsAdmission:
    target_code: str
    target_name: str
    theme: str
    context_id: str
    fingerprint: str
    policy_version: str
    model_key: str
    assessments: tuple[NewsAssessment, ...]


@dataclass(frozen=True)
class CompanyRelation:
    fact_id: str
    target_code: str
    target_name: str
    subject_name: str
    relation: str
    quote: str
    source_id: str
    source_hash: str
    span: tuple[int, int]
    source_url: str
    source: str = 'OpenDART 공시 원문'
    published_at: str | None = None
    retrieved_at: str = ''
    validity: str = 'document_only'


@dataclass(frozen=True)
class NewsData:
    articles: tuple[NewsArticle, ...]
    retrieved_at: datetime
    status: str = "ok"
    message: str = ""
    source: str = "NAVER 뉴스 검색 API"
    sort: str = "date"
    admission: NewsAdmission | None = None
    queries: tuple[str, ...] = ()
    collection_note: str = ""
    relationships: tuple[CompanyRelation, ...] = ()


@dataclass(frozen=True)
class SourceDocument:
    evidence_id: str
    stock_code: str
    stock_name: str
    title: str
    text: str
    source: str
    url: str
    retrieved_at: datetime
    scope: str = "official_disclosure"
    published_at: str | None = None
    document_id: str = ""


@dataclass(frozen=True)
class StructuredFact:
    fact_id: str
    evidence_id: str
    item: str
    target: str
    value: Decimal
    unit: str
    direction: str
    scope: str
    raw_text: str
    span: tuple[int, int]
    source_hash: str
    article_published_at: str | None = None
    event_occurred_at: str | None = None
    financial_period: str | None = None
    status: str = "candidate"
    reason: str = ""
    qualifier: str = ""
    validity: str = "current"
    ownership_basis: str = "unknown"
    input_fact_ids: tuple[str, ...] = ()
    formula: str = ""


@dataclass(frozen=True)
class Statement:
    text: str
    news_ids: tuple[int, ...]
    fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, init=False)
class AnswerBlock:
    """검증된 설명 하나와 그 설명에만 연결되는 근거 ID."""
    title: str
    text: str
    evidence_ids: tuple[str, ...] = ()
    implication: str | None = None

    def __init__(self, title=_UNSET, text=_UNSET, evidence_ids=(), implication=None, *,
                 headline=_UNSET, summary=_UNSET):
        for legacy, alias, name in ((title,headline,'title/headline'),(text,summary,'text/summary')):
            if legacy is _UNSET and alias is _UNSET:
                raise TypeError('필수 필드 누락: '+name)
            if legacy is not _UNSET and alias is not _UNSET and legacy!=alias:
                raise TypeError('상충하는 필드: '+name)
        object.__setattr__(self,'title',headline if title is _UNSET else title)
        object.__setattr__(self,'text',summary if text is _UNSET else text)
        object.__setattr__(self,'evidence_ids',tuple(evidence_ids))
        object.__setattr__(self,'implication',implication or None)

    @property
    def headline(self):
        return self.title

    @property
    def summary(self):
        return self.text


@dataclass(frozen=True)
class CompanyCardSection:
    role: str
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyCard:
    stock_code: str
    stock_name: str
    sections: tuple[CompanyCardSection, ...] = ()
    card_id: str = ""


@dataclass(frozen=True)
class ChatResponse:
    """화면은 블록을 사용하고 기존 호출자는 세 값으로 풀어 읽을 수 있다."""
    intro: str
    evidence: list[dict]
    follow_up: str = ""
    blocks: tuple[AnswerBlock, ...] = ()
    lead_evidence_ids: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()
    company_cards: tuple[CompanyCard, ...] = ()

    @property
    def text(self) -> str:
        parts = [self.intro] if self.intro else []
        if self.blocks:
            parts.extend(f"**{b.title}**\n{b.text}" + ('\n' + b.implication if b.implication else '') for b in self.blocks)
        elif self.company_cards:
            for c in self.company_cards:
                card_parts = [f"**{c.stock_name}**"]
                for s in c.sections:
                    if s.text:
                        card_parts.append(s.text)
                parts.append("\n".join(card_parts))
        return "\n\n".join(p for p in parts if p)

    def __iter__(self):
        # 기존 스크립트와 테스트의 text, evidence, follow_up 반환 계약.
        return iter((self.text, self.evidence, self.follow_up))


@dataclass(frozen=True)
class Commentary:
    theme_trend: tuple[Statement, ...]
    stock_comment: str
    opportunity: Statement | None
    risk: Statement | None
    summary: Statement | None
    financial_commentary: tuple[Statement, ...] = ()


@dataclass(frozen=True, init=False)
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
    annual_summaries: tuple[AnnualFinancialSummary, ...] = ()
    quarterly_summaries: tuple[QuarterlyFinancialSummary, ...] = ()
    financial_ratios: FinancialRatios | None = None
    financial_facts: tuple[FinancialFact, ...] = ()
    related_stocks: tuple[RelatedStockSummary, ...] = ()
    section_status: dict[str, str] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    result_id: str = ""
    source_documents: tuple[SourceDocument, ...] = ()

    def __init__(
        self,
        theme: str,
        candidates: tuple[StockCandidate, ...],
        financial: FinancialData,
        news: NewsData,
        commentary: Commentary | None,
        ai_error: str | None = None,
        selected_code: str | None = None,
        query_options: QueryOptions = None,
        price_history: PriceHistory | None = None,
        financial_statements: tuple[FinancialStatementData, ...] = _UNSET,
        statements: FinancialStatementData | None = None,
        annual_summaries: tuple[AnnualFinancialSummary, ...] = (),
        quarterly_summaries: tuple[QuarterlyFinancialSummary, ...] = (),
        financial_ratios: FinancialRatios | None = _UNSET,
        ratios: FinancialRatios | None = None,
        financial_facts: tuple[FinancialFact, ...] = (),
        related_stocks: tuple[RelatedStockSummary, ...] = _UNSET,
        related_summaries: tuple[RelatedStockSummary, ...] = (),
        section_status: dict[str, str] = None,
        timings_ms: dict[str, float] = None,
        result_id: str = '',
        source_documents: tuple[SourceDocument, ...] = (),
    ):
        """별칭 인수는 생성 시 변환하고 정식 필드만 저장한다."""
        object.__setattr__(self, "theme", theme)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "news", news)
        object.__setattr__(self, "commentary", commentary)
        object.__setattr__(self, "ai_error", ai_error)
        object.__setattr__(self, "selected_code", selected_code)
        object.__setattr__(self, "query_options", QueryOptions() if query_options is None else query_options)
        object.__setattr__(self, "price_history", price_history)
        object.__setattr__(self, "financial_statements", ((statements,) if statements is not None else ()) if financial_statements is _UNSET else financial_statements)
        object.__setattr__(self, "annual_summaries", annual_summaries)
        object.__setattr__(self, "quarterly_summaries", quarterly_summaries)
        object.__setattr__(self, "financial_ratios", ratios if financial_ratios is _UNSET else financial_ratios)
        object.__setattr__(self, "financial_facts", financial_facts)
        object.__setattr__(self, "related_stocks", related_summaries if related_stocks is _UNSET else related_stocks)
        object.__setattr__(self, "section_status", dict() if section_status is None else section_status)
        object.__setattr__(self, "timings_ms", dict() if timings_ms is None else timings_ms)
        object.__setattr__(self, "result_id", result_id)
        object.__setattr__(self, "source_documents", tuple(source_documents))

    @property
    def statements(self):
        return self.financial_statements[0] if self.financial_statements else None

    @property
    def ratios(self):
        return self.financial_ratios

    @property
    def related_summaries(self):
        return self.related_stocks

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
            and self.financial.price is not None
            and all(status == "ok" for key, status in self.section_status.items() if key in {"history", "dart", "news", "commentary"})
        )


DashboardResult = AnalysisResult


def resolve_roe_metric(result: AnalysisResult) -> MetricValue | None:
    """재무비율의 ROE를 우선하고 없으면 기본 금융 자료의 ROE를 사용한다."""
    if result.financial_ratios and result.financial_ratios.roe is not None:
        return result.financial_ratios.roe
    return result.financial.roe_metric
