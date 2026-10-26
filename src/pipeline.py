"""입력 → 후보 확인 → 선택 종목 수집 → AI 설명을 연결하는 처리 순서."""

import time
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from src.agents.report import (
    generate_commentary,
    generate_financial_commentary,
    propose_candidates,
)
from src.config import Settings, load_settings
from src.data.financials import collect_company_financials
from src.data.history import fetch_price_history, fetch_related_stock_summaries
from src.data.news import fetch_news
from src.data.stock import (
    candidate_options,
    fetch_financial,
    load_listing,
    require_target,
    resolve_candidates,
    resolve_selected_target,
)
from src.models import (
    AnalysisResult,
    AppError,
    CandidateDiscoveryResult,
    QueryOptions,
    StockCandidate,
    now_kst,
    FinancialData,
    NewsData,
)


def identify_stock(name_or_code: str, *, listing=None) -> StockCandidate:
    """명시한 회사 하나만 공식 목록과 대조한다. 별칭·부분 일치는 추측하지 않는다."""
    import re
    table = load_listing() if listing is None else listing
    value = name_or_code.strip()
    if re.fullmatch(r"[0-9A-Za-z]{6}", value):
        codes = table["Code"].astype(str).str.strip().str.upper().str.zfill(6)
        rows = table[codes == value.upper()]
        if len(rows) == 1:
            value = str(rows.iloc[0]["Name"])
    found = resolve_candidates((value,), table)[0]
    if not found.selectable:
        raise AppError("stock_unconfirmed", "입력한 회사의 공식 종목명·코드를 확인하지 못했습니다. 공식 명칭이나 6자리 코드를 입력해 주세요.")
    return found


def normalize_theme(theme: str) -> str:
    if not isinstance(theme, str):
        raise AppError("input_empty", "테마를 입력해 주세요.")
    normalized = " ".join(theme.split())
    if not normalized:
        raise AppError("input_empty", "테마를 입력해 주세요.")
    if len(normalized) > 120:
        raise AppError("input_length", "테마는 120자 이내로 입력해 주세요.")
    return normalized


def discover_theme_candidates(
    theme: str,
    on_progress: Callable[[str], None] | None = None,
    *,
    settings: Settings | None = None,
) -> CandidateDiscoveryResult:
    """테마 입력 검증 → AI 후보 3개 제안 → KRX 상장 대조(필요 시 1회 재제안)까지만 수행한다."""
    progress = on_progress or (lambda _: None)
    normalized_theme = normalize_theme(theme)
    active_settings = settings or load_settings()
    progress("관련 종목 후보를 제안하고 있습니다.")
    names = propose_candidates(normalized_theme, active_settings)
    progress("상장 여부와 시장·종목코드를 확인하고 있습니다.")
    listing = load_listing()
    candidates = resolve_candidates(names, listing)
    rejected = tuple(stock.name for stock in candidates if not stock.verified or stock.reason)
    if rejected:
        progress("확인되지 않은 종목명을 제외하고 후보를 한 번 더 확인하고 있습니다.")
        try:
            options = candidate_options(normalized_theme, candidates, listing) if listing is not None else ()
            revised_names = propose_candidates(
                normalized_theme,
                active_settings,
                rejected_names=rejected,
                available_names=options,
            )
            revised = resolve_candidates(revised_names, listing)
            if all(stock.verified and not stock.reason for stock in revised):
                candidates = revised
        except AppError:
            # 최초 결과와 기존 중단/미확인 안내를 보존한다. 무한 재시도하지 않는다.
            pass
    failure_reason = ""
    if not any(stock.selectable for stock in candidates):
        failure_reason = "선택 가능한 상장 종목 후보를 확인하지 못했습니다. 테마를 다시 입력해 주세요."
    return CandidateDiscoveryResult(
        theme=normalized_theme,
        candidates=candidates,
        retrieved_at=now_kst(),
        failure_reason=failure_reason,
    )


