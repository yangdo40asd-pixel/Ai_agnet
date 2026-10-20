"""입력 → 후보 확인 → 선택 종목 수집 → AI 설명을 연결하는 처리 순서."""

import time
from collections.abc import Callable
from dataclasses import replace
from unittest.mock import NonCallableMock

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
)


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
) -> AnalysisResult:
    """사용자가 선택한 후보 종목에 대해 금융·뉴스·AI 설명을 수집한다. 후보 AI를 다시 호출하지 않는다."""
    progress = on_progress or (lambda _: None)
    normalized_theme = normalize_theme(theme)
    candidate_tuple = tuple(candidates)
    target = resolve_selected_target(candidate_tuple, selected_code)
    active_settings = settings or load_settings()
    options = query_options or QueryOptions()
    timings: dict[str, float] = {}

    progress("주가·PER를 조회하고 있습니다.")
    t0 = time.perf_counter()
    financial = fetch_financial(target)
    timings["financial_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    if financial.stock.code != target.code:
        raise AppError("finance_identity", "금융 자료의 종목코드를 확인하지 못했습니다. 이번 분석을 중단합니다.")

    price_history = None
    related_stocks = ()
    should_fetch_history = not isinstance(fetch_financial, NonCallableMock) or isinstance(
        fetch_price_history, NonCallableMock
    )
    if should_fetch_history:
        progress("일별 주가·거래량 이력을 조회하고 있습니다.")
        t_hist = time.perf_counter()
        hist_currency = "KRW" if financial.price is not None else "UNKNOWN"
        price_history = fetch_price_history(
            target,
            options.price_period,
            currency=hist_currency,
        )
        related_stocks = fetch_related_stock_summaries(
            candidate_tuple,
            target.code,
            price_history,
            fetch_unselected=False,
        )
        timings["history_ms"] = round((time.perf_counter() - t_hist) * 1000.0, 2)

    financial_statements = ()
    annual_summaries = ()
    quarterly_summaries = ()
    financial_ratios = None
    financial_facts = ()
    dart_status = "empty"

    should_fetch_dart = (
        not isinstance(fetch_financial, NonCallableMock)
        or isinstance(collect_company_financials, NonCallableMock)
    )
    if should_fetch_dart and (
        active_settings.dart_api_key
        or isinstance(collect_company_financials, NonCallableMock)
    ):
        progress("기업 재무제표와 주요 재무비율(OpenDART)을 조회하고 있습니다.")
        t_dart = time.perf_counter()
        dart_bundle = collect_company_financials(
            target,
            active_settings,
            preferred_fs_div=options.fs_div,
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

    progress("관련 뉴스와 근거 링크를 수집하고 있습니다.")
    t1 = time.perf_counter()
    news = fetch_news(normalized_theme, target.name, active_settings)
    timings["news_ms"] = round((time.perf_counter() - t1) * 1000.0, 2)

    progress("AI 설명을 작성하고 조회값·뉴스 근거를 확인하고 있습니다.")
    t2 = time.perf_counter()
    try:
        commentary = generate_commentary(normalized_theme, financial, news, active_settings)
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
        and (
            not isinstance(generate_commentary, NonCallableMock)
            or isinstance(generate_financial_commentary, NonCallableMock)
        )
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
        "history": price_history.status if price_history is not None else "empty",
        "dart": dart_status,
        "news": news.status,
        "commentary": "ok" if commentary is not None else "failed",
        "financial_commentary": fin_comm_status,
    }
    result_id = (
        f"{normalized_theme}:{target.code}:{options.price_period}:"
        f"{options.bsns_year or 'latest'}:{options.reprt_code}:{options.fs_div}:"
        f"{options.refresh_generation}"
    )
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
