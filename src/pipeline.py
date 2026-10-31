"""입력 → 후보 확인 → 선택 종목 수집 → AI 설명을 연결하는 처리 순서."""

import time
import re
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
    previous: CandidateDiscoveryResult | None = None,
) -> CandidateDiscoveryResult:
    """소수의 새 후보를 상장 대조한다. 추가 탐색은 기존 후보를 보존한다."""
    progress = on_progress or (lambda _: None)
    normalized_theme = normalize_theme(theme)
    active_settings = settings or load_settings()
    if previous is not None and normalize_theme(previous.theme) != normalized_theme:
        raise AppError("candidate_theme", "추가 탐색의 테마가 기존 탐색과 일치하지 않습니다.")
    excluded = tuple(stock.name for stock in previous.candidates) if previous else ()
    progress("관련 종목 후보를 제안하고 있습니다.")
    names = (propose_candidates(normalized_theme, active_settings, excluded_names=excluded)
             if previous else propose_candidates(normalized_theme, active_settings))
    progress("상장 여부와 시장·종목코드를 확인하고 있습니다.")
    listing = load_listing()
    candidates = resolve_candidates(names, listing)
    rejected = tuple(stock.name for stock in candidates if not stock.verified or stock.reason)
    if rejected:
        progress("확인되지 않은 종목명을 제외하고 후보를 한 번 더 확인하고 있습니다.")
        try:
            options = candidate_options(normalized_theme, candidates, listing) if listing is not None else ()
            if excluded:
                options = tuple(name for name in options if name not in excluded)
            revised_names = propose_candidates(
                normalized_theme,
                active_settings,
                rejected_names=rejected,
                available_names=options,
                **({"excluded_names": excluded} if previous else {}),
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
    batch_codes = ()
    if previous is not None:
        old_codes = {stock.code for stock in previous.candidates if stock.code}
        added = tuple(stock for stock in candidates if stock.selectable and stock.code not in old_codes)
        if not added:
            return replace(previous, failure_reason="기존 후보와 구분되는 새 상장 종목 후보를 확인하지 못했습니다. 기존 탐색 결과는 유지됩니다.")
        candidates = (*previous.candidates, *added)
        batch_codes = tuple(stock.code for stock in added)
    return CandidateDiscoveryResult(
        theme=normalized_theme,
        candidates=candidates,
        retrieved_at=now_kst(),
        failure_reason=failure_reason,
        batch_codes=batch_codes,
        business_profiles=previous.business_profiles if previous else (),
        business_sources=getattr(previous, 'business_sources', ()),
        business_source_statuses=getattr(previous, 'business_source_statuses', ()),
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
    question: str = "",
    quarter_context=None,
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
    from src.data.report_period import quarter_request
    requested_quarter = quarter_context or quarter_request(question)
    market_requested = bool(re.search(r"PER|PBR|ROE|EPS|BPS|주가|현재가|가격", question, re.I))
    history_requested = bool(re.search(r"차트|추이|거래량|주가.{0,15}왜|왜.{0,15}주가", question))
    collect_finance = scope in {"all", "finance"} and (requested_quarter is None or market_requested)
    collect_history = scope in {"all", "history"} and (requested_quarter is None or history_requested)
    collect_news = scope in {"all", "news"} and requested_quarter is None
    create_commentary = scope == "all" and requested_quarter is None and not question
    result_id = uuid4().hex
    timings: dict[str, float] = {}

    if collect_finance:
        progress("주가·금융 지표를 조회하고 있습니다.")
    t0 = time.perf_counter()
    financial = (fetch_financial(target) if collect_finance else
                 previous.financial if previous else FinancialData(target, None, None, now_kst(), warnings=("금융 지표를 아직 조회하지 않았습니다.",), collection_status="not_collected"))
    timings["financial_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    if financial.stock.code != target.code:
        raise AppError("finance_identity", "금융 자료의 종목코드를 확인하지 못했습니다. 이번 분석을 중단합니다.")

    price_history = previous.price_history if previous else None
    related_stocks = previous.related_stocks if previous else ()
    if collect_history:
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
    quarter_status = previous.section_status.get("dart_quarterly", "not_collected") if previous else "not_collected"
    quarter_token = previous.section_status.get("quarterly_request", "") if previous else ""
    quarter_checked = previous.section_status.get("quarterly_checked_at", "") if previous else ""
    quarter_message = previous.section_status.get("quarterly_message", "") if previous else ""


    if scope in {"all", "financials"} and active_settings.dart_api_key and requested_quarter is None:
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

    if (requested_quarter is not None and scope in {"all", "financials"}
            and active_settings.dart_api_key and not requested_quarter.reason):
        from src.data.quarterly import collect_quarterly_financials
        progress("요청한 분기와 전년 동기의 공시 재무자료를 확인하고 있습니다.")
        started = time.perf_counter()
        quarter_bundle = collect_quarterly_financials(target, requested_quarter, active_settings)
        timings["dart_quarterly_ms"] = round((time.perf_counter() - started) * 1000, 2)
        for index, call in enumerate(quarter_bundle["calls"]):
            timings[f"dart_quarterly_call_{index}_ms"] = call["elapsed_ms"]
        quarter_status, quarter_token = quarter_bundle["status"], requested_quarter.token
        quarter_checked = now_kst().isoformat()
        quarter_message = str(quarter_bundle.get("message") or "")
        statement_map = {(s.bsns_year, s.reprt_code, s.fs_div): s for s in financial_statements}
        statement_map.update({(s.bsns_year, s.reprt_code, s.fs_div): s for s in quarter_bundle["statements"]})
        financial_statements = tuple(statement_map.values())
        quarter_map = {(q.period_label, q.fs_div): q for q in quarterly_summaries}
        # 재조회에서 사라진 요청 기간을 이전 성공 값으로 채우지 않는다.
        requested_labels = {f"{requested_quarter.year} {requested_quarter.quarter}Q",
                            f"{requested_quarter.year-1} {requested_quarter.quarter}Q"}
        quarter_map = {key: value for key, value in quarter_map.items() if key[0] not in requested_labels}
        quarter_map.update({(q.period_label, q.fs_div): q for q in quarter_bundle["summaries"]})
        quarterly_summaries = tuple(quarter_map.values())

    if collect_news:
        progress("관련 뉴스와 근거 링크를 수집하고 있습니다.")
    t1 = time.perf_counter()
    news = (fetch_news(normalized_theme, target.name, active_settings) if collect_news else
            previous.news if previous else NewsData((), now_kst(), status="not_collected", message="뉴스를 아직 조회하지 않았습니다."))
    timings["news_ms"] = round((time.perf_counter() - t1) * 1000.0, 2)

    source_documents = previous.source_documents if previous else ()
    disclosure_status = previous.section_status.get("disclosures", "not_requested") if previous else "not_requested"
    if question and collect_news:
        from src.data.disclosures import collect_disclosures
        source_documents, disclosure_status = collect_disclosures(target, active_settings, question)

    if collect_news:
        from src.data.relations import extract_relationships
        news=replace(news,relationships=extract_relationships(source_documents,target))

    if create_commentary:
        progress("AI 설명을 작성하고 조회값·뉴스 근거를 확인하고 있습니다.")
    t2 = time.perf_counter()
    try:
        if collect_news and active_settings.strict_news:
            from src.agents.news_relevance import prepare_news
            news = prepare_news(news, target, normalized_theme, active_settings, context_id=result_id)
        commentary = generate_commentary(normalized_theme, financial, news, active_settings) if create_commentary else None
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
        "dart_quarterly": quarter_status,
        "quarterly_request": quarter_token,
        "quarterly_checked_at": quarter_checked,
        "quarterly_message": quarter_message,
        "news": news.status,
        "disclosures": disclosure_status,
        "commentary": "ok" if commentary is not None else "failed" if create_commentary else "not_requested",
        "financial_commentary": fin_comm_status,
    }
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
        source_documents=source_documents,
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