def analyze_selected_stock(
    theme: str,
    candidates: tuple[StockCandidate, ...] | list[StockCandidate],
    selected_code: object,
    query_options: QueryOptions | None = None,
    on_progress: Callable[[str], None] | None = None,
    *,
    settings: Settings | None = None,
    scope: str = "all",
    previous: AnalysisResult | None = None,
) -> AnalysisResult:
    """사용자가 선택한 후보 종목에 대해 금융·뉴스·AI 설명을 수집한다. 후보 AI를 다시 호출하지 않는다."""
    progress = on_progress or (lambda _: None)
    normalized_theme = normalize_theme(theme)
    candidate_tuple = tuple(candidates)
    target = resolve_selected_target(candidate_tuple, selected_code)
    active_settings = settings or load_settings()
    options = query_options or QueryOptions()
    if scope not in {"all", "finance", "news", "history", "financials"}:
        raise AppError("request_scope", "지원하지 않는 조회 범위입니다.")
    if previous is not None and previous.target_code != target.code:
        previous = None
    timings: dict[str, float] = {}

    if scope in {"all", "finance"}:
        progress("주가·금융 지표를 조회하고 있습니다.")
    t0 = time.perf_counter()
    financial = (fetch_financial(target) if scope in {"all", "finance"} else
                 previous.financial if previous else FinancialData(target, None, None, now_kst(), warnings=("금융 지표를 아직 조회하지 않았습니다.",), collection_status="not_collected"))
    timings["financial_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    if financial.stock.code != target.code:
        raise AppError("finance_identity", "금융 자료의 종목코드를 확인하지 못했습니다. 이번 분석을 중단합니다.")

    price_history = previous.price_history if previous else None
    related_stocks = previous.related_stocks if previous else ()
    if scope in {"all", "history"}:
        progress("주가·거래량과 후보 시세를 조회하고 있습니다.")
        t_hist = time.perf_counter()
        price_history = fetch_price_history(target, options.price_period, currency="KRW")
        related_stocks = fetch_related_stock_summaries(candidate_tuple, target.code, price_history, fetch_unselected=True)
        timings["history_ms"] = round((time.perf_counter() - t_hist) * 1000.0, 2)

    financial_statements = previous.financial_statements if previous else ()
    annual_summaries = previous.annual_summaries if previous else ()
    quarterly_summaries = previous.quarterly_summaries if previous else ()
    financial_ratios = previous.financial_ratios if previous else None
    financial_facts = previous.financial_facts if previous else ()
    dart_status = previous.section_status.get("dart", "not_collected") if previous else "not_collected"

    if scope in {"all", "financials"} and active_settings.dart_api_key:
        progress("기업 재무제표와 주요 재무비율(OpenDART)을 조회하고 있습니다.")
        t_dart = time.perf_counter()
        dart_bundle = collect_company_financials(
            target,
            active_settings,
            preferred_fs_div=options.fs_div,
            bsns_year=options.bsns_year,
            reprt_code=options.reprt_code,
        )
        timings["dart_ms"] = round((time.perf_counter() - t_dart) * 1000.0, 2)
        dart_status = str(dart_bundle.get("status") or "empty")
        financial_statements = tuple(dart_bundle.get("statements") or ())
        annual_summaries = tuple(dart_bundle.get("annual_summaries") or ())
        quarterly_summaries = tuple(dart_bundle.get("quarterly_summaries") or ())
        financial_ratios = dart_bundle.get("ratios")
        financial_facts = tuple(dart_bundle.get("facts") or ())
        if financial_ratios is not None and financial_ratios.roe is not None:
            financial = replace(financial, roe_metric=financial_ratios.roe)

    if scope in {"all", "news"}:
        progress("관련 뉴스와 근거 링크를 수집하고 있습니다.")
    t1 = time.perf_counter()
    news = (fetch_news(normalized_theme, target.name, active_settings) if scope in {"all", "news"} else
            previous.news if previous else NewsData((), now_kst(), status="not_collected", message="뉴스를 아직 조회하지 않았습니다."))
    timings["news_ms"] = round((time.perf_counter() - t1) * 1000.0, 2)

    if scope == "all":
        progress("AI 설명을 작성하고 조회값·뉴스 근거를 확인하고 있습니다.")
    t2 = time.perf_counter()
    try:
        commentary = generate_commentary(normalized_theme, financial, news, active_settings) if scope == "all" else None
        ai_error = None
    except AppError as error:
        # 수집 자료를 보존하되 AI 리포트 생성 완료로 표시하지 않는다.
        commentary = None
        ai_error = error.message
    timings["commentary_ms"] = round((time.perf_counter() - t2) * 1000.0, 2)

    fin_comm_status = "empty"
    should_generate_fin_comm = (
        commentary is not None
        and bool(financial_facts)
    )
    if should_generate_fin_comm and commentary is not None:
        progress("기업 재무제표 근거 AI 설명을 작성하고 사실(fact_id)을 대조하고 있습니다.")
        t_fcomm = time.perf_counter()
        try:
            fin_stmts = generate_financial_commentary(
                normalized_theme, financial, financial_facts, active_settings
            )
            commentary = replace(commentary, financial_commentary=fin_stmts)
            fin_comm_status = "ok" if fin_stmts else "empty"
        except AppError:
            fin_comm_status = "failed"
        timings["financial_commentary_ms"] = round((time.perf_counter() - t_fcomm) * 1000.0, 2)

    section_status = {
        "financial": "partial" if financial.warnings else "ok",
        "history": price_history.status if price_history is not None else "not_collected",
        "dart": dart_status,
        "news": news.status,
        "commentary": "ok" if commentary is not None else "failed" if scope == "all" else "not_requested",
        "financial_commentary": fin_comm_status,
    }
    result_id = uuid4().hex
    return AnalysisResult(
        theme=normalized_theme,
        candidates=candidate_tuple,
        financial=financial,
        news=news,
        commentary=commentary,
        ai_error=ai_error,
        selected_code=target.code,
        query_options=options,
        price_history=price_history,
        financial_statements=financial_statements,
        annual_summaries=annual_summaries,
        quarterly_summaries=quarterly_summaries,
        financial_ratios=financial_ratios,
        financial_facts=financial_facts,
        related_stocks=related_stocks,
        section_status=section_status,
        timings_ms=timings,
        result_id=result_id,
    )


def analyze_theme(
    theme: str,
    on_progress: Callable[[str], None] | None = None,
    *,
    selected_code: str | None = None,
    query_options: QueryOptions | None = None,
) -> AnalysisResult:
    """기존 첫 후보 자동 분석 호환 경로. 후보 탐색과 선택 종목 분석을 순차 연결한다."""
    progress = on_progress or (lambda _: None)
    normalized_theme = normalize_theme(theme)
    settings = load_settings()
    discovery = discover_theme_candidates(normalized_theme, progress, settings=settings)
    if selected_code is None:
        target = require_target(discovery.candidates)
        code_to_use = target.code
    else:
        code_to_use = selected_code
    return analyze_selected_stock(
        discovery.theme,
        discovery.candidates,
        code_to_use,
        query_options=query_options,
        on_progress=progress,
        settings=settings,
    )
